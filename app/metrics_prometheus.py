"""
Prometheus Metrics Module.

Dieses Modul konfiguriert und exportiert Prometheus-Metriken für die FastAPI-App.
Es bietet sowohl automatische HTTP-Request-Metriken als auch benutzerdefinierte
Business-Metriken für Pipelines und System-Ressourcen.

Metriken:
- HTTP Request/Response Metriken (automatisch via Instrumentator)
- Pipeline Run Metriken (aktive Runs, Queue-Länge, Dauer)
- System Metriken (CPU, RAM, Disk)
- Docker Container Metriken

Endpunkt: GET /metrics (Prometheus-Scraping-Format)
"""

import logging
import time
from typing import Callable, Optional

from prometheus_client import Counter, Gauge, Histogram, Info
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from prometheus_fastapi_instrumentator.metrics import Info as MetricsInfo
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import config

logger = logging.getLogger(__name__)

# ============================================================================
# Benutzerdefinierte Metriken
# ============================================================================

# --- Pipeline Run Metriken ---

# Aktive/Laufende Pipeline Runs (Gauge - kann steigen und fallen)
pipeline_runs_active = Gauge(
    "fastflow_pipeline_runs_active",
    "Anzahl der aktuell laufenden Pipeline-Runs",
    labelnames=["pipeline_name"],
)

# Wartende Pipeline Runs in der Queue
pipeline_runs_queued = Gauge(
    "fastflow_pipeline_runs_queued",
    "Anzahl der Pipeline-Runs in der Warteschlange (wenn Concurrency-Limit erreicht)",
)

# Gesamtzahl der gestarteten Pipeline Runs (Counter - nur steigend)
pipeline_runs_total = Counter(
    "fastflow_pipeline_runs_total",
    "Gesamtzahl der gestarteten Pipeline-Runs",
    labelnames=["pipeline_name", "status"],  # status: started, completed, failed, cancelled
)

# Pipeline Run Dauer (Histogram - für Latenz-Verteilung)
pipeline_run_duration_seconds = Histogram(
    "fastflow_pipeline_run_duration_seconds",
    "Dauer der Pipeline-Runs in Sekunden",
    labelnames=["pipeline_name", "status"],
    buckets=(10, 30, 60, 120, 300, 600, 1800, 3600, 7200, float("inf")),
)

# --- Concurrency Metriken ---

concurrency_limit = Gauge(
    "fastflow_concurrency_limit",
    "Konfiguriertes Concurrency-Limit für gleichzeitige Runs",
)

concurrency_utilization = Gauge(
    "fastflow_concurrency_utilization_ratio",
    "Verhältnis von aktiven Runs zum Concurrency-Limit (0.0 - 1.0)",
)

# --- System Metriken ---

system_cpu_percent = Gauge(
    "fastflow_system_cpu_percent",
    "CPU-Auslastung des Systems in Prozent",
)

system_memory_percent = Gauge(
    "fastflow_system_memory_percent",
    "RAM-Auslastung des Systems in Prozent",
)

system_memory_used_bytes = Gauge(
    "fastflow_system_memory_used_bytes",
    "Verwendeter RAM in Bytes",
)

system_memory_total_bytes = Gauge(
    "fastflow_system_memory_total_bytes",
    "Gesamter RAM in Bytes",
)

system_disk_free_bytes = Gauge(
    "fastflow_system_disk_free_bytes",
    "Freier Speicherplatz auf dem Datenverzeichnis in Bytes",
)

system_disk_total_bytes = Gauge(
    "fastflow_system_disk_total_bytes",
    "Gesamter Speicherplatz auf dem Datenverzeichnis in Bytes",
)

# --- Database Metriken ---

database_size_bytes = Gauge(
    "fastflow_database_size_bytes",
    "Größe der Datenbank-Datei in Bytes (nur SQLite)",
)

database_connections_active = Gauge(
    "fastflow_database_connections_active",
    "Anzahl der aktiven Datenbank-Verbindungen",
)

# --- Log Storage Metriken ---

log_files_count = Gauge(
    "fastflow_log_files_total",
    "Gesamtzahl der Log-Dateien",
)

log_files_size_bytes = Gauge(
    "fastflow_log_files_size_bytes",
    "Gesamtgröße der Log-Dateien in Bytes",
)

# --- Docker Metriken ---

docker_containers_total = Gauge(
    "fastflow_docker_containers_total",
    "Anzahl der Docker-Container (alle Status)",
    labelnames=["status"],  # running, exited, created, etc.
)

docker_available = Gauge(
    "fastflow_docker_available",
    "Docker-Daemon erreichbar (1) oder nicht (0)",
)

# --- App Info ---

app_info = Info(
    "fastflow",
    "Informationen über die Fast-Flow-Instanz",
)


# ============================================================================
# Metriken-Aktualisierung
# ============================================================================

def update_system_metrics() -> None:
    """
    Aktualisiert System-Metriken (CPU, RAM, Disk).
    Wird bei jedem /metrics-Request aufgerufen.
    """
    try:
        import psutil

        # CPU
        cpu_percent = psutil.cpu_percent(interval=None)  # Non-blocking
        system_cpu_percent.set(cpu_percent)

        # RAM
        mem = psutil.virtual_memory()
        system_memory_percent.set(mem.percent)
        system_memory_used_bytes.set(mem.used)
        system_memory_total_bytes.set(mem.total)

        # Disk (DATA_DIR)
        try:
            disk = psutil.disk_usage(str(config.DATA_DIR))
            system_disk_free_bytes.set(disk.free)
            system_disk_total_bytes.set(disk.total)
        except Exception as e:
            logger.debug(f"Disk-Metriken nicht verfügbar: {e}")

    except ImportError:
        logger.warning("psutil nicht verfügbar für System-Metriken")
    except Exception as e:
        logger.warning(f"Fehler beim Aktualisieren der System-Metriken: {e}")


def update_database_metrics() -> None:
    """
    Aktualisiert Datenbank-Metriken.
    """
    try:
        # SQLite: Dateigröße
        if config.DATABASE_URL is None:  # SQLite
            db_path = config.DATA_DIR / "fastflow.db"
            if db_path.exists():
                database_size_bytes.set(db_path.stat().st_size)
    except Exception as e:
        logger.debug(f"Datenbank-Metriken nicht verfügbar: {e}")


def update_log_metrics() -> None:
    """
    Aktualisiert Log-Storage-Metriken.
    """
    try:
        total_count = 0
        total_size = 0

        if config.LOGS_DIR.exists():
            for log_file in config.LOGS_DIR.rglob("*.log"):
                total_count += 1
                try:
                    total_size += log_file.stat().st_size
                except OSError:
                    pass

        log_files_count.set(total_count)
        log_files_size_bytes.set(total_size)
    except Exception as e:
        logger.debug(f"Log-Metriken nicht verfügbar: {e}")


def update_pipeline_metrics() -> None:
    """
    Aktualisiert Pipeline-Run-Metriken.
    """
    try:
        from app.executor import _running_containers, _concurrency_lock
        import asyncio

        # Aktive Runs zählen (synchron, da wir nicht im async context sind)
        active_count = len(_running_containers)

        # Concurrency-Limit setzen
        concurrency_limit.set(config.MAX_CONCURRENT_RUNS)

        # Utilization berechnen
        if config.MAX_CONCURRENT_RUNS > 0:
            utilization = active_count / config.MAX_CONCURRENT_RUNS
            concurrency_utilization.set(utilization)

    except Exception as e:
        logger.debug(f"Pipeline-Metriken nicht verfügbar: {e}")


def update_docker_metrics() -> None:
    """
    Aktualisiert Docker-Container-Metriken.
    """
    try:
        from app.executor import _get_docker_client

        client = _get_docker_client()
        if client is None:
            docker_available.set(0)
            return

        # Docker erreichbar
        try:
            client.ping()
            docker_available.set(1)
        except Exception:
            docker_available.set(0)
            return

        # Container nach Status zählen
        containers = client.containers.list(all=True)
        status_counts: dict[str, int] = {}
        for container in containers:
            status = container.status or "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1

        # Metriken setzen
        for status, count in status_counts.items():
            docker_containers_total.labels(status=status).set(count)

    except Exception as e:
        logger.debug(f"Docker-Metriken nicht verfügbar: {e}")
        docker_available.set(0)


def update_all_metrics() -> None:
    """
    Aktualisiert alle benutzerdefinierten Metriken.
    Wird vor jedem /metrics-Request aufgerufen.
    """
    update_system_metrics()
    update_database_metrics()
    update_log_metrics()
    update_pipeline_metrics()
    update_docker_metrics()


# ============================================================================
# Helper-Funktionen für Pipeline-Tracking
# ============================================================================

def track_run_started(pipeline_name: str) -> None:
    """
    Wird aufgerufen, wenn ein Pipeline-Run startet.
    
    Args:
        pipeline_name: Name der Pipeline
    """
    pipeline_runs_active.labels(pipeline_name=pipeline_name).inc()
    pipeline_runs_total.labels(pipeline_name=pipeline_name, status="started").inc()


def track_run_finished(pipeline_name: str, status: str, duration_seconds: float) -> None:
    """
    Wird aufgerufen, wenn ein Pipeline-Run endet.
    
    Args:
        pipeline_name: Name der Pipeline
        status: End-Status (completed, failed, cancelled)
        duration_seconds: Dauer in Sekunden
    """
    pipeline_runs_active.labels(pipeline_name=pipeline_name).dec()
    pipeline_runs_total.labels(pipeline_name=pipeline_name, status=status).inc()
    pipeline_run_duration_seconds.labels(
        pipeline_name=pipeline_name, status=status
    ).observe(duration_seconds)


# ============================================================================
# Instrumentator Setup
# ============================================================================

def create_instrumentator() -> Instrumentator:
    """
    Erstellt und konfiguriert den Prometheus-Instrumentator für FastAPI.
    
    Returns:
        Konfigurierter Instrumentator
    """
    instrumentator = Instrumentator(
        should_group_status_codes=True,  # 2xx, 3xx, 4xx, 5xx gruppieren
        should_ignore_untemplated=True,  # Unbekannte Routen ignorieren
        should_respect_env_var=True,     # ENABLE_METRICS env var respektieren
        should_instrument_requests_inprogress=True,  # In-Progress-Requests tracken
        excluded_handlers=[
            "/metrics",      # Metrics-Endpoint selbst ausschließen
            "/health",       # Health-Check ausschließen
            "/api/health",
            "/ready",
            "/api/ready",
        ],
        env_var_name="ENABLE_METRICS",
        inprogress_name="fastflow_http_requests_inprogress",
        inprogress_labels=True,
    )

    # Standard HTTP Metriken hinzufügen (Latenz, Request-Count)
    instrumentator.add(
        metrics.default(
            metric_namespace="fastflow",
            metric_subsystem="http",
            latency_highr_buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0, 7.5, 10.0, float("inf")),
        )
    )

    # Request-Size-Metriken
    instrumentator.add(
        metrics.request_size(
            metric_namespace="fastflow",
            metric_subsystem="http",
        )
    )

    # Response-Size-Metriken
    instrumentator.add(
        metrics.response_size(
            metric_namespace="fastflow",
            metric_subsystem="http",
        )
    )

    return instrumentator


def setup_prometheus_metrics(app: FastAPI) -> None:
    """
    Initialisiert Prometheus-Metriken für die FastAPI-App.
    
    Fügt den /metrics-Endpunkt hinzu und registriert alle Metriken.
    
    Args:
        app: FastAPI-App-Instanz
    """
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from starlette.responses import Response as StarletteResponse
    
    # App-Info setzen
    app_info.info({
        "version": config.VERSION,
        "environment": config.ENVIRONMENT,
        "python_version": config.DEFAULT_PYTHON_VERSION,
    })

    # Concurrency-Limit initial setzen
    concurrency_limit.set(config.MAX_CONCURRENT_RUNS)

    # Instrumentator erstellen und konfigurieren
    instrumentator = create_instrumentator()

    # Instrumentator aktivieren (fügt HTTP-Metriken hinzu)
    instrumentator.instrument(app)

    # Manueller /metrics Endpoint (zuverlässiger als instrumentator.expose())
    @app.get("/metrics", tags=["monitoring"], include_in_schema=True)
    async def metrics_endpoint() -> StarletteResponse:
        """
        Prometheus-Metriken-Endpoint.
        
        Gibt alle registrierten Metriken im Prometheus-Format zurück.
        Benutzerdefinierte Metriken werden vor dem Abruf aktualisiert.
        """
        # Benutzerdefinierte Metriken aktualisieren
        update_all_metrics()
        
        # Prometheus-Metriken generieren
        metrics_output = generate_latest()
        
        return StarletteResponse(
            content=metrics_output,
            media_type=CONTENT_TYPE_LATEST,
        )

    logger.info("Prometheus-Metriken initialisiert (/metrics)")
