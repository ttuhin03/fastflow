"""
Scheduler API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Scheduler-Management:
- Jobs auflisten
- Job erstellen/aktualisieren/löschen
"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.database import get_session
from app.models import ScheduledJob, TriggerType
from app.scheduler import (
    add_job,
    update_job,
    delete_job,
    get_all_jobs,
    get_job,
    get_scheduler
)
from app.pipeline_discovery import get_pipeline

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

    class Config:
        from_attributes = True


@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(session: Session = Depends(get_session)) -> List[JobResponse]:
    """
    Gibt alle geplanten Jobs zurück.
    
    Returns:
        Liste aller ScheduledJob-Datensätze
    """
    try:
        jobs = get_all_jobs(session)
        return [JobResponse(
            id=job.id,
            pipeline_name=job.pipeline_name,
            trigger_type=job.trigger_type,
            trigger_value=job.trigger_value,
            enabled=job.enabled,
            created_at=job.created_at.isoformat()
        ) for job in jobs]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Jobs: {str(e)}"
        )


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_by_id(
    job_id: UUID,
    session: Session = Depends(get_session)
) -> JobResponse:
    """
    Gibt einen Job anhand der ID zurück.
    
    Args:
        job_id: Job-ID
    
    Returns:
        JobResponse: Job-Daten
    
    Raises:
        HTTPException: Wenn Job nicht gefunden ist
    """
    job = get_job(job_id, session)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job nicht gefunden: {job_id}"
        )
    
    return JobResponse(
        id=job.id,
        pipeline_name=job.pipeline_name,
        trigger_type=job.trigger_type,
        trigger_value=job.trigger_value,
        enabled=job.enabled,
        created_at=job.created_at.isoformat()
    )


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_data: JobCreate,
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


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job_by_id(
    job_id: UUID,
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
