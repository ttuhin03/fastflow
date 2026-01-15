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
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.config import config
from app.cleanup import cleanup_logs, cleanup_docker_resources

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
