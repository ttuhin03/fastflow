"""
Request Performance Tracking Middleware.

Misst die Dauer jedes HTTP-Requests, loggt strukturierte Request-Metriken
und markiert langsame Requests (konfigurierbar via SLOW_REQUEST_THRESHOLD_SECONDS).
"""

import logging
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import config

logger = logging.getLogger(__name__)


class PerformanceTrackingMiddleware(BaseHTTPMiddleware):
    """
    Middleware für Request-Performance-Tracking.
    
    - Misst die Dauer jedes Requests
    - Loggt method, path, status_code, duration_ms, request_id
    - Slow-Request-Detection: WARNING wenn Dauer > SLOW_REQUEST_THRESHOLD_SECONDS
    - Strukturiertes Logging wenn LOG_JSON aktiv
    """

    # Pfade die nicht geloggt werden (z.B. Health-Checks, Metrics)
    SKIP_PATHS = frozenset({
        "/health", "/healthz", "/api/health", "/ready", "/api/ready",
        "/metrics",  # Metrics-Endpoint selbst, sonst Feedback-Loop
    })

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Skips für häufige, wenig aussagekräftige Requests
        if path in self.SKIP_PATHS or path.rstrip("/") in self.SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_seconds = time.perf_counter() - start
        duration_ms = round(duration_seconds * 1000, 2)

        method = request.method
        status_code = response.status_code
        request_id = getattr(request.state, "request_id", None)

        # Slow-Request-Detection
        if duration_seconds >= config.SLOW_REQUEST_THRESHOLD_SECONDS:
            if config.LOG_JSON:
                logger.warning(
                    "Slow request",
                    extra={
                        "event": "slow_request",
                        "method": method,
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "duration_seconds": round(duration_seconds, 3),
                        "threshold_seconds": config.SLOW_REQUEST_THRESHOLD_SECONDS,
                        "request_id": request_id,
                    },
                )
            else:
                logger.warning(
                    "Slow request: %s %s -> %d in %dms (threshold: %.1fs) request_id=%s",
                    method, path, status_code, duration_ms,
                    config.SLOW_REQUEST_THRESHOLD_SECONDS, request_id,
                )
        else:
            # Normales Request-Logging (INFO)
            if config.LOG_JSON:
                logger.info(
                    "Request",
                    extra={
                        "event": "request",
                        "method": method,
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "request_id": request_id,
                    },
                )
            else:
                logger.info(
                    "%s %s -> %d %dms request_id=%s",
                    method, path, status_code, duration_ms, request_id,
                )

        return response
