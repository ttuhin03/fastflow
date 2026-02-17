"""
Git Sync API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Git-Synchronisation:
- Git Pull ausführen
- Git-Status anzeigen
"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import Session
import logging

from app.core.database import get_session
from app.core.errors import get_500_detail
from app.git_sync import sync_pipelines, get_sync_status, get_sync_logs, test_sync_repo_config, clear_pipelines_directory
from app.core.config import config
from app.auth import require_write, get_current_user
from app.middleware.rate_limiting import limiter
from app.models import User
from app.services.git_sync_repo_config import (
    get_sync_repo_config_public,
    save_sync_repo_config,
    delete_sync_repo_config,
    generate_and_save_deploy_key,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


class SyncRequest(BaseModel):
    """Request-Model für Git-Sync."""
    branch: Optional[str] = Field(default=None, min_length=1, max_length=255, description="Git-Branch (z.B. main)")


@router.post("", response_model=Dict[str, Any])
@limiter.limit("6/minute")
async def sync(
    request: Request,
    body: SyncRequest | None = Body(None),
    current_user = Depends(require_write),
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Führt Git Pull ausführen (mit Branch-Auswahl).
    
    Führt Git-Sync mit UV Pre-Heating aus:
    - Step 1: Git Pull (Aktualisierung des Codes)
    - Step 2: Discovery (Suche nach allen requirements.txt)
    - Step 3: Pre-Heating: Für jede Pipeline mit requirements.txt wird
      `uv pip compile` + `uv pip install` ausgeführt (erstellt Lock-File und cached Pakete)
    
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
            branch=body.branch if body else None,
            session=session
        )

        if result.get("already_running"):
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "success": False,
                    "message": result.get("message", "Ein Sync läuft bereits."),
                    "already_running": True,
                    "branch": result.get("branch"),
                    "timestamp": result.get("timestamp"),
                },
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
        logger.exception("Fehler beim Git-Sync")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e)
        )


@router.get("/status", response_model=Dict[str, Any])
async def sync_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """
    Gibt Git-Status anzeigen.
    Enthält auch repo_configured (ob Repository-URL gesetzt ist).
    """
    try:
        status_info = await get_sync_status()
        repo_public = get_sync_repo_config_public(session)
        status_info["repo_configured"] = repo_public.get("configured", False)
        return status_info
    except Exception as e:
        logger.exception("Fehler beim Abrufen des Git-Status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )


class SyncSettingsRequest(BaseModel):
    """Request-Model für Sync-Einstellungen."""
    auto_sync_enabled: Optional[bool] = None
    auto_sync_interval: Optional[int] = None


@router.get("/settings", response_model=Dict[str, Any])
async def get_sync_settings(
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
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
    request: SyncSettingsRequest,
    current_user = Depends(require_write),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """
    Aktualisiert Sync-Einstellungen und speichert sie in der Datenbank.
    Die laufende config wird sofort aktualisiert.
    """
    if request.auto_sync_interval is not None and request.auto_sync_interval < 60:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Auto-Sync-Intervall muss mindestens 60 Sekunden betragen"
        )
    from app.services.orchestrator_settings import (
        get_orchestrator_settings_or_default,
        apply_orchestrator_settings_to_config,
    )
    row = get_orchestrator_settings_or_default(session)
    if request.auto_sync_enabled is not None:
        row.auto_sync_enabled = request.auto_sync_enabled
    if request.auto_sync_interval is not None:
        row.auto_sync_interval = request.auto_sync_interval
    session.add(row)
    session.commit()
    session.refresh(row)
    apply_orchestrator_settings_to_config(row)
    return {
        "auto_sync_enabled": config.AUTO_SYNC_ENABLED,
        "auto_sync_interval": config.AUTO_SYNC_INTERVAL,
        "message": "Einstellungen wurden gespeichert und sind sofort aktiv."
    }


@router.get("/logs", response_model=List[Dict[str, Any]])
async def get_sync_logs_endpoint(
    limit: int = Query(100, ge=1, le=1000, description="Maximale Anzahl Log-Einträge"),
    current_user: User = Depends(get_current_user)
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
        logger.exception("Fehler beim Abrufen der Sync-Logs")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e)
        )


def _is_ssh_url(url: str) -> bool:
    """True wenn URL SSH-Format hat (git@... oder ssh://...)."""
    u = (url or "").strip()
    return u.startswith("git@") or u.startswith("ssh://")


class GenerateDeployKeyRequest(BaseModel):
    """Request-Model für server-seitige Deploy-Key-Erzeugung (SSH-URL)."""
    repo_url: str = Field(..., min_length=1, description="SSH-URL (git@... oder ssh://...)")
    branch: Optional[str] = Field(default=None, description="Branch (z. B. main)")
    pipelines_subdir: Optional[str] = Field(default=None, description="Unterordner im Repo mit Pipeline-Ordnern")


class RepoConfigRequest(BaseModel):
    """Request-Model für Repository-URL + Token oder Deploy Key."""
    repo_url: str = Field(
        ...,
        min_length=1,
        description="HTTPS- oder SSH-URL (z. B. https://github.com/org/repo.git oder git@github.com:org/repo.git)",
    )
    token: Optional[str] = Field(default=None, description="Personal Access Token (optional, für private Repos per HTTPS)")
    deploy_key: Optional[str] = Field(default=None, description="Privater SSH-Deploy-Key (erforderlich bei SSH-URL)")
    branch: Optional[str] = Field(default=None, description="Branch (z. B. main)")
    pipelines_subdir: Optional[str] = Field(default=None, description="Unterordner im Repo mit Pipeline-Ordnern, z. B. pipelines")


@router.get("/repo-config", response_model=Dict[str, Any])
async def get_repo_config(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """
    Gibt die Sync-Repository-Konfiguration zurück (ohne Token).
    Env-Variablen GIT_REPO_URL / GIT_SYNC_TOKEN haben Vorrang vor DB.
    """
    try:
        return get_sync_repo_config_public(session)
    except Exception as e:
        logger.exception("Fehler beim Abrufen der Repo-Config")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )


@router.post("/repo-config", response_model=Dict[str, Any])
async def save_repo_config(
    request: RepoConfigRequest,
    current_user=Depends(require_write),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Speichert Repository-URL, optional Token oder Deploy Key (verschlüsselt) und Branch in der DB."""
    url = (request.repo_url or "").strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository-URL ist erforderlich",
        )
    if not url.startswith("https://") and not url.startswith("http://") and not url.startswith("git@") and not url.startswith("ssh://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository-URL muss mit https://, http://, git@ oder ssh:// beginnen",
        )
    try:
        save_sync_repo_config(
            session,
            repo_url=url,
            token=(request.token or "").strip() or None,
            deploy_key=(request.deploy_key or "").strip() or None,
            branch=(request.branch or "").strip() or None,
            pipelines_subdir=(request.pipelines_subdir or "").strip() or None,
        )
        from app.services.orchestrator_settings import (
            get_orchestrator_settings_or_default,
            apply_orchestrator_settings_to_config,
        )
        apply_orchestrator_settings_to_config(get_orchestrator_settings_or_default(session))
        return {
            "success": True,
            "message": "Repository-Konfiguration gespeichert",
            **get_sync_repo_config_public(session),
        }
    except Exception as e:
        logger.exception("Fehler beim Speichern der Repo-Config")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )


@router.delete("/repo-config", response_model=Dict[str, Any])
async def delete_repo_config(
    current_user: User = Depends(require_write),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Löscht die Sync-Repository-Konfiguration aus der DB (Env-Werte bleiben unberührt)."""
    try:
        delete_sync_repo_config(session)
        return {"success": True, "message": "Repository-Konfiguration gelöscht"}
    except Exception as e:
        logger.exception("Fehler beim Löschen der Repo-Config")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )


@router.post("/repo-config/generate-deploy-key", response_model=Dict[str, Any])
async def generate_deploy_key(
    request: GenerateDeployKeyRequest,
    current_user: User = Depends(require_write),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """
    Erzeugt ein Ed25519-Deploy-Key-Paar, speichert den privaten Key verschlüsselt
    sowie repo_url, branch, pipelines_subdir. Gibt nur den öffentlichen Key zurück;
    diesen bei GitHub unter Settings → Deploy keys eintragen.
    """
    url = (request.repo_url or "").strip()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Repository-URL ist erforderlich",
        )
    if not _is_ssh_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nur SSH-URL erlaubt (git@... oder ssh://...). Für HTTPS PAT verwenden.",
        )
    try:
        public_key = generate_and_save_deploy_key(
            session,
            repo_url=url,
            branch=(request.branch or "").strip() or None,
            pipelines_subdir=(request.pipelines_subdir or "").strip() or None,
        )
        from app.services.orchestrator_settings import (
            get_orchestrator_settings_or_default,
            apply_orchestrator_settings_to_config,
        )
        apply_orchestrator_settings_to_config(get_orchestrator_settings_or_default(session))
        return {
            "success": True,
            "message": "Deploy-Key erzeugt. Öffentlichen Key bei GitHub (Settings → Deploy keys) eintragen.",
            "public_key": public_key,
            **get_sync_repo_config_public(session),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Fehler beim Erzeugen des Deploy-Keys")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )


@router.post("/repo-config/test", response_model=Dict[str, Any])
async def test_repo_config(
    current_user: User = Depends(require_write),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Testet die Repository-Konfiguration per git ls-remote."""
    try:
        success, message = test_sync_repo_config(session)
        return {"success": success, "message": message}
    except Exception as e:
        logger.exception("Fehler beim Testen der Repo-Config")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )


@router.post("/clear-pipelines", response_model=Dict[str, Any])
async def clear_pipelines(
    current_user: User = Depends(require_write),
) -> Dict[str, Any]:
    """
    Leert das Pipelines-Verzeichnis vollständig (inkl. .git).
    Danach kann ein neues Repository per Sync geklont werden.
    Erfordert Schreibrechte.
    """
    try:
        ok, message = clear_pipelines_directory()
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=message,
            )
        return {"success": True, "message": message}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Fehler beim Leeren des Pipeline-Verzeichnisses")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )
