"""
Kubernetes Job Execution Backend.

Führt Pipeline-Runs als Kubernetes Jobs aus (für containerd-only/Talos-Cluster).
- Erstellt Job mit gleichen Env/Limits wie Docker-Pfad
- Kopiert Pipeline in shared RWM-Volume (pipeline_runs/<run_id>)
- Streamt Pod-Logs in Log-Queue, optionale Metrics
- Cancel, Reconcile, Graceful Shutdown
"""

import asyncio
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from sqlmodel import Session, select

from app.analytics import track_pipeline_run_finished, track_pipeline_run_started
from app.core.config import config as app_config
from app.core.database import get_session
from app.metrics_prometheus import track_run_finished, track_run_started
from app.models import Pipeline, PipelineRun, RunStatus
from app.services.pipeline_discovery import DiscoveredPipeline, get_pipeline
from app.services.downstream_triggers import get_downstream_pipelines_to_trigger
from app.resilience.retry_strategy import wait_for_retry

# Notebook-Zellen-Protokoll: gleiche Präfixe wie in core, für RunCellLog-Persistenz
from app.executor.core import (
    PREFIX_CELL_END,
    PREFIX_CELL_OUTPUT,
    PREFIX_CELL_START,
    _parse_and_persist_cell_line,
)

logger = logging.getLogger(__name__)

# K8s API-Clients (bei init gesetzt)
_batch_api: Optional[client.BatchV1Api] = None
_core_api: Optional[client.CoreV1Api] = None
_initialized = False

# Label für Run-Zuordnung
JOB_LABEL_RUN_ID = "fastflow-run-id"
JOB_LABEL_PIPELINE = "fastflow-pipeline"

def init_kubernetes_client() -> None:
    """Lädt Kubeconfig (in-cluster oder KUBECONFIG) und initialisiert API-Clients."""
    global _batch_api, _core_api, _initialized
    try:
        try:
            config.load_incluster_config()
            logger.info("Kubernetes in-cluster config geladen")
        except config.ConfigException:
            config.load_kube_config()
            logger.info("Kubernetes kubeconfig geladen")
        _batch_api = client.BatchV1Api()
        _core_api = client.CoreV1Api()
        _initialized = True
    except Exception as e:
        logger.error("Kubernetes-Client-Initialisierung fehlgeschlagen: %s", e)
        raise RuntimeError(f"Kubernetes-Client fehlgeschlagen: {e}") from e


def _get_apis() -> tuple:
    if not _initialized or _batch_api is None or _core_api is None:
        raise RuntimeError("Kubernetes-Backend nicht initialisiert (init_kubernetes_client aufrufen)")
    return _batch_api, _core_api


def _shared_pipeline_run_path(run_id: UUID) -> Path:
    """Pfad für Pipeline-Kopie im shared Volume (Orchestrator + Job)."""
    base = Path(app_config.KUBERNETES_SHARED_CACHE_MOUNT_PATH)
    return base / "pipeline_runs" / str(run_id)


def _copy_pipeline_to_shared(pipeline: DiscoveredPipeline, run_id: UUID) -> Path:
    """Kopiert Pipeline-Verzeichnis nach shared Volume; gibt Zielpfad zurück."""
    dest = _shared_pipeline_run_path(run_id)
    dest.mkdir(parents=True, exist_ok=True)
    # Ziel leeren falls vorheriger Run abgebrochen
    for p in dest.iterdir():
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
    shutil.copytree(pipeline.path, dest, dirs_exist_ok=True)
    return dest


def _cleanup_shared_pipeline_run(run_id: UUID) -> None:
    """Löscht das Pipeline-Run-Verzeichnis im shared Volume (nach Run-Ende, um Speicher freizugeben)."""
    path = _shared_pipeline_run_path(run_id)
    if not path.exists():
        return
    try:
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():
            logger.warning("Cleanup pipeline_runs/%s: Verzeichnis nicht vollständig gelöscht", run_id)
        else:
            logger.debug("Cleanup pipeline_runs/%s ok", run_id)
    except Exception as e:
        logger.warning("Cleanup pipeline_runs/%s fehlgeschlagen: %s", run_id, e)


def cleanup_orphaned_shared_pipeline_runs(session: Session) -> int:
    """
    Löscht alle pipeline_runs/<run_id>-Verzeichnisse im shared Volume, deren Run
    nicht mehr RUNNING ist (oder in der DB fehlt). Wird beim App-Start aufgerufen,
    um nach Update bestehende alte Verzeichnisse zu bereinigen.
    Returns: Anzahl gelöschter Verzeichnisse.
    """
    from app.models import PipelineRun, RunStatus

    base = Path(app_config.KUBERNETES_SHARED_CACHE_MOUNT_PATH) / "pipeline_runs"
    if not base.is_dir():
        return 0
    deleted = 0
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        try:
            run_id = UUID(entry.name)
        except ValueError:
            logger.debug("Startup-Cleanup: ignoriere Nicht-UUID-Verzeichnis %s", entry.name)
            continue
        run = session.get(PipelineRun, run_id)
        if run is None or run.status != RunStatus.RUNNING:
            _cleanup_shared_pipeline_run(run_id)
            deleted += 1
    if deleted:
        logger.info("Startup-Cleanup: %d alte pipeline_runs-Verzeichnisse gelöscht", deleted)
    return deleted


def _memory_to_quantity(mem_limit: str) -> str:
    """Konvertiert Memory-Limit (z. B. '512m', '1g') in K8s quantity."""
    s = (mem_limit or "").strip().lower()
    if not s:
        return ""
    if s.endswith("i"):  # Ki, Mi, Gi
        return s
    if s.endswith("mb"):
        return s[:-2].strip() + "Mi"
    if s.endswith("m") and not s.endswith("em"):
        return s[:-1].strip() + "Mi"
    if s.endswith("gb"):
        return s[:-2].strip() + "Gi"
    if s.endswith("g") and not s.endswith("ig"):
        return s[:-1].strip() + "Gi"
    if s.endswith("k"):
        return s[:-1].strip() + "Ki"
    return s


def _classify_exit_code(exit_code: int, oom_killed: bool = False) -> Optional[str]:
    """Exit-Code in Fehlertyp (wie in core)."""
    if oom_killed or exit_code == 137:
        return "OOM (Out of Memory) - Container wurde wegen Memory-Limit gekillt"
    if exit_code == 125:
        return "Container-Start fehlgeschlagen"
    if exit_code == 126:
        return "Command nicht ausführbar"
    if exit_code == 127:
        return "Command nicht gefunden"
    if exit_code == -1:
        return "Timeout - Container wurde wegen Timeout beendet"
    if exit_code != 0:
        return f"Pipeline-Fehler (Exit-Code: {exit_code})"
    return None


async def run_container_task(
    run_id: UUID,
    pipeline: DiscoveredPipeline,
    env_vars: Dict[str, str],
    pre_heating_lock: asyncio.Lock,
) -> None:
    """
    Führt einen Pipeline-Run als Kubernetes Job aus.
    Erstellt Log/Metrics-Queues in core, kopiert Pipeline ins shared Volume,
    erstellt Job, streamt Logs, wartet auf Abschluss, aktualisiert DB.
    """
    from app.executor import core as executor_core

    session_gen = get_session()
    session = next(session_gen)
    log_queue: Optional[asyncio.Queue] = None
    metrics_queue: Optional[asyncio.Queue] = None
    job_name: Optional[str] = None

    try:
        run = session.get(PipelineRun, run_id)
        if not run:
            logger.error("Run %s nicht in Datenbank gefunden", run_id)
            return

        # Effektive Limits/Timeout/Retry (wie in _run_container_task)
        schedule_config: Optional[Dict[str, Any]] = None
        if getattr(run, "run_config_id", None) and getattr(pipeline.metadata, "schedules", None):
            for s in pipeline.metadata.schedules:
                if s.get("id") == run.run_config_id:
                    schedule_config = s
                    break
        _cpu = schedule_config.get("cpu_hard_limit") if schedule_config else None
        effective_cpu = _cpu if _cpu is not None else getattr(pipeline.metadata, "cpu_hard_limit", None)
        _mem = schedule_config.get("mem_hard_limit") if schedule_config else None
        effective_mem = _mem if _mem is not None else getattr(pipeline.metadata, "mem_hard_limit", None)
        _timeout = schedule_config.get("timeout") if schedule_config else None
        effective_timeout = None
        if _timeout is not None:
            effective_timeout = None if _timeout == 0 else _timeout
        else:
            t = pipeline.get_timeout()
            effective_timeout = None if t == 0 else t
        # Globaler Container-Timeout aus Einstellungen (Pipeline & Runs), falls weder Schedule noch Pipeline einen setzen
        if effective_timeout is None:
            effective_timeout = app_config.CONTAINER_TIMEOUT
        _retry = schedule_config.get("retry_attempts") if schedule_config else None
        effective_retry = _retry if _retry is not None else getattr(pipeline.metadata, "retry_attempts", None)
        _retry_strat = schedule_config.get("retry_strategy") if schedule_config else None
        effective_retry_strategy = _retry_strat if _retry_strat is not None else getattr(pipeline.metadata, "retry_strategy", None)

        if app_config.UV_PRE_HEAT:
            async with pre_heating_lock:
                pass

        py_version = pipeline.get_python_version()
        try:
            from app.git_sync.sync import ensure_python_version
            await asyncio.get_running_loop().run_in_executor(
                executor_core._executor,
                lambda: ensure_python_version(py_version),
            )
        except Exception as e:
            logger.warning("Python-Version %s sicherstellen fehlgeschlagen: %s", py_version, e)

        log_file_path = Path(run.log_file)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_file_path.exists():
            log_file_path.touch()
        metrics_file_path = Path(app_config.LOGS_DIR / f"{run_id}_metrics.jsonl")

        log_queue = asyncio.Queue()
        metrics_queue = asyncio.Queue()
        executor_core._log_queues[run_id] = log_queue
        executor_core._metrics_queues[run_id] = metrics_queue

        # Pipeline ins shared Volume kopieren; UV-Cache-Verzeichnisse anlegen
        _copy_pipeline_to_shared(pipeline, run_id)
        base = Path(app_config.KUBERNETES_SHARED_CACHE_MOUNT_PATH)
        (base / "uv_cache").mkdir(parents=True, exist_ok=True)
        (base / "uv_python").mkdir(parents=True, exist_ok=True)

        namespace = app_config.KUBERNETES_NAMESPACE
        pvc_name = app_config.KUBERNETES_CACHE_PVC_NAME
        sub_path_run = f"pipeline_runs/{run_id}"
        run_id_short = str(run_id).replace("-", "")[:8]
        pipeline_slug = (pipeline.name or "run").replace("_", "-").lower()
        if not pipeline_slug.replace("-", "").isalnum():
            pipeline_slug = "run"
        job_name = f"ff-{pipeline_slug}-{run_id_short}"[:63]

        base_env = {
            "UV_CACHE_DIR": "/root/.cache/uv",
            "UV_PYTHON_INSTALL_DIR": "/cache/uv_python",
            "UV_LINK_MODE": "copy",
            "PYTHONUNBUFFERED": "1",
        }
        container_env = [client.V1EnvVar(name=k, value=v) for k, v in {**base_env, **env_vars}.items()]

        resources: Dict[str, Any] = {}
        if effective_mem:
            resources["limits"] = {"memory": _memory_to_quantity(effective_mem)}
        if effective_cpu:
            resources.setdefault("limits", {})["cpu"] = str(effective_cpu)
            # Request wenig CPU, damit der Pod auch auf kleinen Nodes (z. B. Minikube) geplant werden kann
            resources.setdefault("requests", {})["cpu"] = "100m"

        volume = client.V1Volume(
            name="cache",
            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name=pvc_name),
        )
        # /app rw, damit Pipelines Ausgabedateien schreiben können
        mounts = [
            client.V1VolumeMount(name="cache", mount_path="/app", sub_path=sub_path_run, read_only=False),
            client.V1VolumeMount(name="cache", mount_path="/root/.cache/uv", sub_path="uv_cache", read_only=False),
            client.V1VolumeMount(name="cache", mount_path="/cache/uv_python", sub_path="uv_python", read_only=False),
        ]
        container = client.V1Container(
            name="pipeline",
            image=app_config.WORKER_BASE_IMAGE,
            image_pull_policy="IfNotPresent",
            command=executor_core._build_container_command(pipeline),
            env=container_env,
            volume_mounts=mounts,
            resources=client.V1ResourceRequirements(**resources) if resources else None,
        )
        pod_spec = client.V1PodSpec(
            restart_policy="Never",
            containers=[container],
            volumes=[volume],
        )
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    "app": "fastflow-orchestrator",
                    JOB_LABEL_RUN_ID: str(run_id),
                    JOB_LABEL_PIPELINE: pipeline.name,
                }
            ),
            spec=pod_spec,
        )
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name,
                labels={
                    "app": "fastflow-orchestrator",
                    JOB_LABEL_RUN_ID: str(run_id),
                    JOB_LABEL_PIPELINE: pipeline.name,
                },
            ),
            spec=client.V1JobSpec(
                ttl_seconds_after_finished=app_config.KUBERNETES_JOB_TTL_SECONDS_AFTER_FINISHED or None,
                backoff_limit=0,
                template=template,
                active_deadline_seconds=int(effective_timeout) if effective_timeout else None,
            ),
        )
        batch_api, core_api = _get_apis()
        batch_api.create_namespaced_job(namespace=namespace, body=job)
        logger.info("Job %s für Run %s erstellt", job_name, run_id)
        job_creation_time = datetime.now(timezone.utc)

        run.status = RunStatus.RUNNING
        session.add(run)
        session.commit()

        setup_start = time.time()
        try:
            track_run_started(pipeline.name)
        except Exception:
            pass

        first_log_event = asyncio.Event()
        setup_container_ts_queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        log_task = asyncio.create_task(
            _stream_pod_logs(
                run_id, namespace, job_name, log_file_path, log_queue, first_log_event,
                setup_container_ts_queue=setup_container_ts_queue,
            )
        )
        metrics_task = asyncio.create_task(
            _emit_placeholder_metrics(
                metrics_file_path, metrics_queue, run_id,
                namespace=namespace, job_name=job_name,
            )
        )

        try:
            await asyncio.wait_for(first_log_event.wait(), timeout=120.0)
            try:
                setup_container_ts = setup_container_ts_queue.get_nowait()
                setup_duration = (setup_container_ts - job_creation_time).total_seconds()
            except asyncio.QueueEmpty:
                setup_duration = time.time() - setup_start
        except asyncio.TimeoutError:
            setup_duration = None
        run = session.get(PipelineRun, run_id)
        if run:
            run.setup_duration = setup_duration
            session.add(run)
            session.commit()

        # Warten auf Job-Ende
        exit_code_value, oom_killed = await _wait_for_job_completion(
            run_id, namespace, job_name, effective_timeout
        )

        await asyncio.sleep(0.5)
        log_task.cancel()
        try:
            await asyncio.wait_for(log_task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        metrics_task.cancel()
        try:
            await asyncio.wait_for(metrics_task, timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

        error_type = _classify_exit_code(exit_code_value, oom_killed)
        run = session.get(PipelineRun, run_id)
        if not run:
            logger.error("Run %s beim Status-Update nicht gefunden", run_id)
            return
        run.exit_code = exit_code_value
        run.finished_at = datetime.now(timezone.utc)
        if exit_code_value == 0:
            run.status = RunStatus.SUCCESS
        else:
            run.status = RunStatus.FAILED
            if run.env_vars is None:
                run.env_vars = {}
            run.env_vars["_fastflow_error_type"] = "pipeline_error"
            if error_type:
                run.env_vars["_fastflow_error_message"] = error_type
        if metrics_file_path.exists():
            run.metrics_file = str(metrics_file_path)
        session.add(run)
        session.commit()

        duration_seconds = (run.finished_at - run.started_at).total_seconds() if run.finished_at and run.started_at else 0.0
        if exit_code_value == 0:
            try:
                track_pipeline_run_finished(session, pipeline.name, "SUCCESS", run.triggered_by, duration_seconds, pipeline.has_requirements)
            except Exception:
                pass
            try:
                track_run_finished(pipeline.name, "completed", duration_seconds)
            except Exception:
                pass
        else:
            try:
                track_run_finished(pipeline.name, "failed", duration_seconds)
            except Exception:
                pass

        await executor_core._update_pipeline_stats(pipeline.name, exit_code_value == 0, session, triggered_by=run.triggered_by)
        if exit_code_value == 0:
            await executor_core._trigger_downstream_pipelines(pipeline.name, success=True, session=session)

        # Retry
        if exit_code_value != 0 and pipeline.get_entry_type() != "notebook":
            run = session.get(PipelineRun, run_id)
            retry_attempts = effective_retry or app_config.RETRY_ATTEMPTS
            if run and retry_attempts and retry_attempts > 0:
                current_retry_count = (run.env_vars or {}).get("_fastflow_retry_count", "0")
                try:
                    current_retry_count = int(current_retry_count)
                except (ValueError, TypeError):
                    current_retry_count = 0
                if current_retry_count < retry_attempts:
                    await wait_for_retry(current_retry_count + 1, effective_retry_strategy)
                    new_env = run.env_vars.copy()
                    new_env["_fastflow_retry_count"] = str(current_retry_count + 1)
                    new_env["_fastflow_previous_run_id"] = str(run.id)
                    from app.executor.core import run_pipeline
                    await run_pipeline(
                        run.pipeline_name,
                        env_vars=new_env,
                        parameters=None,
                        session=session,
                        triggered_by=f"{run.triggered_by}_retry",
                        run_config_id=run.run_config_id,
                    )
                    return
        if exit_code_value != 0 and run:
            from app.services.notifications import send_notifications
            await send_notifications(run, RunStatus.FAILED)
    except Exception as e:
        logger.exception("Kubernetes run_container_task Fehler für Run %s: %s", run_id, e)
        run = session.get(PipelineRun, run_id)
        if run:
            run.status = RunStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.exit_code = -1
            if run.env_vars is None:
                run.env_vars = {}
            run.env_vars["_fastflow_error_type"] = "infrastructure_error"
            run.env_vars["_fastflow_error_message"] = str(e)
            session.add(run)
            session.commit()
            await executor_core._update_pipeline_stats(run.pipeline_name, False, session, triggered_by=run.triggered_by)
    finally:
        executor_core._log_queues.pop(run_id, None)
        executor_core._metrics_queues.pop(run_id, None)
        _cleanup_shared_pipeline_run(run_id)
        try:
            next(session_gen)
        except StopIteration:
            pass


def _is_only_k8s_timestamp(line: str) -> bool:
    """True wenn die Zeile nur ein K8s RFC3339-Timestamp ist (Chunk-Grenze trennt Timestamp und Inhalt)."""
    s = (line or "").strip()
    if len(s) < 20 or s[-1] != "Z":
        return False
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _format_k8s_log_timestamp(line: str):
    """
    Extrahiert K8s-Log-Timestamp (RFC3339 am Zeilenanfang) und gibt (display_ts, content, dt) zurück.
    Bei timestamps=True: "2026-02-13T14:37:41.123456789Z Log text" oder "…Z\\tLog text".
    Returns: (display_ts, content, datetime|None) oder None wenn kein K8s-Timestamp.
    """
    if not line or len(line) < 20:
        return None
    # K8s nutzt Space oder Tab nach dem Z
    idx_space = line.find("Z ")
    idx_tab = line.find("Z\t")
    idx = -1
    if idx_space >= 20:
        idx = idx_space
    if idx_tab >= 20 and (idx < 0 or idx_tab < idx):
        idx = idx_tab
    if idx < 20:
        return None
    ts_str = line[: idx + 1]
    content = line[idx + 2 :].lstrip()
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        display = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        return (display, content, dt)
    except ValueError:
        return None


def _parse_leading_rfc3339(content: str):
    """
    Wenn der Log-Inhalt mit einem RFC3339-Timestamp beginnt (vom Skript gedruckt), diesen für
    die Anzeige nutzen. Returns (display_ts, rest_content) oder None.
    """
    if not content or len(content) < 20:
        return None
    for sep in ("Z ", "Z\t"):
        idx = content.find(sep)
        if idx >= 20:
            ts_str = content[: idx + 1]
            rest = content[idx + 2 :].lstrip()
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                display = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                return (display, rest)
            except ValueError:
                pass
    return None


async def _stream_pod_logs(
    run_id: UUID,
    namespace: str,
    job_name: str,
    log_file_path: Path,
    log_queue: asyncio.Queue,
    first_log_event: asyncio.Event,
    setup_container_ts_queue: Optional[asyncio.Queue] = None,
) -> None:
    """Streamt Pod-Logs in Datei und Queue (Zeilen mit Timestamp)."""
    import aiofiles
    batch_api, core_api = _get_apis()
    SETUP_READY = "FASTFLOW_SETUP_READY"
    pending_ts_line: Optional[str] = None

    def _get_pod_name() -> Optional[str]:
        try:
            jobs = batch_api.list_namespaced_job(namespace=namespace, label_selector=f"{JOB_LABEL_RUN_ID}={run_id}")
            if not jobs.items:
                return None
            job = jobs.items[0]
            if not job.metadata or not job.metadata.name:
                return None
            pods = core_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"job-name={job.metadata.name}",
            )
            if not pods.items:
                return None
            return pods.items[0].metadata.name
        except ApiException:
            return None

    pod_name = None
    for _ in range(60):
        pod_name = await asyncio.get_running_loop().run_in_executor(None, _get_pod_name)
        if pod_name:
            break
        await asyncio.sleep(1)
    if not pod_name:
        logger.warning("Pod für Job %s (Run %s) nicht gefunden", job_name, run_id)
        return

    def _can_stream_pod_logs() -> bool:
        """True wenn Log-Stream starten kann: Container läuft ODER Pod bereits beendet (dann Logs trotzdem lesbar)."""
        try:
            pod = core_api.read_namespaced_pod(name=pod_name, namespace=namespace)
            if not pod.status:
                return False
            if pod.status.phase == "Running":
                for cs in (pod.status.container_statuses or []):
                    if cs.name == "pipeline" and cs.ready:
                        return True
            if pod.status.phase in ("Succeeded", "Failed"):
                return True
        except ApiException:
            pass
        return False

    for _ in range(120):
        if await asyncio.get_running_loop().run_in_executor(None, _can_stream_pod_logs):
            break
        await asyncio.sleep(1)
    else:
        logger.warning("Pod %s (Run %s) weder Running noch beendet – Log-Stream übersprungen", pod_name, run_id)
        return

    try:
        resp = core_api.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container="pipeline",
            follow=True,
            timestamps=True,
            _preload_content=False,
        )
        async with aiofiles.open(log_file_path, "a", encoding="utf-8") as log_file:
            line_buffer = b""
            while True:
                try:
                    chunk = await asyncio.get_running_loop().run_in_executor(None, resp.read, 4096)
                    if not chunk:
                        break
                    line_buffer += chunk
                    while b"\n" in line_buffer:
                        line_part, line_buffer = line_buffer.split(b"\n", 1)
                        try:
                            line = line_part.decode("utf-8").rstrip()
                        except UnicodeDecodeError:
                            line = line_part.decode("utf-8", errors="replace").rstrip()
                        if not line:
                            continue
                        if _is_only_k8s_timestamp(line):
                            pending_ts_line = line.strip()
                            if not pending_ts_line.endswith(" "):
                                pending_ts_line += " "
                            continue
                        if pending_ts_line is not None:
                            line = pending_ts_line + line
                            pending_ts_line = None
                        parsed = _format_k8s_log_timestamp(line)
                        if parsed is not None:
                            ts_display, content_part, dt = parsed
                            if content_part.strip() == SETUP_READY:
                                first_log_event.set()
                                if setup_container_ts_queue is not None and dt is not None:
                                    try:
                                        setup_container_ts_queue.put_nowait(dt)
                                    except asyncio.QueueFull:
                                        pass
                                continue
                        elif line.strip() == SETUP_READY:
                            first_log_event.set()
                            continue
                        if parsed is not None:
                            ts_display, content, _ = parsed
                        else:
                            ts_display = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                            content = line
                        # Bevorzuge Timestamp aus dem Log-Inhalt (vom Skript), falls vorhanden
                        app_ts = _parse_leading_rfc3339(content)
                        if app_ts is not None:
                            ts_display, content = app_ts
                        is_cell_protocol = (
                            content.startswith(PREFIX_CELL_START)
                            or content.startswith(PREFIX_CELL_END)
                            or content.startswith(PREFIX_CELL_OUTPUT)
                        )
                        if is_cell_protocol:
                            await asyncio.get_running_loop().run_in_executor(
                                None,
                                lambda c=content: _parse_and_persist_cell_line(run_id, c),
                            )
                        log_line = f"[{ts_display}] {content}"
                        await log_file.write(log_line + "\n")
                        await log_file.flush()
                        if app_config.LOG_MAX_SIZE_MB and log_file_path.exists():
                            file_size_mb = log_file_path.stat().st_size / (1024 * 1024)
                            if file_size_mb > app_config.LOG_MAX_SIZE_MB:
                                logger.warning(
                                    "Log-Datei für Run %s überschreitet LOG_MAX_SIZE_MB (%s MB): %.2f MB – Stream gekappt",
                                    run_id, app_config.LOG_MAX_SIZE_MB, file_size_mb,
                                )
                                break
                        try:
                            log_queue.put_nowait(log_line)
                        except asyncio.QueueFull:
                            try:
                                log_queue.get_nowait()
                                log_queue.put_nowait(log_line)
                            except asyncio.QueueEmpty:
                                pass
                except (StopIteration, AttributeError):
                    break
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning("Log-Stream für Run %s: %s", run_id, e)


def _parse_cpu_quantity(s: str) -> float:
    """Konvertiert K8s CPU-Quantity (z. B. '100m', '1') in Kerne (float). 1 Kern = 100%."""
    if not s:
        return 0.0
    s = s.strip()
    if s.endswith("n"):
        return int(s[:-1]) / 1_000_000_000.0
    if s.endswith("u"):
        return int(s[:-1]) / 1_000_000.0
    if s.endswith("m"):
        return int(s[:-1]) / 1000.0
    return float(s)


def _parse_memory_quantity_to_mb(s: str) -> float:
    """Konvertiert K8s Memory-Quantity (z. B. '128Ki', '50Mi') in MB."""
    if not s:
        return 0.0
    s = s.strip()
    num = 0
    i = 0
    while i < len(s) and (s[i].isdigit() or s[i] == "."):
        i += 1
    try:
        num = float(s[:i]) if s[:i] else 0.0
    except ValueError:
        return 0.0
    suffix = s[i:].lower() if i < len(s) else ""
    if suffix in ("", "b"):
        return num / (1024 * 1024)
    if suffix == "ki":
        return num / 1024
    if suffix == "mi":
        return num
    if suffix == "gi":
        return num * 1024
    return num / (1024 * 1024)


def _get_pod_metrics_from_api(namespace: str, pod_name: str) -> tuple:
    """Liest Pod-Metriken von metrics.k8s.io (falls metrics-server läuft). Returns (cpu_percent, ram_mb)."""
    try:
        custom_api = client.CustomObjectsApi()
        obj = custom_api.get_namespaced_custom_object(
            "metrics.k8s.io", "v1beta1", namespace, "pods", pod_name
        )
        containers = obj.get("containers", [])
        total_cpu = 0.0
        total_mem_mb = 0.0
        for c in containers:
            usage = c.get("usage", {})
            cpu_str = usage.get("cpu", "0")
            mem_str = usage.get("memory", "0")
            total_cpu += _parse_cpu_quantity(cpu_str)
            total_mem_mb += _parse_memory_quantity_to_mb(mem_str)
        return (total_cpu * 100.0, total_mem_mb)
    except Exception:
        return (0.0, 0.0)


def get_kubernetes_system_metrics() -> Dict[str, Any]:
    """
    Liefert System-Metriken für laufende Pipeline-Jobs (für /settings/system-metrics).
    Returns: active_containers, containers_ram_mb, containers_cpu_percent, container_details.
    """
    out = {
        "active_containers": 0,
        "containers_ram_mb": 0.0,
        "containers_cpu_percent": 0.0,
        "container_details": [],
    }
    try:
        batch_api, core_api = _get_apis()
        namespace = app_config.KUBERNETES_NAMESPACE
        jobs = batch_api.list_namespaced_job(
            namespace=namespace,
            label_selector="app=fastflow-orchestrator",
        )
        total_ram_mb = 0.0
        total_cpu_percent = 0.0
        details = []
        for job in jobs.items or []:
            if not job.status or not getattr(job.status, "active", None) or job.status.active < 1:
                continue
            run_id_str = (job.metadata.labels or {}).get(JOB_LABEL_RUN_ID, "unknown")
            pipeline_name = (job.metadata.labels or {}).get(JOB_LABEL_PIPELINE, "unknown")
            job_name_val = job.metadata.name if job.metadata else None
            if not job_name_val:
                continue
            pods = core_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"job-name={job_name_val}",
            )
            pod_name = pods.items[0].metadata.name if pods.items else None
            ram_mb, cpu_percent = 0.0, 0.0
            if pod_name:
                cpu_percent, ram_mb = _get_pod_metrics_from_api(namespace, pod_name)
            total_ram_mb += ram_mb
            total_cpu_percent += cpu_percent
            details.append({
                "run_id": run_id_str,
                "pipeline_name": pipeline_name,
                "container_id": pod_name[:12] if pod_name else "-",
                "ram_mb": round(ram_mb, 2),
                "ram_percent": 0.0,
                "cpu_percent": round(cpu_percent, 2),
                "status": "running",
            })
        out["active_containers"] = len(details)
        out["containers_ram_mb"] = round(total_ram_mb, 2)
        out["containers_cpu_percent"] = round(total_cpu_percent, 2)
        out["container_details"] = details
    except RuntimeError:
        pass
    except Exception as e:
        logger.warning("Kubernetes-System-Metriken: %s", e)
    return out


async def _emit_placeholder_metrics(
    metrics_file_path: Path,
    metrics_queue: asyncio.Queue,
    run_id: UUID,
    namespace: Optional[str] = None,
    job_name: Optional[str] = None,
) -> None:
    """Sendet Metrics: bei namespace+job_name wird die K8s Metrics-API (metrics-server) genutzt, sonst 0."""
    import aiofiles
    loop = asyncio.get_running_loop()

    def _get_pod_name() -> Optional[str]:
        if not namespace or not job_name:
            return None
        try:
            _, core_api = _get_apis()
            pods = core_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"job-name={job_name}",
            )
            if pods.items:
                return pods.items[0].metadata.name
        except Exception:
            pass
        return None

    try:
        async with aiofiles.open(metrics_file_path, "a", encoding="utf-8") as f:
            while True:
                cpu_percent, ram_mb = 0.0, 0.0
                if namespace and job_name:
                    pod_name = await loop.run_in_executor(None, _get_pod_name)
                    if pod_name:
                        cpu_percent, ram_mb = await loop.run_in_executor(
                            None, lambda: _get_pod_metrics_from_api(namespace, pod_name)
                        )
                metric = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "cpu_percent": round(cpu_percent, 2),
                    "ram_mb": round(ram_mb, 2),
                    "ram_limit_mb": 0.0,
                    "soft_limit_exceeded": False,
                }
                await f.write(json.dumps(metric) + "\n")
                await f.flush()
                try:
                    metrics_queue.put_nowait(metric)
                except asyncio.QueueFull:
                    try:
                        metrics_queue.get_nowait()
                        metrics_queue.put_nowait(metric)
                    except asyncio.QueueEmpty:
                        pass
                await asyncio.sleep(2)
    except asyncio.CancelledError:
        pass


async def _wait_for_job_completion(
    run_id: UUID,
    namespace: str,
    job_name: str,
    timeout_seconds: Optional[int],
) -> tuple:
    """Wartet auf Job-Ende; gibt (exit_code, oom_killed) zurück."""
    batch_api, core_api = _get_apis()
    deadline = (time.time() + timeout_seconds) if timeout_seconds else None
    oom_killed = False
    exit_code = -1

    while True:
        try:
            job = batch_api.read_namespaced_job(name=job_name, namespace=namespace)
        except ApiException as e:
            if e.status == 404:
                return -1, False
            raise
        if job.status.succeeded is not None and job.status.succeeded > 0:
            exit_code = 0
            break
        if job.status.failed is not None and job.status.failed > 0:
            # Exit-Code aus Pod-Container-Status
            pods = core_api.list_namespaced_pod(
                namespace=namespace,
                label_selector=f"job-name={job_name}",
            )
            for pod in pods.items or []:
                for cs in (pod.status.container_statuses or []):
                    if cs.name != "pipeline":
                        continue
                    if cs.state and cs.state.terminated:
                        exit_code = cs.state.terminated.exit_code or -1
                        if getattr(cs.state.terminated, "reason", None) == "OOMKilled":
                            oom_killed = True
                    break
            break
        if deadline and time.time() > deadline:
            exit_code = -1
            try:
                batch_api.delete_namespaced_job(name=job_name, namespace=namespace, propagation_policy="Background")
            except ApiException:
                pass
            break
        await asyncio.sleep(2)
    return exit_code, oom_killed


async def cancel_run(run_id: UUID, session: Session) -> bool:
    """Löscht den Job für run_id."""
    batch_api, _ = _get_apis()
    namespace = app_config.KUBERNETES_NAMESPACE
    try:
        jobs = batch_api.list_namespaced_job(
            namespace=namespace,
            label_selector=f"{JOB_LABEL_RUN_ID}={run_id}",
        )
        for job in jobs.items or []:
            if job.metadata and job.metadata.name:
                batch_api.delete_namespaced_job(
                    name=job.metadata.name,
                    namespace=namespace,
                    propagation_policy="Background",
                )
                run = session.get(PipelineRun, run_id)
                if run:
                    run.status = RunStatus.INTERRUPTED
                    run.finished_at = datetime.now(timezone.utc)
                    session.add(run)
                    session.commit()
                _cleanup_shared_pipeline_run(run_id)
                return True
    except ApiException as e:
        logger.warning("Job-Löschung für Run %s: %s", run_id, e)
    return False


async def check_container_health(run_id: UUID, session: Session) -> Dict[str, Any]:
    """Health-Check für laufenden Job."""
    batch_api, _ = _get_apis()
    namespace = app_config.KUBERNETES_NAMESPACE
    try:
        jobs = batch_api.list_namespaced_job(
            namespace=namespace,
            label_selector=f"{JOB_LABEL_RUN_ID}={run_id}",
        )
        if not jobs.items:
            return {"healthy": False, "reason": "Job nicht gefunden"}
        job = jobs.items[0]
        if job.status.succeeded and job.status.succeeded > 0:
            return {"healthy": True, "reason": "Job erfolgreich beendet"}
        if job.status.failed and job.status.failed > 0:
            return {"healthy": False, "reason": "Job fehlgeschlagen"}
        return {"healthy": True, "reason": "Job läuft"}
    except ApiException as e:
        return {"healthy": False, "reason": str(e)}


async def reconcile_zombie_jobs(session: Session) -> None:
    """Reconciliert Jobs mit DB (orphaned beenden, laufende ggf. re-attach)."""
    batch_api, _ = _get_apis()
    namespace = app_config.KUBERNETES_NAMESPACE
    try:
        jobs = batch_api.list_namespaced_job(
            namespace=namespace,
            label_selector=JOB_LABEL_RUN_ID,
        )
        for job in jobs.items or []:
            run_id_str = job.metadata.labels.get(JOB_LABEL_RUN_ID) if job.metadata and job.metadata.labels else None
            if not run_id_str:
                continue
            try:
                run_id = UUID(run_id_str)
            except ValueError:
                continue
            run = session.get(PipelineRun, run_id)
            if run is None:
                try:
                    batch_api.delete_namespaced_job(
                        name=job.metadata.name,
                        namespace=namespace,
                        propagation_policy="Background",
                    )
                    logger.info("Orphaned Job %s (Run %s) gelöscht", job.metadata.name, run_id)
                except ApiException:
                    pass
                _cleanup_shared_pipeline_run(run_id)
                continue
            if job.status.succeeded and job.status.succeeded > 0 and run.status == RunStatus.RUNNING:
                run.status = RunStatus.SUCCESS
                run.finished_at = datetime.now(timezone.utc)
                run.exit_code = 0
                session.add(run)
                session.commit()
                _cleanup_shared_pipeline_run(run_id)
            elif job.status.failed and job.status.failed > 0 and run.status == RunStatus.RUNNING:
                run.status = RunStatus.FAILED
                run.finished_at = datetime.now(timezone.utc)
                run.exit_code = -1
                session.add(run)
                session.commit()
                _cleanup_shared_pipeline_run(run_id)
        logger.info("Kubernetes Zombie-Reconciliation abgeschlossen")
    except Exception as e:
        logger.error("Zombie-Reconciliation Fehler: %s", e, exc_info=True)


async def graceful_shutdown(session: Session) -> None:
    """Beendet alle laufenden Runs (Jobs löschen, DB auf INTERRUPTED/WARNING)."""
    logger.info("Graceful Shutdown (Kubernetes): Beende alle laufenden Runs...")
    runs = session.exec(select(PipelineRun).where(PipelineRun.status == RunStatus.RUNNING)).all()
    batch_api, _ = _get_apis()
    namespace = app_config.KUBERNETES_NAMESPACE
    for run in runs:
        try:
            jobs = batch_api.list_namespaced_job(
                namespace=namespace,
                label_selector=f"{JOB_LABEL_RUN_ID}={run.id}",
            )
            if jobs.items:
                for job in jobs.items:
                    if job.metadata and job.metadata.name:
                        try:
                            batch_api.delete_namespaced_job(
                                name=job.metadata.name,
                                namespace=namespace,
                                propagation_policy="Background",
                            )
                        except ApiException:
                            pass
            run.status = RunStatus.INTERRUPTED
            run.finished_at = datetime.now(timezone.utc)
            session.add(run)
            session.commit()
            _cleanup_shared_pipeline_run(run.id)
        except Exception as e:
            logger.warning("Graceful Shutdown Run %s: %s", run.id, e)
    logger.info("Graceful Shutdown (Kubernetes) abgeschlossen: %s Runs", len(runs))
