"""
Product Analytics (Phase 2 Telemetrie).

Zentrale track_event und Wrapper für Backend-Events. Respektiert
SystemSettings.enable_telemetry. distinct_id = telemetry_distinct_id (eine
UUID pro Instanz) für anonyme Auswertung von aktiven Instanzen.
"""

import logging
import os
import shutil
from typing import Any, Dict, Optional

from sqlmodel import Session, select, func

from app.config import config
from app.database import database_url
from app.models import ScheduledJob, User
from app.pipeline_discovery import discover_pipelines
from app.posthog_client import (
    _scrub_properties,
    get_distinct_id,
    get_posthog_client_for_telemetry,
)

logger = logging.getLogger(__name__)


def _base_properties() -> Dict[str, Any]:
    return {
        "ff_version": config.VERSION,
        "source": "backend",
        "env": config.ENVIRONMENT,
        # Server-side Backend: keine Person-Profile für Instanz-UUIDs (vgl. PostHog-Docs)
        "$process_person_profile": False,
    }


def _users_bucket(count: int) -> str:
    if count <= 1:
        return "1"
    if count <= 5:
        return "2-5"
    if count <= 10:
        return "6-10"
    if count <= 50:
        return "11-50"
    return "51+"


def track_event(
    session: Session,
    event_name: str,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Sendet Event an PostHog, wenn enable_telemetry und Client verfügbar.
    distinct_id = telemetry_distinct_id (eine UUID pro Instanz).
    Properties werden mit _scrub_properties bereinigt.
    """
    client = get_posthog_client_for_telemetry(session)
    if client is None:
        return
    base = _base_properties()
    merged = {**base, **(properties or {})}
    props = _scrub_properties(merged)
    try:
        did = get_distinct_id(session)
        # PostHog capture(event, distinct_id=…, properties=…), vgl. Product Analytics Installation
        client.capture(event_name, distinct_id=did, properties=props)
    except Exception as e:
        logger.warning("PostHog track_event fehlgeschlagen: %s", e)


# --- User ---


def track_user_registered(
    session: Session,
    provider: str,
    invitation: bool,
    initial_admin: bool,
    anklopfen: bool,
) -> None:
    """Neuer User via OAuth: Einladung, Anklopfen oder INITIAL_ADMIN."""
    track_event(
        session,
        "user_registered",
        {
            "provider": provider,
            "invitation": invitation,
            "initial_admin": initial_admin,
            "anklopfen": anklopfen,
        },
    )


def track_user_logged_in(
    session: Session,
    provider: str,
    is_new_user: bool,
) -> None:
    """Login (GitHub oder Google). provider für Auswertung GitHub vs. Google."""
    track_event(
        session,
        "user_logged_in",
        {"provider": provider, "is_new_user": is_new_user},
    )


# --- Pipeline ---


def track_pipeline_run_started(
    session: Session,
    pipeline_name: str,
    triggered_by: str,
    has_requirements: bool,
) -> None:
    """Run gestartet (manual, webhook, scheduler)."""
    track_event(
        session,
        "pipeline_run_started",
        {
            "pipeline_name": pipeline_name,
            "triggered_by": triggered_by,
            "has_requirements": has_requirements,
        },
    )


def track_pipeline_run_finished(
    session: Session,
    pipeline_name: str,
    status: str,
    triggered_by: str,
    duration_seconds: Optional[float],
    has_requirements: bool,
) -> None:
    """Run beendet; bei status=SUCCESS für Erfolgsauswertung."""
    props = {
        "pipeline_name": pipeline_name,
        "status": status,
        "triggered_by": triggered_by,
        "has_requirements": has_requirements,
    }
    if duration_seconds is not None:
        props["duration_seconds"] = round(duration_seconds, 2)
    track_event(session, "pipeline_run_finished", props)


# --- Sync ---


def track_sync_completed(
    session: Session,
    branch: str,
    duration_seconds: float,
    pipelines_discovered: int,
    pipelines_pre_heated: int,
    pre_heat_failures: int,
) -> None:
    """Git-Sync erfolgreich abgeschlossen."""
    track_event(
        session,
        "sync_completed",
        {
            "branch": branch,
            "duration_seconds": round(duration_seconds, 2),
            "pipelines_discovered": pipelines_discovered,
            "pipelines_pre_heated": pipelines_pre_heated,
            "pre_heat_failures": pre_heat_failures,
            "uv_pre_heat_enabled": config.UV_PRE_HEAT,
        },
    )


def track_sync_failed(session: Session, branch: str, error_type: str) -> None:
    """Git-Sync fehlgeschlagen."""
    track_event(
        session,
        "sync_failed",
        {"branch": branch, "error_type": error_type},
    )


# --- Instance (Heartbeat + Storage/RAM/CPU) ---


def _collect_storage_and_system(session: Session) -> Dict[str, Any]:
    """Sammelt Speicher- und System-Metriken (Logs, DB, Disk, RAM, CPU)."""
    from sqlmodel import text

    out: Dict[str, Any] = {}
    logs_dir = config.LOGS_DIR

    # Log-Dateien
    log_files_count = 0
    log_files_size_bytes = 0
    if logs_dir.exists():
        for p in logs_dir.rglob("*"):
            if p.is_file():
                log_files_count += 1
                try:
                    log_files_size_bytes += p.stat().st_size
                except (OSError, PermissionError):
                    pass
    out["log_files_count"] = log_files_count
    out["log_files_size_mb"] = round(log_files_size_bytes / (1024 * 1024), 2)

    # Disk
    try:
        disk = shutil.disk_usage(logs_dir if logs_dir.exists() else "/")
        out["free_disk_gb"] = round(disk.free / (1024 ** 3), 2)
    except (OSError, PermissionError):
        out["free_disk_gb"] = None

    # DB-Größe
    try:
        if database_url.startswith("sqlite"):
            db_path = database_url.replace("sqlite:///", "")
            n = 0
            if os.path.exists(db_path):
                n += os.path.getsize(db_path)
            for ext in ("-wal", "-shm"):
                if os.path.exists(db_path + ext):
                    n += os.path.getsize(db_path + ext)
            out["database_size_mb"] = round(n / (1024 * 1024), 2)
        else:
            r = session.exec(text("SELECT pg_database_size(current_database())")).first()
            out["database_size_mb"] = round((r or 0) / (1024 * 1024), 2)
    except Exception:
        out["database_size_mb"] = None

    # RAM & CPU (psutil)
    try:
        import psutil

        mem = psutil.virtual_memory()
        out["system_ram_total_mb"] = round(mem.total / (1024 * 1024), 2)
        out["system_ram_percent"] = round(mem.percent, 2)
        out["system_cpu_percent"] = round(psutil.cpu_percent(interval=0.1), 2)
    except Exception:
        out["system_ram_total_mb"] = None
        out["system_ram_percent"] = None
        out["system_cpu_percent"] = None

    return out


def track_instance_heartbeat(session: Session) -> None:
    """
    Täglicher Instance-Heartbeat: ff_version, total_pipelines, total_scheduled_jobs,
    total_users_bucket, uv_pre_heat_enabled, pipelines_with_requirements, db_kind.
    Zusätzlich einmal täglich: instance_storage mit log_files_count, log_files_size_mb,
    database_size_mb, free_disk_gb, system_ram_total_mb, system_ram_percent, system_cpu_percent.
    """
    discovered = discover_pipelines()
    total_pipelines = len(discovered)
    pipelines_with_requirements = sum(1 for p in discovered if p.has_requirements)

    total_scheduled = session.exec(select(func.count(ScheduledJob.id))).one() or 0
    total_users = session.exec(select(func.count(User.id))).one() or 0
    total_users_bucket = _users_bucket(total_users)

    db_kind = "sqlite" if database_url.startswith("sqlite") else "postgres"

    props = {
        "ff_version": config.VERSION,
        "total_pipelines": total_pipelines,
        "total_scheduled_jobs": total_scheduled,
        "total_users_bucket": total_users_bucket,
        "uv_pre_heat_enabled": config.UV_PRE_HEAT,
        "pipelines_with_requirements": pipelines_with_requirements,
        "db_kind": db_kind,
    }

    extra = _collect_storage_and_system(session)
    props["log_files_count"] = extra.get("log_files_count", 0)
    props["log_files_size_mb"] = extra.get("log_files_size_mb")
    props["database_size_mb"] = extra.get("database_size_mb")
    props["free_disk_gb"] = extra.get("free_disk_gb")
    props["system_ram_total_mb"] = extra.get("system_ram_total_mb")
    props["system_ram_percent"] = extra.get("system_ram_percent")
    props["system_cpu_percent"] = extra.get("system_cpu_percent")

    track_event(session, "instance_heartbeat", props)


def run_instance_heartbeat_sync() -> None:
    """
    Synchrone Ausführung für den Scheduler: einmal täglich instance_heartbeat
    inkl. Storage/RAM/CPU senden. Nur aktiv wenn enable_telemetry.
    """
    try:
        from sqlmodel import Session

        from app.database import engine

        with Session(engine) as session:
            track_instance_heartbeat(session)
    except Exception as e:
        logger.warning("Telemetry instance_heartbeat fehlgeschlagen: %s", e)


def schedule_telemetry_heartbeat() -> None:
    """Planiert den täglichen instance_heartbeat um 03:00 UTC."""
    try:
        from apscheduler.triggers.cron import CronTrigger

        from app.scheduler import get_scheduler

        s = get_scheduler()
        if s is None or not s.running:
            return
        s.add_job(
            run_instance_heartbeat_sync,
            trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
            id="telemetry_instance_heartbeat",
            name="Telemetry Instance Heartbeat",
            replace_existing=True,
        )
        logger.info("Telemetry instance_heartbeat geplant: täglich 03:00 UTC")
    except Exception as e:
        logger.warning("Telemetry Heartbeat konnte nicht geplant werden: %s", e)
