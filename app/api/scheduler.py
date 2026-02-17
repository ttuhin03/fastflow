"""
Scheduler API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Scheduler-Management:
- Jobs auflisten
- Job aktualisieren (Erstellen/Löschen nur via pipeline.json)

Schedules werden aus pipeline.json (schedule_cron, schedule_interval_seconds etc.) synchronisiert.
Bearbeitung erfolgt über den GitHub-Link der pipeline.json.
"""

from typing import List, Optional, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.database import get_session
from app.models import ScheduledJob, TriggerType, User
from app.git_sync import get_pipeline_json_github_url
from app.services.scheduler import (
    update_job,
    get_all_jobs,
    get_job,
    get_job_details,
    get_scheduler,
    _parse_schedule_datetime,
)
from app.services.pipeline_discovery import get_pipeline
from app.auth import require_write, get_current_user

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


class JobUpdate(BaseModel):
    """Request-Model für Job-Aktualisierung."""
    pipeline_name: Optional[str] = Field(None, description="Neuer Pipeline-Name")
    trigger_type: Optional[TriggerType] = Field(None, description="Neuer Trigger-Typ")
    trigger_value: Optional[str] = Field(None, description="Neuer Trigger-Wert")
    enabled: Optional[bool] = Field(None, description="Neuer Enabled-Status")
    start_date: Optional[str] = Field(None, description="Neuer Start des Zeitraums (ISO-Datum/Zeit)")
    end_date: Optional[str] = Field(None, description="Neues Ende des Zeitraums (ISO-Datum/Zeit)")
    run_config_id: Optional[str] = Field(None, description="Run-Konfiguration aus pipeline.json schedules")


class JobResponse(BaseModel):
    """Response-Model für Job-Daten."""
    id: UUID
    pipeline_name: str
    trigger_type: TriggerType
    trigger_value: str
    enabled: bool
    created_at: str
    next_run_time: Optional[str] = None
    last_run_time: Optional[str] = None
    run_count: int = 0
    source: str = "api"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    run_config_id: Optional[str] = None
    pipeline_json_edit_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> List[JobResponse]:
    """
    Gibt alle geplanten Jobs zurück.
    
    Returns:
        Liste aller ScheduledJob-Datensätze mit Details
    """
    try:
        jobs = get_all_jobs(session)
        result = []
        for job in jobs:
            details = get_job_details(job.id, session)
            edit_url = get_pipeline_json_github_url(job.pipeline_name)
            if details:
                details["pipeline_json_edit_url"] = edit_url
                result.append(JobResponse(**details))
            else:
                # Fallback wenn Details nicht verfügbar
                result.append(JobResponse(
                    id=job.id,
                    pipeline_name=job.pipeline_name,
                    trigger_type=job.trigger_type,
                    trigger_value=job.trigger_value,
                    enabled=job.enabled,
                    created_at=job.created_at.isoformat(),
                    source=getattr(job, "source", "api"),
                    start_date=job.start_date.isoformat() if getattr(job, "start_date", None) else None,
                    end_date=job.end_date.isoformat() if getattr(job, "end_date", None) else None,
                    run_config_id=getattr(job, "run_config_id", None),
                    pipeline_json_edit_url=edit_url,
                ))
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Jobs: {str(e)}"
        )


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_by_id(
    job_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> JobResponse:
    """
    Gibt einen Job anhand der ID zurück.
    
    Args:
        job_id: Job-ID
    
    Returns:
        JobResponse: Job-Daten mit Details
    
    Raises:
        HTTPException: Wenn Job nicht gefunden ist
    """
    job = get_job(job_id, session)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job nicht gefunden: {job_id}"
        )
    details = get_job_details(job_id, session)
    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job nicht gefunden: {job_id}"
        )
    details["pipeline_json_edit_url"] = get_pipeline_json_github_url(job.pipeline_name)
    return JobResponse(**details)


@router.put("/jobs/{job_id}", response_model=JobResponse)
async def update_job_by_id(
    job_id: UUID,
    job_data: JobUpdate,
    current_user = Depends(require_write),
    session: Session = Depends(get_session)
) -> JobResponse:
    """
    Aktualisiert einen bestehenden Job.
    
    Args:
        job_id: Job-ID
        job_data: Zu aktualisierende Job-Daten
        session: SQLModel Session
    
    Returns:
        JobResponse: Aktualisierter Job
    
    Raises:
        HTTPException: Wenn Job nicht gefunden ist oder Parameter ungültig sind
    """
    # Prüfe ob Scheduler läuft
    scheduler = get_scheduler()
    if scheduler is None or not scheduler.running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler ist nicht verfügbar"
        )
    
    # Pipeline-Validierung (wenn Pipeline-Name geändert wird)
    if job_data.pipeline_name is not None:
        pipeline = get_pipeline(job_data.pipeline_name)
        if pipeline is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pipeline nicht gefunden: {job_data.pipeline_name}"
            )
    
    start_dt = _parse_schedule_datetime(job_data.start_date, end_of_day=False) if job_data.start_date else None
    end_dt = _parse_schedule_datetime(job_data.end_date, end_of_day=True) if job_data.end_date else None
    set_fields = job_data.model_dump(exclude_unset=True)
    update_kwargs = dict(
        job_id=job_id,
        pipeline_name=job_data.pipeline_name,
        trigger_type=job_data.trigger_type,
        trigger_value=job_data.trigger_value,
        enabled=job_data.enabled,
        start_date=start_dt,
        end_date=end_dt,
        session=session,
    )
    if "run_config_id" in set_fields:
        update_kwargs["run_config_id"] = job_data.run_config_id
    try:
        job = update_job(**update_kwargs)
        
        # Job-Details abrufen für vollständige Response
        details = get_job_details(job.id, session)
        if details:
            return JobResponse(**details)
        else:
            # Fallback
            return JobResponse(
                id=job.id,
                pipeline_name=job.pipeline_name,
                trigger_type=job.trigger_type,
                trigger_value=job.trigger_value,
                enabled=job.enabled,
                created_at=job.created_at.isoformat(),
                source=getattr(job, "source", "api"),
                start_date=job.start_date.isoformat() if getattr(job, "start_date", None) else None,
                end_date=job.end_date.isoformat() if getattr(job, "end_date", None) else None,
                run_config_id=getattr(job, "run_config_id", None),
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Aktualisieren des Jobs: {str(e)}"
        )


@router.get("/jobs/{job_id}/runs", response_model=List[Dict[str, Any]])
async def get_job_runs(
    job_id: UUID,
    limit: int = Query(50, ge=1, le=500, description="Maximale Anzahl Runs"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    Gibt die Run-Historie für einen Job zurück.
    
    Args:
        job_id: Job-ID
        limit: Maximale Anzahl Runs (Standard: 50, Max: 500)
        session: SQLModel Session
    
    Returns:
        Liste aller Runs für diesen Job (sortiert nach started_at, neueste zuerst)
    
    Raises:
        HTTPException: Wenn Job nicht gefunden ist
    """
    job = get_job(job_id, session)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job nicht gefunden: {job_id}"
        )
    
    # Runs für diese Pipeline (und ggf. run_config_id) abrufen
    from app.models import PipelineRun
    from sqlmodel import select

    stmt = (
        select(PipelineRun)
        .where(PipelineRun.pipeline_name == job.pipeline_name)
        .order_by(PipelineRun.started_at.desc())
        .limit(limit)
    )
    job_rcid = getattr(job, "run_config_id", None)
    if job_rcid is not None:
        stmt = stmt.where(PipelineRun.run_config_id == job_rcid)
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
            "metrics_file": run.metrics_file
        })
    
    return runs_response
