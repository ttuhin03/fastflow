"""
Log Streaming API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Log-Streaming:
- Logs aus Datei lesen
- Server-Sent Events für Live-Logs
"""

import asyncio
import aiofiles
from pathlib import Path
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse, PlainTextResponse
from sqlmodel import Session

from app.database import get_session
from app.models import PipelineRun
from app.executor import get_log_queue
from app.config import config

router = APIRouter(prefix="/runs", tags=["logs"])


@router.get("/{run_id}/logs")
async def get_run_logs(
    run_id: UUID,
    tail: Optional[int] = None,
    session: Session = Depends(get_session)
) -> PlainTextResponse:
    """
    Gibt Logs aus Datei lesen (für abgeschlossene Runs).
    
    Args:
        run_id: Run-ID (UUID)
        tail: Anzahl der letzten Zeilen (optional, wenn nicht gesetzt: gesamte Datei)
        session: SQLModel Session
        
    Returns:
        PlainTextResponse mit Log-Inhalten
        
    Raises:
        HTTPException: Wenn Run nicht gefunden wurde oder Log-Datei nicht existiert
    """
    # Run aus DB abrufen
    run = session.get(PipelineRun, run_id)
    
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run nicht gefunden: {run_id}"
        )
    
    log_file_path = Path(run.log_file)
    
    if not log_file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log-Datei nicht gefunden: {run.log_file}"
        )
    
    try:
        # Asynchrones Datei-Lesen (verhindert Blocking des Event-Loops)
        async with aiofiles.open(log_file_path, "r", encoding="utf-8") as f:
            contents = await f.read()
        
        # Tail-Funktionalität (letzte N Zeilen)
        if tail is not None and tail > 0:
            lines = contents.split("\n")
            contents = "\n".join(lines[-tail:])
        
        return PlainTextResponse(content=contents, media_type="text/plain")
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Lesen der Log-Datei: {str(e)}"
        )


@router.get("/{run_id}/logs/stream")
async def stream_run_logs(
    run_id: UUID,
    session: Session = Depends(get_session)
) -> StreamingResponse:
    """
    Server-Sent Events für Live-Logs (für laufende Runs).
    
    Verwendet asyncio.Queue für Log-Zeilen (pro Run-ID eine Queue).
    Docker-Client schiebt jede neue Log-Zeile in die Queue.
    Rate-Limiting: Maximal X Zeilen pro Sekunde an Frontend senden (konfigurierbar, Standard: 100).
    
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
    
    # Log-Queue abrufen
    log_queue = get_log_queue(run_id)
    
    if log_queue is None:
        # Queue nicht vorhanden (Run ist bereits beendet oder noch nicht gestartet)
        # Versuche Logs aus Datei zu lesen (für abgeschlossene Runs)
        log_file_path = Path(run.log_file)
        if log_file_path.exists():
            try:
                async with aiofiles.open(log_file_path, "r", encoding="utf-8") as f:
                    contents = await f.read()
                # Sende gesamte Log-Datei als SSE-Events
                async def generate():
                    for line in contents.split("\n"):
                        yield f"data: {line}\n\n"
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
        
        Liest Log-Zeilen aus Queue und sendet sie als SSE-Events.
        Rate-Limiting: Maximal LOG_STREAM_RATE_LIMIT Zeilen pro Sekunde.
        """
        rate_limit = config.LOG_STREAM_RATE_LIMIT
        min_interval = 1.0 / rate_limit if rate_limit > 0 else 0.01
        
        last_send_time = 0.0
        
        try:
            while True:
                try:
                    # Warte auf nächste Log-Zeile (mit Timeout für Keep-Alive)
                    log_line = await asyncio.wait_for(log_queue.get(), timeout=1.0)
                    
                    # Rate-Limiting: Warte bis nächster Send-Zeitpunkt
                    current_time = asyncio.get_event_loop().time()
                    time_since_last_send = current_time - last_send_time
                    
                    if time_since_last_send < min_interval:
                        await asyncio.sleep(min_interval - time_since_last_send)
                    
                    # SSE-Event senden
                    # Format: data: {json}\n\n
                    import json
                    event_data = json.dumps({"line": log_line})
                    yield f"data: {event_data}\n\n"
                    
                    last_send_time = asyncio.get_event_loop().time()
                    
                except asyncio.TimeoutError:
                    # Timeout: Sende Keep-Alive (leeres Event)
                    yield ": keep-alive\n\n"
                    continue
                    
        except asyncio.CancelledError:
            # Client hat Verbindung getrennt
            pass
        except Exception as e:
            # Fehler: Sende Fehler-Event
            import json
            error_data = json.dumps({"error": str(e)})
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
