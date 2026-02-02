"""
Scheduler API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Scheduler-Management:
- Jobs auflisten
- Job erstellen/aktualisieren/löschen
"""

from typing import List, Optional, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.database import get_session
from app.models import ScheduledJob, TriggerType, User
from app.services.scheduler import (
    add_job,
    update_job,
    delete_job,
    get_all_jobs,
    get_job,
    get_job_details,
    get_scheduler
)
from app.services.pipeline_discovery import get_pipeline
from app.auth import require_write, get_current_user

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


class JobCreate(BaseModel):
    """Request-Model für Job-Erstellung."""
    pipeline_name: str = Field(..., description="Name der Pipeline")
    trigger_type: TriggerType = Field(..., description="Typ des Triggers (CRON oder INTERVAL)")
    trigger_value: str = Field(
        ...,
        description="Cron-Expression (z.B. '0 0 * * *') oder Interval in Sekunden (z.B. '3600')"
    )
    enabled: bool = Field(default=True, description="Job aktiviert/deaktiviert")


class JobUpdate(BaseModel):
    """Request-Model für Job-Aktualisierung."""
    pipeline_name: Optional[str] = Field(None, description="Neuer Pipeline-Name")
    trigger_type: Optional[TriggerType] = Field(None, description="Neuer Trigger-Typ")
    trigger_value: Optional[str] = Field(None, description="Neuer Trigger-Wert")
    enabled: Optional[bool] = Field(None, description="Neuer Enabled-Status")


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

    class Config:
        from_attributes = True


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
            if details:
                result.append(JobResponse(**details))
            else:
                # Fallback wenn Details nicht verfügbar
                result.append(JobResponse(
                    id=job.id,
                    pipeline_name=job.pipeline_name,
                    trigger_type=job.trigger_type,
                    trigger_value=job.trigger_value,
                    enabled=job.enabled,
                    created_at=job.created_at.isoformat()
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
    details = get_job_details(job_id, session)
    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job nicht gefunden: {job_id}"
        )
    
    return JobResponse(**details)


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_data: JobCreate,
    current_user = Depends(require_write),
    session: Session = Depends(get_session)
) -> JobResponse:
    """
    Erstellt einen neuen geplanten Job.
    
    Args:
        job_data: Job-Daten (Pipeline-Name, Trigger-Typ, Trigger-Wert)
        session: SQLModel Session
    
    Returns:
        JobResponse: Erstellter Job
    
    Raises:
        HTTPException: Wenn Pipeline nicht existiert oder Trigger ungültig ist
    """
    # Prüfe ob Scheduler läuft
    scheduler = get_scheduler()
    if scheduler is None or not scheduler.running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler ist nicht verfügbar"
        )
    
    # Pipeline-Validierung
    pipeline = get_pipeline(job_data.pipeline_name)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline nicht gefunden: {job_data.pipeline_name}"
        )
    
    try:
        job = add_job(
            pipeline_name=job_data.pipeline_name,
            trigger_type=job_data.trigger_type,
            trigger_value=job_data.trigger_value,
            enabled=job_data.enabled,
            session=session
        )
        
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
                created_at=job.created_at.isoformat()
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Erstellen des Jobs: {str(e)}"
        )


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
    
    try:
        job = update_job(
            job_id=job_id,
            pipeline_name=job_data.pipeline_name,
            trigger_type=job_data.trigger_type,
            trigger_value=job_data.trigger_value,
            enabled=job_data.enabled,
            session=session
        )
        
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
                created_at=job.created_at.isoformat()
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
    
    # Runs für diese Pipeline abrufen
    from app.models import PipelineRun
    from sqlmodel import select
    
    stmt = (
        select(PipelineRun)
        .where(PipelineRun.pipeline_name == job.pipeline_name)
        .order_by(PipelineRun.started_at.desc())
        .limit(limit)
    )
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


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job_by_id(
    job_id: UUID,
    current_user = Depends(require_write),
    session: Session = Depends(get_session)
) -> None:
    """
    Löscht einen Job.
    
    Args:
        job_id: Job-ID
        session: SQLModel Session
    
    Raises:
        HTTPException: Wenn Job nicht gefunden ist
    """
    try:
        delete_job(job_id, session)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Löschen des Jobs: {str(e)}"
        )
