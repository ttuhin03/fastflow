"""
Rate Limiting Module.

Dieses Modul stellt Rate Limiting für API-Endpoints bereit.
Verwendet slowapi für in-memory Rate Limiting basierend auf IP-Adressen.

Rate Limits:
- /api/auth/login: 5 Requests pro Minute pro IP (Schutz vor Brute-Force)
- /api/webhooks/*: 100 Requests pro Minute pro IP (Schutz vor DDoS)
- Allgemein: 100 Requests pro Minute pro IP
"""

import logging
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)


def get_client_identifier(request: Request) -> str:
    """
    Ermittelt Client-Identifier für Rate Limiting.
    
    Verwendet IP-Adresse aus Request. Berücksichtigt X-Forwarded-For
    Header wenn hinter einem Reverse-Proxy.
    
    Args:
        request: FastAPI Request
        
    Returns:
        str: Client-Identifier (IP-Adresse)
    """
    # Prüfe X-Forwarded-For Header (wenn hinter Reverse-Proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Nehme erste IP (Original-Client)
        client_ip = forwarded_for.split(",")[0].strip()
        return client_ip
    
    # Fallback: Standard-Funktion von slowapi
    return get_remote_address(request)


# Rate Limiter initialisieren
# Exportiert für Verwendung in Endpoints
limiter = Limiter(key_func=get_client_identifier)
