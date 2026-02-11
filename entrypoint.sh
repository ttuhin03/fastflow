#!/bin/bash
set -e

echo "[entrypoint] Initializing database and running migrations..."
python scripts/init_db_for_migrations.py

# Bei Entwicklung: Pipelines aus Image ins leere pipelines-Verzeichnis kopieren
if [ "${ENVIRONMENT:-production}" = "development" ]; then
  if [ -d /app/pipelines-seed ] && [ -z "$(ls -A /app/pipelines 2>/dev/null)" ]; then
    echo "[entrypoint] Dev mode: copying pipelines to /app/pipelines"
    cp -r /app/pipelines-seed/. /app/pipelines/
  fi
fi

echo "[entrypoint] Starting Fast-Flow..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
