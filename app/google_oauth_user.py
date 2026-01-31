"""
Google OAuth 2.0 / OIDC für User-Login.

Bietet authorize-URL und Code-Exchange + Userinfo für Login,
Einladungs-Flow, INITIAL_ADMIN_EMAIL und Link-Account.
"""

import logging
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.config import config

logger = logging.getLogger(__name__)

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = "openid email profile"


def get_google_authorize_url(state: str) -> str:
    """
    Erzeugt die Google OAuth 2.0 Authorize-URL.

    Args:
        state: CSRF-Token, Invitation-Token oder Link-State

    Returns:
        URL zum Redirect des Browsers
    """
    if not config.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth ist nicht konfiguriert (GOOGLE_CLIENT_ID fehlt)",
        )
    base = config.BASE_URL or "http://localhost:8000"
    redirect_uri = f"{base.rstrip('/')}/api/auth/google/callback"
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


async def get_google_user_data(code: str) -> dict[str, Any]:
    """
    Tauscht den OAuth-Code gegen ein Access-Token und lädt Userinfo.

    1. POST zu Google token (Code-Exchange)
    2. GET userinfo (OIDC)

    Args:
        code: OAuth Authorization Code aus dem Callback

    Returns:
        dict mit: id (sub), email, name, login (für username), avatar_url (picture)

    Raises:
        HTTPException: Bei Fehlern
    """
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth ist nicht konfiguriert (GOOGLE_CLIENT_ID oder GOOGLE_CLIENT_SECRET fehlt)",
        )
    base = config.BASE_URL or "http://localhost:8000"
    redirect_uri = f"{base.rstrip('/')}/api/auth/google/callback"

    async with httpx.AsyncClient() as client:
        # 1. Code → Access Token
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        if token_resp.status_code != 200:
            logger.warning("Google token exchange failed: %s", token_resp.text)
            raise HTTPException(
                status_code=400,
                detail="Google OAuth: Code-Austausch fehlgeschlagen",
            )
        tok = token_resp.json()
        access_token = tok.get("access_token")
        if not access_token:
            err = tok.get("error_description") or tok.get("error") or "access_token fehlt"
            raise HTTPException(status_code=400, detail=f"Google OAuth: {err}")

        # 2. Userinfo
        user_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Google OAuth: Benutzerdaten konnten nicht geladen werden",
            )
        info = user_resp.json()

    # Normalisiertes Format (angleichen an GitHub: id, email, name, login, avatar_url)
    sub = info.get("sub") or ""
    email = info.get("email")
    name = (info.get("name") or "").strip()
    picture = info.get("picture")
    login = name or (email.split("@")[0] if email else "user")

    return {
        "id": sub,
        "email": email,
        "name": name,
        "login": login,
        "avatar_url": picture,
        "picture": picture,
    }
