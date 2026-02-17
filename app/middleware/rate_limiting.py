"""
Rate Limiting Module.

Dieses Modul stellt Rate Limiting für API-Endpoints bereit.
Verwendet slowapi für in-memory Rate Limiting basierend auf IP-Adressen.

Rate Limits:
- Global (default): 200/min pro IP für alle /api/*-Routen
- /api/auth/*: 20–60/min (spezifisch pro Endpoint)
- /api/webhooks/*: 30/min (Bruteforce-Schutz)
- /api/pipelines/daily-stats/all: 10/min (ressourcenintensiv)
- /api/pipelines/dependencies: 15/min (pip-audit)
- /api/sync (POST): 6/min
- /health, /ready, /metrics: exempt (Load-Balancer/Monitoring)
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
# default_limits: gilt für alle API-Routen ohne eigene @limiter.limit()
# Enterprise: DoS-Schutz bei vielen gleichzeitigen Nutzern
limiter = Limiter(
    key_func=get_client_identifier,
    default_limits=["200/minute"],
)
