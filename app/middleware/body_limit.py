"""
Request-Body-Limit Middleware.

Lehnt Requests ab, deren Content-Length oder tatsächliche Body-Größe
das konfigurierte Limit überschreitet (413 Payload Too Large).
"""

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import config

logger = logging.getLogger(__name__)

_MUTATION_METHODS = {"POST", "PUT", "PATCH"}


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware für maximale Request-Body-Größe.

    Prüft Content-Length wenn vorhanden; für Chunked-Requests auf
    mutierenden Methoden (POST/PUT/PATCH) wird der Body-Stream
    mit Byte-Zähler gelesen und bei Überschreitung abgebrochen.
    """

    async def dispatch(self, request: Request, call_next):
        if config.MAX_REQUEST_BODY_MB is None:
            return await call_next(request)
        limit_bytes = config.MAX_REQUEST_BODY_MB * 1024 * 1024
        content_length = request.headers.get("content-length")

        if content_length:
            try:
                size_bytes = int(content_length)
            except ValueError:
                return await call_next(request)
            if size_bytes > limit_bytes:
                logger.warning(
                    "Request body too large: %s bytes (limit %s MB)",
                    size_bytes,
                    config.MAX_REQUEST_BODY_MB,
                )
                return _too_large_response()
        elif request.method in _MUTATION_METHODS:
            body = b""
            async for chunk in request.stream():
                body += chunk
                if len(body) > limit_bytes:
                    logger.warning(
                        "Chunked request body exceeds limit (%s MB)",
                        config.MAX_REQUEST_BODY_MB,
                    )
                    return _too_large_response()
            request._body = body

        return await call_next(request)


def _too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={
            "detail": f"Request body exceeds maximum size of {config.MAX_REQUEST_BODY_MB} MB",
        },
    )
