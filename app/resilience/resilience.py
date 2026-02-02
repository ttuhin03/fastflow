"""
Resilience Module: Circuit Breaker und Retry für externe Dependencies.

7.1 Circuit Breaker:
- Verhindert wiederholte Aufrufe an ausgefallene Services
- Öffnet nach N Fehlern, blockiert Aufrufe für recovery_timeout Sekunden

7.2 Retry:
- Tenacity-basierte Retries mit Exponential Backoff
- Für Git, S3, Notifications
"""

import asyncio
import logging
import threading
import time
from functools import wraps
from typing import Callable, TypeVar, Optional, Type, Tuple, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError,
)

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


# =============================================================================
# Circuit Breaker
# =============================================================================


class CircuitBreakerOpenError(Exception):
    """Wird geworfen wenn der Circuit Breaker offen ist."""

    def __init__(self, name: str, recovery_in_seconds: float):
        self.name = name
        self.recovery_in_seconds = recovery_in_seconds
        super().__init__(
            f"Circuit breaker '{name}' ist offen. "
            f"Nächster Versuch in {recovery_in_seconds:.0f}s."
        )


class CircuitBreaker:
    """
    Einfacher Circuit Breaker für externe Dependencies.
    
    States: closed (normal) -> open (nach failure_threshold Fehlern)
    -> half-open (nach recovery_timeout) -> closed/open
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.Lock()

    def _state(self) -> str:
        with self._lock:
            if self._failure_count < self.failure_threshold:
                return "closed"
            if self._last_failure_time is None:
                return "closed"
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                return "half-open"
            return "open"

    def _recovery_in_seconds(self) -> float:
        with self._lock:
            if self._last_failure_time is None:
                return 0.0
            elapsed = time.monotonic() - self._last_failure_time
            return max(0.0, self.recovery_timeout - elapsed)

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._last_failure_time = None
            # Bei Erfolg in closed state: Zähler war bereits 0 oder wird zurückgesetzt

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self.failure_threshold:
                logger.warning(
                    "Circuit breaker '%s' geöffnet nach %d Fehlern. "
                    "Recovery in %.0fs.",
                    self.name,
                    self._failure_count,
                    self.recovery_timeout,
                )

    def call(self, func: Callable[[], _F], *args: Any, **kwargs: Any) -> Any:
        """
        Führt func(*args, **kwargs) aus. Bei offenem Circuit: CircuitBreakerOpenError.
        """
        state = self._state()
        if state == "open":
            raise CircuitBreakerOpenError(self.name, self._recovery_in_seconds())

        try:
            result = func(*args, **kwargs)
            self.record_success()  # Erfolg: Zähler zurücksetzen (consecutive failures)
            if state == "half-open":
                logger.info("Circuit breaker '%s' geschlossen (Erfolg nach Recovery)", self.name)
            return result
        except Exception as e:
            self.record_failure()
            raise


async def call_async_with_circuit_breaker(
    breaker: CircuitBreaker,
    coro_func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Führt eine async Funktion mit Circuit Breaker aus.
    """
    state = breaker._state()
    if state == "open":
        raise CircuitBreakerOpenError(breaker.name, breaker._recovery_in_seconds())

    try:
        result = await coro_func(*args, **kwargs)
        breaker.record_success()
        if state == "half-open":
            logger.info("Circuit breaker '%s' geschlossen (Erfolg nach Recovery)", breaker.name)
        return result
    except Exception as e:
        breaker.record_failure()
        raise


# Singleton Circuit Breakers für externe Dependencies
circuit_docker = CircuitBreaker("docker", failure_threshold=5, recovery_timeout=60.0)
circuit_s3 = CircuitBreaker("s3", failure_threshold=5, recovery_timeout=60.0)
circuit_oauth = CircuitBreaker("oauth", failure_threshold=3, recovery_timeout=120.0)


# =============================================================================
# Retry (Tenacity)
# =============================================================================

# Retry für Netzwerk-/Transport-Fehler (Git, HTTP, S3, SMTP)
_retry_exceptions: list = [
    ConnectionError,
    TimeoutError,
    OSError,
]
try:
    import httpx
    _retry_exceptions.append(httpx.HTTPError)
except ImportError:
    pass
try:
    from botocore.exceptions import ClientError, EndpointConnectionError
    _retry_exceptions.extend([ClientError, EndpointConnectionError])
except ImportError:
    pass
RETRY_EXCEPTIONS = tuple(_retry_exceptions)


def retry_external(
    stop_attempts: int = 3,
    min_wait: float = 2.0,
    max_wait: float = 30.0,
):
    """
    Decorator für Retry mit Exponential Backoff bei externen Aufrufen.
    """
    return retry(
        stop=stop_after_attempt(stop_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(RETRY_EXCEPTIONS),
        reraise=True,
    )


async def with_retry_async(
    coro_func: Callable[..., Any],
    *args: Any,
    stop_attempts: int = 3,
    min_wait: float = 2.0,
    max_wait: float = 30.0,
    **kwargs: Any,
) -> Any:
    """
    Führt eine async Funktion mit Retry aus.
    """
    last_exc = None
    for attempt in range(1, stop_attempts + 1):
        try:
            return await coro_func(*args, **kwargs)
        except RETRY_EXCEPTIONS as e:
            last_exc = e
            if attempt < stop_attempts:
                wait = min(max_wait, min_wait * (2 ** (attempt - 1)))
                logger.warning(
                    "Retry %d/%d nach %s: %s. Warte %.1fs.",
                    attempt, stop_attempts, type(e).__name__, e, wait,
                )
                await asyncio.sleep(wait)
            else:
                raise
    raise last_exc  # type: ignore[misc]


def with_retry_sync(
    func: Callable[..., Any],
    *args: Any,
    stop_attempts: int = 3,
    min_wait: float = 2.0,
    max_wait: float = 30.0,
    **kwargs: Any,
) -> Any:
    """
    Führt eine sync Funktion mit Retry aus (für run_in_executor).
    """
    import time as _time
    last_exc = None
    for attempt in range(1, stop_attempts + 1):
        try:
            return func(*args, **kwargs)
        except RETRY_EXCEPTIONS as e:
            last_exc = e
            if attempt < stop_attempts:
                wait = min(max_wait, min_wait * (2 ** (attempt - 1)))
                logger.warning(
                    "Retry %d/%d nach %s: %s. Warte %.1fs.",
                    attempt, stop_attempts, type(e).__name__, e, wait,
                )
                _time.sleep(wait)
            else:
                raise
    raise last_exc  # type: ignore[misc]
