"""
Request-ID Middleware.

Setzt pro Request eine X-Request-ID (aus Header oder neu generiert)
und schreibt sie in Response-Header und request.state für Logs/Fehlerantworten.
"""

import logging
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware für Request-Korrelations-ID.
    
    Liest X-Request-ID aus dem Request oder erzeugt eine UUID.
    Setzt request.state.request_id und fügt X-Request-ID der Response hinzu.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER)
        if not request_id or not request_id.strip():
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
