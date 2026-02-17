"""
Log Streaming API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Log-Streaming:
- Logs aus Datei lesen
- Server-Sent Events für Live-Logs

Sicherheit: Alle Endpunkte erfordern Authentifizierung.
Alle authentifizierten Benutzer (READONLY, WRITE, ADMIN) können Logs lesen.
"""

import asyncio
import aiofiles
from pathlib import Path
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import Session, select

from app.core.database import get_session, retry_on_sqlite_io
from app.models import PipelineRun, User
from app.executor import get_log_queue
from app.core.config import config
from app.auth import (
    get_current_user,
    create_log_download_token,
    verify_log_download_token,
    verify_token,
    get_session_by_token,
)
from app.core.errors import get_500_detail
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["logs"])
_security = HTTPBearer(auto_error=False)


async def require_log_access(
    run_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> None:
    """Prüft Bearer-Auth ODER gültigen download_token."""
    download_token = request.query_params.get("download_token")

    if credentials is not None:
        token = credentials.credentials
        if verify_token(token) and get_session_by_token(session, token):
            return

    if download_token and verify_log_download_token(download_token, run_id):
        return

    raise HTTPException(status_code=401, detail="Authentifizierung erforderlich")


@router.get("/{run_id}/logs/download-url")
async def get_logs_download_url(
    run_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Liefert einen kurzlebigen Download-Token für die Log-Datei.
    Das Frontend baut die URL (gleicher Origin wie API-Requests).
    """
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run nicht gefunden: {run_id}")
    token = create_log_download_token(run_id)
    return {"token": token}


@router.get("/{run_id}/logs")
async def get_run_logs(
    run_id: UUID,
    tail: Optional[int] = Query(default=None, ge=1, le=100_000, description="Letzte N Zeilen (max. 100.000)"),
    session: Session = Depends(get_session),
    _: None = Depends(require_log_access),
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
    
    # Pfad auflösen (falls relativ, wird relativ zu LOGS_DIR aufgelöst)
    # Path Traversal-Schutz: Sicherstellen dass Pfad innerhalb LOGS_DIR liegt
    log_file_path = Path(run.log_file)
    if not log_file_path.is_absolute():
        # Relativer Pfad: Auflösen relativ zu LOGS_DIR
        # Normalisiere den Pfad um .. zu entfernen
        normalized_log_file = log_file_path.resolve()
        log_file_path = config.LOGS_DIR / normalized_log_file
    else:
        # Absoluter Pfad: Verwende direkt, aber prüfe dass er innerhalb LOGS_DIR liegt
        log_file_path = log_file_path
    
    # Sicherstellen dass der finale Pfad wirklich innerhalb LOGS_DIR liegt
    # Verhindert Path Traversal-Angriffe
    try:
        logs_dir_abs = config.LOGS_DIR.resolve()
        log_file_path_abs = log_file_path.resolve()
        
        # Prüfe dass log_file_path innerhalb logs_dir liegt
        if not str(log_file_path_abs).startswith(str(logs_dir_abs)):
            logger.warning(
                f"Path Traversal-Versuch erkannt bei Log-Zugriff: "
                f"Run {run_id}, Pfad {run.log_file} -> {log_file_path_abs}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Zugriff auf Log-Datei verweigert"
            )
    except (ValueError, OSError) as e:
        logger.error(f"Fehler bei Pfad-Validierung für Log-Datei: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Fehler beim Validieren des Log-Pfads"
        )
    
    if not log_file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log-Datei nicht gefunden: {log_file_path} (original: {run.log_file})"
        )
    
    try:
        # Asynchrones Datei-Lesen (verhindert Blocking des Event-Loops)
        async with aiofiles.open(log_file_path, "r", encoding="utf-8") as f:
            contents = await f.read()
        
        # Tail-Funktionalität (letzte N Zeilen)
        if tail is not None and tail > 0:
            lines = contents.split("\n")
            contents = "\n".join(lines[-tail:])
        
        filename = f"run-{run_id}-logs.txt"
        return PlainTextResponse(
            content=contents,
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
        
    except Exception as e:
        logger.exception("Fehler beim Lesen der Log-Datei")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )


@router.get("/{run_id}/logs/stream")
async def stream_run_logs(
    run_id: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
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
        # Pfad auflösen (falls relativ, wird relativ zu LOGS_DIR aufgelöst)
        # Path Traversal-Schutz: Sicherstellen dass Pfad innerhalb LOGS_DIR liegt
        if not log_file_path.is_absolute():
            normalized_log_file = log_file_path.resolve()
            log_file_path = config.LOGS_DIR / normalized_log_file
        
        # Sicherstellen dass der finale Pfad wirklich innerhalb LOGS_DIR liegt
        try:
            logs_dir_abs = config.LOGS_DIR.resolve()
            log_file_path_abs = log_file_path.resolve()
            
            if not str(log_file_path_abs).startswith(str(logs_dir_abs)):
                logger.warning(
                    f"Path Traversal-Versuch erkannt bei Log-Stream: "
                    f"Run {run_id}, Pfad {run.log_file} -> {log_file_path_abs}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Zugriff auf Log-Datei verweigert"
                )
        except (ValueError, OSError) as e:
            logger.error(f"Fehler bei Pfad-Validierung für Log-Datei: {e}")
            # Nicht weiterwerfen, da wir im Fallback sind
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
        
        WICHTIG: Liest zuerst alle vorhandenen Logs aus der Queue (falls vorhanden),
        dann wartet es auf neue Logs.
        """
        rate_limit = config.LOG_STREAM_RATE_LIMIT
        min_interval = 1.0 / rate_limit if rate_limit > 0 else 0.01
        
        last_send_time = 0.0
        import json
        
        try:
            # SCHRITT 1: Lese bereits vorhandene Logs aus der Queue (max. LOG_STREAM_PENDING_MAX_LINES)
            # Verhindert OOM bei spätem Connect und großer Queue
            pending_logs = []
            skipped_count = 0
            max_pending = config.LOG_STREAM_PENDING_MAX_LINES
            try:
                while len(pending_logs) < max_pending:
                    log_line = log_queue.get_nowait()
                    pending_logs.append(log_line)
                # Weitere Zeilen verwerfen (Queue leeren, um Platz für neue zu machen)
                while True:
                    log_queue.get_nowait()
                    skipped_count += 1
            except asyncio.QueueEmpty:
                pass

            if skipped_count > 0:
                # Hinweis an Frontend: ältere Zeilen übersprungen
                skip_data = json.dumps({
                    "skipped": skipped_count,
                    "message": f"{skipped_count} ältere Log-Zeilen übersprungen (max. {max_pending}). Log-Datei enthält alle Zeilen.",
                })
                yield f"data: {skip_data}\n\n"

            # Sende alle vorhandenen Logs (mit Rate-Limiting)
            for log_line in pending_logs:
                # Rate-Limiting
                current_time = asyncio.get_running_loop().time()
                time_since_last_send = current_time - last_send_time
                
                if time_since_last_send < min_interval:
                    await asyncio.sleep(min_interval - time_since_last_send)
                
                event_data = json.dumps({"line": log_line})
                yield f"data: {event_data}\n\n"
                last_send_time = asyncio.get_running_loop().time()
            
            # SCHRITT 2: Warte auf neue Logs (Streaming)
            while True:
                try:
                    # Warte auf nächste Log-Zeile (mit Timeout für Keep-Alive)
                    log_line = await asyncio.wait_for(log_queue.get(), timeout=1.0)
                    
                    # Rate-Limiting: Warte bis nächster Send-Zeitpunkt
                    current_time = asyncio.get_running_loop().time()
                    time_since_last_send = current_time - last_send_time
                    
                    if time_since_last_send < min_interval:
                        await asyncio.sleep(min_interval - time_since_last_send)
                    
                    # SSE-Event senden
                    # Format: data: {json}\n\n
                    event_data = json.dumps({"line": log_line})
                    yield f"data: {event_data}\n\n"
                    
                    last_send_time = asyncio.get_running_loop().time()
                    
                except asyncio.TimeoutError:
                    # Timeout: Sende Keep-Alive (leeres Event)
                    yield ": keep-alive\n\n"
                    continue
                    
        except asyncio.CancelledError:
            # Client hat Verbindung getrennt
            pass
        except Exception as e:
            logger.exception("Fehler beim Log-SSE-Stream")
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
