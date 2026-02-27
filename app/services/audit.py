"""
Audit-Log Service.

Schreibt Einträge in die audit_log-Tabelle für wichtige Aktionen
(Run starten/abbrechen, Stats zurücksetzen, User einladen/freigeben, Einstellungen ändern, etc.).
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlmodel import Session

from app.models import AuditLogEntry, User

logger = logging.getLogger(__name__)


def log_audit(
    session: Session,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    user: Optional[User] = None,
) -> None:
    """
    Schreibt einen Audit-Log-Eintrag.

    Args:
        session: SQLModel-Session (wird für commit genutzt)
        action: Aktion (z.B. run_start, run_cancel, pipeline_stats_reset, user_invite, settings_update)
        resource_type: Betroffene Ressource (pipeline, run, user, settings, secret, invite)
        resource_id: Optionale ID der Ressource (Run-ID, Pipeline-Name, User-ID, …)
        details: Optionale Zusatzdaten (z.B. {"new_run_id": "…"})
        user: Ausführender User (optional; wenn None: username="system" oder "")
    """
    try:
        username = (user.username if user else "") or "system"
        user_id = user.id if user else None
        entry = AuditLogEntry(
            user_id=user_id,
            username=username,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        session.add(entry)
        session.commit()
    except Exception as e:
        logger.warning("Audit-Log konnte nicht geschrieben werden: %s", e)
        session.rollback()
