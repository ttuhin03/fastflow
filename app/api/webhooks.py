"""
Webhook API Endpoints.

Dieses Modul enthält REST-API-Endpoints für Webhook-Trigger:
- POST /webhooks/{pipeline_name}/{webhook_key} - Pipeline via Webhook starten

Der webhook_key kann auf Pipeline-Ebene oder pro Schedule (schedules[].webhook_key) gesetzt sein.
Bei Übereinstimmung mit einem Schedule wird der Run mit der zugehörigen Run-Konfiguration
(run_config_id) gestartet.
"""

import logging
import secrets as secrets_module
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.core.database import get_session
from app.core.errors import get_500_detail
from app.executor import run_pipeline
from app.middleware.rate_limiting import limiter
from app.services.pipeline_discovery import get_pipeline as get_discovered_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _resolve_webhook_key(
    pipeline_webhook_key: Optional[str],
    schedules: list,
    provided_key: str,
) -> tuple[bool, Optional[str]]:
    """
    Löst den übergebenen Webhook-Key auf. Constant-time Vergleiche.
    Returns:
        (matched, run_config_id): Bei Treffer run_config_id = None (Pipeline-Level)
        oder Schedule-ID; bei keinem Treffer matched=False.
    """
    if pipeline_webhook_key and pipeline_webhook_key.strip():
        if secrets_module.compare_digest(provided_key, pipeline_webhook_key):
            return (True, None)
    for s in schedules or []:
        if not isinstance(s, dict):
            continue
        sk = s.get("webhook_key")
        if sk and isinstance(sk, str) and secrets_module.compare_digest(provided_key, sk):
            rcid = (s.get("id") or "").strip() or None
            return (True, rcid)
    return (False, None)


@router.post("/{pipeline_name}/{webhook_key}", response_model=Dict[str, Any])
@limiter.limit("30/minute")
async def trigger_pipeline_via_webhook(
    request: Request,
    pipeline_name: str,
    webhook_key: str,
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Triggert eine Pipeline via Webhook.
    
    Validiert dass:
    - Pipeline existiert und aktiviert ist
    - Mindestens ein webhook_key (Pipeline-Level oder in schedules[]) ist gesetzt
    - Der übergebene webhook_key stimmt mit einem dieser Keys überein
    
    Bei Übereinstimmung mit Pipeline-Level-Key: Run mit Default-Config (run_config_id=null).
    Bei Übereinstimmung mit schedules[].webhook_key: Run mit dieser Run-Konfiguration.
    
    Args:
        request: FastAPI Request (für Rate Limiting)
        pipeline_name: Name der Pipeline
        webhook_key: Webhook-Schlüssel (aus URL-Pfad)
        session: SQLModel Session
        
    Returns:
        Dictionary mit Run-Informationen (id, status, pipeline_name, etc.)
        
    Raises:
        HTTPException: 
            - 404 wenn Pipeline nicht existiert oder Webhooks deaktiviert sind
            - 401 wenn webhook_key nicht übereinstimmt
            - 429 wenn Concurrency-Limit erreicht ist
    """
    # Pipeline-Metadaten laden
    pipeline = get_discovered_pipeline(pipeline_name)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline nicht gefunden: {pipeline_name}"
        )
    
    # Prüfe ob Pipeline aktiviert ist
    if not pipeline.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline ist deaktiviert: {pipeline_name}"
        )
    
    pipeline_webhook_key = pipeline.metadata.webhook_key
    pipeline_key_set = pipeline_webhook_key and pipeline_webhook_key.strip()
    schedules = getattr(pipeline.metadata, "schedules", None) or []
    schedule_has_key = any(
        isinstance(s, dict) and s.get("webhook_key") and str(s.get("webhook_key", "")).strip()
        for s in schedules
    )
    if not pipeline_key_set and not schedule_has_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhooks sind für diese Pipeline deaktiviert: {pipeline_name}"
        )
    
    matched, run_config_id = _resolve_webhook_key(
        pipeline_webhook_key, schedules, webhook_key
    )
    if not matched:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger Webhook-Schlüssel"
        )
    
    # Pipeline starten mit triggered_by="webhook" und optional run_config_id
    try:
        run = await run_pipeline(
            name=pipeline_name,
            env_vars=None,
            parameters=None,
            session=session,
            triggered_by="webhook",
            run_config_id=run_config_id
        )
        
        return {
            "id": str(run.id),
            "pipeline_name": run.pipeline_name,
            "status": run.status.value,
            "started_at": run.started_at.isoformat(),
            "log_file": run.log_file
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except RuntimeError as e:
        # Concurrency-Limit erreicht
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )
    except Exception as e:
        logger.exception("Fehler beim Starten der Pipeline via Webhook")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )
