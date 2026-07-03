"""
Client-IP Middleware.

Legt die Client-IP des aktuellen Requests in einer ContextVar ab, damit
tiefer liegende Services (z.B. log_audit) sie ohne Request-Objekt lesen können.
"""

import ipaddress
import logging
from contextvars import ContextVar
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Pro-Request gesetzte Client-IP (None außerhalb eines Requests, z.B. Background-Tasks).
_client_ip_var: ContextVar[Optional[str]] = ContextVar("client_ip", default=None)


def get_client_ip() -> Optional[str]:
    """Gibt die Client-IP des aktuellen Requests zurück (oder None)."""
    return _client_ip_var.get()


def _valid_ip(value: Optional[str]) -> Optional[str]:
    """Akzeptiert nur syntaktisch gültige IPv4/IPv6-Adressen (verhindert, dass
    beliebiger, vom Client kontrollierter Header-Text im Audit-Log landet)."""
    if not value:
        return None
    candidate = value.strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _extract_ip(request: Request) -> Optional[str]:
    # Hinter einem Reverse-Proxy steht die echte Client-IP im ersten Hop von X-Forwarded-For.
    # Hinweis: X-Forwarded-For ist client-spoofbar, wenn die App nicht ausschließlich hinter
    # einem vertrauenswürdigen Proxy läuft — daher wird der Wert strikt als IP validiert und
    # dient nur informativ im Audit-Log.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        ip = _valid_ip(xff.split(",")[0])
        if ip:
            return ip
    ip = _valid_ip(request.headers.get("x-real-ip"))
    if ip:
        return ip
    if request.client and request.client.host:
        return _valid_ip(request.client.host)
    return None


class ClientIPMiddleware(BaseHTTPMiddleware):
    """Setzt die Client-IP für die Dauer des Requests in einer ContextVar."""

    async def dispatch(self, request: Request, call_next) -> Response:
        token = _client_ip_var.set(_extract_ip(request))
        try:
            return await call_next(request)
        finally:
            _client_ip_var.reset(token)
