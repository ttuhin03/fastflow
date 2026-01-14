"""
FastAPI Main Application Module.

Dieses Modul enthält die FastAPI-App mit Lifecycle-Management,
Signal-Handling und Integration von NiceGUI.
"""

import asyncio
import signal
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.config import config
from app.database import init_db

# Logger konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Globale Variablen für Graceful Shutdown
shutdown_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle-Manager für FastAPI-App.
    
    Verwaltet Startup- und Shutdown-Events:
    - Startup: Datenbank-Initialisierung, Verzeichnisse erstellen
    - Shutdown: Scheduler stoppen, Cleanup-Tasks
    
    Args:
        app: FastAPI-App-Instanz
        
    Yields:
        None: App läuft während des Context-Managers
    """
    # Startup
    logger.info("Fast-Flow Orchestrator startet...")
    
    # Verzeichnisse erstellen
    config.ensure_directories()
    logger.info("Verzeichnisse erstellt/geprüft")
    
    # Datenbank initialisieren
    try:
        init_db()
        logger.info("Datenbank initialisiert")
    except Exception as e:
        logger.error(f"Fehler bei Datenbank-Initialisierung: {e}")
        raise
    
    # Docker-Client initialisieren
    try:
        from app.executor import init_docker_client, reconcile_zombie_containers
        init_docker_client()
        logger.info("Docker-Client initialisiert")
    except Exception as e:
        logger.error(f"Fehler bei Docker-Client-Initialisierung: {e}")
        raise
    
    # Zombie-Reconciliation (Crash-Recovery)
    try:
        from app.database import get_session
        session_gen = get_session()
        session = next(session_gen)
        try:
            await reconcile_zombie_containers(session)
            logger.info("Zombie-Reconciliation abgeschlossen")
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Fehler bei Zombie-Reconciliation: {e}")
        # Nicht kritisch, App kann trotzdem starten
    
    # Scheduler starten (Phase 8)
    try:
        from app.scheduler import start_scheduler
        start_scheduler()
        logger.info("Scheduler gestartet")
    except Exception as e:
        logger.error(f"Fehler beim Scheduler-Start: {e}")
        # Nicht kritisch, App kann trotzdem starten (Jobs können manuell gestartet werden)
    
    # NiceGUI UI initialisieren (Phase 9.2, 13)
    try:
        from app.ui import init_ui
        init_ui(app)
        logger.info("NiceGUI UI initialisiert")
    except Exception as e:
        logger.error(f"Fehler bei NiceGUI-Initialisierung: {e}")
        # Nicht kritisch, API funktioniert auch ohne UI
    
    logger.info("Fast-Flow Orchestrator gestartet")
    
    yield
    
    # Shutdown
    logger.info("Fast-Flow Orchestrator wird heruntergefahren...")
    
    # Scheduler stoppen
    try:
        from app.scheduler import stop_scheduler
        stop_scheduler()
    except Exception as e:
        logger.error(f"Fehler beim Scheduler-Shutdown: {e}")
    
    # Graceful Shutdown: Laufende Runs beenden
    try:
        from app.executor import graceful_shutdown
        from app.database import get_session
        session_gen = get_session()
        session = next(session_gen)
        try:
            await graceful_shutdown(session)
            logger.info("Graceful Shutdown abgeschlossen")
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Fehler beim Graceful Shutdown: {e}")
    
    logger.info("Fast-Flow Orchestrator heruntergefahren")


def setup_signal_handlers() -> None:
    """
    Konfiguriert Signal-Handler für Graceful Shutdown.
    
    Behandelt SIGTERM und SIGINT Signale, um die App sauber
    herunterzufahren ohne Zombie-Container oder Datenbank-Inkonsistenzen.
    """
    def signal_handler(signum, frame):
        """
        Signal-Handler für SIGTERM/SIGINT.
        
        Setzt das Shutdown-Event, damit die App sauber beendet werden kann.
        """
        signal_name = signal.Signals(signum).name
        logger.info(f"Signal {signal_name} empfangen, starte Graceful Shutdown...")
        shutdown_event.set()
    
    # Signal-Handler registrieren
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logger.info("Signal-Handler registriert (SIGTERM, SIGINT)")


# FastAPI-App erstellen
app = FastAPI(
    title="Fast-Flow Orchestrator",
    description="Workflow-Orchestrierungstool für schnelle, isolierte Pipeline-Ausführungen",
    version="0.1.0",
    lifespan=lifespan
)

# Signal-Handler einrichten
setup_signal_handlers()


@app.get("/health")
async def health_check() -> JSONResponse:
    """
    Health-Check-Endpoint für Monitoring.
    
    Returns:
        JSONResponse: Status-Informationen der App
    """
    return JSONResponse(
        content={
            "status": "healthy",
            "version": "0.1.0"
        }
    )


# API-Router registrieren (Phase 6)
from app.api import pipelines, runs, logs, metrics, sync, secrets

app.include_router(pipelines.router)
app.include_router(runs.router)
app.include_router(logs.router)
app.include_router(metrics.router)
app.include_router(sync.router)
app.include_router(secrets.router)

# Scheduler-Endpoints (Phase 8)
from app.api import scheduler as scheduler_api
app.include_router(scheduler_api.router)

# Auth-Endpoints (Phase 9)
from app.api import auth as auth_api
app.include_router(auth_api.router)

# NiceGUI Integration (Phase 9.2, 13)
# UI wird in lifespan() initialisiert

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
