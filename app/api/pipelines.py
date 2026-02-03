"""
Pipeline Management API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Pipeline-Management:
- Pipeline-Liste abrufen
- Pipeline starten
- Pipeline-Statistiken abrufen/zurücksetzen
"""

import asyncio
from collections import defaultdict
from typing import List, Optional, Dict, Any, Tuple
from uuid import UUID
from datetime import datetime, timedelta, timezone
from pathlib import Path
import aiofiles
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from sqlmodel import Session, select, func, text
from sqlalchemy import case

from app.core.database import get_session
from app.models import Pipeline, PipelineRun, RunStatus, User
from app.executor import run_pipeline
from app.services.pipeline_discovery import discover_pipelines, get_pipeline as get_discovered_pipeline
from app.auth import require_write, get_current_user
from app.core.config import config
from app.core import dependencies as deps_module
from app.schemas.pipelines import (
    PipelineResponse,
    RunPipelineRequest,
    PipelineStatsResponse,
    DailyStat,
    DailyStatsResponse,
    PipelineSourceFilesResponse,
)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _path_within_pipelines_dir(path: Path) -> bool:
    """Prüft ob der Pfad innerhalb von PIPELINES_DIR liegt (Path Traversal-Schutz)."""
    try:
        path.resolve().relative_to(config.PIPELINES_DIR.resolve())
        return True
    except ValueError:
        return False


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
            return start_dt, datetime.now(timezone.utc)
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
    now = datetime.now(timezone.utc)
    end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_dt = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start_dt, end_dt


def _aggregate_runs_to_daily_stats(
    runs: List[PipelineRun],
    include_run_ids: bool = False,
) -> List[DailyStat]:
    """Gruppiert Runs nach Datum und gibt DailyStat-Liste zurück (Legacy, für kleine Mengen)."""
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


def _get_daily_stats_from_db(
    session: Session,
    start_dt: datetime,
    end_dt: datetime,
    pipeline_name: Optional[str] = None,
    include_run_ids: bool = False,
) -> List[DailyStat]:
    """
    Tägliche Statistiken per SQL-Aggregation (DB-Ebene statt In-Memory).
    Vermeidet das Laden aller Run-Objekte bei vielen Runs.
    """
    date_expr = func.date(PipelineRun.started_at)
    success_case = case((PipelineRun.status == RunStatus.SUCCESS, 1), else_=0)
    failed_case = case((PipelineRun.status == RunStatus.FAILED, 1), else_=0)

    stmt = (
        select(
            date_expr.label("date"),
            func.count(PipelineRun.id).label("total"),
            func.sum(success_case).label("successful"),
            func.sum(failed_case).label("failed"),
        )
        .where(PipelineRun.started_at >= start_dt)
        .where(PipelineRun.started_at <= end_dt)
    )
    if pipeline_name is not None:
        stmt = stmt.where(PipelineRun.pipeline_name == pipeline_name)
    stmt = stmt.group_by(date_expr).order_by(date_expr)

    rows = session.exec(stmt).all()
    result: List[DailyStat] = []
    run_ids_by_date: Dict[str, List[str]] = {}

    if include_run_ids:
        ids_stmt = (
            select(date_expr.label("date"), PipelineRun.id)
            .where(PipelineRun.started_at >= start_dt)
            .where(PipelineRun.started_at <= end_dt)
        )
        if pipeline_name is not None:
            ids_stmt = ids_stmt.where(PipelineRun.pipeline_name == pipeline_name)
        ids_stmt = ids_stmt.order_by(PipelineRun.started_at.desc())
        for row in session.exec(ids_stmt).all():
            d = row.date
            date_str = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
            if date_str not in run_ids_by_date:
                run_ids_by_date[date_str] = []
            if len(run_ids_by_date[date_str]) < 10:
                run_ids_by_date[date_str].append(str(row.id))

    for row in rows:
        d = row.date
        date_str = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10]
        total = row.total or 0
        successful = row.successful or 0
        failed = row.failed or 0
        success_rate = (successful / total * 100.0) if total > 0 else 0.0
        run_ids = (run_ids_by_date.get(date_str, [])[:10] or None) if include_run_ids else None
        result.append(
            DailyStat(
                date=date_str,
                total_runs=total,
                successful_runs=int(successful),
                failed_runs=int(failed),
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
        # Pipelines via Discovery abrufen (im Thread-Pool, blockiert nicht den Event-Loop)
        discovered_pipelines = await asyncio.to_thread(discover_pipelines)
        if not discovered_pipelines:
            return []

        # Batch-Query: Alle Pipeline-Metadaten in einem DB-Roundtrip abrufen
        names = [d.name for d in discovered_pipelines]
        stmt = select(Pipeline).where(Pipeline.pipeline_name.in_(names))
        db_pipelines = {p.pipeline_name: p for p in session.exec(stmt).all()}

        # Fehlende Pipelines sammeln, einmal anlegen und committen (Batch)
        new_pipelines: List[Tuple[str, Pipeline]] = []
        for discovered in discovered_pipelines:
            if discovered.name not in db_pipelines:
                pipeline = Pipeline(
                    pipeline_name=discovered.name,
                    has_requirements=discovered.has_requirements
                )
                session.add(pipeline)
                new_pipelines.append((discovered.name, pipeline))
        if new_pipelines:
            session.commit()
            for name, pipeline in new_pipelines:
                session.refresh(pipeline)
                db_pipelines[name] = pipeline

        # Response-Objekte erstellen (keine weiteren DB-Zugriffe)
        pipelines_response: List[PipelineResponse] = []
        for discovered in discovered_pipelines:
            pipeline = db_pipelines[discovered.name]
            response = PipelineResponse(
                name=discovered.name,
                has_requirements=pipeline.has_requirements,
                last_cache_warmup=pipeline.last_cache_warmup.isoformat() if pipeline.last_cache_warmup else None,
                total_runs=pipeline.total_runs,
                successful_runs=pipeline.successful_runs,
                failed_runs=pipeline.failed_runs,
                enabled=discovered.is_enabled(),
                metadata=discovered.metadata.to_dict()
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
    If audit=true, runs pip-audit per pipeline in parallel and includes vulnerabilities (CVE).
    """
    all_pipelines = await asyncio.to_thread(discover_pipelines)
    pipelines = [p for p in all_pipelines if p.has_requirements]
    if not pipelines:
        return []

    packages_list = [deps_module.get_pipeline_packages(p.name) for p in pipelines]
    result: List[Dict[str, Any]] = []

    if audit:
        sem = asyncio.Semaphore(3)  # Max 3 parallele pip-audit-Aufrufe

        async def audit_one(p: Any, packages: List[Dict]) -> Dict[str, Any]:
            async with sem:
                req_path = p.path / "requirements.txt"
                vulns, err = await deps_module.run_pip_audit(req_path)
            entry: Dict[str, Any] = {"pipeline": p.name, "packages": packages}
            entry["vulnerabilities"] = vulns
            if err:
                entry["audit_error"] = err
            return entry

        tasks = [audit_one(p, pkgs) for p, pkgs in zip(pipelines, packages_list)]
        result = list(await asyncio.gather(*tasks))
    else:
        result = [
            {"pipeline": p.name, "packages": pkgs}
            for p, pkgs in zip(pipelines, packages_list)
        ]
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
    limit: int = Query(100, ge=1, le=1000, description="Maximale Anzahl Runs (Standard: 100)"),
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
    daily_stats = _get_daily_stats_from_db(
        session, start_dt, end_dt, pipeline_name=name, include_run_ids=True
    )
    return DailyStatsResponse(daily_stats=daily_stats)


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

    async def _read_file_safe(path: Path) -> Optional[str]:
        if path.exists() and path.is_file() and _path_within_pipelines_dir(path):
            try:
                async with aiofiles.open(path, "r", encoding="utf-8") as f:
                    return await f.read()
            except Exception:
                pass
        return None

    # main.py lesen
    main_py_path = pipeline_dir / "main.py"
    result.main_py = await _read_file_safe(main_py_path)

    # requirements.txt lesen
    requirements_path = pipeline_dir / "requirements.txt"
    result.requirements_txt = await _read_file_safe(requirements_path)

    # pipeline.json lesen (oder {pipeline_name}.json) - pipeline_name aus Discovery, nicht aus Request
    metadata_path = pipeline_dir / "pipeline.json"
    if not metadata_path.exists():
        metadata_path = pipeline_dir / f"{pipeline_name}.json"
    result.pipeline_json = await _read_file_safe(metadata_path)

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
    daily_stats = _get_daily_stats_from_db(
        session, start_dt, end_dt, pipeline_name=None, include_run_ids=False
    )
    return DailyStatsResponse(daily_stats=daily_stats)
