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
scheduler = None  # Wird später in scheduler.py initialisiert


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
    
    # TODO: Scheduler starten (Phase 8)
    # TODO: Zombie-Reconciliation (Phase 5.7)
    
    logger.info("Fast-Flow Orchestrator gestartet")
    
    yield
    
    # Shutdown
    logger.info("Fast-Flow Orchestrator wird heruntergefahren...")
    
    # Scheduler stoppen
    if scheduler is not None:
        try:
            scheduler.shutdown()
            logger.info("Scheduler gestoppt")
        except Exception as e:
            logger.error(f"Fehler beim Scheduler-Shutdown: {e}")
    
    # Laufende Runs auf INTERRUPTED oder WARNING setzen
    # TODO: Implementierung in Phase 5.3 (executor.py)
    # - Alle RUNNING-Runs in DB finden
    # - Status auf INTERRUPTED oder WARNING setzen
    # - Optional: Versuch, Docker-Container sauber herunterzufahren (nicht hart killen)
    
    # Container-Cleanup
    # TODO: Implementierung in Phase 5.3 (executor.py)
    # - Verwaiste Container aufräumen
    
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


# TODO: Weitere Endpoints in Phase 6
# TODO: NiceGUI Integration in Phase 13

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
