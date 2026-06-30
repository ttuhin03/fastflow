"""
Client-IP Middleware.

Legt die Client-IP des aktuellen Requests in einer ContextVar ab, damit
tiefer liegende Services (z.B. log_audit) sie ohne Request-Objekt lesen können.
"""

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


def _extract_ip(request: Request) -> Optional[str]:
    # Hinter einem Reverse-Proxy steht die echte Client-IP im ersten Hop von X-Forwarded-For.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first[:64]
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return None


class ClientIPMiddleware(BaseHTTPMiddleware):
    """Setzt die Client-IP für die Dauer des Requests in einer ContextVar."""

    async def dispatch(self, request: Request, call_next) -> Response:
        token = _client_ip_var.set(_extract_ip(request))
        try:
            return await call_next(request)
        finally:
            _client_ip_var.reset(token)
