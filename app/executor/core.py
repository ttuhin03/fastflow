"""
Docker Container Execution Module.

Dieses Modul verwaltet die Ausführung von Pipeline-Containers über einen
sicheren Docker-Socket-Proxy (tecnativa/docker-socket-proxy).

Hauptfunktionen:
- Container-Start mit Resource-Limits (CPU/RAM Hard/Soft Limits)
- Log-Streaming und Persistenz (asynchron, Echtzeit)
- Metrics-Monitoring (CPU/RAM) mit Live-Streaming via SSE
- Container-Cleanup und Error-Handling (OOM Detection, Exit-Code-Klassifizierung)
- Pre-Heating für UV-Cache (optional)

Sicherheit:
- Alle Docker-API-Zugriffe erfolgen über docker-socket-proxy
- Proxy filtert und erlaubt nur konfigurierte Operationen
- Kein direkter Zugriff auf Docker-Socket

Architektur:
- Asynchrone Tasks für Log-Streaming und Metrics-Monitoring
- ThreadPoolExecutor für synchrone Docker-API-Calls
- Queue-basiertes SSE-Streaming für Live-Updates
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, List, Any, AsyncGenerator
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor

import docker
from docker.errors import DockerException, APIError, ImageNotFound
from sqlmodel import Session, select, update

from app.analytics import track_pipeline_run_finished, track_pipeline_run_started
from app.core.config import config
from app.metrics_prometheus import track_run_started, track_run_finished
from app.resilience import circuit_docker, CircuitBreakerOpenError
from app.models import Pipeline, PipelineRun, RunStatus, RunCellLog
from app.services.pipeline_discovery import DiscoveredPipeline, get_pipeline
from app.services.downstream_triggers import get_downstream_pipelines_to_trigger
from app.resilience.retry_strategy import wait_for_retry
from app.core.database import get_session

logger = logging.getLogger(__name__)

# Präfixe für Notebook-Zellen-Log-Protokoll (nb_runner.py)
PREFIX_CELL_START = "FASTFLOW_CELL_START\t"
PREFIX_CELL_END = "FASTFLOW_CELL_END\t"
PREFIX_CELL_OUTPUT = "FASTFLOW_CELL_OUTPUT\t"

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

# Marker für setup_duration: wird vor main.py ausgegeben, in Logs/SSE herausgefiltert
SETUP_READY_MARKER = "FASTFLOW_SETUP_READY"

# Wrapper-Code für -c: print(Marker), dann main.py via runpy (CWD, sys.argv, __main__)
_SETUP_READY_WRAPPER = (
    "print('FASTFLOW_SETUP_READY', flush=True); "
    "import os, sys, runpy; "
    "os.chdir('/app'); "
    "sys.argv = ['main.py']; "
    "runpy.run_path('/app/main.py', run_name='__main__')"
)


def init_docker_client() -> None:
    """
    Initialisiert das Pipeline-Executor-Backend (Docker oder Kubernetes).
    
    Bei PIPELINE_EXECUTOR=kubernetes wird der K8s-Client initialisiert,
    sonst der Docker-Client (docker-socket-proxy).
    """
    if config.PIPELINE_EXECUTOR == "kubernetes":
        from app.executor import kubernetes_backend
        kubernetes_backend.init_kubernetes_client()
        return
    _init_docker_client_impl()


def _init_docker_client_impl() -> None:
    """Initialisiert den Docker-Client (nur bei PIPELINE_EXECUTOR=docker)."""
    global _docker_client
    
    try:
        # Docker-Client initialisieren - Verbindung über Proxy
        proxy_url = config.DOCKER_PROXY_URL
        _docker_client = docker.DockerClient(base_url=proxy_url)
        
        # Health-Check: Docker-Proxy-Verbindung prüfen
        _docker_client.ping()
        logger.info(f"Docker-Proxy-Verbindung erfolgreich ({proxy_url})")
        
        # Worker-Image prüfen/pullen
        _ensure_worker_image()
        
    except DockerException as e:
        error_msg = (
            f"Docker-Proxy ist nicht erreichbar ({config.DOCKER_PROXY_URL}): {e}. "
            "Stelle sicher, dass der docker-proxy Service läuft und erreichbar ist."
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
        # 1) Container-Name = HOSTNAME (Pod-Name in K8s); unter K8s heißen Docker-Container oft anders
        container_name = os.getenv("HOSTNAME", "fastflow-orchestrator")
        try:
            container = client.containers.get(container_name)
            mounts = container.attrs.get("Mounts", [])
            for mount in mounts:
                destination = mount.get("Destination")
                if destination == container_path or container_path.startswith(destination + "/"):
                    source = mount.get("Source")
                    if source and os.path.isabs(source):
                        logger.debug(f"Host-Pfad für {container_path} aus Volume extrahiert: {source}")
                        return source
        except docker.errors.NotFound:
            pass

        # 2) Unter Kubernetes: Orchestrator-Container per Mount-Ziel finden (Docker-Name != Pod-Name)
        for container in client.containers.list(all=True):
            try:
                mounts = container.attrs.get("Mounts", [])
                for mount in mounts:
                    destination = mount.get("Destination")
                    if destination == container_path or container_path.startswith(destination + "/"):
                        source = mount.get("Source")
                        if source and os.path.isabs(source):
                            logger.debug(
                                "Host-Pfad für %s aus Container %s extrahiert: %s",
                                container_path, container.name, source,
                            )
                            return source
            except Exception:
                continue
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
    session: Optional[Session] = None,
    triggered_by: str = "manual",
    run_config_id: Optional[str] = None
) -> PipelineRun:
    """
    Startet eine Pipeline mit optionalen Environment-Variablen und Parametern.
    
    Args:
        name: Name der Pipeline (muss existieren)
        env_vars: Dictionary mit Environment-Variablen (werden als Secrets injiziert)
        parameters: Dictionary mit Pipeline-Parametern (werden als Env-Vars injiziert)
        session: SQLModel Session (optional, wird intern erstellt wenn nicht vorhanden)
        triggered_by: Trigger-Quelle ("manual", "webhook", oder "scheduler", Standard: "manual")
        run_config_id: Optionale Run-Konfiguration aus pipeline.json schedules (z.B. prod, staging)
    
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
    
    # Datenbank-Session verwenden oder neue erstellen (für max_instances-Check und Run-Erstellung)
    if session is None:
        from app.core.database import get_session
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    
    try:
        # Pipeline-spezifisches max_instances-Limit prüfen
        max_instances = getattr(pipeline.metadata, "max_instances", None)
        if max_instances is not None and max_instances > 0:
            from sqlmodel import select, func
            count_stmt = (
                select(func.count(PipelineRun.id))
                .where(PipelineRun.pipeline_name == name)
                .where(PipelineRun.status.in_([RunStatus.PENDING, RunStatus.RUNNING]))
            )
            running_count = session.exec(count_stmt).one()
            if running_count >= max_instances:
                raise RuntimeError(
                    f"Max-Instanzen-Limit für Pipeline '{name}' erreicht ({running_count}/{max_instances}). "
                    "Bitte warte bis ein Run abgeschlossen ist."
                )

        # Pre-Heating-Lock abrufen (wenn Pre-Heating aktiv ist)
        pre_heating_lock = _get_pre_heating_lock(name)
        # Secrets aus Datenbank abrufen
        from app.services.secrets import get_all_secrets, decrypt
        all_secrets = get_all_secrets(session)
        
        # Run-Konfiguration aus schedules (falls run_config_id gesetzt)
        schedule_config: Optional[Dict[str, Any]] = None
        if run_config_id and getattr(pipeline.metadata, "schedules", None):
            for s in pipeline.metadata.schedules:
                if s.get("id") == run_config_id:
                    schedule_config = s
                    break
        
        # Environment-Variablen zusammenführen
        # 1. Default-Env-Vars aus Pipeline-Metadaten
        merged_env_vars = pipeline.metadata.default_env.copy()
        # 2. Schedule-spezifische default_env (überschreibt/ergänzt)
        if schedule_config and schedule_config.get("default_env"):
            merged_env_vars.update(schedule_config["default_env"])
        # 3. Verschluesselte Env-Vars aus pipeline.json (Pipeline-Level)
        if getattr(pipeline.metadata, "encrypted_env", None):
            for env_key, ciphertext in pipeline.metadata.encrypted_env.items():
                try:
                    merged_env_vars[env_key] = decrypt(ciphertext)
                except ValueError as e:
                    logger.warning(
                        "encrypted_env: Eintrag '%s' fuer Pipeline '%s' konnte nicht entschluesselt werden: %s",
                        env_key, name, e,
                    )
        # 4. Schedule-spezifische encrypted_env (überschreibt bei gleichem Key)
        if schedule_config and schedule_config.get("encrypted_env"):
            for env_key, ciphertext in schedule_config["encrypted_env"].items():
                try:
                    merged_env_vars[env_key] = decrypt(ciphertext)
                except ValueError as e:
                    logger.warning(
                        "schedules[].encrypted_env: Eintrag '%s' fuer Pipeline '%s' (run_config_id=%s) konnte nicht entschluesselt werden: %s",
                        env_key, name, run_config_id, e,
                    )
        # 5. Secrets aus Datenbank (haben Vorrang)
        merged_env_vars.update(all_secrets)
        # 6. UI-spezifische Env-Vars und Parameter (haben Vorrang bei Duplikaten)
        merged_env_vars.update(env_vars)
        merged_env_vars.update(parameters)
        
        # PipelineRun-Datensatz erstellen
        run = PipelineRun(
            pipeline_name=name,
            status=RunStatus.PENDING,
            log_file=str(config.LOGS_DIR / f"{name}_{datetime.now(timezone.utc).isoformat()}.log"),
            env_vars=merged_env_vars,
            parameters=parameters,
            triggered_by=triggered_by,
            run_config_id=run_config_id
        )
        
        session.add(run)
        session.commit()
        session.refresh(run)

        try:
            track_pipeline_run_started(session, name, triggered_by, pipeline.has_requirements)
        except Exception:
            pass

        # Container-Start in Hintergrund-Task (Backend: Docker oder Kubernetes Jobs)
        if config.PIPELINE_EXECUTOR == "kubernetes":
            from app.executor import kubernetes_backend
            asyncio.create_task(
                kubernetes_backend.run_container_task(
                    run.id,
                    pipeline,
                    merged_env_vars,
                    pre_heating_lock,
                )
            )
        else:
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
        env_vars: Zusammengeführte Environment-Variablen
        pre_heating_lock: Lock für Pre-Heating-Operationen
    """
    from app.core.database import get_session
    
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

        # Pro-Schedule-Overrides: aus run_config_id die Schedule-Config holen und effektive Limits/Timeout/Retry ermitteln
        schedule_config: Optional[Dict[str, Any]] = None
        if getattr(run, "run_config_id", None) and getattr(pipeline.metadata, "schedules", None):
            for s in pipeline.metadata.schedules:
                if s.get("id") == run.run_config_id:
                    schedule_config = s
                    break
        _cpu_hard = schedule_config.get("cpu_hard_limit") if schedule_config else None
        effective_cpu_hard_limit = _cpu_hard if _cpu_hard is not None else getattr(pipeline.metadata, "cpu_hard_limit", None)
        _mem_hard = schedule_config.get("mem_hard_limit") if schedule_config else None
        effective_mem_hard_limit = _mem_hard if _mem_hard is not None else getattr(pipeline.metadata, "mem_hard_limit", None)
        _cpu_soft = schedule_config.get("cpu_soft_limit") if schedule_config else None
        effective_cpu_soft_limit = _cpu_soft if _cpu_soft is not None else getattr(pipeline.metadata, "cpu_soft_limit", None)
        _mem_soft = schedule_config.get("mem_soft_limit") if schedule_config else None
        effective_mem_soft_limit = _mem_soft if _mem_soft is not None else getattr(pipeline.metadata, "mem_soft_limit", None)
        _timeout = schedule_config.get("timeout") if schedule_config else None
        if _timeout is not None:
            effective_timeout = None if _timeout == 0 else _timeout
        else:
            t = pipeline.get_timeout()
            effective_timeout = None if t == 0 else t
        _retry = schedule_config.get("retry_attempts") if schedule_config else None
        effective_retry_attempts = _retry if _retry is not None else getattr(pipeline.metadata, "retry_attempts", None)
        _retry_strat = schedule_config.get("retry_strategy") if schedule_config else None
        effective_retry_strategy = _retry_strat if _retry_strat is not None else getattr(pipeline.metadata, "retry_strategy", None)
        
        # Warte auf Pre-Heating-Lock (falls Pre-Heating aktiv ist)
        if config.UV_PRE_HEAT:
            async with pre_heating_lock:
                # Pre-Heating läuft oder ist abgeschlossen
                pass
        
        # Benötigte Python-Version sicherstellen (auch bei nicht-Standard-Version),
        # damit Runs nicht fehlschlagen wenn z. B. nach Pipeline-Änderung kein Sync lief
        py_version = pipeline.get_python_version()
        try:
            from app.git_sync.sync import ensure_python_version
            await asyncio.get_running_loop().run_in_executor(
                _executor, lambda: ensure_python_version(py_version)
            )
        except Exception as e:
            logger.warning("Sicherstellen der Python-Version %s fehlgeschlagen: %s", py_version, e)
        
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
        
        # Resource-Limits (Pipeline oder pro-Schedule-Override)
        cpu_hard_limit = effective_cpu_hard_limit
        mem_hard_limit = effective_mem_hard_limit
        
        # Container-Konfiguration
        # Host-Pfade für Volume-Mounts verwenden (falls in Docker-Container)
        # WICHTIG: Host-Pfade müssen absolut sein und vom Host-System stammen, nicht vom Container
        # Versuche, Host-Pfade aus den gemounteten Volumes zu extrahieren
        pipelines_base_path = _get_host_path_for_volume(
            client, str(config.PIPELINES_DIR), config.PIPELINES_HOST_DIR
        )
        # Mount spezifisches Pipeline-Verzeichnis (nicht gesamtes pipelines-Verzeichnis)
        pipeline_host_path = str(Path(pipelines_base_path) / pipeline.name)
        uv_cache_host_path = _get_host_path_for_volume(
            client, str(config.UV_CACHE_DIR), config.UV_CACHE_HOST_DIR
        )
        uv_python_host_path = _get_host_path_for_volume(
            client, str(config.UV_PYTHON_INSTALL_DIR), config.UV_PYTHON_INSTALL_HOST_DIR
        )
        
        # Basis-Env für uv (Cache + Python-Install); env_vars/Secrets können überschreiben
        # UV_LINK_MODE=copy verhindert Probleme mit Hardlinks in Docker-Volumes
        base_env = {
            "UV_CACHE_DIR": "/root/.cache/uv",
            "UV_PYTHON_INSTALL_DIR": "/cache/uv_python",
            "UV_LINK_MODE": "copy",
        }
        container_env = {**base_env, **env_vars}
        
        # Bei Notebook-Pipelines: Runner-Verzeichnis (app/runners) nach /runner mounten
        volumes_dict: Dict[str, Dict[str, str]] = {
            pipeline_host_path: {"bind": "/app", "mode": "ro"},
            uv_cache_host_path: {"bind": "/root/.cache/uv", "mode": "rw"},
            uv_python_host_path: {"bind": "/cache/uv_python", "mode": "rw"},
        }
        if pipeline.get_entry_type() == "notebook":
            runners_host_path = _get_host_path_for_volume(
                client, str(config.RUNNERS_DIR), config.RUNNERS_HOST_DIR
            )
            # Nur mounten wenn echter Host-Pfad (z. B. Docker Compose). In K8s ist
            # app/runners nur im Image – kein Volume; Worker-Image enthält /runner.
            if not runners_host_path.strip().startswith("/app"):
                volumes_dict[runners_host_path] = {"bind": "/runner", "mode": "ro"}

        # Container-Konfiguration für docker-socket-proxy
        container_config = {
            "image": config.WORKER_BASE_IMAGE,
            "command": _build_container_command(pipeline),
            "environment": container_env,
            # Volumes als Dictionary (korrektes Format für docker Python library)
            "volumes": volumes_dict,
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
        
        # Container starten (mit Circuit Breaker gegen Docker-Proxy-Ausfälle)
        logger.info(
            f"Starte Container für Run {run_id} (Pipeline: {pipeline.name}, "
            f"CPU-Limit: {cpu_hard_limit or 'unbegrenzt'}, RAM-Limit: {mem_hard_limit or 'unbegrenzt'})"
        )
        try:
            def _run_with_circuit_breaker():
                return circuit_docker.call(lambda: client.containers.run(**container_config))

            container = await asyncio.get_running_loop().run_in_executor(
                _executor,
                _run_with_circuit_breaker,
            )
            setup_start = time.time()  # Ende: wenn SETUP_READY_MARKER im Log erscheint
        except CircuitBreakerOpenError as e:
            logger.error("Docker Circuit Breaker offen: %s", e)
            raise RuntimeError(str(e)) from e
        except APIError as e:
            # Infrastructure-Fehler: Docker-Proxy blockiert Request
            logger.error(
                f"Infrastructure-Fehler bei Container-Erstellung für Run {run_id}: {e}. "
                f"Prüfe docker-proxy Konfiguration (POST=1, CONTAINERS=1, VOLUMES=1)."
            )
            raise
        
        logger.info(f"Container {container.id[:12]} erfolgreich gestartet für Run {run_id}")
        
        # Container in Tracking-Dictionary speichern
        async with _concurrency_lock:
            _running_containers[run_id] = container
        
        # Status auf RUNNING setzen
        run.status = RunStatus.RUNNING
        session.add(run)
        session.commit()
        
        # Prometheus-Metriken: Run gestartet
        try:
            track_run_started(pipeline.name)
        except Exception as e:
            logger.debug(f"Prometheus track_run_started fehlgeschlagen: {e}")
        
        # WICHTIG: Log-Streaming SOFORT starten, damit keine Logs verloren gehen
        # Laut IMPLEMENTATION_PLAN sollen Logs während des gesamten Container-Laufs gestreamt werden
        logger.debug(f"Starte Log-Streaming für Run {run_id}")
        first_log_event = asyncio.Event()
        log_task = asyncio.create_task(
            _stream_logs(container, log_file_path, log_queue, run_id, first_log_event)
        )
        
        logger.debug(f"Starte Metrics-Monitoring für Run {run_id}")
        metrics_task = asyncio.create_task(
            _monitor_metrics(
                container,
                metrics_file_path,
                metrics_queue,
                pipeline,
                run_id,
                session,
                env_vars
            )
        )
        
        # UV-Version parallel, setup_duration = Zeit Container-Start bis SETUP_READY_MARKER
        uv_version_task = asyncio.create_task(_get_uv_version(container))
        try:
            await asyncio.wait_for(first_log_event.wait(), timeout=60.0)
            setup_duration = time.time() - setup_start
        except asyncio.TimeoutError:
            setup_duration = None

        uv_version = await uv_version_task
        run.uv_version = uv_version
        run.setup_duration = setup_duration
        session.add(run)
        session.commit()
        
        # Pipeline- oder Schedule-spezifisches Timeout
        timeout = effective_timeout or config.CONTAINER_TIMEOUT
        
        # Container-Wait mit Timeout
        if timeout:
            try:
                exit_code = await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
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
            exit_code = await asyncio.get_running_loop().run_in_executor(
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
            remaining_logs_bytes = await asyncio.get_running_loop().run_in_executor(
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
        
        # OOM Detection: Prüfe container.attrs["State"]["OOMKilled"] und exit_code 137
        oom_killed = False
        if container:
            try:
                container.reload()
                oom_killed = container.attrs.get("State", {}).get("OOMKilled", False)
            except Exception as e:
                logger.warning(f"Fehler beim Prüfen von OOMKilled für Run {run_id}: {e}")
        
        # Exit-Code 137 (SIGKILL) deutet oft auf OOM hin
        if exit_code_value == 137:
            oom_killed = True
        
        # Spezielle Exit-Code-Erkennung
        error_type = _classify_exit_code(exit_code_value, oom_killed)
        
        # Run-Objekt aktualisieren
        run = session.get(PipelineRun, run_id)
        if not run:
            logger.error(f"Run {run_id} nicht in Datenbank gefunden beim Status-Update")
            return
        
        # Status basierend auf Exit-Code setzen
        run.exit_code = exit_code_value
        run.finished_at = datetime.now(timezone.utc)
        
        if exit_code_value == 0:
            run.status = RunStatus.SUCCESS
        else:
            run.status = RunStatus.FAILED
            # Pipeline Error: Script-Fehler (nicht Infrastructure)
            if run.env_vars is None:
                run.env_vars = {}
            run.env_vars["_fastflow_error_type"] = "pipeline_error"
            if error_type:
                run.env_vars["_fastflow_error_message"] = error_type
                logger.warning(f"Run {run_id} fehlgeschlagen: {error_type} (Exit-Code: {exit_code_value}, OOMKilled: {oom_killed})")
        
        # Metrics-Datei-Pfad speichern
        if metrics_file_path.exists():
            run.metrics_file = str(metrics_file_path)
        
        session.add(run)
        session.commit()

        # Dauer berechnen für Metriken
        duration_seconds = (run.finished_at - run.started_at).total_seconds() if run.finished_at and run.started_at else 0.0

        if exit_code_value == 0:
            try:
                track_pipeline_run_finished(
                    session, pipeline.name, "SUCCESS", run.triggered_by, duration_seconds, pipeline.has_requirements
                )
            except Exception:
                pass
            # Prometheus-Metriken: Run erfolgreich beendet
            try:
                track_run_finished(pipeline.name, "completed", duration_seconds)
            except Exception as e:
                logger.debug(f"Prometheus track_run_finished fehlgeschlagen: {e}")
        else:
            # Prometheus-Metriken: Run fehlgeschlagen
            try:
                track_run_finished(pipeline.name, "failed", duration_seconds)
            except Exception as e:
                logger.debug(f"Prometheus track_run_finished fehlgeschlagen: {e}")
        
        # Pipeline-Statistiken aktualisieren (atomar)
        await _update_pipeline_stats(pipeline.name, exit_code_value == 0, session, triggered_by=run.triggered_by)

        # Downstream-Trigger bei Erfolg (Pipeline-Chaining)
        if exit_code_value == 0:
            await _trigger_downstream_pipelines(pipeline.name, success=True, session=session)
        
        # Retry-Logik: Prüfe ob Retry nötig ist (nur für Script-Pipelines; Notebooks haben Zellen-Retry im selben Run)
        if exit_code_value != 0:
            run = session.get(PipelineRun, run_id)
            if pipeline.get_entry_type() == "notebook":
                # Notebook: Kein Pipeline-Retry (neuer Run). Retries passieren nur auf Zellen-Ebene im selben Run.
                pass
            else:
                # Script-Pipeline: ggf. neuen Run als Retry starten
                retry_attempts = effective_retry_attempts
                if retry_attempts is None:
                    retry_attempts = config.RETRY_ATTEMPTS

                if run and retry_attempts > 0:
                    # Prüfe ob wir bereits retries gemacht haben (über retry_count in env_vars)
                    current_retry_count = run.env_vars.get("_fastflow_retry_count", "0")
                    try:
                        current_retry_count = int(current_retry_count)
                    except (ValueError, TypeError):
                        current_retry_count = 0
                    
                    if current_retry_count < retry_attempts:
                        # Retry nötig
                        retry_strategy = effective_retry_strategy
                        
                        # Warte basierend auf Retry-Strategie
                        await wait_for_retry(current_retry_count + 1, retry_strategy)
                        
                        # Starte neuen Run mit erhöhtem retry_count (run_config_id beibehalten)
                        new_env_vars = env_vars.copy()
                        new_env_vars["_fastflow_retry_count"] = str(current_retry_count + 1)
                        new_env_vars["_fastflow_previous_run_id"] = str(run_id)
                        
                        logger.info(f"Starte Retry-Versuch {current_retry_count + 1}/{retry_attempts} für Pipeline {pipeline.name} (vorheriger Run: {run_id})")
                        
                        # Neuen Run starten
                        from app.executor.core import run_pipeline
                        await run_pipeline(
                            pipeline.name,
                            env_vars=new_env_vars,
                            parameters=None,  # Parameter werden nicht retry'd
                            session=session,
                            triggered_by=f"{run.triggered_by}_retry",
                            run_config_id=run.run_config_id
                        )
                        return  # Originaler Run bleibt als FAILED, neuer Run wird gestartet
            
            # Downstream-Trigger bei finalem Fehler (kein Retry) – Pipeline-Chaining
            await _trigger_downstream_pipelines(pipeline.name, success=False, session=session)

            # Benachrichtigungen senden (nur bei finalen Fehlern)
            if run:
                from app.services.notifications import send_notifications
                await send_notifications(run, RunStatus.FAILED)
                # Dauerläufer: restart_on_crash – nach Cooldown neu starten
                if pipeline and getattr(pipeline.metadata, "restart_on_crash", False):
                    cooldown = getattr(pipeline.metadata, "restart_cooldown", 60) or 60
                    from app.services.daemon_watcher import schedule_restart_on_crash
                    asyncio.create_task(schedule_restart_on_crash(run.pipeline_name, cooldown))
        
    except (docker.errors.APIError, docker.errors.DockerException, ConnectionError, OSError) as e:
        # Infrastructure Error: Docker-Proxy-Verbindungsfehler oder Docker-API-Fehler
        logger.error(f"Infrastructure-Fehler bei Container-Ausführung für Run {run_id}: {e}", exc_info=True)
        
        # Status auf FAILED setzen
        run = session.get(PipelineRun, run_id)
        if run:
            run.status = RunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.exit_code = -1
            # Error-Type als Infrastructure Error markieren (in env_vars für Frontend)
            if run.env_vars is None:
                run.env_vars = {}
            run.env_vars["_fastflow_error_type"] = "infrastructure_error"
            run.env_vars["_fastflow_error_message"] = str(e)
            session.add(run)
            session.commit()
            
            # Prometheus-Metriken: Run fehlgeschlagen (Docker-Fehler)
            duration_seconds = (run.finished_at - run.started_at).total_seconds() if run.finished_at and run.started_at else 0.0
            try:
                track_run_finished(pipeline.name, "failed", duration_seconds)
            except Exception as prom_err:
                logger.debug(f"Prometheus track_run_finished fehlgeschlagen: {prom_err}")
            # Benachrichtigungen und Dauerläufer-Restart
            if run:
                from app.services.notifications import send_notifications
                await send_notifications(run, RunStatus.FAILED)
                if pipeline and getattr(pipeline.metadata, "restart_on_crash", False):
                    cooldown = getattr(pipeline.metadata, "restart_cooldown", 60) or 60
                    from app.services.daemon_watcher import schedule_restart_on_crash
                    asyncio.create_task(schedule_restart_on_crash(run.pipeline_name, cooldown))
    except Exception as e:
        # Andere Exceptions (könnten auch Infrastructure-Fehler sein)
        logger.error(f"Unerwarteter Fehler bei Container-Ausführung für Run {run_id}: {e}", exc_info=True)
        
        # Status auf FAILED setzen
        run = session.get(PipelineRun, run_id)
        if run:
            run.status = RunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.exit_code = -1
            # Prüfe ob es ein Connection-Error ist (Infrastructure)
            if "connection" in str(e).lower() or "proxy" in str(e).lower() or "unreachable" in str(e).lower():
                if run.env_vars is None:
                    run.env_vars = {}
                run.env_vars["_fastflow_error_type"] = "infrastructure_error"
                run.env_vars["_fastflow_error_message"] = str(e)
            session.add(run)
            session.commit()
            
            # Prometheus-Metriken: Run fehlgeschlagen (Exception)
            duration_seconds = (run.finished_at - run.started_at).total_seconds() if run.finished_at and run.started_at else 0.0
            try:
                track_run_finished(run.pipeline_name, "failed", duration_seconds)
            except Exception as prom_err:
                logger.debug(f"Prometheus track_run_finished fehlgeschlagen: {prom_err}")
            
            # Pipeline-Statistiken aktualisieren (Fehler)
            await _update_pipeline_stats(run.pipeline_name, False, session, triggered_by=run.triggered_by)
            
            # Retry-Logik auch für Exceptions (nur für Script-Pipelines; Notebooks haben Zellen-Retry im selben Run)
            if run:
                pipeline = get_pipeline(run.pipeline_name)
                if pipeline and pipeline.get_entry_type() != "notebook":
                    sched = None
                    if getattr(run, "run_config_id", None) and getattr(pipeline.metadata, "schedules", None):
                        for s in pipeline.metadata.schedules:
                            if s.get("id") == run.run_config_id:
                                sched = s
                                break
                    retry_attempts = sched.get("retry_attempts") if sched else None
                    if retry_attempts is None:
                        retry_attempts = pipeline.get_retry_attempts()
                    if retry_attempts is None:
                        retry_attempts = config.RETRY_ATTEMPTS
                    retry_strategy = sched.get("retry_strategy") if sched else None
                    if retry_strategy is None:
                        retry_strategy = getattr(pipeline.metadata, "retry_strategy", None)
                    
                    current_retry_count = run.env_vars.get("_fastflow_retry_count", "0")
                    try:
                        current_retry_count = int(current_retry_count)
                    except (ValueError, TypeError):
                        current_retry_count = 0
                    
                    if retry_attempts > 0 and current_retry_count < retry_attempts:
                        await wait_for_retry(current_retry_count + 1, retry_strategy)
                        
                        new_env_vars = run.env_vars.copy()
                        new_env_vars["_fastflow_retry_count"] = str(current_retry_count + 1)
                        new_env_vars["_fastflow_previous_run_id"] = str(run.id)
                        
                        logger.info(f"Starte Retry-Versuch {current_retry_count + 1}/{retry_attempts} für Pipeline {run.pipeline_name} nach Exception")
                        
                        from app.executor.core import run_pipeline
                        await run_pipeline(
                            run.pipeline_name,
                            env_vars=new_env_vars,
                            parameters=None,
                            session=session,
                            triggered_by=f"{run.triggered_by}_retry",
                            run_config_id=run.run_config_id
                        )
                        return
            
            # Benachrichtigungen senden (nur bei finalen Fehlern)
            if run:
                from app.services.notifications import send_notifications
                await send_notifications(run, RunStatus.FAILED)
                # Dauerläufer: restart_on_crash – nach Cooldown neu starten
                pipeline = get_pipeline(run.pipeline_name)
                if pipeline and getattr(pipeline.metadata, "restart_on_crash", False):
                    cooldown = getattr(pipeline.metadata, "restart_cooldown", 60) or 60
                    from app.services.daemon_watcher import schedule_restart_on_crash
                    asyncio.create_task(schedule_restart_on_crash(run.pipeline_name, cooldown))
        
    finally:
        # Container-Cleanup
        if container:
            try:
                await asyncio.get_running_loop().run_in_executor(
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
    
    Das Pipeline-Verzeichnis wird nach /app gemountet, daher sind die Pfade
    relativ zu /app (z.B. /app/main.py, /app/requirements.txt, /app/main.ipynb).
    
    Args:
        pipeline: DiscoveredPipeline-Objekt
    
    Returns:
        Liste mit Container-Befehl (uv run --python {version} ...)
    """
    py = pipeline.get_python_version()
    is_notebook = pipeline.get_entry_type() == "notebook"
    nb_runner_cmd = ["python", "-u", "/runner/nb_runner.py", "/app/main.ipynb"]

    if pipeline.has_requirements:
        requirements_path = "/app/requirements.txt"
        lock_file_path_host = pipeline.path / "requirements.txt.lock"

        if lock_file_path_host.exists():
            lock_file_path_container = "/app/requirements.txt.lock"
            base = [
                "uv", "run", "--python", py,
                "--with-requirements", lock_file_path_container,
            ]
            if is_notebook:
                return base + nb_runner_cmd
            return base + ["python", "-u", "-c", _SETUP_READY_WRAPPER]
        else:
            base = [
                "uv", "run", "--python", py,
                "--with-requirements", requirements_path,
            ]
            if is_notebook:
                return base + nb_runner_cmd
            return base + ["python", "-u", "-c", _SETUP_READY_WRAPPER]
    if is_notebook:
        return ["uv", "run", "--python", py] + nb_runner_cmd
    return ["uv", "run", "--python", py, "python", "-u", "-c", _SETUP_READY_WRAPPER]


async def _get_uv_version(container: docker.models.containers.Container) -> Optional[str]:
    """
    Ermittelt die UV-Version aus dem Container.
    
    Args:
        container: Docker-Container-Objekt
    
    Returns:
        UV-Version-String oder None
    """
    try:
        result = await asyncio.get_running_loop().run_in_executor(
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


def _cell_line_to_readable_log(line: str) -> Optional[str]:
    """
    Wandelt eine FASTFLOW_CELL_*-Zeile in eine lesbare Log-Zeile um.
    Returns None für OUTPUT (keine Doppelausgabe) oder wenn nicht erkennbar.
    """
    if line.startswith(PREFIX_CELL_START):
        try:
            cell_index = int(line[len(PREFIX_CELL_START) :].strip())
            return f"[Notebook] Zelle {cell_index}: Start"
        except ValueError:
            return None
    if line.startswith(PREFIX_CELL_END):
        rest = line[len(PREFIX_CELL_END) :].strip()
        parts = rest.split("\t", 2)
        if len(parts) < 2:
            return None
        try:
            cell_index = int(parts[0])
            status = parts[1].upper()
            msg = parts[2].strip() if len(parts) > 2 else ""
            if status == "SUCCESS":
                return f"[Notebook] Zelle {cell_index}: Erfolg"
            if status == "FAILED":
                return f"[Notebook] Zelle {cell_index}: Fehlgeschlagen" + (f" ({msg[:200]})" if msg else "")
            if status == "RETRYING":
                attempt_part = msg.split("\t", 1)
                attempt_num = attempt_part[0] if attempt_part else "?"
                err = attempt_part[1].strip() if len(attempt_part) > 1 and attempt_part[1] else ""
                if err:
                    return f"[Notebook] Zelle {cell_index}: Retry-Versuch {attempt_num} ({err[:150]})"
                return f"[Notebook] Zelle {cell_index}: Retry-Versuch {attempt_num}"
            return f"[Notebook] Zelle {cell_index}: {status}"
        except (ValueError, IndexError):
            return None
    return None


def _parse_and_persist_cell_line(run_id: UUID, line: str) -> None:
    """
    Parst eine FASTFLOW_CELL_*-Zeile vom Notebook-Runner und schreibt in RunCellLog.
    Wird synchron im ThreadPool ausgeführt (DB-Zugriff).
    """
    import base64
    session_gen = get_session()
    try:
        session = next(session_gen)
    except StopIteration:
        return
    try:
        if line.startswith(PREFIX_CELL_START):
            cell_index = int(line[len(PREFIX_CELL_START) :].strip())
            existing = session.get(RunCellLog, (run_id, cell_index))
            if existing:
                existing.status = "RUNNING"
            else:
                session.add(
                    RunCellLog(run_id=run_id, cell_index=cell_index, status="RUNNING")
                )
            session.commit()
            return
        if line.startswith(PREFIX_CELL_END):
            rest = line[len(PREFIX_CELL_END) :].strip()
            parts = rest.split("\t", 2)
            if len(parts) < 2:
                return
            cell_index = int(parts[0])
            status = parts[1].upper()
            msg = parts[2].strip() if len(parts) > 2 else ""
            existing = session.get(RunCellLog, (run_id, cell_index))
            if not existing:
                existing = RunCellLog(run_id=run_id, cell_index=cell_index, status=status)
                session.add(existing)
                session.flush()
            else:
                existing.status = status
            # Alle Versuche in stderr sammeln (Retries + Final), damit sie in der UI sichtbar sind
            if status == "RETRYING" and msg:
                attempt_part = msg.split("\t", 1)
                attempt_num = attempt_part[0] if attempt_part else "?"
                err_text = attempt_part[1].strip() if len(attempt_part) > 1 else ""
                existing.stderr = (existing.stderr or "") + f"--- Retry-Versuch {attempt_num} fehlgeschlagen ---\n{err_text}\n\n"
            elif status == "FAILED":
                existing.stderr = (existing.stderr or "") + "--- Endgültig fehlgeschlagen ---\n"
            session.commit()
            return
        if line.startswith(PREFIX_CELL_OUTPUT):
            rest = line[len(PREFIX_CELL_OUTPUT) :]
            parts = rest.split("\t", 3)
            if len(parts) < 3:
                return
            cell_index = int(parts[0])
            stream = parts[1]
            third = parts[2]
            payload = parts[3] if len(parts) > 3 else ""
            existing = session.get(RunCellLog, (run_id, cell_index))
            if not existing:
                existing = RunCellLog(run_id=run_id, cell_index=cell_index, status="RUNNING")
                session.add(existing)
                session.flush()
            if stream in ("stdout", "stderr"):
                encoding = third
                if encoding == "base64":
                    try:
                        payload = base64.b64decode(payload).decode("utf-8")
                    except Exception:
                        payload = ""
                if stream == "stdout":
                    existing.stdout = (existing.stdout or "") + payload + "\n"
                else:
                    existing.stderr = (existing.stderr or "") + payload + "\n"
            elif stream == "image":
                mime = third
                if existing.outputs is None:
                    existing.outputs = {"images": []}
                existing.outputs.setdefault("images", []).append({"mime": mime, "data": payload})
            session.commit()
    except Exception as e:
        logger.warning("Fehler beim Parsen/Persistieren einer Zellen-Log-Zeile: %s", e)
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass


async def _stream_logs(
    container: docker.models.containers.Container,
    log_file_path: Path,
    log_queue: asyncio.Queue,
    run_id: UUID,
    first_log_event: Optional[asyncio.Event] = None
) -> None:
    """
    Streamt Logs aus Container und schreibt sie in Datei und Queue.
    
    Args:
        container: Docker-Container-Objekt
        log_file_path: Pfad zur Log-Datei
        log_queue: Queue für SSE-Streaming
        run_id: Run-ID
        first_log_event: Optional; wird gesetzt wenn SETUP_READY_MARKER erscheint (für setup_duration)
    """
    import aiofiles
    
    try:
        logger.info(f"Starte Log-Streaming für Run {run_id}, Container: {container.id}")
        
        # Log-Stream aus Container abrufen
        log_stream = await asyncio.get_running_loop().run_in_executor(
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
                        # SETUP_READY_MARKER: nur für setup_duration, nicht in Log/SSE
                        if log_line.strip() == SETUP_READY_MARKER:
                            if first_log_event is not None:
                                first_log_event.set()
                            continue
                        is_cell_protocol = (
                            log_line.startswith(PREFIX_CELL_START)
                            or log_line.startswith(PREFIX_CELL_END)
                            or log_line.startswith(PREFIX_CELL_OUTPUT)
                        )
                        if is_cell_protocol:
                            await asyncio.get_running_loop().run_in_executor(
                                _executor,
                                lambda l=log_line: _parse_and_persist_cell_line(run_id, l),
                            )
                            # Lesbare Zeile für Log/SSE (Retries etc.); OUTPUT nicht doppelt ausgeben
                            line_to_write = _cell_line_to_readable_log(log_line)
                            if line_to_write is None:
                                continue  # z. B. CELL_OUTPUT – kein Eintrag in Log (Inhalt in Zellen-UI)
                        else:
                            line_to_write = log_line
                        if not first_log_received:
                            logger.info(f"Erste Log-Zeile für Run {run_id} empfangen: {line_to_write[:100]}")
                            first_log_received = True
                        
                        # Zeitstempel hinzufügen (Format: YYYY-MM-DD HH:MM:SS.mmm)
                        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                        log_line_with_timestamp = f"[{timestamp}] {line_to_write}"
                        
                        # In Datei schreiben (asynchron)
                        await log_file.write(log_line_with_timestamp + "\n")
                        await log_file.flush()
                        
                        # In Queue für SSE-Streaming (mit Zeitstempel)
                        try:
                            log_queue.put_nowait(log_line_with_timestamp)
                        except asyncio.QueueFull:
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
                    if log_line.strip() == SETUP_READY_MARKER:
                        if first_log_event is not None:
                            first_log_event.set()
                    else:
                        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
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
    loop = asyncio.get_running_loop()
    
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
    run_id: UUID,
    session: Session,
    env_vars: Dict[str, str]
) -> None:
    """
    Überwacht Container-Metrics (CPU & RAM) und speichert sie.
    
    Sammelt kontinuierlich CPU- und RAM-Usage-Daten vom Container und speichert
    sie sowohl in einer JSONL-Datei als auch in einer Queue für Live-Streaming
    via Server-Sent Events.
    
    Args:
        container: Docker-Container-Objekt
        metrics_file_path: Pfad zur Metrics-Datei (JSONL-Format)
        metrics_queue: Queue für SSE-Streaming (pro Run-ID)
        pipeline: DiscoveredPipeline-Objekt (für Soft-Limit-Überwachung)
        run_id: Run-ID (UUID)
        session: SQLModel Session (für DB-Zugriffe bei Notifications)
        env_vars: Environment-Variablen-Dictionary (für Notification-Flag)
    
    Notes:
        - CPU-Berechnung verwendet Delta-Vergleich mit precpu_stats
        - RAM-Werte werden direkt aus memory_stats extrahiert
        - Metrics werden alle 2 Sekunden gesammelt (Rate-Limiting)
        - Soft-Limit-Überschreitungen werden einmalig per Notification gemeldet
    """
    import aiofiles
    
    try:
        logger.debug(f"Starte Stats-Stream für Container {container.id[:12]} (Run {run_id})")
        # Stats-Stream aus Container abrufen
        stats_stream = await asyncio.get_running_loop().run_in_executor(
            _executor,
            lambda: container.stats(stream=True, decode=True)
        )
        
        logger.info(f"Metrics-Monitoring gestartet für Run {run_id} (Datei: {metrics_file_path})")
        metrics_count = 0
        
        # Datei-Handle öffnen (asynchron)
        async with aiofiles.open(metrics_file_path, "w", encoding="utf-8") as metrics_file:
            async for stats in _iter_stats_stream(stats_stream):
                try:
                    # RAM-Usage erfassen (in MB) - immer verfügbar
                    memory_stats = stats.get("memory_stats", {})
                    ram_usage_mb = round(memory_stats.get("usage", 0) / (1024 * 1024), 2)
                    ram_limit_mb = round(memory_stats.get("limit", 0) / (1024 * 1024), 2)
                    
                    # CPU-Usage berechnen (Delta-Vergleich mit precpu_stats aus aktuellen stats)
                    # Docker liefert precpu_stats automatisch in jedem stats-Objekt
                    cpu_percent = _calculate_cpu_percent(stats, None, None)
                    # Wenn CPU-Berechnung nicht möglich (erste Iteration oder system_delta = 0), verwende 0.0
                    if cpu_percent is None:
                        cpu_percent = 0.0
                    
                    # Soft-Limit-Überwachung
                    soft_limit_exceeded = False
                    exceeded_resource = None
                    exceeded_value = None
                    exceeded_limit = None
                    
                    if effective_cpu_soft_limit and cpu_percent:
                        cpu_soft_limit_percent = effective_cpu_soft_limit * 100
                        if cpu_percent > cpu_soft_limit_percent:
                            soft_limit_exceeded = True
                            if not exceeded_resource:  # Nur erste Überschreitung melden
                                exceeded_resource = "CPU"
                                exceeded_value = cpu_percent
                                exceeded_limit = cpu_soft_limit_percent
                    
                    if effective_mem_soft_limit:
                        mem_soft_limit_bytes = _convert_memory_to_bytes(effective_mem_soft_limit)
                        mem_soft_limit_mb = mem_soft_limit_bytes / (1024 * 1024)
                        if ram_usage_mb > mem_soft_limit_mb:
                            soft_limit_exceeded = True
                            if not exceeded_resource:  # Nur erste Überschreitung melden
                                exceeded_resource = "RAM"
                                exceeded_value = ram_usage_mb
                                exceeded_limit = mem_soft_limit_mb
                    
                    # Metrics-Objekt erstellen
                    # WICHTIG: Frontend erwartet 'ram_mb', nicht 'mem_usage_mb'
                    metric = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "cpu_percent": cpu_percent if cpu_percent is not None else 0.0,
                        "ram_mb": ram_usage_mb,  # Frontend erwartet 'ram_mb'
                        "ram_limit_mb": ram_limit_mb,
                        "soft_limit_exceeded": soft_limit_exceeded
                    }
                    
                    # Sende Notification bei Soft-Limit-Überschreitung (nur einmal pro Run)
                    if soft_limit_exceeded and exceeded_resource:
                        # Prüfe ob bereits benachrichtigt wurde (über env_var)
                        if "_fastflow_soft_limit_notified" not in env_vars:
                            # Hole Run aus DB
                            run_for_notification = session.get(PipelineRun, run_id)
                            if run_for_notification:
                                # Markiere als benachrichtigt
                                env_vars["_fastflow_soft_limit_notified"] = "1"
                                # Sende Notification im Hintergrund
                                asyncio.create_task(
                                    _send_soft_limit_notification_async(
                                        run_for_notification, exceeded_resource, exceeded_value, exceeded_limit
                                    )
                                )
                    
                    # In Datei schreiben (JSONL-Format)
                    await metrics_file.write(json.dumps(metric) + "\n")
                    await metrics_file.flush()
                    
                    # In Queue für SSE-Streaming
                    try:
                        metrics_queue.put_nowait(metric)
                    except asyncio.QueueFull:
                        # Queue voll, alte Einträge entfernen (FIFO)
                        logger.debug(f"Metrics-Queue voll für Run {run_id}, entferne ältesten Eintrag")
                        try:
                            metrics_queue.get_nowait()
                            metrics_queue.put_nowait(metric)
                        except asyncio.QueueEmpty:
                            pass
                    
                    metrics_count += 1
                    if metrics_count % 10 == 0:  # Alle 20 Sekunden (10 * 2s)
                        logger.debug(
                            f"Metrics-Monitoring für Run {run_id}: {metrics_count} Samples gesammelt "
                            f"(CPU: {cpu_percent:.1f}%, RAM: {ram_usage_mb:.1f}MB/{ram_limit_mb:.1f}MB)"
                        )
                    
                    # Rate-Limiting: Alle 2 Sekunden messen
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.warning(
                        f"Fehler beim Verarbeiten von Container-Stats für Run {run_id}: {e}",
                        exc_info=True
                    )
        
    except asyncio.CancelledError:
        # Task wurde abgebrochen (normal bei Container-Ende)
        logger.debug(f"Metrics-Monitoring-Task für Run {run_id} wurde abgebrochen (Container beendet)")
        pass
    except Exception as e:
        logger.error(
            f"Fehler beim Metrics-Monitoring für Run {run_id}: {e}",
            exc_info=True
        )
    finally:
        # Stream explizit schließen
        try:
            if 'stats_stream' in locals() and hasattr(stats_stream, 'close'):
                stats_stream.close()
                logger.debug(f"Stats-Stream für Run {run_id} geschlossen")
        except Exception as e:
            logger.warning(f"Fehler beim Schließen des Stats-Streams für Run {run_id}: {e}")
        
        logger.info(f"Metrics-Monitoring beendet für Run {run_id} ({metrics_count if 'metrics_count' in locals() else 0} Samples gesammelt)")


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
            stats = await asyncio.get_running_loop().run_in_executor(
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


async def _send_soft_limit_notification_async(
    run: PipelineRun,
    resource_type: str,
    current_value: float,
    limit_value: float
) -> None:
    """
    Interne Funktion zum asynchronen Senden von Soft-Limit-Benachrichtigungen.
    
    Args:
        run: PipelineRun-Objekt
        resource_type: Art der Ressource ("CPU" oder "RAM")
        current_value: Aktueller Wert
        limit_value: Soft-Limit-Wert
    """
    try:
        from app.services.notifications import send_soft_limit_notification
        await send_soft_limit_notification(run, resource_type, current_value, limit_value)
    except Exception as e:
        logger.error(f"Fehler beim Senden der Soft-Limit-Notification für Run {run.id}: {e}")


def _classify_exit_code(exit_code: int, oom_killed: bool = False) -> Optional[str]:
    """
    Klassifiziert Exit-Code in Fehler-Typ.
    
    Args:
        exit_code: Exit-Code des Container-Prozesses
        oom_killed: True wenn Container wegen OOM gekillt wurde
    
    Returns:
        Fehler-Typ-String oder None wenn nicht klassifizierbar
    """
    # OOM Detection: Prüfe OOMKilled Flag oder Exit-Code 137
    if oom_killed or exit_code == 137:
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
    
    Verwendet die Delta-Berechnung zwischen aktuellen und vorherigen CPU-Stats.
    Docker liefert automatisch 'precpu_stats' in jedem Stats-Objekt, daher werden
    die prev_cpu_stats Parameter nicht verwendet (für zukünftige Erweiterungen).
    
    Formel: (cpu_delta / system_delta) * online_cpus * 100.0
    
    Args:
        stats: Aktuelle Container-Stats (enthält cpu_stats und precpu_stats)
        prev_cpu_stats: Vorherige CPU-Stats (wird nicht verwendet, da precpu_stats in stats enthalten ist)
        prev_system_cpu: Vorherige System-CPU-Stats (wird nicht verwendet)
    
    Returns:
        CPU-Usage in Prozent (0.0-100.0) oder None wenn Berechnung nicht möglich
        (z.B. bei system_delta <= 0 oder fehlenden Stats)
    
    Notes:
        - Erste Iteration kann None zurückgeben, wenn precpu_stats noch leer ist
        - system_delta muss > 0 sein, sonst wird None zurückgegeben
    """
    cpu_stats = stats.get("cpu_stats", {})
    precpu_stats = stats.get("precpu_stats", {})
    
    # CPU-Delta berechnen (exakte Formel aus Plan)
    cpu_delta = (
        cpu_stats.get("cpu_usage", {}).get("total_usage", 0) -
        precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
    )
    
    # System-CPU-Delta berechnen (exakte Formel aus Plan)
    system_delta = (
        cpu_stats.get("system_cpu_usage", 0) -
        precpu_stats.get("system_cpu_usage", 0)
    )
    
    if system_delta <= 0.0:
        return None
    
    # Online-CPUs aus cpu_stats
    online_cpus = cpu_stats.get("online_cpus", 1)
    if online_cpus == 0:
        online_cpus = 1
    
    # CPU-Prozentsatz berechnen (exakte Formel aus Plan)
    cpu_pct = (cpu_delta / system_delta) * online_cpus * 100.0
    
    return round(max(0.0, min(100.0, cpu_pct)), 2)  # Clamp zwischen 0 und 100, auf 2 Dezimalstellen runden


async def _update_pipeline_stats(
    pipeline_name: str,
    success: bool,
    session: Session,
    triggered_by: Optional[str] = None
) -> None:
    """
    Aktualisiert Pipeline-Statistiken (atomar).
    
    Args:
        pipeline_name: Name der Pipeline
        success: True wenn Run erfolgreich war, sonst False
        session: SQLModel Session
        triggered_by: Trigger-Quelle ("manual", "webhook", oder "scheduler")
    """
    try:
        # Atomare Updates (verhindert Race-Conditions)
        pipeline = session.get(Pipeline, pipeline_name)
        if pipeline:
            # Atomare Zähler-Updates
            # Wenn triggered_by == "webhook", auch webhook_runs erhöhen
            update_values = {
                "total_runs": Pipeline.total_runs + 1,
                "successful_runs": Pipeline.successful_runs + (1 if success else 0),
                "failed_runs": Pipeline.failed_runs + (1 if not success else 0)
            }
            
            # Webhook-Statistik aktualisieren
            if triggered_by == "webhook":
                update_values["webhook_runs"] = Pipeline.webhook_runs + 1
            
            stmt = (
                update(Pipeline)
                .where(Pipeline.pipeline_name == pipeline_name)
                .values(**update_values)
            )
            session.execute(stmt)
            session.commit()
    except Exception as e:
        logger.error(f"Fehler beim Aktualisieren der Pipeline-Statistiken für {pipeline_name}: {e}")


async def _trigger_downstream_pipelines(
    upstream_pipeline_name: str,
    success: bool,
    session: Session,
) -> None:
    """
    Triggert Downstream-Pipelines nach Abschluss einer Upstream-Pipeline.

    Kombiniert Triggert aus pipeline.json und DB. Startet jeden Downstream-Run
    mit triggered_by="downstream".

    Args:
        upstream_pipeline_name: Name der Upstream-Pipeline
        success: True wenn Upstream erfolgreich, False bei Fehlschlag
        session: SQLModel Session
    """
    try:
        pipelines_to_trigger = get_downstream_pipelines_to_trigger(
            upstream_pipeline_name, on_success=success, session=session
        )
        for downstream_name, run_config_id in pipelines_to_trigger:
            try:
                await run_pipeline(
                    name=downstream_name,
                    env_vars=None,
                    parameters=None,
                    session=session,
                    triggered_by="downstream",
                    run_config_id=run_config_id,
                )
                logger.info(
                    "Downstream-Pipeline '%s' gestartet (Upstream '%s' %s)%s",
                    downstream_name,
                    upstream_pipeline_name,
                    "erfolgreich" if success else "fehlgeschlagen",
                    f" (run_config_id={run_config_id})" if run_config_id else "",
                )
            except Exception as e:
                logger.warning(
                    "Downstream-Trigger fehlgeschlagen: Pipeline '%s' nach '%s': %s",
                    downstream_name,
                    upstream_pipeline_name,
                    e,
                )
    except Exception as e:
        logger.warning(
            "Fehler beim Abrufen der Downstream-Triggert für '%s': %s",
            upstream_pipeline_name,
            e,
        )


async def cancel_run(run_id: UUID, session: Session) -> bool:
    """
    Bricht einen laufenden Run ab (Container/Job stoppen).
    
    Args:
        run_id: Run-ID
        session: SQLModel Session
    
    Returns:
        True wenn Run erfolgreich abgebrochen wurde, sonst False
    """
    if config.PIPELINE_EXECUTOR == "kubernetes":
        from app.executor import kubernetes_backend
        return await kubernetes_backend.cancel_run(run_id, session)
    try:
        # Container aus Tracking-Dictionary abrufen
        async with _concurrency_lock:
            container = _running_containers.get(run_id)
        
        if container is None:
            # Container nicht gefunden (bereits beendet?)
            return False
        
        # Container stoppen
        await asyncio.get_running_loop().run_in_executor(
            _executor,
            lambda: container.stop(timeout=10)
        )
        
        # Status auf INTERRUPTED setzen
        run = session.get(PipelineRun, run_id)
        if run:
            run.status = RunStatus.INTERRUPTED
            run.finished_at = datetime.now(timezone.utc)
            session.add(run)
            session.commit()
            
            # Benachrichtigungen senden
            from app.services.notifications import send_notifications
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
    Reconciliert Zombie-Container/Jobs (Crash-Recovery).
    
    Beim App-Start: Scannt laufende Runs (Docker-Container oder K8s-Jobs)
    und gleicht sie mit der Datenbank ab.
    
    Args:
        session: SQLModel Session
    """
    if config.PIPELINE_EXECUTOR == "kubernetes":
        from app.executor import kubernetes_backend
        await kubernetes_backend.reconcile_zombie_jobs(session)
        return
    try:
        client = _get_docker_client()
        
        # Alle Container mit fastflow-run-id Label finden
        containers = await asyncio.get_running_loop().run_in_executor(
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
                    await asyncio.get_running_loop().run_in_executor(
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
                    
                    # OOM Detection
                    oom_killed = container.attrs.get("State", {}).get("OOMKilled", False)
                    if exit_code == 137:
                        oom_killed = True
                    
                    # Spezielle Exit-Code-Erkennung
                    error_type = _classify_exit_code(exit_code, oom_killed)
                    
                    run.exit_code = exit_code
                    run.finished_at = datetime.now(timezone.utc)
                    
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
                    await _update_pipeline_stats(run.pipeline_name, exit_code == 0, session, triggered_by=run.triggered_by)
                    
                    # Container entfernen
                    try:
                        await asyncio.get_running_loop().run_in_executor(
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
        session: SQLModel Session (vom Aufrufer übergeben)
    """
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
        env_vars = run.env_vars or {}
        log_task = asyncio.create_task(
            _stream_logs(container, log_file_path, log_queue, run_id)
        )
        
        if metrics_file_path:
            metrics_task = asyncio.create_task(
                _monitor_metrics(container, metrics_file_path, metrics_queue, pipeline, run_id, session, env_vars)
            )
        else:
            # Metrics-Datei-Pfad erstellen
            metrics_file_path = Path(config.LOGS_DIR / f"{run_id}_metrics.jsonl")
            metrics_task = asyncio.create_task(
                _monitor_metrics(container, metrics_file_path, metrics_queue, pipeline, run_id, session, env_vars)
            )
            run.metrics_file = str(metrics_file_path)
            session.add(run)
            session.commit()
        
        # Container-Wait
        exit_code = await asyncio.get_running_loop().run_in_executor(
            _executor,
            container.wait
        )
        
        # Tasks beenden
        log_task.cancel()
        metrics_task.cancel()
        
        # Exit-Code extrahieren
        exit_code_value = exit_code.get("StatusCode", -1) if isinstance(exit_code, dict) else exit_code
        
        # Spezielle Exit-Code-Erkennung
        # OOM Detection wird bereits in _run_container_task durchgeführt
        error_type = _classify_exit_code(exit_code_value, False)
        
        # Status aktualisieren
        run = session.get(PipelineRun, run_id)
        if run:
            run.exit_code = exit_code_value
            run.finished_at = datetime.now(timezone.utc)
            
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
        await _update_pipeline_stats(run.pipeline_name, exit_code_value == 0, session, triggered_by=run.triggered_by)
        
        # Container entfernen
        try:
            await asyncio.get_running_loop().run_in_executor(
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


async def check_container_health(run_id: UUID, session: Session) -> Dict[str, Any]:
    """
    Führt einen Health-Check für einen laufenden Run (Container oder Job) durch.
    
    Args:
        run_id: Run-ID
        session: SQLModel Session
    
    Returns:
        Dictionary mit Health-Status-Informationen
    """
    if config.PIPELINE_EXECUTOR == "kubernetes":
        from app.executor import kubernetes_backend
        return await kubernetes_backend.check_container_health(run_id, session)
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
    
    Wird beim App-Shutdown aufgerufen, um alle laufenden Container/Jobs
    sauber zu beenden und Status in DB zu aktualisieren.
    
    Args:
        session: SQLModel Session
    """
    if config.PIPELINE_EXECUTOR == "kubernetes":
        from app.executor import kubernetes_backend
        await kubernetes_backend.graceful_shutdown(session)
        return
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
                    await asyncio.get_running_loop().run_in_executor(
                        _executor,
                        lambda: container.stop(timeout=30)  # Graceful Stop mit 30s Timeout
                    )
                    run.status = RunStatus.INTERRUPTED
                except Exception as e:
                    logger.warning(f"Fehler beim Stoppen von Container für Run {run.id}: {e}")
                    run.status = RunStatus.WARNING
            else:
                run.status = RunStatus.WARNING
            
            run.finished_at = datetime.now(timezone.utc)
            session.add(run)
            session.commit()
            
        except Exception as e:
            logger.error(f"Fehler beim Graceful Shutdown für Run {run.id}: {e}")
    
    logger.info(f"Graceful Shutdown abgeschlossen: {len(runs)} Runs beendet")
