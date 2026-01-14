"""
Git Sync API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Git-Synchronisation:
- Git Pull ausführen
- Git-Status anzeigen
"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.git_sync import sync_pipelines, get_sync_status, get_sync_logs
from app.config import config

router = APIRouter(prefix="/sync", tags=["sync"])


class SyncRequest(BaseModel):
    """Request-Model für Git-Sync."""
    branch: Optional[str] = None


@router.post("", response_model=Dict[str, Any])
async def sync(
    request: SyncRequest,
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Führt Git Pull ausführen (mit Branch-Auswahl).
    
    Führt Git-Sync mit UV Pre-Heating aus:
    - Step 1: Git Pull (Aktualisierung des Codes)
    - Step 2: Discovery (Suche nach allen requirements.txt)
    - Step 3: Pre-Heating: Für jede Pipeline mit requirements.txt wird
      `uv pip compile` ausgeführt (lädt alle Pakete in Host-Cache)
    
    Args:
        request: Request-Body mit optionalem Branch (Standard: config.GIT_BRANCH)
        session: SQLModel Session
        
    Returns:
        Dictionary mit Sync-Status und Pre-Heating-Ergebnissen
        
    Raises:
        HTTPException: Wenn Git-Sync fehlschlägt
    """
    try:
        result = await sync_pipelines(
            branch=request.branch,
            session=session
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message", "Git-Sync fehlgeschlagen")
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Git-Sync: {str(e)}"
        )


@router.get("/status", response_model=Dict[str, Any])
async def sync_status() -> Dict[str, Any]:
    """
    Gibt Git-Status anzeigen.
    
    Zeigt Informationen über:
    - Aktueller Branch
    - Remote-URL
    - Letzter Commit
    - Pipeline-Discovery-Status
    - Pre-Heating-Status (welche Pipelines sind gecached)
    
    Returns:
        Dictionary mit Git-Status-Informationen
    """
    try:
        status_info = await get_sync_status()
        return status_info
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen des Git-Status: {str(e)}"
        )


class SyncSettingsRequest(BaseModel):
    """Request-Model für Sync-Einstellungen."""
    auto_sync_enabled: Optional[bool] = None
    auto_sync_interval: Optional[int] = None


@router.get("/settings", response_model=Dict[str, Any])
async def get_sync_settings() -> Dict[str, Any]:
    """
    Gibt aktuelle Sync-Einstellungen zurück.
    
    Returns:
        Dictionary mit Sync-Einstellungen
    """
    return {
        "auto_sync_enabled": config.AUTO_SYNC_ENABLED,
        "auto_sync_interval": config.AUTO_SYNC_INTERVAL
    }


@router.put("/settings", response_model=Dict[str, Any])
async def update_sync_settings(
    request: SyncSettingsRequest
) -> Dict[str, Any]:
    """
    Aktualisiert Sync-Einstellungen.
    
    Hinweis: Einstellungen werden in Environment-Variablen gespeichert.
    Für persistente Änderungen muss die .env-Datei aktualisiert werden.
    Diese Funktion aktualisiert nur die laufende Instanz.
    
    Args:
        request: Request-Body mit neuen Einstellungen
    
    Returns:
        Dictionary mit aktualisierten Einstellungen
    """
    import os
    
    # Einstellungen aktualisieren (nur für laufende Instanz)
    if request.auto_sync_enabled is not None:
        os.environ["AUTO_SYNC_ENABLED"] = str(request.auto_sync_enabled).lower()
        config.AUTO_SYNC_ENABLED = request.auto_sync_enabled
    
    if request.auto_sync_interval is not None:
        if request.auto_sync_interval < 60:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Auto-Sync-Intervall muss mindestens 60 Sekunden betragen"
            )
        os.environ["AUTO_SYNC_INTERVAL"] = str(request.auto_sync_interval)
        config.AUTO_SYNC_INTERVAL = request.auto_sync_interval
    
    return {
        "auto_sync_enabled": config.AUTO_SYNC_ENABLED,
        "auto_sync_interval": config.AUTO_SYNC_INTERVAL,
        "message": "Einstellungen aktualisiert (nur für laufende Instanz. Für persistente Änderungen .env-Datei bearbeiten)"
    }


@router.get("/logs", response_model=List[Dict[str, Any]])
async def get_sync_logs_endpoint(
    limit: int = Query(100, ge=1, le=1000, description="Maximale Anzahl Log-Einträge")
) -> List[Dict[str, Any]]:
    """
    Gibt Sync-Logs zurück.
    
    Args:
        limit: Maximale Anzahl Log-Einträge (Standard: 100, Max: 1000)
    
    Returns:
        Liste von Sync-Log-Einträgen (neueste zuerst)
    """
    try:
        logs = await get_sync_logs(limit=limit)
        return logs
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Sync-Logs: {str(e)}"
        )
