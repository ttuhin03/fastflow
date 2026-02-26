"""
FastAPI Main Application Module.

Dieses Modul enthält die FastAPI-App mit Lifecycle-Management,
Signal-Handling und Serving des React-Frontends.
"""

import asyncio
import signal
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os

from app.core.config import config
from app.metrics_prometheus import setup_prometheus_metrics
from app.startup import run_startup_tasks, run_shutdown_tasks

# Logger konfigurieren (Level/Format werden in lifespan aus config gesetzt)
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
    Startup und Shutdown sind in app.startup ausgelagert.
    """
    await run_startup_tasks()
    yield
    await run_shutdown_tasks()


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
        try:
            signal_name = signal.Signals(signum).name
        except (ValueError, AttributeError):
            signal_name = str(signum)
        logger.info(f"Signal {signal_name} empfangen, starte Graceful Shutdown...")
        shutdown_event.set()
    
    # Signal-Handler registrieren
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    logger.info("Signal-Handler registriert (SIGTERM, SIGINT)")


# FastAPI-App erstellen
# In Produktion: OpenAPI-Docs deaktivieren (Angriffsfläche / Informationspreisgabe reduzieren)
_docs_url = None if config.ENVIRONMENT == "production" else "/docs"
_redoc_url = None if config.ENVIRONMENT == "production" else "/redoc"
_openapi_url = None if config.ENVIRONMENT == "production" else "/openapi.json"

app = FastAPI(
    title="Fast-Flow Orchestrator",
    description="Workflow-Orchestrierungstool für schnelle, isolierte Pipeline-Ausführungen",
    version=config.VERSION,
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# Rate Limiter initialisieren und an App binden
from app.middleware.rate_limiting import limiter
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def _sync_posthog_capture(
    exc: Exception,
    method: str,
    url_no_query: str,
    path: str,
) -> None:
    """Sync: DB-Session + PostHog capture (wird in to_thread ausgeführt)."""
    from sqlmodel import Session
    from app.core.database import engine
    from app.analytics.posthog_client import capture_exception, get_system_settings
    with Session(engine) as session:
        ss = get_system_settings(session)
        if ss.enable_error_reporting:
            capture_exception(
                exc,
                session,
                properties={
                    "$request_method": method,
                    "$current_url": url_no_query,
                    "$request_path": path,
                },
            )


async def _posthog_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI-Exception-Handler: PostHog capture_exception wenn enable_error_reporting; einheitliche 500-Antwort via get_500_detail."""
    logger.exception("Unhandled exception: %s", exc)
    try:
        u = str(request.url)
        url_no_query = u.split("?")[0] if "?" in u else u
        await asyncio.to_thread(
            _sync_posthog_capture,
            exc,
            request.method,
            url_no_query,
            request.url.path,
        )
    except Exception as e:
        logger.warning("PostHog in exception_handler: %s", e)
    from app.core.errors import get_500_detail
    detail = get_500_detail(exc)
    content = {"detail": detail}
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        content["request_id"] = request_id
    return JSONResponse(status_code=500, content=content)


app.add_exception_handler(Exception, _posthog_exception_handler)

# Security Headers Middleware (muss vor CORS sein)
from app.middleware.security_headers import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)

# CORS konfigurieren für React-Frontend
# Origins können über CORS_ORIGINS Environment-Variable konfiguriert werden
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request-Body-Limit (optional, MAX_REQUEST_BODY_MB in config)
from app.middleware.body_limit import BodyLimitMiddleware
app.add_middleware(BodyLimitMiddleware)

# Request-ID: zuletzt hinzufügen = läuft zuerst (outermost)
from app.middleware.request_id import RequestIDMiddleware
app.add_middleware(RequestIDMiddleware)

# Performance-Tracking: Request-Dauer messen, Slow-Request-Detection
from app.middleware.performance import PerformanceTrackingMiddleware
app.add_middleware(PerformanceTrackingMiddleware)

# GZip-Kompression für API-Responses (große JSON-Listen)
from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def static_cache_middleware(request: Request, call_next):
    """Cache-Control für hashed static assets (JS/CSS): 1 Jahr immutable."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/assets/") and response.status_code == 200:
        response.headers["Cache-Control"] = "max-age=31536000, immutable"
    return response

# Signal-Handler einrichten
setup_signal_handlers()


@app.get("/health")
@app.get("/healthz")
@app.get("/api/health")
@limiter.exempt
async def health_check() -> JSONResponse:
    """
    Liveness-Check: Prozess lebt, ohne externe Abhängigkeiten.
    Für Kubernetes livenessProbe / Docker HEALTHCHECK.
    """
    return JSONResponse(
        content={
            "status": "healthy",
            "version": config.VERSION,
            "environment": config.ENVIRONMENT,
            "pipeline_executor": config.PIPELINE_EXECUTOR,
        }
    )


@app.get("/ready")
@app.get("/api/ready")
@limiter.exempt
async def readiness_check() -> JSONResponse:
    """
    Readiness-Check: DB, Docker, UV-Cache-Volume und Disk-Space.
    Gibt 503 zurück, wenn die App nicht verkehrsfähig ist.
    Für Kubernetes readinessProbe.
    """
    from app.core.readiness import run_readiness_checks
    checks, ok = run_readiness_checks()
    status = "not_ready" if not ok else "ready"
    status_code = 503 if not ok else 200
    return JSONResponse(
        status_code=status_code,
        content={
            "status": status,
            "checks": checks,
            "version": config.VERSION,
        },
    )


# API-Router registrieren (Phase 6)
# Alle API-Router haben /api-Präfix für klare Trennung von Frontend-Routen
from app.api import ROUTERS

for router in ROUTERS:
    app.include_router(router, prefix="/api")

# Prometheus-Metriken initialisieren (NACH allen API-Routen, BEVOR Static-Files)
setup_prometheus_metrics(app)

# Static Files für React-Frontend
# Prüfe ob static-Verzeichnis existiert (nach Build)
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    # Docusaurus-Doku unter /doku (VITE_DOCS_URL; /docs = FastAPI Swagger)
    docs_dir = os.path.join(static_dir, "docs")
    _docs_dir = docs_dir  # für Closure in serve_react_app
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Serve React-App für alle nicht-API-Routen
    # Diese Route muss als letzte registriert werden, damit API-Routen zuerst matchen
    from fastapi.responses import FileResponse
    from pathlib import Path as PathLib
    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        """
        Serve React-App für alle Routen, die nicht mit /api beginnen.
        Diese Route wird als Fallback verwendet für React Router.
        
        Sicherheit: Path Traversal wird verhindert durch Validierung dass
        der finale Pfad innerhalb von static_dir liegt.
        """
        # Ignoriere API-Routen, health/ready, static assets
        if full_path.startswith("api") or full_path in ("health", "ready") or full_path.startswith("static"):
            return JSONResponse({"detail": "Not found"}, status_code=404)

        # Docusaurus-Doku: /doku und /doku/... aus static/docs servieren
        if full_path == "doku" or full_path.startswith("doku/"):
            if os.path.exists(_docs_dir):
                docs_path = PathLib(_docs_dir)
                subpath = full_path[5:].lstrip("/") if len(full_path) > 5 else ""
                if not subpath:
                    idx = docs_path / "index.html"
                    if idx.exists():
                        return FileResponse(str(idx))
                else:
                    # Kein User-Input in Pfad: nur Basis + validierte Segmente (kein "..", keine Separatoren)
                    parts = [p for p in subpath.split("/") if p and p not in (".", "..")]
                    if any(".." in p or "/" in p or "\\" in p for p in parts):
                        return JSONResponse({"detail": "Not found"}, status_code=404)
                    safe_path = docs_path
                    for seg in parts:
                        safe_path = safe_path / seg
                    safe_path = safe_path.resolve()
                    try:
                        safe_path.relative_to(docs_path)
                    except ValueError:
                        return JSONResponse({"detail": "Not found"}, status_code=404)
                    if safe_path.exists() and safe_path.is_file():
                        return FileResponse(str(safe_path))
                    if safe_path.is_dir() and (safe_path / "index.html").exists():
                        return FileResponse(str(safe_path / "index.html"))
            return JSONResponse({"detail": "Not found"}, status_code=404)

        # Path Traversal-Schutz: Verwende pathlib für sichere Pfad-Auflösung
        try:
            static_path = PathLib(static_dir).resolve()
            # Konstruiere Pfad nur aus user input - kein direktes Join
            request_path = PathLib(full_path)
            if request_path.is_absolute() or ".." in request_path.parts:
                return JSONResponse({"detail": "Not found"}, status_code=404)
            # Resolve innerhalb static_dir um Path Traversal zu verhindern
            file_path = (static_path / request_path).resolve()
            try:
                file_path.relative_to(static_path)
            except ValueError:
                logger.warning(f"Path Traversal-Versuch erkannt: {full_path} -> {file_path}")
                return JSONResponse({"detail": "Not found"}, status_code=404)
            # Prüfe ob Datei existiert (für static assets wie JS/CSS)
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            # Ansonsten serve index.html (für React Router)
            index_path = static_path / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            
        except Exception as e:
            logger.error(f"Fehler beim Servieren von {full_path}: {e}")
            return JSONResponse({"detail": "Not found"}, status_code=404)
        
        return JSONResponse({"detail": "Not found"}, status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
