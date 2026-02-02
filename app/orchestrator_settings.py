"""
Orchestrator Settings Module.

Liest und schreibt persistente Einstellungen aus der Settings-UI in der DB.
Beim App-Start werden DB-Werte auf config angewendet (Override von Env).
"""

import logging
from typing import List, Optional

from sqlmodel import Session

from app.config import config
from app.models import OrchestratorSettings
from app.secrets import decrypt, encrypt

logger = logging.getLogger(__name__)


def get_orchestrator_settings(session: Session) -> Optional[OrchestratorSettings]:
    """
    Liest das OrchestratorSettings-Singleton (id=1).
    Gibt None zurück, wenn keine Zeile existiert (vor erster Migration/Nutzung).
    """
    return session.get(OrchestratorSettings, 1)


def get_orchestrator_settings_or_default(session: Session) -> OrchestratorSettings:
    """
    Liest OrchestratorSettings (id=1) oder legt eine Zeile mit Defaults (alle None) an.
    """
    row = session.get(OrchestratorSettings, 1)
    if row is None:
        row = OrchestratorSettings(id=1)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def apply_orchestrator_settings_to_config(settings: OrchestratorSettings) -> None:
    """
    Wendet gespeicherte Einstellungen auf die laufende config an.
    Nur Felder mit Wert != None überschreiben die aktuellen config-Werte.
    """
    if settings.log_retention_runs is not None:
        config.LOG_RETENTION_RUNS = settings.log_retention_runs
    if settings.log_retention_days is not None:
        config.LOG_RETENTION_DAYS = settings.log_retention_days
    if settings.log_max_size_mb is not None:
        config.LOG_MAX_SIZE_MB = settings.log_max_size_mb
    if settings.max_concurrent_runs is not None:
        config.MAX_CONCURRENT_RUNS = settings.max_concurrent_runs
    if settings.container_timeout is not None:
        config.CONTAINER_TIMEOUT = settings.container_timeout
    if settings.retry_attempts is not None:
        config.RETRY_ATTEMPTS = settings.retry_attempts
    if settings.auto_sync_enabled is not None:
        config.AUTO_SYNC_ENABLED = settings.auto_sync_enabled
    if settings.auto_sync_interval is not None:
        config.AUTO_SYNC_INTERVAL = settings.auto_sync_interval
    if settings.email_enabled is not None:
        config.EMAIL_ENABLED = settings.email_enabled
    if settings.smtp_host is not None:
        config.SMTP_HOST = settings.smtp_host
    if settings.smtp_port is not None:
        config.SMTP_PORT = settings.smtp_port
    if settings.smtp_user is not None:
        config.SMTP_USER = settings.smtp_user
    if settings.smtp_password_encrypted is not None:
        try:
            config.SMTP_PASSWORD = decrypt(settings.smtp_password_encrypted)
        except Exception as e:
            logger.warning("SMTP-Passwort aus DB konnte nicht entschlüsselt werden: %s", e)
    if settings.smtp_from is not None:
        config.SMTP_FROM = settings.smtp_from
    if settings.email_recipients is not None:
        config.EMAIL_RECIPIENTS = _parse_email_recipients(settings.email_recipients)
    if settings.teams_enabled is not None:
        config.TEAMS_ENABLED = settings.teams_enabled
    if settings.teams_webhook_url is not None:
        config.TEAMS_WEBHOOK_URL = settings.teams_webhook_url


def _parse_email_recipients(value: Optional[str]) -> List[str]:
    """Komma-separierte E-Mail-Liste zu Liste parsen."""
    if not value or not value.strip():
        return []
    return [e.strip() for e in value.split(",") if e.strip()]
