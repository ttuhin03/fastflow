"""
Notification API Endpoints.

POST /api/notifications/send – Sendet E-Mail und/oder Teams-Benachrichtigungen per API-Key.
Für Skripte/CI; Keys werden in den Einstellungen erzeugt und verwaltet.
"""

import hashlib
import logging
import secrets as secrets_module
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import config
from app.core.database import get_session
from app.middleware.rate_limiting import get_client_identifier
from app.models import NotificationApiKey
from app.services.notifications import send_custom_email, send_custom_teams

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])

# In-Memory Rate-Limit: client_id -> list of request timestamps (last minute)
_notification_rate_limit_store: Dict[str, List[float]] = defaultdict(list)
_notification_rate_limit_cleanup_last = 0.0


def _get_client_id(request: Request) -> str:
    """Client-Identifier für Rate-Limiting (IP)."""
    return get_client_identifier(request)


def _check_notification_rate_limit() -> None:
    """Raises HTTPException 429 if rate limit exceeded."""
    global _notification_rate_limit_cleanup_last
    limit = getattr(config, "NOTIFICATION_API_RATE_LIMIT_PER_MINUTE", 30) or 30
    now = time.monotonic()
    # Gelegentlich alte Einträge aufräumen
    if now - _notification_rate_limit_cleanup_last > 60:
        _notification_rate_limit_cleanup_last = now
        cutoff = time.time() - 60
        for key in list(_notification_rate_limit_store.keys()):
            _notification_rate_limit_store[key] = [t for t in _notification_rate_limit_store[key] if t > cutoff]
            if not _notification_rate_limit_store[key]:
                del _notification_rate_limit_store[key]


def _consume_rate_limit(client_id: str) -> None:
    """Record request and raise 429 if over limit."""
    _check_notification_rate_limit()
    limit = getattr(config, "NOTIFICATION_API_RATE_LIMIT_PER_MINUTE", 30) or 30
    now = time.time()
    window_start = now - 60
    times = _notification_rate_limit_store[client_id]
    times = [t for t in times if t > window_start]
    if len(times) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate-Limit überschritten (max {limit} Anfragen pro Minute)",
        )
    times.append(now)
    _notification_rate_limit_store[client_id] = times


def _hash_key(key: str) -> str:
    """Hash for storage/lookup only. Key is high-entropy (e.g. token_urlsafe(32));
    SHA-256 is appropriate here. Not for password hashing (use bcrypt/Argon2)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _validate_notification_key(session: Session, provided_key: str) -> bool:
    """Constant-time Vergleich gegen alle gespeicherten Key-Hashes."""
    if not provided_key or not provided_key.strip():
        return False
    key_hash = _hash_key(provided_key.strip())
    rows = session.exec(select(NotificationApiKey)).all()
    for row in rows:
        if secrets_module.compare_digest(key_hash, row.key_hash):
            return True
    return False


class NotificationSendRequest(BaseModel):
    """Body für POST /api/notifications/send."""
    subject: str
    body: str
    recipients: Optional[List[str]] = None
    channels: Optional[List[str]] = None  # ["email", "teams"], default: beide wenn konfiguriert


class NotificationSendResponse(BaseModel):
    status: str
    message: str


@router.post("/send", response_model=NotificationSendResponse)
async def send_notification(
    request: Request,
    body: NotificationSendRequest,
    session: Session = Depends(get_session),
) -> NotificationSendResponse:
    """
    Sendet E-Mail und/oder Teams-Benachrichtigung (für Skripte).
    Erfordert Header X-Notification-Key mit einem gültigen API-Key.
    """
    if not getattr(config, "NOTIFICATION_API_ENABLED", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Benachrichtigungs-API ist deaktiviert (in Einstellungen aktivieren)",
        )
    api_key = request.headers.get("X-Notification-Key") or request.headers.get("x-notification-key")
    if not _validate_notification_key(session, api_key or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger oder fehlender API-Key (Header: X-Notification-Key)",
        )
    client_id = _get_client_id(request)
    _consume_rate_limit(client_id)

    channels = body.channels if body.channels is not None else ["email", "teams"]
    send_email = "email" in channels and config.EMAIL_ENABLED
    send_teams = "teams" in channels and config.TEAMS_ENABLED and config.TEAMS_WEBHOOK_URL

    if not send_email and not send_teams:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Weder E-Mail noch Teams konfiguriert oder in channels angegeben",
        )

    if not body.subject or not body.body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="subject und body sind erforderlich",
        )

    messages = []
    try:
        if send_email:
            await send_custom_email(body.subject, body.body, body.recipients)
            messages.append("E-Mail gesendet")
        if send_teams:
            await send_custom_teams(body.subject, body.body)
            messages.append("Teams-Nachricht gesendet")
    except Exception as e:
        logger.exception("Notification API send failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Senden: {str(e)}",
        ) from e

    return NotificationSendResponse(
        status="success",
        message="; ".join(messages),
    )
