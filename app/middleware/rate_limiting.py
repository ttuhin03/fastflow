"""
Rate Limiting Module.

Dieses Modul stellt Rate Limiting für API-Endpoints bereit.
Verwendet slowapi für in-memory Rate Limiting basierend auf IP-Adressen.

Rate Limits:
- /api/auth/github/authorize: 20/min (Limiter am Endpoint)
- /api/webhooks/*: 30 Requests pro Minute pro IP (Bruteforce-Schutz)
- Allgemein: 100 Requests pro Minute pro IP
"""

import logging
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import config

logger = logging.getLogger(__name__)


def get_client_identifier(request: Request) -> str:
    """
    Ermittelt Client-Identifier für Rate Limiting.
    
    Verwendet IP-Adresse aus Request. X-Forwarded-For wird nur genutzt, wenn
    PROXY_HEADERS_TRUSTED=True gesetzt ist (Schutz vor Spoofing).
    
    Args:
        request: FastAPI Request
        
    Returns:
        str: Client-Identifier (IP-Adresse)
    """
    if config.PROXY_HEADERS_TRUSTED:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
            return client_ip
    return get_remote_address(request)


# Rate Limiter initialisieren
# Exportiert für Verwendung in Endpoints
limiter = Limiter(key_func=get_client_identifier)
