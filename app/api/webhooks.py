"""
Webhook API Endpoints.

Dieses Modul enthält REST-API-Endpoints für Webhook-Trigger:
- POST /webhooks/{pipeline_name}/{webhook_key} - Pipeline via Webhook starten
"""

import logging
import secrets as secrets_module
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.database import get_session
from app.errors import get_500_detail
from app.executor import run_pipeline
from app.middleware.rate_limiting import limiter
from app.pipeline_discovery import get_pipeline as get_discovered_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/{pipeline_name}/{webhook_key}", response_model=Dict[str, Any])
@limiter.limit("100/minute")
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
    - Pipeline hat webhook_key gesetzt (nicht None oder leer)
    - webhook_key stimmt mit dem in pipeline.json überein
    
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
    
    # Prüfe ob Webhooks aktiviert sind (webhook_key muss gesetzt und nicht leer sein)
    pipeline_webhook_key = pipeline.metadata.webhook_key
    if not pipeline_webhook_key or pipeline_webhook_key.strip() == "":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhooks sind für diese Pipeline deaktiviert: {pipeline_name}"
        )
    
    # Validiere webhook_key (constant-time Vergleich gegen Timing-Angriffe)
    if not secrets_module.compare_digest(webhook_key, pipeline_webhook_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültiger Webhook-Schlüssel"
        )
    
    # Pipeline starten mit triggered_by="webhook"
    try:
        run = await run_pipeline(
            name=pipeline_name,
            env_vars=None,
            parameters=None,
            session=session,
            triggered_by="webhook"
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
