"""
FastAPI API Endpoints Package.

Dieses Paket enthält alle REST-API-Endpoints für Pipeline-Management,
Run-Management, Log-Streaming, Git-Sync, Scheduler und Authentication.
"""

from app.api import (
    audit,
    auth,
    logs,
    metrics,
    notifications,
    pipelines,
    runs,
    scheduler,
    secrets,
    settings,
    sync,
    users,
    version,
    webhooks,
)

# Alle API-Router für zentrale Registrierung in main.py (prefix="/api")
ROUTERS = [
    audit.router,
    pipelines.router,
    runs.router,
    logs.router,
    metrics.router,
    sync.router,
    secrets.router,
    settings.router,
    scheduler.router,
    auth.router,
    users.router,
    webhooks.router,
    notifications.router,
    version.router,
]
