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

import httpx

from app.config import config
from app.database import init_db
from app.github_oauth_user import GITHUB_ACCESS_TOKEN_URL
from app.google_oauth_user import GOOGLE_TOKEN_URL
from app.metrics_prometheus import setup_prometheus_metrics

# Logger konfigurieren (Level/Format werden in lifespan aus config gesetzt)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Setzt Log-Level und optional JSON-Format aus config (wird in lifespan aufgerufen)."""
    root = logging.getLogger()
    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    root.setLevel(level)
    if config.LOG_JSON:
        try:
            import json as _json
            from datetime import datetime, timezone

            class JsonFormatter(logging.Formatter):
                def format(self, record: logging.LogRecord) -> str:
                    log_obj = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "level": record.levelname,
                        "logger": record.name,
                        "message": record.getMessage(),
                    }
                    if record.exc_info:
                        log_obj["exception"] = self.formatException(record.exc_info)
                    return _json.dumps(log_obj, default=str)
            for h in root.handlers:
                h.setFormatter(JsonFormatter())
        except Exception as e:
            logger.warning("LOG_JSON aktiviert, Formatter-Setup fehlgeschlagen: %s", e)

# Globale Variablen für Graceful Shutdown
shutdown_event = asyncio.Event()



# Startup Banner (version will be inserted dynamically)
STARTUP_BANNER_TEMPLATE = r"""
________                 __     ___________.__                     
\______   \_____    ______/  |_  \_   _____/|  |   ______  _  __     
 |    |  _/\__  \  /  ___/\   __\  |    __)  |  |  /  _ \ \/ \/ /     
 |    |   \ / __ \_\___ \  |  |    |     \   |  |_|  <_> )     /      
 |______  /(____  /____  > |__|    \___  /   |____/____/ \/\_/       
        \/      \/     \/              \/                            

[SYSTEM] Fast-Flow v{version} initialized.
[INFO]   Philosophy: Complexity is a bug, not a feature.
[INFO]   Status: 100% Free of Air-Castles, Daggers, and Magic Spells.
[INFO]   Mode: Pure Python Execution.
---------------------------------------------------------------------
"""

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
    _setup_logging()
    print(STARTUP_BANNER_TEMPLATE.format(version=config.VERSION))
    logger.info("Fast-Flow Orchestrator startet...")

    # Sicherheits-Validierungen beim Start
    _validate_security_config()
    
    # OAuth-Validierung: mind. ein Provider muss vollständig sein; Konfiguration wird verifiziert
    await _validate_oauth_config()
    
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

    # Dependency-Audit-Job (pip-audit täglich; Benachrichtigung bei Schwachstellen)
    try:
        from app.dependency_audit import schedule_dependency_audit_job
        schedule_dependency_audit_job()
        logger.info("Dependency-Audit-Job aus SystemSettings geladen")
    except Exception as e:
        logger.warning("Dependency-Audit-Job konnte nicht geplant werden: %s", e)

    # Version Check initialisieren und planen (Phase 12)
    try:
        from app.version_checker import check_version_update, schedule_version_check
        # Initiale Version-Prüfung beim Start
        await check_version_update()
        # Version-Check planen (täglich um 2 Uhr)
        schedule_version_check()
        logger.info("Version Check initialisiert und geplant")
    except Exception as e:
        logger.error(f"Fehler bei Version-Check-Initialisierung: {e}")
        # Nicht kritisch, App kann trotzdem starten

    # Telemetry: instance_heartbeat täglich 03:00 UTC (Storage, RAM, CPU, total_users_bucket)
    try:
        from app.analytics import run_instance_heartbeat_sync, schedule_telemetry_heartbeat
        schedule_telemetry_heartbeat()
        logger.info("Telemetry instance_heartbeat geplant")
        # Einmalig beim Start: Instance-Heartbeat (total_users_bucket, Pipelines, Storage, RAM, CPU)
        # Nur gesendet wenn enable_telemetry; danach wie geplant (z.B. täglich 03:00 UTC)
        asyncio.create_task(asyncio.to_thread(run_instance_heartbeat_sync))
    except Exception as e:
        logger.warning("Telemetry Heartbeat konnte nicht geplant werden: %s", e)

    # UV Pre-Heating beim Start (wenn UV_PRE_HEAT): uv pip compile für alle requirements.txt
    try:
        from app.git_sync import run_pre_heat_at_startup
        asyncio.create_task(run_pre_heat_at_startup())
        logger.info("UV Pre-Heating beim Start geplant (Hintergrund)")
    except Exception as e:
        logger.warning("UV Pre-Heating beim Start konnte nicht gestartet werden: %s", e)

    # PostHog Startup-Test (nur ENVIRONMENT=development): immer eine Test-Exception senden,
    # unabhängig von enable_error_reporting. Prüft, ob PostHog erreichbar ist.
    if config.ENVIRONMENT == "development":
        try:
            from app.posthog_client import capture_startup_test_exception
            capture_startup_test_exception()
        except Exception as ex:
            logger.warning("PostHog Startup-Test übersprungen: %s", ex)
    
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

    # PostHog: Flush und Shutdown (vgl. Product Analytics Installation – sauberes Beenden)
    try:
        from app.posthog_client import shutdown_posthog
        shutdown_posthog()
    except Exception as e:
        logger.warning("PostHog Shutdown: %s", e)

    logger.info("Fast-Flow Orchestrator heruntergefahren")


def _validate_security_config() -> None:
    """
    Validiert Sicherheits-Konfiguration beim App-Start.
    
    Prüft dass keine unsicheren Standardwerte in Produktion verwendet werden.
    Raises:
        RuntimeError: Wenn kritische Sicherheitsprobleme erkannt werden
    """
    from app.config import config
    
    # Prüfe ob wir in Produktion sind
    is_production = config.ENVIRONMENT == "production"
    
    errors = []
    warnings = []
    
    # 1. ENCRYPTION_KEY muss gesetzt sein (kritisch)
    if config.ENCRYPTION_KEY is None:
        errors.append(
            "ENCRYPTION_KEY ist nicht gesetzt. "
            "Bitte setze ENCRYPTION_KEY in der .env-Datei. "
            "Generierung: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    else:
        # Validiere dass ENCRYPTION_KEY gültig ist
        try:
            from cryptography.fernet import Fernet
            Fernet(config.ENCRYPTION_KEY.encode() if isinstance(config.ENCRYPTION_KEY, str) else config.ENCRYPTION_KEY)
        except Exception as e:
            errors.append(
                f"ENCRYPTION_KEY ist ungültig: {str(e)}. "
                "Bitte generiere einen neuen Key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
    
    # 2. JWT_SECRET_KEY sollte nicht der Standardwert sein (kritisch in Produktion)
    if config.JWT_SECRET_KEY == "change-me-in-production":
        if is_production:
            errors.append(
                "JWT_SECRET_KEY verwendet den unsicheren Standardwert 'change-me-in-production'. "
                "Bitte setze einen sicheren, zufälligen Wert (mindestens 32 Zeichen) in der .env-Datei."
            )
        else:
            warnings.append(
                "JWT_SECRET_KEY verwendet den Standardwert 'change-me-in-production'. "
                "Dies sollte in Produktion geändert werden."
            )
    
    # 3. CORS Validierung: Wildcard-Origins mit allow_credentials sind unsicher
    if config.CORS_ORIGINS:
        for origin in config.CORS_ORIGINS:
            if origin == "*" or origin.strip() == "*":
                if is_production:
                    errors.append(
                        "CORS_ORIGINS enthält Wildcard '*', was mit allow_credentials=True unsicher ist. "
                        "Bitte verwende spezifische Origins in der .env-Datei."
                    )
                else:
                    warnings.append(
                        "CORS_ORIGINS enthält Wildcard '*', was mit allow_credentials=True unsicher ist. "
                        "Dies sollte in Produktion geändert werden."
                    )
                break
    
    # Logge Warnungen
    for warning in warnings:
        logger.warning(f"⚠️  Sicherheitswarnung: {warning}")
    
    # Wirf Fehler für kritische Probleme
    if errors:
        error_msg = "Kritische Sicherheitsprobleme gefunden:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.error(error_msg)
        if is_production:
            # In Produktion: Fehler sind fatal
            raise RuntimeError(error_msg)
        else:
            # In Entwicklung: Nur warnen
            logger.error("⚠️  In Produktion würden diese Fehler die App am Start verhindern.")


async def _validate_oauth_config() -> None:
    """
    Prüft, dass mindestens ein OAuth-Provider (GitHub oder Google) vollständig
    konfiguriert ist, und verifiziert die Credentials beim jeweiligen Anbieter.

    - Vollständig = CLIENT_ID und CLIENT_SECRET gesetzt.
    - Verifizierung: Token-Request mit Dummy-Code; erwartet wird
      „falscher Code“ (Credentials ok), nicht „falsche Credentials“.

    Raises:
        RuntimeError: Wenn kein Provider vollständig ist oder eine
            Verifizierung fehlschlägt (ungültige Credentials, Netzwerk, etc.).
    """
    has_github = bool(config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET)
    has_google = bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)

    if not has_github and not has_google:
        raise RuntimeError(
            "OAuth ist nicht konfiguriert: Es muss mindestens einer der folgenden "
            "Provider vollständig gesetzt sein (jeweils CLIENT_ID und CLIENT_SECRET).\n"
            "  - GitHub: GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET\n"
            "  - Google:  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET\n"
            "Siehe .env.example und docs/oauth/."
        )

    base = (config.BASE_URL or "http://localhost:8000").rstrip("/")

    if config.SKIP_OAUTH_VERIFICATION:
        logger.info("OAuth-HTTP-Verifizierung übersprungen (SKIP_OAUTH_VERIFICATION)")
        return

    from app.resilience import circuit_oauth, call_async_with_circuit_breaker

    async with httpx.AsyncClient(timeout=15.0) as client:
        if has_github:
            await call_async_with_circuit_breaker(
                circuit_oauth, _verify_github_oauth, client, base
            )
        if has_google:
            await call_async_with_circuit_breaker(
                circuit_oauth, _verify_google_oauth, client, base
            )


async def _verify_github_oauth(client: httpx.AsyncClient, base: str) -> None:
    """
    Prüft GitHub-OAuth-Credentials über den Token-Endpoint mit Dummy-Code.
    Erwartet: error=bad_verification_code (Credentials ok). Bei
    incorrect_client_credentials oder anderem Fehler: RuntimeError.
    """
    redirect_uri = f"{base}/api/auth/github/callback"
    try:
        resp = await client.post(
            GITHUB_ACCESS_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": config.GITHUB_CLIENT_ID,
                "client_secret": config.GITHUB_CLIENT_SECRET,
                "code": "__startup_verify__",
                "redirect_uri": redirect_uri,
            },
        )
    except httpx.RequestError as e:
        raise RuntimeError(
            f"GitHub OAuth-Verifizierung: Anfrage fehlgeschlagen (Netzwerk/Timeout). "
            f"Konnektivität zu github.com und BASE_URL prüfen. Fehler: {e}"
        ) from e

    try:
        body = resp.json()
    except Exception as e:
        raise RuntimeError(
            f"GitHub OAuth-Verifizierung: Ungültige Antwort (Status {resp.status_code}). "
            f"BASE_URL/Redirect-URI prüfen. Fehler: {e}"
        ) from e

    err = body.get("error") or ""
    if err == "bad_verification_code":
        logger.info("GitHub OAuth: Credentials verifiziert")
        return
    if err == "incorrect_client_credentials":
        raise RuntimeError(
            "GitHub OAuth: GITHUB_CLIENT_ID oder GITHUB_CLIENT_SECRET ist falsch. "
            "Bitte in .env und in der GitHub OAuth App (Developer settings → OAuth Apps) prüfen."
        )
    msg = body.get("error_description") or body.get("error") or resp.text or str(resp.status_code)
    raise RuntimeError(
        f"GitHub OAuth-Verifizierung fehlgeschlagen: {msg}. "
        f"Redirect-URI in der GitHub OAuth App muss exakt sein: {redirect_uri}"
    )


async def _verify_google_oauth(client: httpx.AsyncClient, base: str) -> None:
    """
    Prüft Google-OAuth-Credentials über den Token-Endpoint mit Dummy-Code.
    Erwartet: error=invalid_grant (Credentials ok). Bei invalid_client
    oder anderem Fehler: RuntimeError.
    """
    redirect_uri = f"{base}/api/auth/google/callback"
    try:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "code": "__startup_verify__",
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    except httpx.RequestError as e:
        raise RuntimeError(
            f"Google OAuth-Verifizierung: Anfrage fehlgeschlagen (Netzwerk/Timeout). "
            f"Konnektivität zu oauth2.googleapis.com und BASE_URL prüfen. Fehler: {e}"
        ) from e

    try:
        body = resp.json()
    except Exception as e:
        raise RuntimeError(
            f"Google OAuth-Verifizierung: Ungültige Antwort (Status {resp.status_code}). "
            f"BASE_URL/Redirect-URI prüfen. Fehler: {e}"
        ) from e

    err = body.get("error") or ""
    if err == "invalid_grant":
        logger.info("Google OAuth: Credentials verifiziert")
        return
    if err == "invalid_client":
        raise RuntimeError(
            "Google OAuth: GOOGLE_CLIENT_ID oder GOOGLE_CLIENT_SECRET ist falsch. "
            "Bitte in .env und in der Google Cloud Console (APIs & Services → Anmeldedaten) prüfen."
        )
    msg = body.get("error_description") or body.get("error") or resp.text or str(resp.status_code)
    raise RuntimeError(
        f"Google OAuth-Verifizierung fehlgeschlagen: {msg}. "
        f"Redirect-URI in der Google OAuth App muss exakt sein: {redirect_uri}"
    )


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


async def _posthog_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI-Exception-Handler: PostHog capture_exception wenn enable_error_reporting; einheitliche 500-Antwort via get_500_detail."""
    logger.exception("Unhandled exception: %s", exc)
    try:
        from sqlmodel import Session
        from app.database import engine
        from app.posthog_client import capture_exception, get_system_settings
        with Session(engine) as session:
            ss = get_system_settings(session)
            if ss.enable_error_reporting:
                u = str(request.url)
                url_no_query = u.split("?")[0] if "?" in u else u
                capture_exception(
                    exc,
                    session,
                    properties={
                        "$request_method": request.method,
                        "$current_url": url_no_query,
                        "$request_path": request.url.path,
                    },
                )
    except Exception as e:
        logger.warning("PostHog in exception_handler: %s", e)
    from app.errors import get_500_detail
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

# Signal-Handler einrichten
setup_signal_handlers()


@app.get("/health")
@app.get("/api/health")
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
        }
    )


@app.get("/ready")
@app.get("/api/ready")
async def readiness_check() -> JSONResponse:
    """
    Readiness-Check: DB, Docker, UV-Cache-Volume und Disk-Space.
    Gibt 503 zurück, wenn die App nicht verkehrsfähig ist.
    Für Kubernetes readinessProbe.
    """
    from app.database import engine
    from sqlmodel import text

    checks: dict = {}
    ok = True

    # DB-Check
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.warning("Readiness: DB-Check fehlgeschlagen: %s", e)
        checks["database"] = str(e)
        ok = False

    # Docker-Proxy-Check (mit Circuit Breaker)
    try:
        from app.executor import _get_docker_client
        from app.resilience import circuit_docker, CircuitBreakerOpenError
        client = _get_docker_client()
        if client:
            circuit_docker.call(lambda: client.ping())
        checks["docker"] = "ok"
    except CircuitBreakerOpenError as e:
        checks["docker"] = str(e)
        ok = False
    except Exception as e:
        checks["docker"] = str(e)
        ok = False

    # UV-Cache-Volume beschreibbar (kritisch für Pipeline-Runs)
    try:
        uv_cache = config.UV_CACHE_DIR
        uv_cache.mkdir(parents=True, exist_ok=True)
        test_file = uv_cache / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        checks["uv_cache"] = "ok"
    except Exception as e:
        logger.warning("Readiness: UV-Cache-Check fehlgeschlagen: %s", e)
        checks["uv_cache"] = str(e)
        ok = False

    # Disk-Space verfügbar (kritisch für Logs, DB, UV-Cache)
    try:
        import shutil
        disk = shutil.disk_usage(str(config.DATA_DIR))
        free_gb = disk.free / (1024 ** 3)
        checks["disk_free_gb"] = round(free_gb, 2)
        if free_gb < 0.5:  # < 500 MB = nicht ready
            checks["disk"] = f"kritisch: nur {free_gb:.2f} GB frei"
            ok = False
        else:
            checks["disk"] = "ok"
    except Exception as e:
        logger.warning("Readiness: Disk-Check fehlgeschlagen: %s", e)
        checks["disk"] = str(e)
        ok = False

    if not ok:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "checks": checks,
                "version": config.VERSION,
            },
        )
    return JSONResponse(
        content={
            "status": "ready",
            "checks": checks,
            "version": config.VERSION,
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

# System/Version-Endpoints
from app.api import version as version_api
app.include_router(version_api.router, prefix="/api")

# Prometheus-Metriken initialisieren (NACH allen API-Routen, BEVOR Static-Files)
setup_prometheus_metrics(app)

# Static Files für React-Frontend
# Prüfe ob static-Verzeichnis existiert (nach Build)
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
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
        # Ignoriere API-Routen, health/ready und static assets
        if full_path.startswith("api") or full_path in ("health", "ready") or full_path.startswith("static"):
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
