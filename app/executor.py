"""
Docker Container Execution Module.

Dieses Modul verwaltet die Ausführung von Pipeline-Containers:
- Container-Start mit Resource-Limits
- Log-Streaming und Persistenz
- Metrics-Monitoring (CPU/RAM)
- Container-Cleanup
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Any, AsyncGenerator
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor

import docker
from docker.errors import DockerException, APIError, ImageNotFound
from sqlmodel import Session, select, update

from app.config import config
from app.models import Pipeline, PipelineRun, RunStatus
from app.pipeline_discovery import DiscoveredPipeline, get_pipeline

logger = logging.getLogger(__name__)

# Thread Pool für synchrone Docker-Operationen
_executor = ThreadPoolExecutor(max_workers=10)

# Docker Client (wird beim App-Start initialisiert)
_docker_client: Optional[docker.DockerClient] = None

# Concurrency-Tracking
_running_containers: Dict[UUID, docker.models.containers.Container] = {}
_concurrency_lock = asyncio.Lock()

# Log-Queues für SSE-Streaming (pro Run-ID)
_log_queues: Dict[UUID, asyncio.Queue] = {}

# Metrics-Queues für SSE-Streaming (pro Run-ID)
_metrics_queues: Dict[UUID, asyncio.Queue] = {}

# Pre-Heating-Locks (pro Pipeline-Name)
_pre_heating_locks: Dict[str, asyncio.Lock] = {}


def init_docker_client() -> None:
    """
    Initialisiert den Docker-Client und prüft die Verbindung.
    
    Wird beim App-Start aufgerufen, um sicherzustellen, dass Docker
    verfügbar ist. Pullt das Worker-Image falls nötig.
    
    Raises:
        RuntimeError: Wenn Docker-Daemon nicht erreichbar ist
        docker.errors.APIError: Wenn Image-Pull fehlschlägt
    """
    global _docker_client
    
    try:
        # Docker-Client initialisieren
        _docker_client = docker.from_env()
        
        # Health-Check: Docker-Daemon-Verbindung prüfen
        _docker_client.ping()
        logger.info("Docker-Daemon-Verbindung erfolgreich")
        
        # Worker-Image prüfen/pullen
        _ensure_worker_image()
        
    except DockerException as e:
        error_msg = (
            f"Docker-Daemon ist nicht erreichbar: {e}. "
            "Stelle sicher, dass Docker läuft und der Socket verfügbar ist."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e
    except Exception as e:
        error_msg = f"Unerwarteter Fehler bei Docker-Client-Initialisierung: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


def _ensure_worker_image() -> None:
    """
    Prüft ob Worker-Image vorhanden ist und pullt es falls nötig.
    
    Raises:
        docker.errors.APIError: Wenn Image-Pull fehlschlägt
    """
    if _docker_client is None:
        raise RuntimeError("Docker-Client nicht initialisiert")
    
    try:
        # Prüfe ob Image lokal vorhanden ist
        _docker_client.images.get(config.WORKER_BASE_IMAGE)
        logger.info(f"Worker-Image vorhanden: {config.WORKER_BASE_IMAGE}")
        
    except ImageNotFound:
        # Image nicht vorhanden, versuche es zu pullen
        logger.info(f"Worker-Image nicht gefunden, starte Pull: {config.WORKER_BASE_IMAGE}")
        try:
            _docker_client.images.pull(config.WORKER_BASE_IMAGE)
            logger.info(f"Worker-Image erfolgreich gepullt: {config.WORKER_BASE_IMAGE}")
        except APIError as e:
            error_msg = (
                f"Fehler beim Pullen des Worker-Images {config.WORKER_BASE_IMAGE}: {e}. "
                "Stelle sicher, dass die Registry erreichbar ist."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e


def _get_docker_client() -> docker.DockerClient:
    """
    Gibt den Docker-Client zurück.
    
    Returns:
        Docker-Client-Instanz
        
    Raises:
        RuntimeError: Wenn Docker-Client nicht initialisiert ist
    """
    if _docker_client is None:
        raise RuntimeError("Docker-Client nicht initialisiert. Rufe init_docker_client() auf.")
    return _docker_client


def _get_host_path_for_volume(
    client: docker.DockerClient,
    container_path: str,
    host_path_env: Optional[str]
) -> str:
    """
    Ermittelt den Host-Pfad für ein gemountetes Volume.
    
    Versucht zuerst, den Host-Pfad aus den Container-Volumes zu extrahieren (zuverlässigste Methode).
    Falls das nicht möglich ist, wird der host_path_env verwendet oder container_path als Fallback.
    
    Args:
        client: Docker-Client
        container_path: Container-interner Pfad (z.B. /app/pipelines)
        host_path_env: Host-Pfad aus Environment-Variable (optional)
    
    Returns:
        Absoluter Host-Pfad für Volume-Mounts
    """
    # Versuche zuerst, Host-Pfad aus Container-Volumes zu extrahieren (zuverlässigste Methode)
    try:
        # Container-Name aus Environment-Variable (falls gesetzt)
        container_name = os.getenv("HOSTNAME", "fastflow-orchestrator")
        
        # Versuche, Container zu finden
        try:
            container = client.containers.get(container_name)
            # Container-Volumes inspizieren
            mounts = container.attrs.get("Mounts", [])
            for mount in mounts:
                destination = mount.get("Destination")
                # Prüfe ob der Container-Pfad übereinstimmt
                if destination == container_path or container_path.startswith(destination + "/"):
                    source = mount.get("Source")
                    if source and os.path.isabs(source):
                        logger.debug(f"Host-Pfad für {container_path} aus Volume extrahiert: {source}")
                        return source
        except docker.errors.NotFound:
            # Container nicht gefunden, verwende Fallback
            pass
    except Exception as e:
        logger.debug(f"Fehler beim Extrahieren des Host-Pfads für {container_path}: {e}")
    
    # Fallback 1: Wenn host_path_env gesetzt ist und absolut ist, verwende es
    if host_path_env and os.path.isabs(host_path_env):
        logger.debug(f"Verwende absoluten Host-Pfad aus Environment: {host_path_env}")
        return host_path_env
    
    # Fallback 2: Für lokale Entwicklung außerhalb von Docker
    logger.warning(
        f"Konnte Host-Pfad für {container_path} nicht ermitteln. "
        f"Verwende container_path als Fallback. "
        f"Dies funktioniert nur für lokale Entwicklung außerhalb von Docker."
    )
    return str(Path(container_path).resolve())


def _convert_memory_to_bytes(memory_str: str) -> int:
    """
    Konvertiert Memory-String (z.B. "1g", "512m") zu Bytes.
    
    Args:
        memory_str: Memory-String (z.B. "1g", "512m", "1024")
    
    Returns:
        Memory in Bytes
        
    Raises:
        ValueError: Wenn Format ungültig ist
    """
    memory_str = memory_str.lower().strip()
    
    if memory_str.endswith("g"):
        return int(memory_str[:-1]) * 1024 * 1024 * 1024
    elif memory_str.endswith("m"):
        return int(memory_str[:-1]) * 1024 * 1024
    elif memory_str.endswith("k"):
        return int(memory_str[:-1]) * 1024
    else:
        # Angenommen Bytes
        return int(memory_str)


def _get_pre_heating_lock(pipeline_name: str) -> asyncio.Lock:
    """
    Gibt Lock für Pre-Heating-Operationen zurück (pro Pipeline).
    
    Args:
        pipeline_name: Name der Pipeline
    
    Returns:
        Lock für Pre-Heating-Operationen
    """
    if pipeline_name not in _pre_heating_locks:
        _pre_heating_locks[pipeline_name] = asyncio.Lock()
    return _pre_heating_locks[pipeline_name]


async def run_pipeline(
    name: str,
    env_vars: Optional[Dict[str, str]] = None,
    parameters: Optional[Dict[str, str]] = None,
    session: Optional[Session] = None
) -> PipelineRun:
    """
    Startet eine Pipeline mit optionalen Environment-Variablen und Parametern.
    
    Args:
        name: Name der Pipeline (muss existieren)
        env_vars: Dictionary mit Environment-Variablen (werden als Secrets injiziert)
        parameters: Dictionary mit Pipeline-Parametern (werden als Env-Vars injiziert)
        session: SQLModel Session (optional, wird intern erstellt wenn nicht vorhanden)
    
    Returns:
        PipelineRun: Der erstellte PipelineRun-Datensatz mit Status PENDING
    
    Raises:
        ValueError: Wenn Pipeline nicht existiert oder deaktiviert ist
        RuntimeError: Wenn Concurrency-Limit erreicht ist oder Docker nicht verfügbar
    """
    if env_vars is None:
        env_vars = {}
    if parameters is None:
        parameters = {}
    
    # Pipeline-Metadaten laden
    pipeline = get_pipeline(name)
    if pipeline is None:
        raise ValueError(f"Pipeline nicht gefunden: {name}")
    
    # Prüfe ob Pipeline aktiviert ist
    if not pipeline.is_enabled():
        raise ValueError(f"Pipeline ist deaktiviert: {name}")
    
    # Concurrency-Limit prüfen
    async with _concurrency_lock:
        if len(_running_containers) >= config.MAX_CONCURRENT_RUNS:
            raise RuntimeError(
                f"Concurrency-Limit erreicht ({config.MAX_CONCURRENT_RUNS}). "
                "Bitte warte bis ein Run abgeschlossen ist."
            )
    
    # Pre-Heating-Lock abrufen (wenn Pre-Heating aktiv ist)
    pre_heating_lock = _get_pre_heating_lock(name)
    
    # Datenbank-Session verwenden oder neue erstellen
    if session is None:
        from app.database import get_session
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    
    try:
        # Secrets aus Datenbank abrufen
        from app.secrets import get_all_secrets
        all_secrets = get_all_secrets(session)
        
        # Environment-Variablen zusammenführen
        # 1. Default-Env-Vars aus Metadaten
        merged_env_vars = pipeline.metadata.default_env.copy()
        
        # 2. Secrets aus Datenbank (haben Vorrang vor Default-Env-Vars)
        merged_env_vars.update(all_secrets)
        
        # 3. UI-spezifische Env-Vars und Parameter (haben Vorrang bei Duplikaten)
        merged_env_vars.update(env_vars)
        merged_env_vars.update(parameters)
        
        # PipelineRun-Datensatz erstellen
        run = PipelineRun(
            pipeline_name=name,
            status=RunStatus.PENDING,
            log_file=str(config.LOGS_DIR / f"{name}_{datetime.utcnow().isoformat()}.log"),
            env_vars=merged_env_vars,
            parameters=parameters
        )
        
        session.add(run)
        session.commit()
        session.refresh(run)
        
        # Container-Start in Hintergrund-Task (Session wird intern erstellt)
        asyncio.create_task(
            _run_container_task(
                run.id,
                pipeline,
                merged_env_vars,
                pre_heating_lock
            )
        )
        
        return run
        
    finally:
        if close_session:
            session.close()


async def _run_container_task(
    run_id: UUID,
    pipeline: DiscoveredPipeline,
    env_vars: Dict[str, str],
    pre_heating_lock: asyncio.Lock
) -> None:
    """
    Hintergrund-Task für Container-Ausführung.
    
    Args:
        run_id: Run-ID
        pipeline: DiscoveredPipeline-Objekt
        env_vars: Zusammenfgeführte Environment-Variablen
        pre_heating_lock: Lock für Pre-Heating-Operationen
    """
    from app.database import get_session
    
    container = None
    log_file_path = None
    metrics_file_path = None
    
    # Session für diese Task erstellen
    session_gen = get_session()
    session = next(session_gen)
    
    try:
        # Run-Objekt aus DB abrufen
        run = session.get(PipelineRun, run_id)
        if not run:
            logger.error(f"Run {run_id} nicht in Datenbank gefunden")
            return
        
        # Warte auf Pre-Heating-Lock (falls Pre-Heating aktiv ist)
        if config.UV_PRE_HEAT:
            async with pre_heating_lock:
                # Pre-Heating läuft oder ist abgeschlossen
                pass
        
        # Log-Datei-Pfad aus Run-Objekt verwenden
        log_file_path = Path(run.log_file)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        # Leere Log-Datei erstellen, damit der Endpoint sie finden kann
        if not log_file_path.exists():
            log_file_path.touch()
        
        # Metrics-Datei-Pfad erstellen
        metrics_file_path = Path(config.LOGS_DIR / f"{run_id}_metrics.jsonl")
        
        # Queue für Log-Streaming erstellen
        log_queue = asyncio.Queue()
        _log_queues[run_id] = log_queue
        
        # Queue für Metrics-Streaming erstellen
        metrics_queue = asyncio.Queue()
        _metrics_queues[run_id] = metrics_queue
        
        # Container-Start vorbereiten
        client = _get_docker_client()
        
        # Resource-Limits aus Metadaten
        cpu_hard_limit = pipeline.metadata.cpu_hard_limit
        mem_hard_limit = pipeline.metadata.mem_hard_limit
        
        # Container-Konfiguration
        # Host-Pfade für Volume-Mounts verwenden (falls in Docker-Container)
        # WICHTIG: Host-Pfade müssen absolut sein und vom Host-System stammen, nicht vom Container
        # Versuche, Host-Pfade aus den gemounteten Volumes zu extrahieren
        pipelines_host_path = _get_host_path_for_volume(
            client, str(config.PIPELINES_DIR), config.PIPELINES_HOST_DIR
        )
        uv_cache_host_path = _get_host_path_for_volume(
            client, str(config.UV_CACHE_DIR), config.UV_CACHE_HOST_DIR
        )
        
        container_config = {
            "image": config.WORKER_BASE_IMAGE,
            "command": _build_container_command(pipeline),
            "environment": env_vars,
            "volumes": {
                pipelines_host_path: {"bind": "/app", "mode": "ro"},
                uv_cache_host_path: {"bind": "/root/.cache/uv", "mode": "rw"}
            },
            "labels": {
                "fastflow-run-id": str(run_id),
                "fastflow-pipeline": pipeline.name
            },
            "auto_remove": False,  # Wird manuell entfernt
            "detach": True,
            "log_config": {
                "type": "json-file",
                "config": {
                    "max-size": "10m",
                    "max-file": "3"
                }
            }
        }
        
        # Hard Limits setzen (wenn in Metadaten definiert)
        if mem_hard_limit:
            mem_bytes = _convert_memory_to_bytes(mem_hard_limit)
            container_config["mem_limit"] = mem_bytes
            container_config["memswap_limit"] = mem_bytes  # Verhindert Swapping
        
        if cpu_hard_limit:
            # CPU-Limit in nano_cpus (1 Kern = 1e9 nano_cpus)
            container_config["nano_cpus"] = int(cpu_hard_limit * 1e9)
        
        # Container starten
        container = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: client.containers.run(**container_config)
        )
        
        # Container in Tracking-Dictionary speichern
        async with _concurrency_lock:
            _running_containers[run_id] = container
        
        # Status auf RUNNING setzen
        run.status = RunStatus.RUNNING
        session.add(run)
        session.commit()
        
        # WICHTIG: Log-Streaming SOFORT starten, damit keine Logs verloren gehen
        # Laut IMPLEMENTATION_PLAN sollen Logs während des gesamten Container-Laufs gestreamt werden
        log_task = asyncio.create_task(
            _stream_logs(container, log_file_path, log_queue, run_id)
        )
        metrics_task = asyncio.create_task(
            _monitor_metrics(
                container,
                metrics_file_path,
                metrics_queue,
                pipeline,
                run_id
            )
        )
        
        # UV-Version erfassen (aus Container) - parallel zu Log-Streaming
        uv_version = await _get_uv_version(container)
        run.uv_version = uv_version
        session.add(run)
        session.commit()
        
        # Setup-Duration messen (Zeit für uv-Setup)
        setup_start = time.time()
        # Warte kurz auf erste Logs (uv-Setup)
        await asyncio.sleep(1)
        setup_duration = time.time() - setup_start
        
        run.setup_duration = setup_duration
        session.add(run)
        session.commit()
        
        # Pipeline-spezifisches Timeout bestimmen
        timeout = pipeline.get_timeout() or config.CONTAINER_TIMEOUT
        
        # Container-Wait mit Timeout
        if timeout:
            try:
                exit_code = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        _executor,
                        lambda: container.wait(timeout=timeout)
                    ),
                    timeout=timeout + 10  # Buffer für Timeout
                )
            except asyncio.TimeoutError:
                # Timeout erreicht, Container killen
                logger.warning(f"Container-Timeout erreicht für Run {run_id}, killen Container")
                container.kill()
                exit_code = {"StatusCode": -1}  # Timeout-Exit-Code
        else:
            # Kein Timeout, warte auf natürliches Ende
            exit_code = await asyncio.get_event_loop().run_in_executor(
                _executor,
                container.wait
            )
        
        # Warte kurz, damit alle Logs geschrieben werden können
        await asyncio.sleep(0.5)
        
        # Tasks beenden (gracefully)
        log_task.cancel()
        try:
            await asyncio.wait_for(log_task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        
        # Versuche, verbleibende Logs aus Container zu lesen (falls Stream nicht alle geliefert hat)
        try:
            import aiofiles
            remaining_logs_bytes = await asyncio.get_event_loop().run_in_executor(
                _executor,
                lambda: container.logs(stdout=True, stderr=True, tail=1000)
            )
            if remaining_logs_bytes:
                # Prüfe ob Log-Datei bereits Logs enthält
                log_file_size = log_file_path.stat().st_size if log_file_path.exists() else 0
                
                # Dekodiere Logs
                remaining_logs = remaining_logs_bytes.decode("utf-8", errors="replace")
                
                # Verarbeite JSON-Log-Format (falls verwendet)
                log_lines = []
                for line in remaining_logs.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    # Docker JSON-Log-Format verarbeiten
                    if line.startswith("{"):
                        try:
                            log_json = json.loads(line)
                            log_lines.append(log_json.get("log", line).rstrip())
                        except (json.JSONDecodeError, AttributeError):
                            log_lines.append(line)
                    else:
                        log_lines.append(line)
                
                # Nur hinzufügen wenn Log-Datei leer oder klein ist
                if log_file_size < 100:  # Datei ist leer oder fast leer
                    async with aiofiles.open(log_file_path, "w", encoding="utf-8") as f:
                        await f.write("\n".join(log_lines))
                        await f.flush()
                else:
                    # Datei hat bereits Inhalte, prüfe ob neue Logs hinzugefügt werden müssen
                    async with aiofiles.open(log_file_path, "r", encoding="utf-8") as f:
                        existing_content = await f.read()
                    
                    # Füge nur neue Logs hinzu
                    new_logs_text = "\n".join(log_lines)
                    if new_logs_text and new_logs_text not in existing_content:
                        async with aiofiles.open(log_file_path, "a", encoding="utf-8") as f:
                            await f.write("\n" + new_logs_text)
                            await f.flush()
        except Exception as e:
            logger.debug(f"Fehler beim Lesen verbleibender Logs für Run {run_id}: {e}")
        
        metrics_task.cancel()
        try:
            await asyncio.wait_for(metrics_task, timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        
        # Exit-Code extrahieren
        exit_code_value = exit_code.get("StatusCode", -1) if isinstance(exit_code, dict) else exit_code
        
        # Spezielle Exit-Code-Erkennung
        error_type = _classify_exit_code(exit_code_value)
        
        # Run-Objekt aktualisieren
        run = session.get(PipelineRun, run_id)
        if not run:
            logger.error(f"Run {run_id} nicht in Datenbank gefunden beim Status-Update")
            return
        
        # Status basierend auf Exit-Code setzen
        run.exit_code = exit_code_value
        run.finished_at = datetime.utcnow()
        
        if exit_code_value == 0:
            run.status = RunStatus.SUCCESS
        else:
            run.status = RunStatus.FAILED
            # Error-Type in Log-Datei schreiben (für UI-Anzeige)
            if error_type:
                logger.warning(f"Run {run_id} fehlgeschlagen: {error_type} (Exit-Code: {exit_code_value})")
        
        # Metrics-Datei-Pfad speichern
        if metrics_file_path.exists():
            run.metrics_file = str(metrics_file_path)
        
        session.add(run)
        session.commit()
        
        # Pipeline-Statistiken aktualisieren (atomar)
        await _update_pipeline_stats(pipeline.name, exit_code_value == 0, session)
        
        # Benachrichtigungen senden (nur bei Fehlern)
        if exit_code_value != 0:
            from app.notifications import send_notifications
            await send_notifications(run, RunStatus.FAILED)
        
    except Exception as e:
        logger.error(f"Fehler bei Container-Ausführung für Run {run_id}: {e}", exc_info=True)
        
        # Status auf FAILED setzen
        run = session.get(PipelineRun, run_id)
        if run:
            run.status = RunStatus.FAILED
            run.finished_at = datetime.utcnow()
            run.exit_code = -1
            session.add(run)
            session.commit()
            
            # Pipeline-Statistiken aktualisieren (Fehler)
            await _update_pipeline_stats(run.pipeline_name, False, session)
            
            # Benachrichtigungen senden
            from app.notifications import send_notifications
            await send_notifications(run, RunStatus.FAILED)
        
    finally:
        # Container-Cleanup
        if container:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    _executor,
                    lambda: container.remove(force=True)
                )
            except Exception as e:
                logger.warning(f"Fehler beim Container-Cleanup für Run {run_id}: {e}")
        
        # Container aus Tracking entfernen
        async with _concurrency_lock:
            _running_containers.pop(run_id, None)
        
        # Queues aufräumen
        _log_queues.pop(run_id, None)
        _metrics_queues.pop(run_id, None)
        
        # Session schließen
        try:
            session.close()
        except Exception:
            pass


def _build_container_command(pipeline: DiscoveredPipeline) -> List[str]:
    """
    Baut den Container-Befehl für Pipeline-Ausführung.
    
    WICHTIG: Fügt Python-Flags hinzu für unbuffered output (-u),
    damit Logs sofort ausgegeben werden und nicht gepuffert werden.
    
    Args:
        pipeline: DiscoveredPipeline-Objekt
    
    Returns:
        Liste mit Container-Befehl (uv run --with-requirements ...)
    """
    if pipeline.has_requirements:
        requirements_path = f"/app/{pipeline.name}/requirements.txt"
        main_py_path = f"/app/{pipeline.name}/main.py"
        return [
            "uv", "run",
            "--with-requirements", requirements_path,
            # Python unbuffered mode: -u Flag für sofortige Ausgabe
            "python", "-u", main_py_path
        ]
    else:
        main_py_path = f"/app/{pipeline.name}/main.py"
        # Python unbuffered mode: -u Flag für sofortige Ausgabe
        return ["uv", "run", "python", "-u", main_py_path]


async def _get_uv_version(container: docker.models.containers.Container) -> Optional[str]:
    """
    Ermittelt die UV-Version aus dem Container.
    
    Args:
        container: Docker-Container-Objekt
    
    Returns:
        UV-Version-String oder None
    """
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: container.exec_run("uv --version")
        )
        if result.exit_code == 0:
            # Output ist Bytes, dekodieren
            output = result.output.decode("utf-8").strip()
            return output
    except Exception as e:
        logger.warning(f"Fehler beim Ermitteln der UV-Version: {e}")
    
    return None


async def _stream_logs(
    container: docker.models.containers.Container,
    log_file_path: Path,
    log_queue: asyncio.Queue,
    run_id: UUID
) -> None:
    """
    Streamt Logs aus Container und schreibt sie in Datei und Queue.
    
    Args:
        container: Docker-Container-Objekt
        log_file_path: Pfad zur Log-Datei
        log_queue: Queue für SSE-Streaming
        run_id: Run-ID
    """
    import aiofiles
    
    try:
        logger.info(f"Starte Log-Streaming für Run {run_id}, Container: {container.id}")
        
        # Log-Stream aus Container abrufen
        log_stream = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: container.logs(stream=True, follow=True, stdout=True, stderr=True)
        )
        
        logger.debug(f"Log-Stream für Run {run_id} erstellt")
        
        # Datei-Handle öffnen (asynchron, append-Modus falls Datei bereits existiert)
        # Verwende "a" (append) statt "w" (write), damit vorhandene Inhalte nicht überschrieben werden
        async with aiofiles.open(log_file_path, "a", encoding="utf-8") as log_file:
            line_count = 0
            last_size_check = time.time()
            first_log_received = False
            should_break = False
            
            # Puffer für unvollständige Zeilen (falls Chunks mitten in Zeilen enden)
            line_buffer = b""
            
            async for log_chunk in _iter_log_stream(log_stream):
                # Prüfe ob wir abbrechen sollen
                if should_break:
                    break
                
                # Füge Chunk zum Buffer hinzu
                line_buffer += log_chunk
                
                # Verarbeite vollständige Zeilen (getrennt durch \n)
                while b"\n" in line_buffer:
                    if should_break:
                        break
                    
                    line_part, line_buffer = line_buffer.split(b"\n", 1)
                    
                    # Log-Zeile dekodieren
                    try:
                        log_line = line_part.decode("utf-8").rstrip()
                    except UnicodeDecodeError:
                        log_line = line_part.decode("utf-8", errors="replace").rstrip()
                    
                    # Docker JSON-Log-Format verarbeiten (falls verwendet)
                    # Docker kann Logs im JSON-Format ausgeben: {"log":"...","stream":"stdout","time":"..."}
                    if log_line.startswith("{"):
                        try:
                            log_json = json.loads(log_line)
                            log_line = log_json.get("log", log_line).rstrip()
                        except (json.JSONDecodeError, AttributeError):
                            # Kein JSON, verwende direkt
                            pass
                    
                    # Nur schreiben wenn Zeile nicht leer ist
                    if log_line:
                        if not first_log_received:
                            logger.info(f"Erste Log-Zeile für Run {run_id} empfangen: {log_line[:100]}")
                            first_log_received = True
                        
                        # Zeitstempel hinzufügen (Format: YYYY-MM-DD HH:MM:SS.mmm)
                        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                        log_line_with_timestamp = f"[{timestamp}] {log_line}"
                        
                        # In Datei schreiben (asynchron)
                        await log_file.write(log_line_with_timestamp + "\n")
                        await log_file.flush()
                        
                        # In Queue für SSE-Streaming (mit Zeitstempel)
                        try:
                            log_queue.put_nowait(log_line_with_timestamp)
                        except asyncio.QueueFull:
                            # Queue voll, alte Einträge entfernen (Ring-Buffer-Verhalten)
                            try:
                                log_queue.get_nowait()
                                log_queue.put_nowait(log_line_with_timestamp)
                            except asyncio.QueueEmpty:
                                pass
                        
                        line_count += 1
                        
                        # Log-Spam-Schutz: Dateigröße prüfen (alle 1000 Zeilen oder alle 10 Sekunden)
                        if line_count % 1000 == 0 or (time.time() - last_size_check) > 10:
                            last_size_check = time.time()
                            
                            if config.LOG_MAX_SIZE_MB:
                                file_size_mb = log_file_path.stat().st_size / (1024 * 1024)
                                if file_size_mb > config.LOG_MAX_SIZE_MB:
                                    logger.warning(
                                        f"Log-Datei für Run {run_id} überschreitet "
                                        f"LOG_MAX_SIZE_MB ({config.LOG_MAX_SIZE_MB} MB): {file_size_mb:.2f} MB"
                                    )
                                    # Stream kappen (keine weiteren Logs schreiben)
                                    should_break = True
                                    break
            
            # Verarbeite verbleibenden Buffer am Ende (letzte unvollständige Zeile)
            if line_buffer and not should_break:
                try:
                    log_line = line_buffer.decode("utf-8").rstrip()
                except UnicodeDecodeError:
                    log_line = line_buffer.decode("utf-8", errors="replace").rstrip()
                
                if log_line:
                    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    log_line_with_timestamp = f"[{timestamp}] {log_line}"
                    await log_file.write(log_line_with_timestamp + "\n")
                    await log_file.flush()
                    try:
                        log_queue.put_nowait(log_line_with_timestamp)
                    except asyncio.QueueFull:
                        try:
                            log_queue.get_nowait()
                            log_queue.put_nowait(log_line_with_timestamp)
                        except asyncio.QueueEmpty:
                            pass
                    line_count += 1
        
    except asyncio.CancelledError:
        # Task wurde abgebrochen (normal bei Container-Ende)
        logger.debug(f"Log-Streaming für Run {run_id} wurde abgebrochen (Container beendet)")
        pass
    except Exception as e:
        logger.error(f"Fehler beim Log-Streaming für Run {run_id}: {e}", exc_info=True)
    finally:
        # Stream explizit schließen
        try:
            if hasattr(log_stream, 'close'):
                log_stream.close()
        except Exception:
            pass


async def _iter_log_stream(stream):
    """
    Iterator für Docker-Log-Stream (asynchron).
    
    Liest kontinuierlich aus dem Docker-Log-Stream und gibt Chunks zurück.
    Verwendet einen separaten Thread, um Blocking zu vermeiden.
    
    Args:
        stream: Docker-Log-Stream (Generator)
    
    Yields:
        Bytes: Log-Chunk
    """
    loop = asyncio.get_event_loop()
    
    while True:
        try:
            # Lese Chunk im Executor (non-blocking)
            chunk = await loop.run_in_executor(
                _executor,
                lambda: next(stream, None)
            )
            if chunk is None:
                # Stream ist beendet
                break
            yield chunk
        except StopIteration:
            # Generator ist erschöpft
            break
        except Exception as e:
            logger.warning(f"Fehler beim Lesen aus Log-Stream: {e}")
            # Warte kurz vor erneutem Versuch (falls temporärer Fehler)
            await asyncio.sleep(0.1)
            try:
                # Versuche nochmal
                chunk = await loop.run_in_executor(
                    _executor,
                    lambda: next(stream, None)
                )
                if chunk is None:
                    break
                yield chunk
            except (StopIteration, Exception):
                # Bei erneutem Fehler: beende Loop
                break


async def _monitor_metrics(
    container: docker.models.containers.Container,
    metrics_file_path: Path,
    metrics_queue: asyncio.Queue,
    pipeline: DiscoveredPipeline,
    run_id: UUID
) -> None:
    """
    Überwacht Container-Metrics (CPU & RAM) und speichert sie.
    
    Args:
        container: Docker-Container-Objekt
        metrics_file_path: Pfad zur Metrics-Datei
        metrics_queue: Queue für SSE-Streaming
        pipeline: DiscoveredPipeline-Objekt
        run_id: Run-ID
    """
    import aiofiles
    
    try:
        # Stats-Stream aus Container abrufen
        stats_stream = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: container.stats(stream=True, decode=True)
        )
        
        # Datei-Handle öffnen (asynchron)
        async with aiofiles.open(metrics_file_path, "w", encoding="utf-8") as metrics_file:
            prev_cpu_stats = None
            prev_system_cpu = None
            
            async for stats in _iter_stats_stream(stats_stream):
                try:
                    # CPU-Usage berechnen (Delta-Vergleich)
                    cpu_percent = _calculate_cpu_percent(stats, prev_cpu_stats, prev_system_cpu)
                    
                    # RAM-Usage erfassen
                    memory_stats = stats.get("memory_stats", {})
                    ram_usage_mb = memory_stats.get("usage", 0) / (1024 * 1024)
                    ram_limit_mb = memory_stats.get("limit", 0) / (1024 * 1024)
                    
                    # Soft-Limit-Überwachung
                    soft_limit_exceeded = False
                    if pipeline.metadata.cpu_soft_limit and cpu_percent:
                        if cpu_percent > (pipeline.metadata.cpu_soft_limit * 100):
                            soft_limit_exceeded = True
                    
                    if pipeline.metadata.mem_soft_limit:
                        mem_soft_limit_bytes = _convert_memory_to_bytes(pipeline.metadata.mem_soft_limit)
                        mem_soft_limit_mb = mem_soft_limit_bytes / (1024 * 1024)
                        if ram_usage_mb > mem_soft_limit_mb:
                            soft_limit_exceeded = True
                    
                    # Metrics-Objekt erstellen
                    metric = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "cpu_percent": cpu_percent,
                        "ram_mb": ram_usage_mb,
                        "ram_limit_mb": ram_limit_mb,
                        "soft_limit_exceeded": soft_limit_exceeded
                    }
                    
                    # In Datei schreiben (JSONL-Format)
                    await metrics_file.write(json.dumps(metric) + "\n")
                    await metrics_file.flush()
                    
                    # In Queue für SSE-Streaming
                    try:
                        metrics_queue.put_nowait(metric)
                    except asyncio.QueueFull:
                        # Queue voll, alte Einträge entfernen
                        try:
                            metrics_queue.get_nowait()
                            metrics_queue.put_nowait(metric)
                        except asyncio.QueueEmpty:
                            pass
                    
                    # Stats für nächste Iteration speichern
                    prev_cpu_stats = stats.get("cpu_stats", {})
                    prev_system_cpu = stats.get("precpu_stats", {})
                    
                    # Rate-Limiting: Alle 2 Sekunden messen
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.warning(f"Fehler beim Verarbeiten von Container-Stats für Run {run_id}: {e}")
        
    except asyncio.CancelledError:
        # Task wurde abgebrochen (normal bei Container-Ende)
        pass
    except Exception as e:
        logger.error(f"Fehler beim Metrics-Monitoring für Run {run_id}: {e}", exc_info=True)
    finally:
        # Stream explizit schließen
        try:
            if hasattr(stats_stream, 'close'):
                stats_stream.close()
        except Exception:
            pass


async def _iter_stats_stream(stream):
    """
    Iterator für Docker-Stats-Stream (asynchron).
    
    Args:
        stream: Docker-Stats-Stream
    
    Yields:
        Dict: Stats-Dictionary
    """
    while True:
        try:
            stats = await asyncio.get_event_loop().run_in_executor(
                _executor,
                lambda: next(stream, None)
            )
            if stats is None:
                break
            yield stats
        except StopIteration:
            break
        except Exception as e:
            logger.warning(f"Fehler beim Lesen aus Stats-Stream: {e}")
            break


def _classify_exit_code(exit_code: int) -> Optional[str]:
    """
    Klassifiziert Exit-Code in Fehler-Typ.
    
    Args:
        exit_code: Exit-Code des Container-Prozesses
    
    Returns:
        Fehler-Typ-String oder None wenn nicht klassifizierbar
    """
    if exit_code == 137:
        return "OOM (Out of Memory) - Container wurde wegen Memory-Limit gekillt"
    elif exit_code == 125:
        return "Docker-Fehler - Container-Start fehlgeschlagen (z.B. Image nicht gefunden)"
    elif exit_code == 126:
        return "Command nicht ausführbar (z.B. 'uv' nicht gefunden im Container)"
    elif exit_code == 127:
        return "Command nicht gefunden (z.B. 'uv run' Befehl fehlgeschlagen)"
    elif exit_code == -1:
        return "Timeout - Container wurde wegen Timeout beendet"
    elif exit_code != 0:
        return f"Pipeline-Fehler (Exit-Code: {exit_code})"
    
    return None


def _calculate_cpu_percent(
    stats: Dict[str, Any],
    prev_cpu_stats: Optional[Dict[str, Any]],
    prev_system_cpu: Optional[Dict[str, Any]]
) -> Optional[float]:
    """
    Berechnet CPU-Usage-Prozentsatz aus Docker-Stats.
    
    Args:
        stats: Aktuelle Container-Stats
        prev_cpu_stats: Vorherige CPU-Stats (für Delta-Berechnung)
        prev_system_cpu: Vorherige System-CPU-Stats
    
    Returns:
        CPU-Usage in Prozent oder None wenn Berechnung nicht möglich
    """
    if prev_cpu_stats is None or prev_system_cpu is None:
        return None
    
    cpu_stats = stats.get("cpu_stats", {})
    precpu_stats = stats.get("precpu_stats", {})
    
    # CPU-Delta berechnen
    cpu_delta = (
        cpu_stats.get("cpu_usage", {}).get("total_usage", 0) -
        prev_cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
    )
    
    # System-CPU-Delta berechnen
    system_delta = (
        cpu_stats.get("system_cpu_usage", 0) -
        precpu_stats.get("system_cpu_usage", 0)
    )
    
    if system_delta == 0:
        return None
    
    # Online-CPUs
    online_cpus = cpu_stats.get("online_cpus", 1)
    if online_cpus == 0:
        online_cpus = 1
    
    # CPU-Prozentsatz berechnen
    cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
    
    return max(0.0, min(100.0, cpu_percent))  # Clamp zwischen 0 und 100


async def _update_pipeline_stats(
    pipeline_name: str,
    success: bool,
    session: Session
) -> None:
    """
    Aktualisiert Pipeline-Statistiken (atomar).
    
    Args:
        pipeline_name: Name der Pipeline
        success: True wenn Run erfolgreich war, sonst False
        session: SQLModel Session
    """
    try:
        # Atomare Updates (verhindert Race-Conditions)
        pipeline = session.get(Pipeline, pipeline_name)
        if pipeline:
            # Atomare Zähler-Updates
            stmt = (
                update(Pipeline)
                .where(Pipeline.pipeline_name == pipeline_name)
                .values(
                    total_runs=Pipeline.total_runs + 1,
                    successful_runs=Pipeline.successful_runs + (1 if success else 0),
                    failed_runs=Pipeline.failed_runs + (1 if not success else 0)
                )
            )
            session.execute(stmt)
            session.commit()
    except Exception as e:
        logger.error(f"Fehler beim Aktualisieren der Pipeline-Statistiken für {pipeline_name}: {e}")


async def cancel_run(run_id: UUID, session: Session) -> bool:
    """
    Bricht einen laufenden Run ab (Container stoppen).
    
    Args:
        run_id: Run-ID
        session: SQLModel Session
    
    Returns:
        True wenn Run erfolgreich abgebrochen wurde, sonst False
    """
    try:
        # Container aus Tracking-Dictionary abrufen
        async with _concurrency_lock:
            container = _running_containers.get(run_id)
        
        if container is None:
            # Container nicht gefunden (bereits beendet?)
            return False
        
        # Container stoppen
        await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: container.stop(timeout=10)
        )
        
        # Status auf INTERRUPTED setzen
        run = session.get(PipelineRun, run_id)
        if run:
            run.status = RunStatus.INTERRUPTED
            run.finished_at = datetime.utcnow()
            session.add(run)
            session.commit()
            
            # Benachrichtigungen senden
            from app.notifications import send_notifications
            await send_notifications(run, RunStatus.INTERRUPTED)
        
        return True
        
    except Exception as e:
        logger.error(f"Fehler beim Abbrechen von Run {run_id}: {e}", exc_info=True)
        return False


def get_log_queue(run_id: UUID) -> Optional[asyncio.Queue]:
    """
    Gibt die Log-Queue für einen Run zurück (für SSE-Streaming).
    
    Args:
        run_id: Run-ID
    
    Returns:
        Log-Queue oder None wenn nicht vorhanden
    """
    return _log_queues.get(run_id)


def get_metrics_queue(run_id: UUID) -> Optional[asyncio.Queue]:
    """
    Gibt die Metrics-Queue für einen Run zurück (für SSE-Streaming).
    
    Args:
        run_id: Run-ID
    
    Returns:
        Metrics-Queue oder None wenn nicht vorhanden
    """
    return _metrics_queues.get(run_id)


async def reconcile_zombie_containers(session: Session) -> None:
    """
    Reconciliert Zombie-Container (Crash-Recovery).
    
    Beim App-Start: Scannt alle laufenden Docker-Container mit Label
    `fastflow-run-id` und gleicht sie mit der Datenbank ab.
    Re-attacht zu laufenden Containern und setzt Status korrekt.
    
    Args:
        session: SQLModel Session
    """
    try:
        client = _get_docker_client()
        
        # Alle Container mit fastflow-run-id Label finden
        containers = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: client.containers.list(
                filters={"label": "fastflow-run-id"},
                all=True  # Auch beendete Container
            )
        )
        
        for container in containers:
            run_id_str = container.labels.get("fastflow-run-id")
            if not run_id_str:
                continue
            
            try:
                run_id = UUID(run_id_str)
            except ValueError:
                logger.warning(f"Ungültige Run-ID in Container-Label: {run_id_str}")
                continue
            
            # Run in Datenbank finden
            run = session.get(PipelineRun, run_id)
            
            if run is None:
                # Run existiert nicht in DB (orphaned Container)
                logger.warning(f"Orphaned Container gefunden (Run-ID nicht in DB): {run_id}")
                # Container entfernen
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        _executor,
                        lambda: container.remove(force=True)
                    )
                except Exception as e:
                    logger.warning(f"Fehler beim Entfernen von orphaned Container {run_id}: {e}")
                continue
            
            # Container-Status prüfen
            container_status = container.status
            
            if container_status == "running":
                # Container läuft noch, aber Run ist nicht RUNNING in DB
                if run.status != RunStatus.RUNNING:
                    logger.info(f"Re-attaching zu laufendem Container für Run {run_id}")
                    # Status auf RUNNING setzen
                    run.status = RunStatus.RUNNING
                    session.add(run)
                    session.commit()
                    
                    # Container in Tracking-Dictionary aufnehmen
                    async with _concurrency_lock:
                        _running_containers[run_id] = container
                    
                    # Log-Streaming und Metrics-Monitoring wieder aufnehmen
                    # (wird in separater Task gemacht)
                    asyncio.create_task(
                        _re_attach_container(run_id, container, session)
                    )
            
            elif container_status in ["exited", "stopped"]:
                # Container beendet, aber Run ist noch RUNNING in DB
                if run.status == RunStatus.RUNNING:
                    logger.info(f"Container beendet für Run {run_id}, Status aktualisieren")
                    # Exit-Code abrufen
                    container.reload()
                    exit_code = container.attrs.get("State", {}).get("ExitCode", -1)
                    
                    # Spezielle Exit-Code-Erkennung
                    error_type = _classify_exit_code(exit_code)
                    
                    run.exit_code = exit_code
                    run.finished_at = datetime.utcnow()
                    
                    if exit_code == 0:
                        run.status = RunStatus.SUCCESS
                    else:
                        run.status = RunStatus.FAILED
                        # Error-Type loggen
                        if error_type:
                            logger.warning(f"Run {run_id} fehlgeschlagen: {error_type} (Exit-Code: {exit_code})")
                    
                    session.add(run)
                    session.commit()
                    
                    # Pipeline-Statistiken aktualisieren
                    await _update_pipeline_stats(run.pipeline_name, exit_code == 0, session)
                    
                    # Container entfernen
                    try:
                        await asyncio.get_event_loop().run_in_executor(
                            _executor,
                            lambda: container.remove(force=True)
                        )
                    except Exception as e:
                        logger.warning(f"Fehler beim Entfernen von beendetem Container {run_id}: {e}")
        
        logger.info(f"Zombie-Reconciliation abgeschlossen: {len(containers)} Container geprüft")
        
    except Exception as e:
        logger.error(f"Fehler bei Zombie-Reconciliation: {e}", exc_info=True)


async def _re_attach_container(
    run_id: UUID,
    container: docker.models.containers.Container,
    session: Session
) -> None:
    """
    Re-attacht zu einem laufenden Container (nach Crash-Recovery).
    
    Args:
        run_id: Run-ID
        container: Docker-Container-Objekt
        session: SQLModel Session (wird intern verwaltet)
    """
    from app.database import get_session
    
    # Neue Session für diese Task erstellen (falls nicht vorhanden)
    if session is None:
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    
    try:
        run = session.get(PipelineRun, run_id)
        if not run:
            return
        
        # Log-Datei-Pfad
        log_file_path = Path(run.log_file)
        
        # Metrics-Datei-Pfad
        metrics_file_path = Path(run.metrics_file) if run.metrics_file else None
        
        # Queues erstellen
        log_queue = asyncio.Queue()
        _log_queues[run_id] = log_queue
        
        metrics_queue = asyncio.Queue()
        _metrics_queues[run_id] = metrics_queue
        
        # Pipeline-Metadaten laden
        pipeline = get_pipeline(run.pipeline_name)
        if not pipeline:
            return
        
        # Log-Streaming und Metrics-Monitoring wieder aufnehmen
        log_task = asyncio.create_task(
            _stream_logs(container, log_file_path, log_queue, run_id)
        )
        
        if metrics_file_path:
            metrics_task = asyncio.create_task(
                _monitor_metrics(container, metrics_file_path, metrics_queue, pipeline, run_id)
            )
        else:
            # Metrics-Datei-Pfad erstellen
            metrics_file_path = Path(config.LOGS_DIR / f"{run_id}_metrics.jsonl")
            metrics_task = asyncio.create_task(
                _monitor_metrics(container, metrics_file_path, metrics_queue, pipeline, run_id)
            )
            run.metrics_file = str(metrics_file_path)
            session.add(run)
            session.commit()
        
        # Container-Wait
        exit_code = await asyncio.get_event_loop().run_in_executor(
            _executor,
            container.wait
        )
        
        # Tasks beenden
        log_task.cancel()
        metrics_task.cancel()
        
        # Exit-Code extrahieren
        exit_code_value = exit_code.get("StatusCode", -1) if isinstance(exit_code, dict) else exit_code
        
        # Spezielle Exit-Code-Erkennung
        error_type = _classify_exit_code(exit_code_value)
        
        # Status aktualisieren
        run = session.get(PipelineRun, run_id)
        if run:
            run.exit_code = exit_code_value
            run.finished_at = datetime.utcnow()
            
            if exit_code_value == 0:
                run.status = RunStatus.SUCCESS
            else:
                run.status = RunStatus.FAILED
                # Error-Type in Log-Datei schreiben (für UI-Anzeige)
                if error_type:
                    logger.warning(f"Run {run_id} fehlgeschlagen: {error_type} (Exit-Code: {exit_code_value})")
            
            session.add(run)
            session.commit()
        
        # Pipeline-Statistiken aktualisieren
        await _update_pipeline_stats(run.pipeline_name, exit_code_value == 0, session)
        
        # Container entfernen
        try:
            await asyncio.get_event_loop().run_in_executor(
                _executor,
                lambda: container.remove(force=True)
            )
        except Exception as e:
            logger.warning(f"Fehler beim Container-Cleanup für Run {run_id}: {e}")
        
        # Container aus Tracking entfernen
        async with _concurrency_lock:
            _running_containers.pop(run_id, None)
        
        # Queues aufräumen
        _log_queues.pop(run_id, None)
        _metrics_queues.pop(run_id, None)
        
    except Exception as e:
        logger.error(f"Fehler beim Re-attach für Run {run_id}: {e}", exc_info=True)
    finally:
        if close_session:
            session.close()


async def check_container_health(run_id: UUID, session: Session) -> Dict[str, Any]:
    """
    Führt einen Health-Check für einen laufenden Container durch.
    
    Args:
        run_id: Run-ID
        session: SQLModel Session
    
    Returns:
        Dictionary mit Health-Status-Informationen
    """
    try:
        # Container aus Tracking-Dictionary abrufen
        async with _concurrency_lock:
            container = _running_containers.get(run_id)
        
        if container is None:
            return {
                "healthy": False,
                "reason": "Container nicht gefunden (bereits beendet?)"
            }
        
        # Container-Status prüfen
        container.reload()
        container_status = container.status
        
        if container_status != "running":
            return {
                "healthy": False,
                "reason": f"Container-Status: {container_status}"
            }
        
        # Health-Check-Status prüfen (falls konfiguriert)
        health_status = container.attrs.get("State", {}).get("Health", {}).get("Status")
        
        if health_status:
            return {
                "healthy": health_status == "healthy",
                "status": health_status,
                "container_status": container_status
            }
        
        # Kein Health-Check konfiguriert, aber Container läuft
        return {
            "healthy": True,
            "status": "running",
            "container_status": container_status
        }
        
    except Exception as e:
        logger.error(f"Fehler beim Health-Check für Run {run_id}: {e}", exc_info=True)
        return {
            "healthy": False,
            "reason": f"Fehler: {str(e)}"
        }


async def graceful_shutdown(session: Session) -> None:
    """
    Führt einen Graceful Shutdown durch (alle laufenden Runs beenden).
    
    Wird beim App-Shutdown aufgerufen, um alle laufenden Container
    sauber zu beenden und Status in DB zu aktualisieren.
    
    Args:
        session: SQLModel Session
    """
    logger.info("Graceful Shutdown: Beende alle laufenden Runs...")
    
    # Alle RUNNING-Runs in DB finden
    runs = session.exec(
        select(PipelineRun).where(PipelineRun.status == RunStatus.RUNNING)
    ).all()
    
    for run in runs:
        try:
            # Container stoppen (nicht killen)
            async with _concurrency_lock:
                container = _running_containers.get(run.id)
            
            if container:
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        _executor,
                        lambda: container.stop(timeout=30)  # Graceful Stop mit 30s Timeout
                    )
                    run.status = RunStatus.INTERRUPTED
                except Exception as e:
                    logger.warning(f"Fehler beim Stoppen von Container für Run {run.id}: {e}")
                    run.status = RunStatus.WARNING
            else:
                run.status = RunStatus.WARNING
            
            run.finished_at = datetime.utcnow()
            session.add(run)
            session.commit()
            
        except Exception as e:
            logger.error(f"Fehler beim Graceful Shutdown für Run {run.id}: {e}")
    
    logger.info(f"Graceful Shutdown abgeschlossen: {len(runs)} Runs beendet")
