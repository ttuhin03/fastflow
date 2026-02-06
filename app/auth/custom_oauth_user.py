"""
Custom OAuth 2.0 / OIDC für User-Login (Keycloak, Auth0, eigener IdP).

Alle URLs und Scopes kommen aus der Konfiguration.
Claim-Mapping (id, email, name) ist konfigurierbar.
"""

import logging
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.core.config import config

logger = logging.getLogger(__name__)


def _is_custom_oauth_configured() -> bool:
    return bool(
        config.CUSTOM_OAUTH_CLIENT_ID
        and config.CUSTOM_OAUTH_CLIENT_SECRET
        and config.CUSTOM_OAUTH_AUTHORIZE_URL
        and config.CUSTOM_OAUTH_TOKEN_URL
        and config.CUSTOM_OAUTH_USERINFO_URL
    )


def get_custom_oauth_authorize_url(state: str) -> str:
    """
    Erzeugt die Custom OAuth Authorize-URL.

    Args:
        state: CSRF-Token, Invitation-Token oder Link-State

    Returns:
        URL zum Redirect des Browsers
    """
    if not _is_custom_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Custom OAuth ist nicht konfiguriert (CUSTOM_OAUTH_* fehlt)",
        )
    base = config.BASE_URL or "http://localhost:8000"
    redirect_uri = f"{base.rstrip('/')}/api/auth/custom/callback"
    params = {
        "client_id": config.CUSTOM_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": config.CUSTOM_OAUTH_SCOPES,
        "state": state,
    }
    return f"{config.CUSTOM_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


async def get_custom_oauth_user_data(code: str) -> dict[str, Any]:
    """
    Tauscht den OAuth-Code gegen ein Access-Token und lädt Userinfo.

    Userinfo wird mit CUSTOM_OAUTH_CLAIM_* in das normierte Format
    (id, email, name, login, avatar_url/picture) gemappt.

    Args:
        code: OAuth Authorization Code aus dem Callback

    Returns:
        dict mit: id, email, name, login, avatar_url (picture)

    Raises:
        HTTPException: Bei Fehlern
    """
    if not _is_custom_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Custom OAuth ist nicht konfiguriert",
        )
    base = config.BASE_URL or "http://localhost:8000"
    redirect_uri = f"{base.rstrip('/')}/api/auth/custom/callback"

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            config.CUSTOM_OAUTH_TOKEN_URL,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": config.CUSTOM_OAUTH_CLIENT_ID,
                "client_secret": config.CUSTOM_OAUTH_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        if token_resp.status_code != 200:
            logger.warning("Custom OAuth token exchange failed: %s", token_resp.text)
            raise HTTPException(
                status_code=400,
                detail="Custom OAuth: Code-Austausch fehlgeschlagen",
            )
        tok = token_resp.json()
        access_token = tok.get("access_token")
        if not access_token:
            err = tok.get("error_description") or tok.get("error") or "access_token fehlt"
            raise HTTPException(status_code=400, detail=f"Custom OAuth: {err}")

        user_resp = await client.get(
            config.CUSTOM_OAUTH_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail="Custom OAuth: Benutzerdaten konnten nicht geladen werden",
            )
        info = user_resp.json()

    claim_id = config.CUSTOM_OAUTH_CLAIM_ID or "sub"
    claim_email = config.CUSTOM_OAUTH_CLAIM_EMAIL or "email"
    claim_name = config.CUSTOM_OAUTH_CLAIM_NAME or "name"

    sub = str(info.get(claim_id) or info.get("sub") or "")
    email = info.get(claim_email) or info.get("email")
    name = (info.get(claim_name) or info.get("name") or info.get("preferred_username") or "").strip()
    picture = info.get("picture") or info.get("avatar_url")
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
