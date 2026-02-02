"""
Metrics API Endpoints (CPU & RAM).

Dieses Modul enthält alle REST-API-Endpoints für Metrics-Monitoring:
- Metrics aus Datei lesen (für abgeschlossene Runs)
- Server-Sent Events für Live-Metrics
"""

import asyncio
import json
import aiofiles
from pathlib import Path
from typing import List, Dict, Any, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse, JSONResponse
from sqlmodel import Session

from app.core.database import get_session
from app.models import PipelineRun, User
from app.executor import get_metrics_queue
from app.auth import get_current_user
from app.core.config import config
from app.core.errors import get_500_detail

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runs", tags=["metrics"])


def _resolve_metrics_path(metrics_file: str) -> Path:
    """
    Resolve metrics file path and validate it is within LOGS_DIR.
    Prevents path traversal when metrics_file comes from database.
    """
    path = Path(metrics_file)
    if not path.is_absolute():
        path = (config.LOGS_DIR / path).resolve()
    else:
        path = path.resolve()

    logs_dir_abs = config.LOGS_DIR.resolve()
    try:
        path.resolve().relative_to(logs_dir_abs)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Zugriff auf Metrics-Datei verweigert"
        )
    return path


@router.get("/{run_id}/metrics")
async def get_run_metrics(
    run_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> JSONResponse:
    """
    Gibt Metrics aus Datei lesen (für abgeschlossene Runs).
    
    Metrics werden im JSONL-Format gespeichert (eine JSON-Zeile pro Timestamp).
    
    Args:
        run_id: Run-ID (UUID)
        session: SQLModel Session
        
    Returns:
        JSONResponse mit Liste aller Metrics (als Array)
        
    Raises:
        HTTPException: Wenn Run nicht gefunden wurde oder Metrics-Datei nicht existiert
    """
    # Run aus DB abrufen
    run = session.get(PipelineRun, run_id)
    
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run nicht gefunden: {run_id}"
        )
    
    if not run.metrics_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Metrics-Datei nicht vorhanden für Run {run_id}"
        )

    try:
        metrics_file_path = _resolve_metrics_path(run.metrics_file)
    except HTTPException:
        raise
    except (ValueError, OSError) as e:
        logger.error(f"Fehler bei Pfad-Validierung für Metrics-Datei: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Validieren des Metrics-Pfads"
        ) from e

    if not metrics_file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Metrics-Datei nicht gefunden: {run.metrics_file}"
        )
    
    try:
        # Asynchrones Datei-Lesen (JSONL-Format: eine JSON-Zeile pro Timestamp)
        metrics: List[Dict[str, Any]] = []
        
        async with aiofiles.open(metrics_file_path, "r", encoding="utf-8") as f:
            async for line in f:
                line = line.strip()
                if line:
                    try:
                        metric = json.loads(line)
                        metrics.append(metric)
                    except json.JSONDecodeError:
                        # Ungültige JSON-Zeile ignorieren
                        continue
        
        return JSONResponse(content=metrics)
        
    except Exception as e:
        logger.exception("Fehler beim Lesen der Metrics-Datei")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )


@router.get("/{run_id}/metrics/stream")
async def stream_run_metrics(
    run_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> StreamingResponse:
    """
    Server-Sent Events für Live-Metrics (für laufende Runs).
    
    Verwendet asyncio.Queue für Metrics (pro Run-ID eine Queue).
    Container-Stats werden in Queue geschoben (CPU %, RAM MB).
    Metrics-Format: {"timestamp": "...", "cpu_percent": 45.2, "ram_mb": 128.5, "ram_limit_mb": 512}
    
    Args:
        run_id: Run-ID (UUID)
        session: SQLModel Session
        
    Returns:
        StreamingResponse mit Server-Sent Events (text/event-stream)
        
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
    
    # Metrics-Queue abrufen
    metrics_queue = get_metrics_queue(run_id)
    
    if metrics_queue is None:
        # Queue nicht vorhanden (Run ist bereits beendet oder noch nicht gestartet)
        # Versuche Metrics aus Datei zu lesen (für abgeschlossene Runs)
        if run.metrics_file:
            try:
                metrics_file_path = _resolve_metrics_path(run.metrics_file)
            except HTTPException:
                raise
            except (ValueError, OSError):
                metrics_file_path = None
            if metrics_file_path is not None and metrics_file_path.exists():
                try:
                    # Lese alle Metrics aus Datei und sende als SSE-Events
                    async def generate():
                        async with aiofiles.open(metrics_file_path, "r", encoding="utf-8") as f:
                            async for line in f:
                                line = line.strip()
                                if line:
                                    try:
                                        metric = json.loads(line)
                                        event_data = json.dumps(metric)
                                        yield f"data: {event_data}\n\n"
                                    except json.JSONDecodeError:
                                        continue
                    return StreamingResponse(
                        generate(),
                        media_type="text/event-stream",
                        headers={
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive"
                        }
                    )
                except Exception:
                    pass
        
        # Keine Queue und keine Datei: Run ist noch nicht gestartet
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run {run_id} ist noch nicht gestartet oder bereits beendet"
        )
    
    # SSE-Streaming-Funktion
    async def generate_sse():
        """
        Generator für Server-Sent Events.
        
        Liest Metrics aus Queue und sendet sie als SSE-Events.
        Metrics werden alle 2 Sekunden gemessen (siehe executor.py).
        """
        try:
            while True:
                try:
                    # Warte auf nächste Metric (mit Timeout für Keep-Alive)
                    metric = await asyncio.wait_for(metrics_queue.get(), timeout=5.0)
                    
                    # SSE-Event senden
                    # Format: data: {json}\n\n
                    event_data = json.dumps(metric)
                    yield f"data: {event_data}\n\n"
                    
                except asyncio.TimeoutError:
                    # Timeout: Sende Keep-Alive (leeres Event)
                    yield ": keep-alive\n\n"
                    continue
                    
        except asyncio.CancelledError:
            # Client hat Verbindung getrennt
            pass
        except Exception as e:
            logger.exception("Fehler beim Metrics-SSE-Stream")
            error_data = json.dumps({"error": get_500_detail(e)})
            yield f"data: {error_data}\n\n"
    
    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Nginx-Buffering deaktivieren
        }
    )
