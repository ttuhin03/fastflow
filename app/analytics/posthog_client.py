"""
PostHog Client Module (Phase 1: Error-Tracking).

Lazy-Init, Exception-Autocapture, capture_exception, Data-Scrubbing.
Phase 2: track_event, pipeline_run_started, Session Replay, Product Analytics.
"""

import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlmodel import Session

from app.core.config import config
from app.models import SystemSettings

logger = logging.getLogger(__name__)

_posthog_client: Optional[Any] = None  # Posthog | None
_SENSITIVE_SUBSTRINGS = ("password", "secret", "api_key", "token")


def get_system_settings(session: Session) -> SystemSettings:
    """
    Liest SystemSettings-Singleton (id=1). Legt mit Defaults an, falls nicht vorhanden.
    """
    ss = session.get(SystemSettings, 1)
    if ss is None:
        ss = SystemSettings(
            id=1,
            is_setup_completed=False,
            enable_telemetry=False,
            enable_error_reporting=False,
            dependency_audit_enabled=False,
            dependency_audit_cron="0 3 * * *",
        )
        session.add(ss)
        session.commit()
        session.refresh(ss)
    return ss


def _scrub_properties(properties: Dict[str, Any]) -> Dict[str, Any]:
    """
    Entfernt oder redigiert Keys, die password, secret, api_key, token enthalten
    (case-insensitiv). Rekursiv für verschachtelte Dicts.
    """
    out: Dict[str, Any] = {}
    for k, v in properties.items():
        kl = k.lower()
        if any(s in kl for s in _SENSITIVE_SUBSTRINGS):
            out[k] = "[REDACTED]"
        elif isinstance(v, dict):
            out[k] = _scrub_properties(v)
        else:
            out[k] = v
    return out


def get_distinct_id(session: Session) -> str:
    """
    Anonyme UUID für PostHog distinct_id. Wird in SystemSettings gespeichert.
    Keine E-Mail/Klarnamen.
    """
    ss = get_system_settings(session)
    if ss.telemetry_distinct_id:
        return ss.telemetry_distinct_id
    did = str(uuid4())
    ss.telemetry_distinct_id = did
    session.add(ss)
    session.commit()
    return did


def _get_or_create_client(session: Session) -> Optional[Any]:
    """
    Lazy-Init: PostHog-Client bei enable_error_reporting ODER enable_telemetry.
    enable_exception_autocapture=True. Host und API-Key aus config (fest).
    """
    global _posthog_client

    if not config.POSTHOG_API_KEY:
        return None
    ss = get_system_settings(session)
    if not ss.enable_error_reporting and not ss.enable_telemetry:
        return None

    if _posthog_client is not None:
        return _posthog_client

    try:
        from posthog import Posthog

        _posthog_client = Posthog(
            project_api_key=config.POSTHOG_API_KEY,
            host=config.POSTHOG_HOST,
            enable_exception_autocapture=True,
        )
        logger.info(
            "PostHog-Client initialisiert (host=%s, exception_autocapture=True)",
            config.POSTHOG_HOST,
        )
        return _posthog_client
    except Exception as e:
        logger.warning("PostHog-Init fehlgeschlagen: %s", e)
        return None


def get_posthog_client_for_telemetry(session: Session) -> Optional[Any]:
    """
    Gibt den PostHog-Client für Product Analytics (Telemetrie) zurück.
    Nur wenn enable_telemetry=True und API-Key gesetzt. Init erfolgt via _get_or_create_client.
    """
    if not config.POSTHOG_API_KEY:
        return None
    ss = get_system_settings(session)
    if not ss.enable_telemetry:
        return None
    return _get_or_create_client(session)


def shutdown_posthog() -> None:
    """Flush und Shutdown des PostHog-Clients. Bei enable_error_reporting=False oder beim App-Exit aufrufen."""
    global _posthog_client
    if _posthog_client is not None:
        try:
            _posthog_client.shutdown()
        except Exception as e:
            logger.warning("PostHog shutdown: %s", e)
        _posthog_client = None
        logger.debug("PostHog-Client heruntergefahren")


def capture_exception(
    exception: BaseException,
    session: Session,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Sendet Exception an PostHog, wenn enable_error_reporting und Client verfügbar.
    Properties werden mit _scrub_properties bereinigt.
    """
    if properties is None:
        properties = {}
    ss = get_system_settings(session)
    if not ss.enable_error_reporting:
        return
    client = _get_or_create_client(session)
    if client is None:
        return
    try:
        did = get_distinct_id(session)
        props = _scrub_properties(properties)
        client.capture_exception(exception, distinct_id=did, properties=props)
    except Exception as e:
        logger.warning("PostHog capture_exception fehlgeschlagen: %s", e)


def capture_startup_test_exception() -> None:
    """
    In ENVIRONMENT=development: sendet immer eine Test-Exception an PostHog,
    unabhängig von enable_error_reporting. Einmaliger Client, flush, shutdown.
    """
    if config.ENVIRONMENT != "development" or not config.POSTHOG_API_KEY:
        return
    try:
        from posthog import Posthog

        ph = Posthog(project_api_key=config.POSTHOG_API_KEY, host=config.POSTHOG_HOST)
        exc = RuntimeError(
            "Fast-Flow Startup-Test: Test-Exception für PostHog (ENVIRONMENT=development). "
            "Kein echter Fehler – nur Verifikation. $fastflow_startup_test=True."
        )
        ph.capture_exception(
            exc,
            distinct_id="fastflow-startup-test",
            properties={
                "$fastflow_startup_test": True,
                "description": "Startup-Verifikation (Dev): immer gesendet, unabhängig von enable_error_reporting.",
                "$current_url": "(startup)",
                "$request_path": "(startup)",
            },
        )
        ph.flush()
        ph.shutdown()
        logger.info("PostHog Startup-Test-Exception gesendet (development, immer).")
    except Exception as e:
        logger.warning("PostHog Startup-Test übersprungen: %s", e)


# track_event wird von app.analytics bereitgestellt (Phase 2).
# Stub hier entfernt; Analytics-Modul nutzt get_posthog_client_for_telemetry.
