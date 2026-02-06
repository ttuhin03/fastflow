"""
Microsoft OAuth 2.0 / OIDC (Entra ID) für User-Login.

Bietet authorize-URL und Code-Exchange + Userinfo für Login,
Einladungs-Flow, INITIAL_ADMIN_EMAIL und Link-Account.
"""

import logging
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.core.config import config

logger = logging.getLogger(__name__)

MICROSOFT_SCOPES = "openid email profile"
MICROSOFT_AUTHORIZE_URL_BASE = "https://login.microsoftonline.com/"


def _get_microsoft_authorize_url_base() -> str:
    tenant = config.MICROSOFT_TENANT_ID or "common"
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"


def _get_microsoft_token_url() -> str:
    tenant = config.MICROSOFT_TENANT_ID or "common"
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


# Microsoft Graph OIDC userinfo (works with access token from Entra ID)
MICROSOFT_USERINFO_URL = "https://graph.microsoft.com/oidc/userinfo"


def get_microsoft_authorize_url(state: str) -> str:
    """
    Erzeugt die Microsoft Entra ID OAuth 2.0 Authorize-URL.

    Args:
        state: CSRF-Token, Invitation-Token oder Link-State

    Returns:
        URL zum Redirect des Browsers
    """
    if not config.MICROSOFT_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Microsoft OAuth ist nicht konfiguriert (MICROSOFT_CLIENT_ID fehlt)",
        )
    base = config.BASE_URL or "http://localhost:8000"
    redirect_uri = f"{base.rstrip('/')}/api/auth/microsoft/callback"
    params = {
        "client_id": config.MICROSOFT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": MICROSOFT_SCOPES,
        "state": state,
        "response_mode": "query",
    }
    url_base = _get_microsoft_authorize_url_base()
    return f"{url_base}?{urlencode(params)}"


async def get_microsoft_user_data(code: str) -> dict[str, Any]:
    """
    Tauscht den OAuth-Code gegen ein Access-Token und lädt Userinfo.

    1. POST zu Microsoft token (Code-Exchange)
    2. GET userinfo (OIDC)

    Args:
        code: OAuth Authorization Code aus dem Callback

    Returns:
        dict mit: id (sub), email, name, login (für username), avatar_url (picture)

    Raises:
        HTTPException: Bei Fehlern
    """
    if not config.MICROSOFT_CLIENT_ID or not config.MICROSOFT_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Microsoft OAuth ist nicht konfiguriert (MICROSOFT_CLIENT_ID oder MICROSOFT_CLIENT_SECRET fehlt)",
        )
    base = config.BASE_URL or "http://localhost:8000"
    redirect_uri = f"{base.rstrip('/')}/api/auth/microsoft/callback"

    async with httpx.AsyncClient() as client:
        # 1. Code → Access Token
        token_url = _get_microsoft_token_url()
        token_resp = await client.post(
            token_url,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": config.MICROSOFT_CLIENT_ID,
                "client_secret": config.MICROSOFT_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        if token_resp.status_code != 200:
            logger.warning("Microsoft token exchange failed: %s", token_resp.text)
            raise HTTPException(
                status_code=400,
                detail="Microsoft OAuth: Code-Austausch fehlgeschlagen",
            )
        tok = token_resp.json()
        access_token = tok.get("access_token")
        if not access_token:
            err = tok.get("error_description") or tok.get("error") or "access_token fehlt"
            raise HTTPException(status_code=400, detail=f"Microsoft OAuth: {err}")

        # 2. Userinfo
        user_resp = await client.get(
            MICROSOFT_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Microsoft OAuth: Benutzerdaten konnten nicht geladen werden",
            )
        info = user_resp.json()

    # Normalisiertes Format (angleichen an GitHub/Google: id, email, name, login, avatar_url)
    sub = info.get("sub") or ""
    email = info.get("email")
    name = (info.get("name") or "").strip()
    picture = info.get("picture")
    preferred_username = info.get("preferred_username") or ""
    login = name or (email.split("@")[0] if email else (preferred_username.split("@")[0] if preferred_username else "user"))

    return {
        "id": sub,
        "email": email,
        "name": name,
        "login": login,
        "avatar_url": picture,
        "picture": picture,
    }
