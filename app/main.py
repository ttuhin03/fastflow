"""
FastAPI Main Application Module.

Dieses Modul enthält die FastAPI-App mit Lifecycle-Management,
Signal-Handling und Serving des React-Frontends.
"""

import asyncio
import signal
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.config import config
from app.database import init_db
import os

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
    
    # Cleanup-Service initialisieren (Phase 11)
    try:
        from app.cleanup import init_docker_client_for_cleanup, schedule_cleanup_job
        init_docker_client_for_cleanup()
        # Cleanup-Job planen (nach Scheduler-Start)
        schedule_cleanup_job()
        logger.info("Cleanup-Service initialisiert")
    except Exception as e:
        logger.error(f"Fehler bei Cleanup-Service-Initialisierung: {e}")
        # Nicht kritisch, App kann trotzdem starten
    
    # bcrypt_sha256 wird beim ersten Login automatisch initialisiert
    # Initialisierung beim Start wird übersprungen, da passlib beim Initialisieren
    # ein Test-Passwort verwendet, das das 72-Byte-Limit überschreitet
    
    # React-Frontend wird über StaticFiles serviert (siehe unten)
    
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

# CORS konfigurieren für React-Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
        "http://0.0.0.0:8000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:3000",
    ],  # Development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Signal-Handler einrichten
setup_signal_handlers()


@app.get("/health")
@app.get("/api/health")
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
# Alle API-Router haben /api-Präfix für klare Trennung von Frontend-Routen
from app.api import pipelines, runs, logs, metrics, sync, secrets, settings

app.include_router(pipelines.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(secrets.router, prefix="/api")
app.include_router(settings.router, prefix="/api")

# Scheduler-Endpoints (Phase 8)
from app.api import scheduler as scheduler_api
app.include_router(scheduler_api.router, prefix="/api")

# Auth-Endpoints (Phase 9)
from app.api import auth as auth_api
app.include_router(auth_api.router, prefix="/api")

# User Management-Endpoints
from app.api import users as users_api
app.include_router(users_api.router, prefix="/api")

# Webhook-Endpoints
from app.api import webhooks as webhooks_api
app.include_router(webhooks_api.router, prefix="/api")

# Static Files für React-Frontend
# Prüfe ob static-Verzeichnis existiert (nach Build)
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    # Serve React-App für alle nicht-API-Routen
    # Diese Route muss als letzte registriert werden, damit API-Routen zuerst matchen
    from fastapi.responses import FileResponse
    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        """
        Serve React-App für alle Routen, die nicht mit /api beginnen.
        Diese Route wird als Fallback verwendet für React Router.
        """
        # Ignoriere API-Routen, health-check und static assets
        if full_path.startswith("api") or full_path == "health" or full_path.startswith("static"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        
        # Prüfe ob Datei existiert (für static assets wie JS/CSS)
        file_path = os.path.join(static_dir, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        
        # Ansonsten serve index.html (für React Router)
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        
        return JSONResponse({"detail": "Not found"}, status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
