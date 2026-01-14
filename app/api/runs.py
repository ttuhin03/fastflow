"""
Run Management API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Run-Management:
- Runs auflisten
- Run-Details abrufen
- Run abbrechen
"""

from typing import List, Optional, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import Session, select

from app.database import get_session
from app.models import PipelineRun, RunStatus
from app.executor import cancel_run

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=List[Dict[str, Any]])
async def get_runs(
    pipeline_name: Optional[str] = Query(None, description="Filter nach Pipeline-Name"),
    status_filter: Optional[RunStatus] = Query(None, description="Filter nach Status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximale Anzahl Runs"),
    session: Session = Depends(get_session)
) -> List[Dict[str, Any]]:
    """
    Gibt alle Runs anzeigen (mit Filterung).
    
    Args:
        pipeline_name: Optionaler Filter nach Pipeline-Name
        status_filter: Optionaler Filter nach Status (PENDING, RUNNING, SUCCESS, FAILED, etc.)
        limit: Maximale Anzahl Runs (Standard: 100, Max: 1000)
        session: SQLModel Session
        
    Returns:
        Liste aller Runs (sortiert nach started_at, neueste zuerst)
    """
    # Query bauen
    stmt = select(PipelineRun)
    
    # Filter anwenden
    if pipeline_name:
        stmt = stmt.where(PipelineRun.pipeline_name == pipeline_name)
    
    if status_filter:
        stmt = stmt.where(PipelineRun.status == status_filter)
    
    # Sortierung und Limit
    stmt = stmt.order_by(PipelineRun.started_at.desc()).limit(limit)
    
    # Runs aus DB abrufen
    runs = session.exec(stmt).all()
    
    # Response-Objekte erstellen
    runs_response = []
    for run in runs:
        runs_response.append({
            "id": str(run.id),
            "pipeline_name": run.pipeline_name,
            "status": run.status.value,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "exit_code": run.exit_code,
            "log_file": run.log_file,
            "metrics_file": run.metrics_file,
            "uv_version": run.uv_version,
            "setup_duration": run.setup_duration
        })
    
    return runs_response


@router.get("/{run_id}", response_model=Dict[str, Any])
async def get_run_details(
    run_id: UUID,
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Gibt Details eines Runs zurück.
    
    Args:
        run_id: Run-ID (UUID)
        session: SQLModel Session
        
    Returns:
        Run-Details mit allen Informationen
        
    Raises:
        HTTPException: Wenn Run nicht gefunden wurde
    """
    run = session.get(PipelineRun, run_id)
    
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run nicht gefunden: {run_id}"
        )
    
    return {
        "id": str(run.id),
        "pipeline_name": run.pipeline_name,
        "status": run.status.value,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "exit_code": run.exit_code,
        "log_file": run.log_file,
        "metrics_file": run.metrics_file,
        "env_vars": run.env_vars,
        "parameters": run.parameters,
        "uv_version": run.uv_version,
        "setup_duration": run.setup_duration
    }


@router.post("/{run_id}/cancel", response_model=Dict[str, str])
async def cancel_run_endpoint(
    run_id: UUID,
    session: Session = Depends(get_session)
) -> Dict[str, str]:
    """
    Bricht einen laufenden Run ab (Container stoppen).
    
    Args:
        run_id: Run-ID (UUID)
        session: SQLModel Session
        
    Returns:
        Bestätigungs-Message
        
    Raises:
        HTTPException: Wenn Run nicht gefunden wurde oder bereits beendet ist
    """
    # Run aus DB abrufen
    run = session.get(PipelineRun, run_id)
    
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run nicht gefunden: {run_id}"
        )
    
    # Prüfe ob Run noch läuft
    if run.status not in [RunStatus.PENDING, RunStatus.RUNNING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run ist bereits beendet (Status: {run.status.value})"
        )
    
    # Run abbrechen
    success = await cancel_run(run_id, session)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abbrechen des Runs: {run_id}"
        )
    
    return {
        "message": f"Run {run_id} wurde erfolgreich abgebrochen"
    }
