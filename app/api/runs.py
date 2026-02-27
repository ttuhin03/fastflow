"""
Run Management API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Run-Management:
- Runs auflisten
- Run-Details abrufen
- Run abbrechen
"""

from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import Session, select, func

from app.core.database import get_session
from app.models import PipelineRun, RunStatus, User, RunCellLog
from app.executor import cancel_run, check_container_health, run_pipeline
from app.auth import get_current_user, require_write
from app.schemas.runs import RunsResponse

# Terminal-Statuses: Run kann nur in diesen Zuständen erneut gestartet werden (Retry)
_RETRY_ALLOWED_STATUSES = {
    RunStatus.SUCCESS,
    RunStatus.FAILED,
    RunStatus.INTERRUPTED,
    RunStatus.WARNING,
}

router = APIRouter(prefix="/runs", tags=["runs"])


def _parse_iso_datetime(value: str, param_name: str) -> datetime:
    """
    Parst ISO-Datum-String; wirft HTTPException bei ungültigem Format.
    Unterstützt YYYY-MM-DD und YYYY-MM-DDTHH:MM:SS (inkl. Z → +00:00).
    """
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ungültiges {param_name}-Format: {value}. Erwartet: ISO-Format (YYYY-MM-DD oder YYYY-MM-DDTHH:MM:SS)",
        )


@router.get("", response_model=RunsResponse)
async def get_runs(
    pipeline_name: Optional[str] = Query(None, description="Filter nach Pipeline-Name"),
    status_filter: Optional[RunStatus] = Query(None, description="Filter nach Status"),
    start_date: Optional[str] = Query(None, description="Startdatum für Filterung (ISO-Format: YYYY-MM-DD oder YYYY-MM-DDTHH:MM:SS)"),
    end_date: Optional[str] = Query(None, description="Enddatum für Filterung (ISO-Format: YYYY-MM-DD oder YYYY-MM-DDTHH:MM:SS)"),
    limit: int = Query(50, ge=1, le=1000, description="Anzahl Runs pro Seite"),
    offset: int = Query(0, ge=0, description="Offset für Pagination"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> RunsResponse:
    """
    Gibt alle Runs anzeigen (mit Filterung und Pagination).
    
    Args:
        pipeline_name: Optionaler Filter nach Pipeline-Name
        status_filter: Optionaler Filter nach Status (PENDING, RUNNING, SUCCESS, FAILED, etc.)
        start_date: Optionales Startdatum für Filterung (ISO-Format)
        end_date: Optionales Enddatum für Filterung (ISO-Format)
        limit: Anzahl Runs pro Seite (Standard: 50, Max: 1000)
        offset: Offset für Pagination (Standard: 0)
        session: SQLModel Session
        
    Returns:
        RunsResponse mit runs, total, page und page_size
    """
    # Query für Filter bauen (ohne Pagination)
    base_stmt = select(PipelineRun)
    
    # Filter anwenden
    if pipeline_name:
        base_stmt = base_stmt.where(PipelineRun.pipeline_name == pipeline_name)
    
    if status_filter:
        base_stmt = base_stmt.where(PipelineRun.status == status_filter)
    
    # Zeitraum-Filterung (einmal parsen, für base_stmt und count_stmt nutzen)
    start_dt = _parse_iso_datetime(start_date, "Startdatum") if start_date else None
    end_dt = _parse_iso_datetime(end_date, "Enddatum") if end_date else None
    if start_dt is not None:
        base_stmt = base_stmt.where(PipelineRun.started_at >= start_dt)
    if end_dt is not None:
        base_stmt = base_stmt.where(PipelineRun.started_at <= end_dt)
    
    # Total count abrufen (mit gleichen Filtern)
    count_stmt = select(func.count(PipelineRun.id))
    if pipeline_name:
        count_stmt = count_stmt.where(PipelineRun.pipeline_name == pipeline_name)
    if status_filter:
        count_stmt = count_stmt.where(PipelineRun.status == status_filter)
    if start_dt is not None:
        count_stmt = count_stmt.where(PipelineRun.started_at >= start_dt)
    if end_dt is not None:
        count_stmt = count_stmt.where(PipelineRun.started_at <= end_dt)
    total = session.exec(count_stmt).one()
    
    # Query für Runs mit Pagination
    stmt = base_stmt.order_by(PipelineRun.started_at.desc()).limit(limit).offset(offset)
    
    # Runs aus DB abrufen
    runs = session.exec(stmt).all()
    
    # Response-Objekte erstellen
    runs_response = []
    for run in runs:
        # Error-Type aus env_vars extrahieren
        error_type = None
        error_message = None
        if run.env_vars:
            error_type = run.env_vars.get("_fastflow_error_type")
            error_message = run.env_vars.get("_fastflow_error_message")
        
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
            "setup_duration": run.setup_duration,
            "error_type": error_type,  # "pipeline_error" oder "infrastructure_error"
            "error_message": error_message
        })
    
    page = (offset // limit) + 1 if limit > 0 else 1
    
    return RunsResponse(
        runs=runs_response,
        total=total,
        page=page,
        page_size=limit
    )


@router.get("/{run_id}", response_model=Dict[str, Any])
async def get_run_details(
    run_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
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
    
    # Error-Type aus env_vars extrahieren
    error_type = None
    error_message = None
    if run.env_vars:
        error_type = run.env_vars.get("_fastflow_error_type")
        error_message = run.env_vars.get("_fastflow_error_message")
    
    # Zellen-Logs (Notebook-Pipelines) laden
    cell_logs_stmt = select(RunCellLog).where(RunCellLog.run_id == run_id).order_by(RunCellLog.cell_index)
    cell_logs = list(session.exec(cell_logs_stmt).all())
    cell_logs_data = [
        {
            "cell_index": c.cell_index,
            "status": c.status,
            "stdout": c.stdout or "",
            "stderr": c.stderr or "",
            "outputs": c.outputs,
        }
        for c in cell_logs
    ]

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
        "error_type": error_type,  # "pipeline_error" oder "infrastructure_error"
        "error_message": error_message,
        "setup_duration": run.setup_duration,
        "cell_logs": cell_logs_data,
    }


@router.get("/{run_id}/cells", response_model=List[Dict[str, Any]])
async def get_run_cells(
    run_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Gibt die Zellen-Logs eines Runs zurück (Notebook-Pipelines).
    
    Args:
        run_id: Run-ID (UUID)
        session: SQLModel Session
        
    Returns:
        Liste der Zellen-Logs, sortiert nach cell_index
    """
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run nicht gefunden: {run_id}"
        )
    stmt = select(RunCellLog).where(RunCellLog.run_id == run_id).order_by(RunCellLog.cell_index)
    cells = list(session.exec(stmt).all())
    return [
        {
            "cell_index": c.cell_index,
            "status": c.status,
            "stdout": c.stdout or "",
            "stderr": c.stderr or "",
            "outputs": c.outputs,
        }
        for c in cells
    ]


@router.post("/{run_id}/cancel", response_model=Dict[str, str])
async def cancel_run_endpoint(
    run_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_write)
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


@router.post("/{run_id}/retry", response_model=Dict[str, Any])
async def retry_run(
    run_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_write),
) -> Dict[str, Any]:
    """
    Startet einen neuen Run mit denselben Parametern und Env-Variablen wie der angegebene Run.

    Nur zulässig für beendete Runs (SUCCESS, FAILED, INTERRUPTED, WARNING).
    Der neue Run wird mit triggered_by="manual" gestartet.

    Returns:
        Run-Informationen des neuen Runs (id, pipeline_name, status, started_at, log_file).
    """
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run nicht gefunden: {run_id}",
        )
    if run.status not in _RETRY_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Retry nur für beendete Runs möglich (aktueller Status: {run.status.value})",
        )
    env_vars = run.env_vars or {}
    parameters = run.parameters or {}
    try:
        new_run = await run_pipeline(
            name=run.pipeline_name,
            env_vars=env_vars,
            parameters=parameters,
            session=session,
            triggered_by="manual",
            run_config_id=run.run_config_id,
        )
        return {
            "id": str(new_run.id),
            "pipeline_name": new_run.pipeline_name,
            "status": new_run.status.value,
            "started_at": new_run.started_at.isoformat(),
            "log_file": new_run.log_file,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim erneuten Start: {str(e)}",
        )


@router.get("/{run_id}/health", response_model=Dict[str, Any])
async def get_run_health(
    run_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Gibt Container-Health-Status für einen Run zurück.
    
    Args:
        run_id: Run-ID (UUID)
        session: SQLModel Session
        
    Returns:
        Dictionary mit Health-Status-Informationen
        
    Raises:
        HTTPException: Wenn Run nicht gefunden wurde
    """
    # Run aus DB abrufen
    run = session.get(PipelineRun, run_id)
    
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run nicht gefunden: {run_id}"
        )
    
    # Health-Check durchführen
    health_info = await check_container_health(run_id, session)
    
    return {
        "run_id": str(run_id),
        "status": run.status.value,
        **health_info
    }
