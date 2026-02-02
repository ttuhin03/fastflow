"""
GitHub OAuth für User-Login (OAuth App, getrennt von GitHub App).

Bietet authorize-URL und Code-Exchange + User-Daten-Abruf für den
Token-Einladungs-Flow und INITIAL_ADMIN_EMAIL-Login.
"""

import logging
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.core.config import config

logger = logging.getLogger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_API = "https://api.github.com/user"
GITHUB_USER_EMAILS_API = "https://api.github.com/user/emails"
SCOPE = "read:user user:email"


def get_github_authorize_url(state: str) -> str:
    """
    Erzeugt die GitHub OAuth Authorize-URL.

    Args:
        state: CSRF-Token oder Invitation-Token (für Einladungs-Flow)

    Returns:
        URL zum Redirect des Browsers
    """
    if not config.GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="GitHub OAuth ist nicht konfiguriert (GITHUB_CLIENT_ID fehlt)",
        )
    base = config.BASE_URL or "http://localhost:8000"
    redirect_uri = f"{base.rstrip('/')}/api/auth/github/callback"
    params = {
        "client_id": config.GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


async def get_github_user_data(code: str) -> dict[str, Any]:
    """
    Tauscht den OAuth-Code gegen ein Access-Token und lädt die User-Daten.

    1. POST zu GitHub access_token (Code-Exchange)
    2. GET /user, ggf. GET /user/emails wenn email fehlt

    Args:
        code: OAuth Authorization Code aus dem Callback

    Returns:
        dict mit: id, login, email (oder aus /user/emails), name, ...

    Raises:
        HTTPException: Bei Fehlern (z.B. ungültiger Code, Config fehlt)
    """
    if not config.GITHUB_CLIENT_ID or not config.GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="GitHub OAuth ist nicht konfiguriert (GITHUB_CLIENT_ID oder GITHUB_CLIENT_SECRET fehlt)",
        )
    base = config.BASE_URL or "http://localhost:8000"
    redirect_uri = f"{base.rstrip('/')}/api/auth/github/callback"

    async with httpx.AsyncClient() as client:
        # 1. Code → Access Token
        token_resp = await client.post(
            GITHUB_ACCESS_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": config.GITHUB_CLIENT_ID,
                "client_secret": config.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        if token_resp.status_code != 200:
            logger.warning("GitHub token exchange failed: %s", token_resp.text)
            raise HTTPException(
                status_code=400,
                detail="GitHub OAuth: Code-Austausch fehlgeschlagen",
            )
        tok = token_resp.json()
        access_token = tok.get("access_token")
        if not access_token:
            err = tok.get("error_description") or tok.get("error") or "access_token fehlt"
            raise HTTPException(status_code=400, detail=f"GitHub OAuth: {err}")

        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github.v3+json"}

        # 2. User-Daten
        user_resp = await client.get(GITHUB_USER_API, headers=headers)
        if user_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="GitHub OAuth: Benutzerdaten konnten nicht geladen werden",
            )
        user = user_resp.json()

        # 3. E-Mail ggf. aus /user/emails
        email = user.get("email")
        if not email:
            em_resp = await client.get(GITHUB_USER_EMAILS_API, headers=headers)
            if em_resp.status_code == 200:
                emails = em_resp.json()
                for e in emails:
                    if e.get("primary") and e.get("verified"):
                        email = e.get("email")
                        break
                if not email and emails:
                    email = emails[0].get("email")
        user["email"] = email
        return user
