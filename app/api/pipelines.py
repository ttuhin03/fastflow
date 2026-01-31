"""
Pipeline Management API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Pipeline-Management:
- Pipeline-Liste abrufen
- Pipeline starten
- Pipeline-Statistiken abrufen/zurücksetzen
"""

from collections import defaultdict
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlmodel import Session, select, func, text
from pydantic import BaseModel

from app.database import get_session
from app.models import Pipeline, PipelineRun, RunStatus, User
from app.executor import run_pipeline
from app.pipeline_discovery import discover_pipelines, get_pipeline as get_discovered_pipeline
from app.auth import require_write, get_current_user
from app.config import config
from app import dependencies as deps_module

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _path_within_pipelines_dir(path: Path) -> bool:
    """Prüft ob der Pfad innerhalb von PIPELINES_DIR liegt (Path Traversal-Schutz)."""
    try:
        path.resolve().relative_to(config.PIPELINES_DIR.resolve())
        return True
    except ValueError:
        return False


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


def _parse_date_range(
    start_date: Optional[str],
    end_date: Optional[str],
    days: int,
) -> Tuple[datetime, datetime]:
    """Berechnet (start_dt, end_dt) aus Parametern. Wirft HTTPException bei ungültigem Format."""
    if start_date and end_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            if start_dt > end_dt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Startdatum muss vor Enddatum liegen",
                )
            return start_dt, end_dt
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiges Datumsformat. Erwartet: YYYY-MM-DD",
            )
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            return start_dt, datetime.utcnow()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiges Datumsformat. Erwartet: YYYY-MM-DD",
            )
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
            end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return end_dt - timedelta(days=days), end_dt
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiges Datumsformat. Erwartet: YYYY-MM-DD",
            )
    now = datetime.utcnow()
    end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_dt = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start_dt, end_dt


def _aggregate_runs_to_daily_stats(
    runs: List[PipelineRun],
    include_run_ids: bool = False,
) -> List[DailyStat]:
    """Gruppiert Runs nach Datum und gibt DailyStat-Liste zurück."""
    daily_data: Dict[str, Dict] = defaultdict(lambda: {"total": 0, "successful": 0, "failed": 0, "run_ids": []})
    for run in runs:
        date_str = run.started_at.date().isoformat()
        daily_data[date_str]["total"] += 1
        if include_run_ids:
            daily_data[date_str]["run_ids"].append(str(run.id))
        if run.status == RunStatus.SUCCESS:
            daily_data[date_str]["successful"] += 1
        elif run.status == RunStatus.FAILED:
            daily_data[date_str]["failed"] += 1
    result: List[DailyStat] = []
    for date_str in sorted(daily_data.keys()):
        d = daily_data[date_str]
        total = d["total"]
        success_rate = (d["successful"] / total * 100.0) if total > 0 else 0.0
        run_ids = (d["run_ids"][:10] or None) if include_run_ids else None
        result.append(
            DailyStat(
                date=date_str,
                total_runs=total,
                successful_runs=d["successful"],
                failed_runs=d["failed"],
                success_rate=success_rate,
                run_ids=run_ids,
            )
        )
    return result


@router.get("", response_model=List[PipelineResponse])
async def get_pipelines(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
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


@router.get("/dependencies", response_model=List[Dict[str, Any]])
async def get_pipelines_dependencies(
    audit: bool = Query(False, description="Run pip-audit for vulnerabilities (can be slow)"),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """
    Returns dependencies (packages + versions) for all pipelines that have requirements.txt.
    If audit=true, runs pip-audit per pipeline and includes vulnerabilities (CVE).
    """
    pipelines = discover_pipelines()
    result: List[Dict[str, Any]] = []
    for p in pipelines:
        if not p.has_requirements:
            continue
        packages = deps_module.get_pipeline_packages(p.name)
        entry: Dict[str, Any] = {"pipeline": p.name, "packages": packages}
        if audit:
            req_path = p.path / "requirements.txt"
            vulns, err = await deps_module.run_pip_audit(req_path)
            entry["vulnerabilities"] = vulns
            if err:
                entry["audit_error"] = err
        result.append(entry)
    return result


@router.get("/{name}/dependencies", response_model=Dict[str, Any])
async def get_pipeline_dependencies(
    name: str,
    audit: bool = Query(False, description="Run pip-audit for vulnerabilities"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Returns dependencies (packages + versions) for one pipeline.
    If audit=true, runs pip-audit and includes vulnerabilities.
    """
    discovered = get_discovered_pipeline(name)
    if discovered is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pipeline nicht gefunden: {name}"
        )
    packages = deps_module.get_pipeline_packages(name)
    result: Dict[str, Any] = {"pipeline": name, "packages": packages}
    if discovered.has_requirements and audit:
        req_path = discovered.path / "requirements.txt"
        vulns, err = await deps_module.run_pip_audit(req_path)
        result["vulnerabilities"] = vulns
        if err:
            result["audit_error"] = err
    return result


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
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
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
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
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
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
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
    
    start_dt, end_dt = _parse_date_range(start_date, end_date, days)
    stmt = (
        select(PipelineRun)
        .where(PipelineRun.pipeline_name == name)
        .where(PipelineRun.started_at >= start_dt)
        .where(PipelineRun.started_at <= end_dt)
    )
    runs = session.exec(stmt).all()
    daily_stats = _aggregate_runs_to_daily_stats(runs, include_run_ids=True)
    return DailyStatsResponse(daily_stats=daily_stats)


class PipelineSourceFilesResponse(BaseModel):
    """Response-Model für Pipeline-Quelldateien."""
    main_py: Optional[str] = None
    requirements_txt: Optional[str] = None
    pipeline_json: Optional[str] = None


@router.get("/{name}/source", response_model=PipelineSourceFilesResponse)
async def get_pipeline_source_files(
    name: str,
    current_user: User = Depends(get_current_user)
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
    # Path Traversal-Schutz: Sicherstellen dass pipeline_dir innerhalb PIPELINES_DIR liegt
    if not _path_within_pipelines_dir(pipeline_dir):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Zugriff auf Pipeline-Dateien verweigert"
        )
    result = PipelineSourceFilesResponse()

    # Verwende discovered.name statt user-provided name für Pfadkonstruktion
    pipeline_name = discovered.name

    # main.py lesen
    main_py_path = pipeline_dir / "main.py"
    if main_py_path.exists() and main_py_path.is_file() and _path_within_pipelines_dir(main_py_path):
        try:
            with open(main_py_path, "r", encoding="utf-8") as f:
                result.main_py = f.read()
        except Exception:
            pass

    # requirements.txt lesen
    requirements_path = pipeline_dir / "requirements.txt"
    if requirements_path.exists() and requirements_path.is_file() and _path_within_pipelines_dir(requirements_path):
        try:
            with open(requirements_path, "r", encoding="utf-8") as f:
                result.requirements_txt = f.read()
        except Exception:
            pass

    # pipeline.json lesen (oder {pipeline_name}.json) - pipeline_name aus Discovery, nicht aus Request
    metadata_path = pipeline_dir / "pipeline.json"
    if not metadata_path.exists():
        metadata_path = pipeline_dir / f"{pipeline_name}.json"
    if metadata_path.exists() and metadata_path.is_file() and _path_within_pipelines_dir(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                result.pipeline_json = f.read()
        except Exception:
            pass

    return result


@router.get("/daily-stats/all", response_model=DailyStatsResponse)
async def get_all_pipelines_daily_stats(
    days: int = Query(365, ge=1, le=3650, description="Anzahl der Tage zurück (Standard: 365, Max: 3650)"),
    start_date: Optional[str] = Query(None, description="Startdatum für Filterung (ISO-Format: YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Enddatum für Filterung (ISO-Format: YYYY-MM-DD)"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
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
    start_dt, end_dt = _parse_date_range(start_date, end_date, days)
    stmt = (
        select(PipelineRun)
        .where(PipelineRun.started_at >= start_dt)
        .where(PipelineRun.started_at <= end_dt)
    )
    runs = session.exec(stmt).all()
    daily_stats = _aggregate_runs_to_daily_stats(runs, include_run_ids=False)
    return DailyStatsResponse(daily_stats=daily_stats)
