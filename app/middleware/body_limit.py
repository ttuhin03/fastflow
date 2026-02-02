"""
Request-Body-Limit Middleware.

Lehnt Requests ab, deren Content-Length das konfigurierte Limit überschreitet (413 Payload Too Large).
"""

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import config

logger = logging.getLogger(__name__)


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware für maximale Request-Body-Größe.
    
    Prüft Content-Length; bei Überschreitung von MAX_REQUEST_BODY_MB
    wird 413 zurückgegeben, ohne den Body zu lesen.
    """

    async def dispatch(self, request: Request, call_next):
        if config.MAX_REQUEST_BODY_MB is None:
            return await call_next(request)
        content_length = request.headers.get("content-length")
        if not content_length:
            return await call_next(request)
        try:
            size_bytes = int(content_length)
        except ValueError:
            return await call_next(request)
        limit_bytes = config.MAX_REQUEST_BODY_MB * 1024 * 1024
        if size_bytes > limit_bytes:
            logger.warning(
                "Request body too large: %s bytes (limit %s MB)",
                size_bytes,
                config.MAX_REQUEST_BODY_MB,
            )
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"Request body exceeds maximum size of {config.MAX_REQUEST_BODY_MB} MB",
                },
            )
        return await call_next(request)
