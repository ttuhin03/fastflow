"""
Settings API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für System-Einstellungen:
- Konfiguration abrufen/aktualisieren
- Force Flush (manueller Cleanup)
- Log-Dateien-Statistiken
"""

import os
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.config import config
from app.cleanup import cleanup_logs, cleanup_docker_resources
from app.models import PipelineRun, RunStatus
from app.notifications import send_email_notification, send_teams_notification

router = APIRouter(prefix="/settings", tags=["settings"])


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
async def get_settings() -> SettingsResponse:
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
    session: Session = Depends(get_session)
) -> Dict[str, str]:
    """
    Aktualisiert System-Einstellungen.
    
    Hinweis: Aktuell werden Einstellungen nur aus Environment-Variablen geladen.
    Diese Funktion gibt eine Warnung zurück, dass Einstellungen über
    Environment-Variablen geändert werden müssen.
    
    Args:
        settings: Zu aktualisierende Einstellungen
        session: SQLModel Session
        
    Returns:
        Dictionary mit Bestätigungs-Message
    """
    # TODO: In Zukunft könnte hier eine Datenbank-Tabelle für persistente Einstellungen verwendet werden
    # Aktuell werden Einstellungen nur aus Environment-Variablen geladen
    return {
        "message": "Einstellungen werden aktuell nur aus Environment-Variablen geladen. "
                   "Bitte ändern Sie die Werte in der .env-Datei oder als Environment-Variablen. "
                   "Ein Neustart der Anwendung ist erforderlich."
    }


@router.get("/storage", response_model=Dict[str, Any])
async def get_storage_stats() -> Dict[str, Any]:
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
        
        total_disk_space_gb = total_disk_space_bytes / (1024 * 1024 * 1024)
        used_disk_space_gb = used_disk_space_bytes / (1024 * 1024 * 1024)
        free_disk_space_gb = free_disk_space_bytes / (1024 * 1024 * 1024)
        
        # Anteil der Log-Dateien am Gesamtspeicherplatz
        log_files_percentage = 0.0
        if total_disk_space_bytes > 0:
            log_files_percentage = (log_files_size_bytes / total_disk_space_bytes) * 100
        
        return {
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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Speicherplatz-Statistiken: {str(e)}"
        )


@router.post("/test-email", response_model=Dict[str, str])
async def test_email() -> Dict[str, str]:
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
        from datetime import datetime
        from uuid import uuid4
        
        test_run = PipelineRun(
            id=uuid4(),
            pipeline_name="test-pipeline",
            status=RunStatus.FAILED,
            log_file="test.log",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
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
async def test_teams() -> Dict[str, str]:
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
        from datetime import datetime
        from uuid import uuid4
        
        test_run = PipelineRun(
            id=uuid4(),
            pipeline_name="test-pipeline",
            status=RunStatus.FAILED,
            log_file="test.log",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
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


@router.post("/cleanup/force", response_model=Dict[str, Any])
async def force_cleanup(
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Führt einen manuellen Force-Flush (Cleanup) durch.
    
    Führt sowohl Log-Cleanup als auch Docker-Ressourcen-Cleanup aus.
    
    Args:
        session: SQLModel Session
        
    Returns:
        Dictionary mit Cleanup-Statistiken
    """
    try:
        # Log-Cleanup durchführen
        log_stats = await cleanup_logs(session)
        
        # Docker-Ressourcen-Cleanup durchführen
        docker_stats = await cleanup_docker_resources()
        
        return {
            "status": "success",
            "message": "Cleanup erfolgreich abgeschlossen",
            "log_cleanup": log_stats,
            "docker_cleanup": docker_stats,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Cleanup: {str(e)}"
        )
