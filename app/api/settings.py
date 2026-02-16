"""
Settings API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für System-Einstellungen:
- Konfiguration abrufen/aktualisieren
- Force Flush (manueller Cleanup)
- Log-Dateien-Statistiken
"""

import os
import shutil
import logging
import psutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session

from app.core.database import get_session, database_url, engine
from app.core.config import config
from app.services.cleanup import cleanup_logs, cleanup_docker_resources
from app.services.s3_backup import get_backup_failures, get_last_backup_timestamp
from app.models import PipelineRun, RunStatus, User
from app.services.notifications import send_email_notification, send_teams_notification
from app.executor import _get_docker_client
from app.executor.kubernetes_backend import get_kubernetes_system_metrics
from app.auth import require_admin, require_write, get_current_user
from app.analytics.posthog_client import get_system_settings, shutdown_posthog, capture_exception
from app.core.errors import get_500_detail
from app.services.orchestrator_settings import (
    get_orchestrator_settings_or_default,
    apply_orchestrator_settings_to_config,
)
from app.services.secrets import encrypt
from app.services.dependency_audit import get_last_dependency_audit
from sqlmodel import text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class TelemetryStatusResponse(BaseModel):
    """Öffentliche Konfiguration für Frontend PostHog (Phase 2a: Error-Tracking). Kein Auth."""
    enable_error_reporting: bool
    posthog_api_key: str
    posthog_host: str


@router.get("/telemetry-status", response_model=TelemetryStatusResponse)
async def get_telemetry_status(
    session: Session = Depends(get_session),
) -> TelemetryStatusResponse:
    """
    Gibt PostHog-Client-Konfiguration für Frontend (Phase 2a).
    Öffentlich (kein Auth), damit Login- und Fehlerseiten auch tracken können.
    """
    enable = False
    try:
        ss = get_system_settings(session)
        enable = bool(ss.enable_error_reporting)
    except Exception as e:
        logger.debug("telemetry-status: SystemSettings nicht lesbar, enable_error_reporting=false: %s", e)
    return TelemetryStatusResponse(
        enable_error_reporting=enable,
        posthog_api_key=config.POSTHOG_API_KEY,
        posthog_host=config.POSTHOG_HOST,
    )


class SettingsResponse(BaseModel):
    """Response-Model für System-Einstellungen."""
    log_retention_runs: Optional[int]
    log_retention_days: Optional[int]
    log_max_size_mb: Optional[int]
    max_concurrent_runs: int
    container_timeout: Optional[int]
    retry_attempts: int
    auto_sync_enabled: bool
    auto_sync_interval: Optional[int]
    email_enabled: bool
    smtp_host: Optional[str]
    smtp_port: int
    smtp_user: Optional[str]
    smtp_from: Optional[str]
    email_recipients: List[str]
    teams_enabled: bool
    teams_webhook_url: Optional[str]


class SystemSettingsResponse(BaseModel):
    """Response für System-Konfiguration (Wizard, Nutzer-Tab, Abhängigkeiten-Audit)."""
    is_setup_completed: bool
    enable_telemetry: bool
    enable_error_reporting: bool
    dependency_audit_enabled: bool = True
    dependency_audit_cron: str = "0 3 * * *"


class SystemSettingsUpdate(BaseModel):
    """Request für System-Konfiguration (nur übergebene Felder werden aktualisiert)."""
    is_setup_completed: Optional[bool] = None
    enable_telemetry: Optional[bool] = None
    enable_error_reporting: Optional[bool] = None
    dependency_audit_enabled: Optional[bool] = None
    dependency_audit_cron: Optional[str] = None


class SettingsUpdate(BaseModel):
    """Request-Model für Einstellungs-Updates."""
    log_retention_runs: Optional[int] = None
    log_retention_days: Optional[int] = None
    log_max_size_mb: Optional[int] = None
    max_concurrent_runs: Optional[int] = None
    container_timeout: Optional[int] = None
    retry_attempts: Optional[int] = None
    auto_sync_enabled: Optional[bool] = None
    auto_sync_interval: Optional[int] = None
    email_enabled: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    email_recipients: Optional[str] = None  # Komma-separiert als String
    teams_enabled: Optional[bool] = None
    teams_webhook_url: Optional[str] = None


@router.get("", response_model=SettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user)
) -> SettingsResponse:
    """
    Gibt die aktuellen System-Einstellungen zurück.
    
    Returns:
        SettingsResponse: Aktuelle Konfigurationswerte
    """
    return SettingsResponse(
        log_retention_runs=config.LOG_RETENTION_RUNS,
        log_retention_days=config.LOG_RETENTION_DAYS,
        log_max_size_mb=config.LOG_MAX_SIZE_MB,
        max_concurrent_runs=config.MAX_CONCURRENT_RUNS,
        container_timeout=config.CONTAINER_TIMEOUT,
        retry_attempts=config.RETRY_ATTEMPTS,
        auto_sync_enabled=config.AUTO_SYNC_ENABLED,
        auto_sync_interval=config.AUTO_SYNC_INTERVAL,
        email_enabled=config.EMAIL_ENABLED,
        smtp_host=config.SMTP_HOST,
        smtp_port=config.SMTP_PORT,
        smtp_user=config.SMTP_USER,
        smtp_from=config.SMTP_FROM,
        email_recipients=config.EMAIL_RECIPIENTS,
        teams_enabled=config.TEAMS_ENABLED,
        teams_webhook_url=config.TEAMS_WEBHOOK_URL,
    )


@router.put("", response_model=Dict[str, str])
async def update_settings(
    settings: SettingsUpdate,
    current_user = Depends(require_write),
    session: Session = Depends(get_session)
) -> Dict[str, str]:
    """
    Aktualisiert System-Einstellungen und speichert sie in der Datenbank.
    Die laufende config wird sofort aktualisiert; ein Neustart ist nicht nötig.
    """
    row = get_orchestrator_settings_or_default(session)
    if settings.log_retention_runs is not None:
        row.log_retention_runs = settings.log_retention_runs
    if settings.log_retention_days is not None:
        row.log_retention_days = settings.log_retention_days
    if settings.log_max_size_mb is not None:
        row.log_max_size_mb = settings.log_max_size_mb
    if settings.max_concurrent_runs is not None:
        row.max_concurrent_runs = settings.max_concurrent_runs
    if settings.container_timeout is not None:
        row.container_timeout = settings.container_timeout
    if settings.retry_attempts is not None:
        row.retry_attempts = settings.retry_attempts
    if settings.auto_sync_enabled is not None:
        row.auto_sync_enabled = settings.auto_sync_enabled
    if settings.auto_sync_interval is not None:
        row.auto_sync_interval = settings.auto_sync_interval
    if settings.email_enabled is not None:
        row.email_enabled = settings.email_enabled
    if settings.smtp_host is not None:
        row.smtp_host = settings.smtp_host
    if settings.smtp_port is not None:
        row.smtp_port = settings.smtp_port
    if settings.smtp_user is not None:
        row.smtp_user = settings.smtp_user
    if settings.smtp_password is not None:
        row.smtp_password_encrypted = encrypt(settings.smtp_password)
    if settings.smtp_from is not None:
        row.smtp_from = settings.smtp_from
    if settings.email_recipients is not None:
        row.email_recipients = settings.email_recipients
    if settings.teams_enabled is not None:
        row.teams_enabled = settings.teams_enabled
    if settings.teams_webhook_url is not None:
        row.teams_webhook_url = settings.teams_webhook_url
    session.add(row)
    session.commit()
    session.refresh(row)
    apply_orchestrator_settings_to_config(row)
    return {
        "message": "Einstellungen wurden gespeichert und sind sofort aktiv."
    }


@router.get("/system", response_model=SystemSettingsResponse)
async def get_system_settings_endpoint(
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> SystemSettingsResponse:
    """
    Gibt System-Konfiguration zurück (is_setup_completed, enable_telemetry, enable_error_reporting).
    Nur für Admins.
    """
    ss = get_system_settings(session)
    return SystemSettingsResponse(
        is_setup_completed=ss.is_setup_completed,
        enable_telemetry=ss.enable_telemetry,
        enable_error_reporting=ss.enable_error_reporting,
        dependency_audit_enabled=getattr(ss, "dependency_audit_enabled", True),
        dependency_audit_cron=getattr(ss, "dependency_audit_cron", "0 3 * * *") or "0 3 * * *",
    )


class DependencyAuditLastResponse(BaseModel):
    """Ergebnisse des letzten Dependency-Audit-Durchgangs (Startup oder Cron-Job)."""
    last_scan_at: Optional[str] = None  # ISO 8601
    results: List[Dict[str, Any]] = []  # [{ pipeline, packages, vulnerabilities?, audit_error? }, ...]


@router.get("/dependency-audit-last", response_model=DependencyAuditLastResponse)
async def get_dependency_audit_last(
    current_user: User = Depends(get_current_user),
) -> DependencyAuditLastResponse:
    """
    Gibt Zeitpunkt und Ergebnisse des letzten Dependency-Audit-Durchgangs zurück.
    Der Scan läuft beim API-Start und optional per Cron. Erfordert Authentifizierung.
    """
    last_at, results = get_last_dependency_audit()
    return DependencyAuditLastResponse(
        last_scan_at=last_at.isoformat() if last_at else None,
        results=results,
    )


@router.put("/system", response_model=SystemSettingsResponse)
async def update_system_settings_endpoint(
    body: SystemSettingsUpdate,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> SystemSettingsResponse:
    """
    Aktualisiert System-Konfiguration. Nur übergebene Felder werden geändert.
    Wenn enable_error_reporting auf False gesetzt wird: PostHog-Client shutdown.
    """
    ss = get_system_settings(session)
    if body.is_setup_completed is not None:
        ss.is_setup_completed = body.is_setup_completed
    if body.enable_telemetry is not None:
        ss.enable_telemetry = body.enable_telemetry
    if body.enable_error_reporting is not None:
        ss.enable_error_reporting = body.enable_error_reporting
    if body.dependency_audit_enabled is not None:
        ss.dependency_audit_enabled = body.dependency_audit_enabled
    if body.dependency_audit_cron is not None:
        ss.dependency_audit_cron = (body.dependency_audit_cron or "0 3 * * *").strip()
    session.add(ss)
    session.commit()
    session.refresh(ss)
    if ss.enable_error_reporting is False:
        shutdown_posthog()
    # Dependency-Audit-Job neu planen (Cron/Enabled geändert)
    try:
        from app.services.dependency_audit import schedule_dependency_audit_job
        schedule_dependency_audit_job()
    except Exception as e:
        logger.warning("Dependency-Audit-Job nach Einstellungs-Update nicht neu geplant: %s", e)
    return SystemSettingsResponse(
        is_setup_completed=ss.is_setup_completed,
        enable_telemetry=ss.enable_telemetry,
        enable_error_reporting=ss.enable_error_reporting,
        dependency_audit_enabled=getattr(ss, "dependency_audit_enabled", True),
        dependency_audit_cron=getattr(ss, "dependency_audit_cron", "0 3 * * *") or "0 3 * * *",
    )


@router.post("/trigger-test-exception")
async def trigger_test_exception_backend(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Dict[str, str]:
    """
    Nur in ENVIRONMENT=development. Sendet eine Test-Exception an PostHog (Backend).
    Nur wirksam, wenn Fehlerberichte (enable_error_reporting) aktiviert sind.
    """
    if config.ENVIRONMENT != "development":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nur in ENVIRONMENT=development verfügbar.",
        )
    u = str(request.url)
    url_no_query = u.split("?")[0] if "?" in u else u
    exc = RuntimeError(
        "Fast-Flow Backend-Test: Test-Exception für PostHog (manuell aus Einstellungen, ENVIRONMENT=development). "
        "Kein echter Fehler. $fastflow_backend_test=True."
    )
    capture_exception(
        exc,
        session,
        properties={
            "$fastflow_backend_test": True,
            "description": "Manuell aus Einstellungen ausgelöst (Backend).",
            "$current_url": url_no_query,
            "$request_path": request.url.path,
            "$request_method": request.method,
        },
    )
    return {"message": "Test-Exception an PostHog gesendet (Backend). In PostHog prüfen."}


@router.get("/storage", response_model=Dict[str, Any])
async def get_storage_stats(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Gibt Speicherplatz-Statistiken zurück.
    
    Returns:
        Dictionary mit:
        - log_files_count: Anzahl Log-Dateien
        - log_files_size_bytes: Gesamtgröße der Log-Dateien in Bytes
        - log_files_size_mb: Gesamtgröße der Log-Dateien in MB
        - total_disk_space_bytes: Gesamter Speicherplatz in Bytes
        - total_disk_space_gb: Gesamter Speicherplatz in GB
        - used_disk_space_bytes: Verwendeter Speicherplatz in Bytes
        - used_disk_space_gb: Verwendeter Speicherplatz in GB
        - free_disk_space_bytes: Freier Speicherplatz in Bytes
        - free_disk_space_gb: Freier Speicherplatz in GB
        - log_files_percentage: Anteil der Log-Dateien am Gesamtspeicherplatz in Prozent
        - database_size_bytes: Größe der Datenbank in Bytes (falls verfügbar)
        - database_size_mb: Größe der Datenbank in MB (falls verfügbar)
        - database_size_gb: Größe der Datenbank in GB (falls verfügbar)
        - database_percentage: Anteil der Datenbank am Gesamtspeicherplatz in Prozent (falls verfügbar)
        - inode_total, inode_free, inode_used, inode_used_percent: Inode-Statistik (nur Unix, df -i)
    """
    try:
        logs_dir = config.LOGS_DIR
        
        # Log-Dateien zählen und Größe berechnen
        log_files_count = 0
        log_files_size_bytes = 0
        
        if logs_dir.exists():
            for file_path in logs_dir.rglob('*'):
                if file_path.is_file():
                    log_files_count += 1
                    try:
                        log_files_size_bytes += file_path.stat().st_size
                    except (OSError, PermissionError):
                        # Datei kann nicht gelesen werden, überspringen
                        pass
        
        log_files_size_mb = log_files_size_bytes / (1024 * 1024)
        
        # Gesamten Speicherplatz ermitteln
        total_disk_space_bytes = 0
        used_disk_space_bytes = 0
        free_disk_space_bytes = 0
        
        try:
            # Versuche Speicherplatz-Informationen zu erhalten
            # shutil.disk_usage gibt (total, used, free) zurück
            if logs_dir.exists():
                disk_usage = shutil.disk_usage(logs_dir)
                total_disk_space_bytes = disk_usage.total
                used_disk_space_bytes = disk_usage.used
                free_disk_space_bytes = disk_usage.free
            else:
                # Fallback: Root-Verzeichnis
                disk_usage = shutil.disk_usage('/')
                total_disk_space_bytes = disk_usage.total
                used_disk_space_bytes = disk_usage.used
                free_disk_space_bytes = disk_usage.free
        except (OSError, PermissionError):
            # Kann nicht ermittelt werden
            pass

        # Inodes (df -i): oft Problem bei vielen kleinen Dateien
        inode_total: Optional[int] = None
        inode_free: Optional[int] = None
        inode_used_percent: Optional[float] = None
        if hasattr(os, "statvfs"):
            try:
                stat_path = str(logs_dir) if logs_dir.exists() else "/"
                st = os.statvfs(stat_path)
                inode_total = st.f_files
                inode_free = getattr(st, "f_favail", st.f_ffree)
                inode_used = inode_total - inode_free
                inode_used_percent = (inode_used / inode_total * 100) if inode_total else None
            except (OSError, PermissionError, AttributeError):
                pass

        total_disk_space_gb = total_disk_space_bytes / (1024 * 1024 * 1024)
        used_disk_space_gb = used_disk_space_bytes / (1024 * 1024 * 1024)
        free_disk_space_gb = free_disk_space_bytes / (1024 * 1024 * 1024)
        
        # Anteil der Log-Dateien am Gesamtspeicherplatz
        log_files_percentage = 0.0
        if total_disk_space_bytes > 0:
            log_files_percentage = (log_files_size_bytes / total_disk_space_bytes) * 100
        
        # Datenbank-Größe ermitteln
        database_size_bytes = 0
        database_size_mb = 0.0
        database_size_gb = 0.0
        database_percentage = 0.0
        
        try:
            if database_url.startswith("sqlite"):
                # SQLite: Dateigröße direkt ermitteln
                db_path = database_url.replace("sqlite:///", "")
                if os.path.exists(db_path):
                    database_size_bytes = os.path.getsize(db_path)
                    # Auch WAL-Datei berücksichtigen
                    wal_path = f"{db_path}-wal"
                    if os.path.exists(wal_path):
                        database_size_bytes += os.path.getsize(wal_path)
                    # Auch SHM-Datei berücksichtigen
                    shm_path = f"{db_path}-shm"
                    if os.path.exists(shm_path):
                        database_size_bytes += os.path.getsize(shm_path)
            else:
                # PostgreSQL: Query für Datenbankgröße
                try:
                    result = session.exec(text(
                        "SELECT pg_database_size(current_database())"
                    ))
                    size = result.scalar()
                    if size:
                        database_size_bytes = size
                except Exception:
                    # Falls Query fehlschlägt, überspringen
                    pass
            
            if database_size_bytes > 0:
                database_size_mb = database_size_bytes / (1024 * 1024)
                database_size_gb = database_size_bytes / (1024 * 1024 * 1024)
                if total_disk_space_bytes > 0:
                    database_percentage = (database_size_bytes / total_disk_space_bytes) * 100
        except Exception:
            # Datenbank-Größe kann nicht ermittelt werden, überspringen
            pass
        
        result = {
            "log_files_count": log_files_count,
            "log_files_size_bytes": log_files_size_bytes,
            "log_files_size_mb": round(log_files_size_mb, 2),
            "total_disk_space_bytes": total_disk_space_bytes,
            "total_disk_space_gb": round(total_disk_space_gb, 2),
            "used_disk_space_bytes": used_disk_space_bytes,
            "used_disk_space_gb": round(used_disk_space_gb, 2),
            "free_disk_space_bytes": free_disk_space_bytes,
            "free_disk_space_gb": round(free_disk_space_gb, 2),
            "log_files_percentage": round(log_files_percentage, 2),
        }
        if inode_total is not None and inode_free is not None:
            result["inode_total"] = inode_total
            result["inode_free"] = inode_free
            result["inode_used"] = inode_total - inode_free
            if inode_used_percent is not None:
                result["inode_used_percent"] = round(inode_used_percent, 2)

        # Datenbank-Statistiken nur hinzufügen, wenn verfügbar
        if database_size_bytes > 0:
            result.update({
                "database_size_bytes": database_size_bytes,
                "database_size_mb": round(database_size_mb, 2),
                "database_size_gb": round(database_size_gb, 2),
                "database_percentage": round(database_percentage, 2),
            })
        
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Speicherplatz-Statistiken: {str(e)}"
        )


@router.post("/test-email", response_model=Dict[str, str])
async def test_email(
    current_user: User = Depends(require_write)
) -> Dict[str, str]:
    """
    Sendet eine Test-E-Mail mit aktuellen E-Mail-Einstellungen.
    
    Returns:
        Dictionary mit Erfolgs- oder Fehlermeldung
    """
    if not config.EMAIL_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-Mail-Benachrichtigungen sind nicht aktiviert"
        )
    
    if not config.SMTP_HOST or not config.SMTP_FROM or not config.EMAIL_RECIPIENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-Mail-Konfiguration unvollständig (SMTP_HOST, SMTP_FROM, EMAIL_RECIPIENTS erforderlich)"
        )
    
    try:
        # Erstelle einen Mock-Run für Test-E-Mail
        from datetime import datetime, timezone
        from uuid import uuid4
        
        test_run = PipelineRun(
            id=uuid4(),
            pipeline_name="test-pipeline",
            status=RunStatus.FAILED,
            log_file="test.log",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            exit_code=1
        )
        
        await send_email_notification(test_run, RunStatus.FAILED)
        
        return {
            "status": "success",
            "message": f"Test-E-Mail erfolgreich an {', '.join(config.EMAIL_RECIPIENTS)} gesendet"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Senden der Test-E-Mail: {str(e)}"
        )


@router.post("/test-teams", response_model=Dict[str, str])
async def test_teams(
    current_user: User = Depends(require_write)
) -> Dict[str, str]:
    """
    Sendet eine Test-Teams-Nachricht mit aktuellen Teams-Einstellungen.
    
    Returns:
        Dictionary mit Erfolgs- oder Fehlermeldung
    """
    if not config.TEAMS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Teams-Benachrichtigungen sind nicht aktiviert"
        )
    
    if not config.TEAMS_WEBHOOK_URL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Teams-Webhook-URL ist nicht konfiguriert"
        )
    
    try:
        # Erstelle einen Mock-Run für Test-Teams-Nachricht
        from datetime import datetime, timezone
        from uuid import uuid4
        
        test_run = PipelineRun(
            id=uuid4(),
            pipeline_name="test-pipeline",
            status=RunStatus.FAILED,
            log_file="test.log",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            exit_code=1
        )
        
        await send_teams_notification(test_run, RunStatus.FAILED)
        
        return {
            "status": "success",
            "message": "Test-Teams-Nachricht erfolgreich gesendet"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Senden der Test-Teams-Nachricht: {str(e)}"
        )


class BackupFailureItem(BaseModel):
    run_id: str
    pipeline_name: str
    error_message: str
    created_at: str


class BackupFailuresResponse(BaseModel):
    failures: List[BackupFailureItem]
    last_backup_at: Optional[str] = None


@router.get("/backup-failures", response_model=BackupFailuresResponse)
async def get_backup_failures_endpoint(
    current_user: User = Depends(get_current_user),
) -> BackupFailuresResponse:
    """
    Gibt die letzten S3-Backup-Fehler und den Zeitstempel des letzten erfolgreichen
    Backups zurück (für UI-Benachrichtigungen und Anzeige in Einstellungen).
    Erfordert Authentifizierung.
    """
    items = [
        BackupFailureItem(
            run_id=f["run_id"],
            pipeline_name=f["pipeline_name"],
            error_message=f["error_message"],
            created_at=f["created_at"],
        )
        for f in get_backup_failures()
    ]
    ts = get_last_backup_timestamp()
    last_backup_at = ts.isoformat() if ts else None
    return BackupFailuresResponse(failures=items, last_backup_at=last_backup_at)


@router.post("/cleanup/force", response_model=Dict[str, Any])
async def force_cleanup(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_write)
) -> Dict[str, Any]:
    """
    Führt einen manuellen Force-Flush (Cleanup) durch.
    
    Führt sowohl Log-Cleanup als auch Docker-Ressourcen-Cleanup aus.
    
    Args:
        session: SQLModel Session
        
    Returns:
        Dictionary mit Cleanup-Statistiken und detaillierten Informationen
    """
    try:
        # Sammle Informationen über was geflusht wird
        cleanup_info = {
            "log_cleanup": {
                "description": "Bereinigt Log-Dateien, Metrics-Dateien und Datenbank-Einträge",
                "actions": []
            },
            "docker_cleanup": {
                "description": "Bereinigt verwaiste Docker-Container und Volumes (nur bei PIPELINE_EXECUTOR=docker)",
                "actions": []
            }
        }
        if config.PIPELINE_EXECUTOR == "docker":
            cleanup_info["docker_cleanup"]["actions"].append(
                "Löscht verwaiste Container mit Label 'fastflow-run-id' (ohne zugehörigen DB-Eintrag)"
            )
            cleanup_info["docker_cleanup"]["actions"].append(
                "Löscht beendete Container mit Label 'fastflow-run-id'"
            )
            cleanup_info["docker_cleanup"]["actions"].append(
                "Löscht verwaiste Volumes mit Label 'fastflow-run-id'"
            )
        else:
            cleanup_info["docker_cleanup"]["actions"].append("Nicht aktiv (PIPELINE_EXECUTOR=kubernetes)")
        
        # Log-Cleanup Informationen
        if config.LOG_RETENTION_RUNS:
            cleanup_info["log_cleanup"]["actions"].append(
                f"Löscht älteste Runs pro Pipeline (max. {config.LOG_RETENTION_RUNS} Runs pro Pipeline behalten)"
            )
        if config.LOG_RETENTION_DAYS:
            cleanup_info["log_cleanup"]["actions"].append(
                f"Löscht Runs älter als {config.LOG_RETENTION_DAYS} Tage"
            )
        if config.LOG_MAX_SIZE_MB:
            cleanup_info["log_cleanup"]["actions"].append(
                f"Kürzt oder löscht Log-Dateien größer als {config.LOG_MAX_SIZE_MB} MB"
            )
        if not cleanup_info["log_cleanup"]["actions"]:
            cleanup_info["log_cleanup"]["actions"].append(
                "Keine Log-Cleanup-Regeln konfiguriert"
            )
        
        # Log-Cleanup durchführen
        log_stats = await cleanup_logs(session)
        
        # Docker-Ressourcen-Cleanup (nur bei PIPELINE_EXECUTOR=docker)
        docker_stats = await cleanup_docker_resources() if config.PIPELINE_EXECUTOR == "docker" else {}
        
        # Detaillierte Zusammenfassung erstellen
        summary = []
        
        if log_stats.get("deleted_runs", 0) > 0:
            summary.append(f"{log_stats['deleted_runs']} Runs aus Datenbank gelöscht")
        if log_stats.get("deleted_logs", 0) > 0:
            summary.append(f"{log_stats['deleted_logs']} Log-Dateien gelöscht")
        if log_stats.get("deleted_metrics", 0) > 0:
            summary.append(f"{log_stats['deleted_metrics']} Metrics-Dateien gelöscht")
        if log_stats.get("truncated_logs", 0) > 0:
            summary.append(f"{log_stats['truncated_logs']} Log-Dateien gekürzt")
        
        if docker_stats.get("deleted_containers", 0) > 0:
            summary.append(f"{docker_stats['deleted_containers']} Docker-Container gelöscht")
        if docker_stats.get("deleted_volumes", 0) > 0:
            summary.append(f"{docker_stats['deleted_volumes']} Docker-Volumes gelöscht")
        
        if not summary:
            summary.append("Keine Ressourcen zum Bereinigen gefunden")
        
        return {
            "status": "success",
            "message": "Cleanup erfolgreich abgeschlossen",
            "summary": summary,
            "cleanup_info": cleanup_info,
            "log_cleanup": log_stats,
            "docker_cleanup": docker_stats,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Cleanup: {str(e)}"
        )


@router.get("/system-metrics", response_model=Dict[str, Any])
async def get_system_metrics(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Gibt System-Metriken zurück (Docker-Container, RAM, CPU).
    
    Erfordert Authentifizierung.
    
    Returns:
        Dictionary mit:
        - active_containers: Anzahl aktiver Pipeline-Container
        - containers_ram_mb: Gesamter RAM-Verbrauch der Container in MB
        - containers_cpu_percent: Gesamter CPU-Verbrauch der Container in Prozent
        - api_ram_mb: RAM-Verbrauch der API in MB
        - api_cpu_percent: CPU-Verbrauch der API in Prozent
        - system_ram_total_mb: Gesamter System-RAM in MB
        - system_ram_used_mb: Verwendeter System-RAM in MB
        - system_ram_percent: System-RAM-Auslastung in Prozent
        - system_cpu_percent: System-CPU-Auslastung in Prozent
        - container_details: Liste mit Details zu jedem Container
    """
    try:
        metrics = {
            "active_containers": 0,
            "containers_ram_mb": 0.0,
            "containers_cpu_percent": 0.0,
            "api_ram_mb": 0.0,
            "api_cpu_percent": 0.0,
            "system_ram_total_mb": 0.0,
            "system_ram_used_mb": 0.0,
            "system_ram_percent": 0.0,
            "system_cpu_percent": 0.0,
            "container_details": []
        }
        
        # API-Prozess-Metriken (psutil)
        try:
            process = psutil.Process()
            api_memory_info = process.memory_info()
            metrics["api_ram_mb"] = round(api_memory_info.rss / (1024 * 1024), 2)
            metrics["api_cpu_percent"] = round(process.cpu_percent(interval=0.1), 2)
        except Exception as e:
            logger.warning(f"Fehler beim Ermitteln der API-Metriken: {e}")
        
        # System-Metriken
        try:
            system_memory = psutil.virtual_memory()
            metrics["system_ram_total_mb"] = round(system_memory.total / (1024 * 1024), 2)
            metrics["system_ram_used_mb"] = round(system_memory.used / (1024 * 1024), 2)
            metrics["system_ram_percent"] = round(system_memory.percent, 2)
            metrics["system_cpu_percent"] = round(psutil.cpu_percent(interval=0.1), 2)
        except Exception as e:
            logger.warning(f"Fehler beim Ermitteln der System-Metriken: {e}")
        
        # Docker-Container-Metriken (nur bei PIPELINE_EXECUTOR=docker)
        if config.PIPELINE_EXECUTOR == "docker":
            try:
                docker_client = _get_docker_client()
                containers = docker_client.containers.list(
                    filters={"label": "fastflow-run-id"},
                    all=False
                )
                metrics["active_containers"] = len(containers)
                total_ram_mb = 0.0
                total_cpu_percent = 0.0
                container_details = []
                for container in containers:
                    try:
                        stats = container.stats(stream=False)
                        memory_usage = stats.get("memory_stats", {}).get("usage", 0)
                        memory_limit = stats.get("memory_stats", {}).get("limit", 0)
                        ram_mb = memory_usage / (1024 * 1024) if memory_usage else 0
                        ram_percent = (memory_usage / memory_limit * 100) if memory_limit > 0 else 0
                        cpu_percent = 0.0
                        cpu_stats = stats.get("cpu_stats", {})
                        precpu_stats = stats.get("precpu_stats", {})
                        if cpu_stats and precpu_stats:
                            cpu_delta = (
                                cpu_stats.get("cpu_usage", {}).get("total_usage", 0) -
                                precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
                            )
                            system_delta = (
                                cpu_stats.get("system_cpu_usage", 0) -
                                precpu_stats.get("system_cpu_usage", 0)
                            )
                            if system_delta > 0:
                                online_cpus = len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])) or 1
                                cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
                        total_ram_mb += ram_mb
                        total_cpu_percent += cpu_percent
                        container_details.append({
                            "run_id": container.labels.get("fastflow-run-id", "unknown"),
                            "pipeline_name": container.labels.get("fastflow-pipeline", "unknown"),
                            "container_id": container.id[:12],
                            "ram_mb": round(ram_mb, 2),
                            "ram_percent": round(ram_percent, 2),
                            "cpu_percent": round(cpu_percent, 2),
                            "status": container.status
                        })
                    except Exception as e:
                        logger.warning(f"Fehler beim Ermitteln der Container-Stats für {container.id}: {e}")
                metrics["containers_ram_mb"] = round(total_ram_mb, 2)
                metrics["containers_cpu_percent"] = round(total_cpu_percent, 2)
                metrics["container_details"] = container_details
            except RuntimeError:
                pass
            except Exception as e:
                logger.warning(f"Fehler beim Ermitteln der Docker-Container-Metriken: {e}")

        # Kubernetes: aktive Pipeline-Jobs (Pods) für Aktive Container / RAM / CPU
        if config.PIPELINE_EXECUTOR == "kubernetes":
            try:
                k8s_metrics = await asyncio.get_running_loop().run_in_executor(
                    None, get_kubernetes_system_metrics
                )
                metrics["active_containers"] = k8s_metrics.get("active_containers", 0)
                metrics["containers_ram_mb"] = k8s_metrics.get("containers_ram_mb", 0.0)
                metrics["containers_cpu_percent"] = k8s_metrics.get("containers_cpu_percent", 0.0)
                metrics["container_details"] = k8s_metrics.get("container_details", [])
            except Exception as e:
                logger.warning(f"Fehler beim Ermitteln der Kubernetes-System-Metriken: {e}")
        
        return metrics
        
    except Exception as e:
        logger.exception("Fehler beim Abrufen der System-Metriken")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )
