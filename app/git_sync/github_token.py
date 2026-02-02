"""
GitHub Apps: Installation Access Token (JWT, Cache).
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import jwt
import requests

from app.core.config import config

logger = logging.getLogger(__name__)

_github_token_cache: Optional[Tuple[str, datetime]] = None


def get_github_app_token() -> Optional[str]:
    """
    Generiert ein GitHub Installation Access Token via GitHub Apps API.
    Token wird gecacht (1 Stunde Gültigkeit).

    Returns:
        Installation Access Token oder None wenn Konfiguration fehlt

    Raises:
        RuntimeError: Wenn Token-Generierung fehlschlägt
    """
    global _github_token_cache
    if not config.GITHUB_APP_ID or not config.GITHUB_INSTALLATION_ID or not config.GITHUB_PRIVATE_KEY_PATH:
        return None
    if _github_token_cache is not None:
        token, expires_at = _github_token_cache
        if datetime.utcnow() < expires_at - timedelta(minutes=5):
            return token
    try:
        private_key_path = Path(config.GITHUB_PRIVATE_KEY_PATH)
        if not private_key_path.exists():
            raise RuntimeError(f"GitHub Private Key nicht gefunden: {private_key_path}")
        with open(private_key_path, "r") as f:
            private_key = f.read()
        now = int(time.time())
        jwt_payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": config.GITHUB_APP_ID,
        }
        jwt_token = jwt.encode(jwt_payload, private_key, algorithm="RS256")
        url = f"https://api.github.com/app/installations/{config.GITHUB_INSTALLATION_ID}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json",
        }
        response = requests.post(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        installation_token = data["token"]
        expires_at_str = data.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        else:
            expires_at = datetime.utcnow() + timedelta(hours=1)
        _github_token_cache = (installation_token, expires_at)
        logger.info("GitHub Installation Access Token erfolgreich generiert")
        return installation_token
    except Exception as e:
        error_msg = f"Fehler bei GitHub App Token-Generierung: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


def test_github_app_token() -> Tuple[bool, str]:
    """
    Testet die GitHub Apps Konfiguration durch Token-Generierung.

    Returns:
        Tuple (success: bool, message: str)
    """
    try:
        token = get_github_app_token()
        if token:
            return (True, "GitHub Apps Konfiguration erfolgreich. Token wurde generiert.")
        return (False, "GitHub Apps ist nicht konfiguriert oder Konfiguration ist unvollständig.")
    except Exception as e:
        return (False, f"Fehler bei Token-Generierung: {str(e)}")
