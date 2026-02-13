"""
Startup- und Shutdown-Logik der FastAPI-App.

Enthält run_startup_tasks() und run_shutdown_tasks() mit einheitlichem
Fehlerhandling (kritisch vs. optional) sowie OAuth- und Sicherheits-Validierung.
"""

import asyncio
import logging
from typing import Callable, Awaitable, Union, Optional

from app.core.config import config

logger = logging.getLogger(__name__)

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


def _setup_logging() -> None:
    """Setzt Log-Level und optional JSON-Format aus config."""
    from app.core.logging_config import setup_logging as do_setup_logging
    do_setup_logging(log_level=config.LOG_LEVEL, log_json=config.LOG_JSON)


def _validate_security_config() -> None:
    """
    Validiert Sicherheits-Konfiguration beim App-Start.
    Raises:
        RuntimeError: Wenn kritische Sicherheitsprobleme in Produktion erkannt werden.
    """
    is_production = config.ENVIRONMENT == "production"
    errors = []
    warnings = []

    if config.ENCRYPTION_KEY is None:
        errors.append(
            "ENCRYPTION_KEY ist nicht gesetzt. "
            "Bitte setze ENCRYPTION_KEY in der .env-Datei. "
            "Generierung: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    else:
        try:
            from cryptography.fernet import Fernet
            Fernet(config.ENCRYPTION_KEY.encode() if isinstance(config.ENCRYPTION_KEY, str) else config.ENCRYPTION_KEY)
        except Exception as e:
            errors.append(
                f"ENCRYPTION_KEY ist ungültig: {str(e)}. "
                "Bitte generiere einen neuen Key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )

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
    elif is_production and len(config.JWT_SECRET_KEY) < 32:
        errors.append(
            "JWT_SECRET_KEY muss in Produktion mindestens 32 Zeichen lang sein. "
            "Aktuell: {} Zeichen. Siehe .env.example.".format(len(config.JWT_SECRET_KEY))
        )

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

    for warning in warnings:
        logger.warning("⚠️  Sicherheitswarnung: %s", warning)
    if errors:
        error_msg = "Kritische Sicherheitsprobleme gefunden:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.error(error_msg)
        if is_production:
            raise RuntimeError(error_msg)
        logger.error("⚠️  In Produktion würden diese Fehler die App am Start verhindern.")


async def _verify_oauth_token_request(
    client: "httpx.AsyncClient",
    url: str,
    data: dict,
    headers: dict,
    redirect_uri: str,
    provider_name: str,
    expected_error_ok: str,
    invalid_credentials_error: str,
    invalid_credentials_message: str,
) -> None:
    """
    Generische OAuth-Token-Verifizierung: POST an url mit data; erwarteter
    „OK“-Fehler = expected_error_ok (z. B. bad_verification_code); bei
    invalid_credentials_error wird invalid_credentials_message geworfen.
    """
    import httpx
    try:
        resp = await client.post(url, headers=headers, data=data)
    except httpx.RequestError as e:
        raise RuntimeError(
            f"{provider_name} OAuth-Verifizierung: Anfrage fehlgeschlagen (Netzwerk/Timeout). "
            f"Konnektivität und BASE_URL prüfen. Fehler: {e}"
        ) from e
    try:
        body = resp.json()
    except Exception as e:
        raise RuntimeError(
            f"{provider_name} OAuth-Verifizierung: Ungültige Antwort (Status {resp.status_code}). "
            f"BASE_URL/Redirect-URI prüfen. Fehler: {e}"
        ) from e
    err = (body.get("error") or "").strip()
    if err == expected_error_ok:
        logger.info("%s OAuth: Credentials verifiziert", provider_name)
        return
    if err == invalid_credentials_error:
        raise RuntimeError(invalid_credentials_message)
    msg = body.get("error_description") or body.get("error") or resp.text or str(resp.status_code)
    raise RuntimeError(
        f"{provider_name} OAuth-Verifizierung fehlgeschlagen: {msg}. "
        f"Redirect-URI muss exakt sein: {redirect_uri}"
    )


async def _validate_oauth_config() -> None:
    """
    Prüft, dass mindestens ein OAuth-Provider vollständig konfiguriert ist
    und verifiziert die Credentials per Token-Request mit Dummy-Code.
    Raises:
        RuntimeError: Wenn kein Provider konfiguriert oder Verifizierung fehlschlägt.
    """
    from app.auth.github_oauth_user import GITHUB_ACCESS_TOKEN_URL
    from app.auth.google_oauth_user import GOOGLE_TOKEN_URL
    from app.resilience import circuit_oauth, call_async_with_circuit_breaker
    import httpx

    has_github = bool(config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET)
    has_google = bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)
    has_microsoft = bool(config.MICROSOFT_CLIENT_ID and config.MICROSOFT_CLIENT_SECRET)
    has_custom = bool(
        config.CUSTOM_OAUTH_CLIENT_ID
        and config.CUSTOM_OAUTH_CLIENT_SECRET
        and config.CUSTOM_OAUTH_AUTHORIZE_URL
        and config.CUSTOM_OAUTH_TOKEN_URL
        and config.CUSTOM_OAUTH_USERINFO_URL
    )
    if not (has_github or has_google or has_microsoft or has_custom):
        raise RuntimeError(
            "OAuth ist nicht konfiguriert: Es muss mindestens einer der folgenden "
            "Provider vollständig gesetzt sein (jeweils CLIENT_ID und CLIENT_SECRET).\n"
            "  - GitHub:   GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET\n"
            "  - Google:   GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET\n"
            "  - Microsoft: MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET\n"
            "  - Custom:   CUSTOM_OAUTH_CLIENT_ID, CUSTOM_OAUTH_CLIENT_SECRET, *_URL\n"
            "Siehe .env.example und docs/oauth/."
        )
    base = (config.BASE_URL or "http://localhost:8000").rstrip("/")
    if config.SKIP_OAUTH_VERIFICATION:
        logger.info("OAuth-HTTP-Verifizierung übersprungen (SKIP_OAUTH_VERIFICATION)")
        return

    async def verify_github(client: httpx.AsyncClient, _base: str) -> None:
        redirect_uri = f"{_base}/api/auth/github/callback"
        await _verify_oauth_token_request(
            client,
            GITHUB_ACCESS_TOKEN_URL,
            {
                "client_id": config.GITHUB_CLIENT_ID,
                "client_secret": config.GITHUB_CLIENT_SECRET,
                "code": "__startup_verify__",
                "redirect_uri": redirect_uri,
            },
            {"Accept": "application/json"},
            redirect_uri,
            "GitHub",
            "bad_verification_code",
            "incorrect_client_credentials",
            "GitHub OAuth: GITHUB_CLIENT_ID oder GITHUB_CLIENT_SECRET ist falsch. "
            "Bitte in .env und in der GitHub OAuth App (Developer settings → OAuth Apps) prüfen.",
        )

    async def verify_google(client: httpx.AsyncClient, _base: str) -> None:
        redirect_uri = f"{_base}/api/auth/google/callback"
        await _verify_oauth_token_request(
            client,
            GOOGLE_TOKEN_URL,
            {
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "code": "__startup_verify__",
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            redirect_uri,
            "Google",
            "invalid_grant",
            "invalid_client",
            "Google OAuth: GOOGLE_CLIENT_ID oder GOOGLE_CLIENT_SECRET ist falsch. "
            "Bitte in .env und in der Google Cloud Console (APIs & Services → Anmeldedaten) prüfen.",
        )

    async def verify_microsoft(client: httpx.AsyncClient, _base: str) -> None:
        from app.auth.microsoft_oauth_user import _get_microsoft_token_url
        redirect_uri = f"{_base}/api/auth/microsoft/callback"
        await _verify_oauth_token_request(
            client,
            _get_microsoft_token_url(),
            {
                "client_id": config.MICROSOFT_CLIENT_ID,
                "client_secret": config.MICROSOFT_CLIENT_SECRET,
                "code": "__startup_verify__",
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            redirect_uri,
            "Microsoft",
            "invalid_grant",
            "invalid_client",
            "Microsoft OAuth: MICROSOFT_CLIENT_ID oder MICROSOFT_CLIENT_SECRET ist falsch. "
            "Bitte in .env und in Azure Portal (App-Registrierung) prüfen.",
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        if has_github:
            await call_async_with_circuit_breaker(circuit_oauth, verify_github, client, base)
        if has_google:
            await call_async_with_circuit_breaker(circuit_oauth, verify_google, client, base)
        if has_microsoft:
            await call_async_with_circuit_breaker(circuit_oauth, verify_microsoft, client, base)


async def _run_step(
    name: str,
    critical: bool,
    step: Union[Callable[[], Awaitable[None]], Callable[[], None]],
    success_msg: Optional[str] = None,
) -> None:
    """Führt einen Startup-/Shutdown-Schritt aus; bei Fehler: kritisch → raise, sonst log."""
    try:
        result = step()
        if asyncio.iscoroutine(result):
            await result
        if success_msg:
            logger.info(success_msg)
    except Exception as e:
        if critical:
            logger.error("Startup fehlgeschlagen bei %s: %s", name, e)
            raise
        logger.warning("Startup-Schritt %s fehlgeschlagen (nicht kritisch): %s", name, e)


async def run_startup_tasks() -> None:
    """
    Führt alle Startup-Schritte aus (Logging, Validierung, DB, Docker, Scheduler, etc.).
    Kritische Schritte werfen bei Fehler; optionale werden geloggt und übersprungen.
    """
    _setup_logging()
    print(STARTUP_BANNER_TEMPLATE.format(version=config.VERSION))
    logger.info("Fast-Flow Orchestrator startet...")

    _validate_security_config()
    await _validate_oauth_config()

    config.ensure_directories()
    logger.info("Verzeichnisse erstellt/geprüft")

    await _run_step(
        "Datenbank-Initialisierung",
        True,
        lambda: __import__("app.core.database", fromlist=["init_db"]).init_db(),
        "Datenbank initialisiert",
    )

    def load_orchestrator_settings():
        from app.core.database import engine
        from app.services.orchestrator_settings import get_orchestrator_settings, apply_orchestrator_settings_to_config
        from sqlmodel import Session
        with Session(engine) as session:
            settings = get_orchestrator_settings(session)
            if settings is not None:
                apply_orchestrator_settings_to_config(settings)
                logger.info("Orchestrator-Einstellungen aus DB geladen")
    await _run_step("Orchestrator-Einstellungen", False, load_orchestrator_settings, None)

    def init_executor():
        from app.executor import init_docker_client
        init_docker_client()
    # In Test-Modus Executor-Init überspringen (kein Docker/K8s nötig)
    if not config.TESTING:
        msg = "Kubernetes-Executor initialisiert" if config.PIPELINE_EXECUTOR == "kubernetes" else "Docker-Client initialisiert"
        await _run_step("Pipeline-Executor-Initialisierung", True, init_executor, msg)

    async def zombie_reconcile():
        from app.core.database import get_session
        from app.executor import reconcile_zombie_containers
        session_gen = get_session()
        session = next(session_gen)
        try:
            await reconcile_zombie_containers(session)
        finally:
            session.close()
    if not config.TESTING:
        await _run_step("Zombie-Reconciliation", False, zombie_reconcile, "Zombie-Reconciliation abgeschlossen")

    def start_sched():
        from app.services.scheduler import start_scheduler
        start_scheduler()
    if not config.TESTING:
        await _run_step("Scheduler-Start", False, start_sched, "Scheduler gestartet")

    def sync_json_schedules():
        from app.services.scheduler import sync_scheduler_jobs_from_pipeline_json
        sync_scheduler_jobs_from_pipeline_json()
    if not config.TESTING:
        await _run_step("Scheduler-Jobs aus pipeline.json", False, sync_json_schedules, "Scheduler-Jobs aus pipeline.json synchronisiert")

    def init_cleanup():
        from app.services.cleanup import init_docker_client_for_cleanup, schedule_cleanup_job
        init_docker_client_for_cleanup()
        schedule_cleanup_job()
    if not config.TESTING:
        await _run_step("Cleanup-Service", False, init_cleanup, "Cleanup-Service initialisiert")

    def schedule_wal_checkpoint():
        from app.core.database import schedule_wal_checkpoint_job
        schedule_wal_checkpoint_job()
    await _run_step("WAL-Checkpoint-Job", False, schedule_wal_checkpoint, None)

    def schedule_audit():
        from app.services.dependency_audit import schedule_dependency_audit_job
        schedule_dependency_audit_job()
    await _run_step("Dependency-Audit-Job", False, schedule_audit, "Dependency-Audit-Job aus SystemSettings geladen")

    # Beim Start einmalig Dependency-Audit durchlaufen (Hintergrund), Ergebnisse für Frontend
    async def run_audit_once():
        from app.services.dependency_audit import run_dependency_audit_on_startup_async
        await run_dependency_audit_on_startup_async()
    asyncio.create_task(run_audit_once())
    logger.info("Dependency-Audit (einmalig beim Start) im Hintergrund gestartet")

    async def version_check():
        from app.services.version_checker import check_version_update, schedule_version_check
        await check_version_update()
        schedule_version_check()
    await _run_step("Version-Check", False, version_check, "Version Check initialisiert und geplant")

    def telemetry():
        from app.analytics import run_instance_heartbeat_sync, schedule_telemetry_heartbeat
        schedule_telemetry_heartbeat()
        asyncio.create_task(asyncio.to_thread(run_instance_heartbeat_sync))
    await _run_step("Telemetry-Heartbeat", False, telemetry, "Telemetry instance_heartbeat geplant")

    def pre_heat():
        from app.git_sync import run_pre_heat_at_startup
        asyncio.create_task(run_pre_heat_at_startup())
    await _run_step("UV Pre-Heating", False, pre_heat, "UV Pre-Heating beim Start geplant (Hintergrund)")

    if config.ENVIRONMENT == "development":
        def posthog_test():
            from app.analytics.posthog_client import capture_startup_test_exception
            capture_startup_test_exception()
        await _run_step("PostHog Startup-Test", False, posthog_test, None)

    logger.info("Fast-Flow Orchestrator gestartet")


async def run_shutdown_tasks() -> None:
    """Führt alle Shutdown-Schritte aus (Scheduler stoppen, Graceful Shutdown, PostHog)."""
    logger.info("Fast-Flow Orchestrator wird heruntergefahren...")

    def stop_sched():
        from app.services.scheduler import stop_scheduler
        stop_scheduler()
    await _run_step("Scheduler-Shutdown", False, stop_sched, None)

    async def graceful():
        from app.executor import graceful_shutdown
        from app.core.database import get_session
        session_gen = get_session()
        session = next(session_gen)
        try:
            await graceful_shutdown(session)
        finally:
            session.close()
    await _run_step("Graceful Shutdown", False, graceful, "Graceful Shutdown abgeschlossen")

    def posthog_shutdown():
        from app.analytics.posthog_client import shutdown_posthog
        shutdown_posthog()
    await _run_step("PostHog Shutdown", False, posthog_shutdown, None)

    logger.info("Fast-Flow Orchestrator heruntergefahren")
