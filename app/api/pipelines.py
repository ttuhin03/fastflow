"""
Pipeline Management API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Pipeline-Management:
- Pipeline-Liste abrufen
- Pipeline starten
- Pipeline-Statistiken abrufen/zurücksetzen
"""

from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlmodel import Session, select, func, text
from pydantic import BaseModel

from app.database import get_session
from app.models import Pipeline, PipelineRun, RunStatus
from app.executor import run_pipeline
from app.pipeline_discovery import discover_pipelines, get_pipeline as get_discovered_pipeline
from app.auth import require_write

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class PipelineResponse(BaseModel):
    """Response-Model für Pipeline-Informationen."""
    name: str
    has_requirements: bool
    last_cache_warmup: Optional[str]
    total_runs: int
    successful_runs: int
    failed_runs: int
    enabled: bool
    metadata: Dict[str, Any]


class RunPipelineRequest(BaseModel):
    """Request-Model für Pipeline-Start."""
    env_vars: Optional[Dict[str, str]] = None
    parameters: Optional[Dict[str, str]] = None


class PipelineStatsResponse(BaseModel):
    """Response-Model für Pipeline-Statistiken."""
    pipeline_name: str
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    webhook_runs: int


class DailyStat(BaseModel):
    """Response-Model für tägliche Pipeline-Statistiken."""
    date: str  # ISO format: YYYY-MM-DD
    total_runs: int
    successful_runs: int
    failed_runs: int
    success_rate: float
    run_ids: Optional[List[str]] = None  # Run-IDs für diesen Tag (optional, für Tooltips)


class DailyStatsResponse(BaseModel):
    """Response-Model für tägliche Pipeline-Statistiken."""
    daily_stats: List[DailyStat]


@router.get("", response_model=List[PipelineResponse])
async def get_pipelines(
    session: Session = Depends(get_session)
) -> List[PipelineResponse]:
    """
    Gibt eine Liste aller verfügbaren Pipelines zurück (via Discovery, inkl. Statistiken).
    
    Returns:
        Liste aller entdeckten Pipelines mit Statistiken aus der Datenbank
        
    Raises:
        HTTPException: Wenn Pipeline-Discovery fehlschlägt
    """
    try:
        # Pipelines via Discovery abrufen
        discovered_pipelines = discover_pipelines()
        
        # Pipeline-Statistiken aus DB abrufen
        pipelines_response: List[PipelineResponse] = []
        
        for discovered in discovered_pipelines:
            # Pipeline-Metadaten aus DB abrufen (oder erstellen wenn nicht vorhanden)
            pipeline = session.get(Pipeline, discovered.name)
            
            if pipeline is None:
                # Pipeline existiert noch nicht in DB, erstelle Eintrag
                pipeline = Pipeline(
                    pipeline_name=discovered.name,
                    has_requirements=discovered.has_requirements
                )
                session.add(pipeline)
                session.commit()
                session.refresh(pipeline)
            
            # Response-Objekt erstellen
            # Metadata dict enthält bereits webhook_key (wenn gesetzt)
            response = PipelineResponse(
                name=discovered.name,
                has_requirements=pipeline.has_requirements,
                last_cache_warmup=pipeline.last_cache_warmup.isoformat() if pipeline.last_cache_warmup else None,
                total_runs=pipeline.total_runs,
                successful_runs=pipeline.successful_runs,
                failed_runs=pipeline.failed_runs,
                enabled=discovered.is_enabled(),
                metadata=discovered.metadata.to_dict()  # Enthält webhook_key wenn gesetzt
            )
            pipelines_response.append(response)
        
        return pipelines_response
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Pipelines: {str(e)}"
        )


@router.post("/{name}/run", response_model=Dict[str, Any])
async def start_pipeline(
    name: str,
    request: RunPipelineRequest,
    current_user = Depends(require_write),
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Startet eine Pipeline manuell mit optionalen Parametern.
    
    Args:
        name: Name der Pipeline
        request: Request-Body mit optionalen env_vars und parameters
        session: SQLModel Session
        
    Returns:
        Dictionary mit Run-Informationen (id, status, pipeline_name, etc.)
        
    Raises:
        HTTPException: Wenn Pipeline nicht existiert, deaktiviert ist oder Concurrency-Limit erreicht ist
    """
    try:
        # Pipeline-Start (manuell getriggert)
        run = await run_pipeline(
            name=name,
            env_vars=request.env_vars,
            parameters=request.parameters,
            session=session,
            triggered_by="manual"
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Starten der Pipeline: {str(e)}"
        )


@router.get("/{name}/runs", response_model=List[Dict[str, Any]])
async def get_pipeline_runs(
    name: str,
    limit: Optional[int] = 100,
    session: Session = Depends(get_session)
) -> List[Dict[str, Any]]:
    """
    Gibt die Historie eines Pipeline-Runs zurück.
    
    Args:
        name: Name der Pipeline
        limit: Maximale Anzahl Runs (Standard: 100)
        session: SQLModel Session
        
    Returns:
        Liste aller Runs für diese Pipeline (sortiert nach started_at, neueste zuerst)
        
    Raises:
        HTTPException: Wenn Pipeline nicht existiert
    """
    # Prüfe ob Pipeline existiert
    discovered = get_discovered_pipeline(name)
    if discovered is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline nicht gefunden: {name}"
        )
    
    # Runs aus DB abrufen
    stmt = (
        select(PipelineRun)
        .where(PipelineRun.pipeline_name == name)
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


@router.get("/{name}/stats", response_model=PipelineStatsResponse)
async def get_pipeline_stats(
    name: str,
    session: Session = Depends(get_session)
) -> PipelineStatsResponse:
    """
    Gibt Pipeline-Statistiken abrufen (total_runs, successful_runs, failed_runs).
    
    Args:
        name: Name der Pipeline
        session: SQLModel Session
        
    Returns:
        Pipeline-Statistiken mit Erfolgsrate
        
    Raises:
        HTTPException: Wenn Pipeline nicht existiert
    """
    # Prüfe ob Pipeline existiert
    discovered = get_discovered_pipeline(name)
    if discovered is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline nicht gefunden: {name}"
        )
    
    # Pipeline-Metadaten aus DB abrufen (oder erstellen wenn nicht vorhanden)
    pipeline = session.get(Pipeline, name)
    
    if pipeline is None:
        # Pipeline existiert noch nicht in DB, erstelle Eintrag
        pipeline = Pipeline(
            pipeline_name=name,
            has_requirements=discovered.has_requirements
        )
        session.add(pipeline)
        session.commit()
        session.refresh(pipeline)
    
    # Erfolgsrate berechnen
    success_rate = 0.0
    if pipeline.total_runs > 0:
        success_rate = (pipeline.successful_runs / pipeline.total_runs) * 100.0
    
    return PipelineStatsResponse(
        pipeline_name=pipeline.pipeline_name,
        total_runs=pipeline.total_runs,
        successful_runs=pipeline.successful_runs,
        failed_runs=pipeline.failed_runs,
        success_rate=success_rate,
        webhook_runs=pipeline.webhook_runs
    )


@router.post("/{name}/stats/reset", response_model=Dict[str, str])
async def reset_pipeline_stats(
    name: str,
    current_user = Depends(require_write),
    session: Session = Depends(get_session)
) -> Dict[str, str]:
    """
    Setzt Pipeline-Statistiken zurück (total_runs, successful_runs, failed_runs auf 0).
    
    Args:
        name: Name der Pipeline
        session: SQLModel Session
        
    Returns:
        Bestätigungs-Message
        
    Raises:
        HTTPException: Wenn Pipeline nicht existiert
    """
    # Prüfe ob Pipeline existiert
    discovered = get_discovered_pipeline(name)
    if discovered is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline nicht gefunden: {name}"
        )
    
    # Pipeline-Metadaten aus DB abrufen (oder erstellen wenn nicht vorhanden)
    pipeline = session.get(Pipeline, name)
    
    if pipeline is None:
        # Pipeline existiert noch nicht in DB, erstelle Eintrag
        pipeline = Pipeline(
            pipeline_name=name,
            has_requirements=discovered.has_requirements
        )
        session.add(pipeline)
    
    # Statistiken zurücksetzen
    pipeline.total_runs = 0
    pipeline.successful_runs = 0
    pipeline.failed_runs = 0
    pipeline.webhook_runs = 0
    
    session.add(pipeline)
    session.commit()
    
    return {
        "message": f"Statistiken für Pipeline '{name}' wurden zurückgesetzt"
    }


@router.get("/{name}/daily-stats", response_model=DailyStatsResponse)
async def get_pipeline_daily_stats(
    name: str,
    days: int = Query(365, ge=1, le=3650, description="Anzahl der Tage zurück (Standard: 365, Max: 3650)"),
    start_date: Optional[str] = Query(None, description="Startdatum für Filterung (ISO-Format: YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Enddatum für Filterung (ISO-Format: YYYY-MM-DD)"),
    session: Session = Depends(get_session)
) -> DailyStatsResponse:
    """
    Gibt tägliche Pipeline-Statistiken zurück, gruppiert nach Datum.
    
    Aggregiert Pipeline-Runs nach Tag und berechnet Erfolgsraten pro Tag.
    
    Args:
        name: Name der Pipeline
        days: Anzahl der Tage zurück (Standard: 365)
        start_date: Optionales Startdatum (ISO-Format: YYYY-MM-DD)
        end_date: Optionales Enddatum (ISO-Format: YYYY-MM-DD)
        session: SQLModel Session
        
    Returns:
        Tägliche Statistiken mit Erfolgsraten
        
    Raises:
        HTTPException: Wenn Pipeline nicht existiert oder Datum ungültig ist
    """
    # Prüfe ob Pipeline existiert
    discovered = get_discovered_pipeline(name)
    if discovered is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline nicht gefunden: {name}"
        )
    
    # Datum-Bereich bestimmen
    if start_date and end_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            # End-Datum auf Ende des Tages setzen (23:59:59)
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            if start_dt > end_dt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Startdatum muss vor Enddatum liegen"
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiges Datumsformat. Erwartet: YYYY-MM-DD"
            )
    elif start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.utcnow()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiges Datumsformat. Erwartet: YYYY-MM-DD"
            )
    elif end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
            # End-Datum auf Ende des Tages setzen
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            start_dt = end_dt - timedelta(days=days)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiges Datumsformat. Erwartet: YYYY-MM-DD"
            )
    else:
        # Standard: Letzte N Tage
        # Setze end_dt auf Ende des heutigen Tages (23:59:59.999999) in UTC
        # um sicherzustellen, dass alle Runs von heute erfasst werden
        now = datetime.utcnow()
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        start_dt = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Query: Alle Runs im Zeitraum abrufen
    stmt = (
        select(PipelineRun)
        .where(PipelineRun.pipeline_name == name)
        .where(PipelineRun.started_at >= start_dt)
        .where(PipelineRun.started_at <= end_dt)
    )
    
    runs = session.exec(stmt).all()
    
    # Debug: Log heute's Datum und Anzahl gefundener Runs
    from datetime import date as date_type
    from collections import defaultdict
    import logging
    logger = logging.getLogger(__name__)
    today_utc = date_type.today()  # UTC date
    logger.info(f"Daily stats for {name}: Found {len(runs)} runs, today UTC: {today_utc}, start_dt: {start_dt}, end_dt: {end_dt}")
    
    # In Python nach Datum gruppieren und aggregieren
    daily_data = defaultdict(lambda: {"total": 0, "successful": 0, "failed": 0, "run_ids": []})
    
    for run in runs:
        # Datum extrahieren (nur Datum, ohne Zeit) - UTC-Datum verwenden
        # started_at ist bereits in UTC gespeichert
        run_date = run.started_at.date()
        date_str = run_date.isoformat()
        
        # Debug: Log Runs von heute
        if run_date == today_utc:
            logger.info(f"Today's run found: {run.id}, status: {run.status}, started_at: {run.started_at}")
        
        # Zähle ALLE Runs, unabhängig vom Status (auch RUNNING/PENDING)
        daily_data[date_str]["total"] += 1
        daily_data[date_str]["run_ids"].append(str(run.id))  # Speichere Run-ID
        if run.status == RunStatus.SUCCESS:
            daily_data[date_str]["successful"] += 1
        elif run.status == RunStatus.FAILED:
            daily_data[date_str]["failed"] += 1
        # RUNNING und PENDING Runs werden als "total" gezählt, aber nicht als successful/failed
    
    # In DailyStat-Objekte umwandeln und sortieren
    daily_stats = []
    for date_str in sorted(daily_data.keys()):
        data = daily_data[date_str]
        total = data["total"]
        successful = data["successful"]
        failed = data["failed"]
        run_ids = data["run_ids"][:10]  # Max 10 Run-IDs für Tooltip (Performance)
        
        # Erfolgsrate berechnen
        success_rate = 0.0
        if total > 0:
            success_rate = (successful / total) * 100.0
        
        daily_stats.append(DailyStat(
            date=date_str,
            total_runs=total,
            successful_runs=successful,
            failed_runs=failed,
            success_rate=success_rate,
            run_ids=run_ids if run_ids else None
        ))
    
    return DailyStatsResponse(daily_stats=daily_stats)


class PipelineSourceFilesResponse(BaseModel):
    """Response-Model für Pipeline-Quelldateien."""
    main_py: Optional[str] = None
    requirements_txt: Optional[str] = None
    pipeline_json: Optional[str] = None


@router.get("/{name}/source", response_model=PipelineSourceFilesResponse)
async def get_pipeline_source_files(
    name: str
) -> PipelineSourceFilesResponse:
    """
    Gibt die Quelldateien einer Pipeline zurück (main.py, requirements.txt, pipeline.json).
    
    Args:
        name: Name der Pipeline
        
    Returns:
        Dictionary mit den Quelldateien (als Strings)
        
    Raises:
        HTTPException: Wenn Pipeline nicht existiert
    """
    # Prüfe ob Pipeline existiert
    discovered = get_discovered_pipeline(name)
    if discovered is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline nicht gefunden: {name}"
        )
    
    pipeline_dir = discovered.path
    result = PipelineSourceFilesResponse()
    
    # main.py lesen
    main_py_path = pipeline_dir / "main.py"
    if main_py_path.exists() and main_py_path.is_file():
        try:
            with open(main_py_path, "r", encoding="utf-8") as f:
                result.main_py = f.read()
        except Exception as e:
            # Fehler beim Lesen: None lassen, aber nicht abbrechen
            pass
    
    # requirements.txt lesen
    requirements_path = pipeline_dir / "requirements.txt"
    if requirements_path.exists() and requirements_path.is_file():
        try:
            with open(requirements_path, "r", encoding="utf-8") as f:
                result.requirements_txt = f.read()
        except Exception as e:
            # Fehler beim Lesen: None lassen, aber nicht abbrechen
            pass
    
    # pipeline.json lesen (oder {pipeline_name}.json)
    metadata_path = pipeline_dir / "pipeline.json"
    if not metadata_path.exists():
        metadata_path = pipeline_dir / f"{name}.json"
    
    if metadata_path.exists() and metadata_path.is_file():
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                result.pipeline_json = f.read()
        except Exception as e:
            # Fehler beim Lesen: None lassen, aber nicht abbrechen
            pass
    
    return result


@router.get("/daily-stats/all", response_model=DailyStatsResponse)
async def get_all_pipelines_daily_stats(
    days: int = Query(365, ge=1, le=3650, description="Anzahl der Tage zurück (Standard: 365, Max: 3650)"),
    start_date: Optional[str] = Query(None, description="Startdatum für Filterung (ISO-Format: YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Enddatum für Filterung (ISO-Format: YYYY-MM-DD)"),
    session: Session = Depends(get_session)
) -> DailyStatsResponse:
    """
    Gibt tägliche Statistiken für alle Pipelines kombiniert zurück.
    
    Aggregiert Pipeline-Runs aller Pipelines nach Tag und berechnet Erfolgsraten pro Tag.
    
    Args:
        days: Anzahl der Tage zurück (Standard: 365)
        start_date: Optionales Startdatum (ISO-Format: YYYY-MM-DD)
        end_date: Optionales Enddatum (ISO-Format: YYYY-MM-DD)
        session: SQLModel Session
        
    Returns:
        Tägliche Statistiken mit Erfolgsraten für alle Pipelines kombiniert
    """
    # Datum-Bereich bestimmen
    if start_date and end_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            if start_dt > end_dt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Startdatum muss vor Enddatum liegen"
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiges Datumsformat. Erwartet: YYYY-MM-DD"
            )
    elif start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.utcnow()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiges Datumsformat. Erwartet: YYYY-MM-DD"
            )
    elif end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            start_dt = end_dt - timedelta(days=days)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiges Datumsformat. Erwartet: YYYY-MM-DD"
            )
    else:
        # Standard: Letzte N Tage
        # Setze end_dt auf Ende des heutigen Tages (23:59:59.999999) in UTC
        # um sicherzustellen, dass alle Runs von heute erfasst werden
        now = datetime.utcnow()
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        start_dt = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Query: Alle Runs im Zeitraum abrufen (alle Pipelines)
    stmt = (
        select(PipelineRun)
        .where(PipelineRun.started_at >= start_dt)
        .where(PipelineRun.started_at <= end_dt)
    )
    
    runs = session.exec(stmt).all()
    
    # Debug: Log heute's Datum und Anzahl gefundener Runs
    from datetime import date as date_type
    from collections import defaultdict
    import logging
    logger = logging.getLogger(__name__)
    today_utc = date_type.today()  # UTC date
    logger.info(f"All pipelines daily stats: Found {len(runs)} runs, today UTC: {today_utc}, start_dt: {start_dt}, end_dt: {end_dt}")
    
    # In Python nach Datum gruppieren und aggregieren
    daily_data = defaultdict(lambda: {"total": 0, "successful": 0, "failed": 0})
    
    for run in runs:
        # Datum extrahieren (nur Datum, ohne Zeit) - UTC-Datum verwenden
        # started_at ist bereits in UTC gespeichert
        run_date = run.started_at.date()
        date_str = run_date.isoformat()
        
        # Debug: Log Runs von heute
        if run_date == today_utc:
            logger.info(f"Today's run found: {run.id}, pipeline: {run.pipeline_name}, status: {run.status}, started_at: {run.started_at}")
        
        # Zähle ALLE Runs, unabhängig vom Status (auch RUNNING/PENDING)
        daily_data[date_str]["total"] += 1
        if run.status == RunStatus.SUCCESS:
            daily_data[date_str]["successful"] += 1
        elif run.status == RunStatus.FAILED:
            daily_data[date_str]["failed"] += 1
        # RUNNING und PENDING Runs werden als "total" gezählt, aber nicht als successful/failed
    
    # In DailyStat-Objekte umwandeln und sortieren
    daily_stats = []
    for date_str in sorted(daily_data.keys()):
        data = daily_data[date_str]
        total = data["total"]
        successful = data["successful"]
        failed = data["failed"]
        
        # Erfolgsrate berechnen
        success_rate = 0.0
        if total > 0:
            success_rate = (successful / total) * 100.0
        
        daily_stats.append(DailyStat(
            date=date_str,
            total_runs=total,
            successful_runs=successful,
            failed_runs=failed,
            success_rate=success_rate
        ))
    
    return DailyStatsResponse(daily_stats=daily_stats)
