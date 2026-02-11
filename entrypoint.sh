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

# PIPELINES_HOST_DIR automatisch aus mountinfo ermitteln (für Pipeline-Worker)
if [ -z "${PIPELINES_HOST_DIR}" ]; then
  LINE=$(grep " /app/pipelines " /proc/self/mountinfo 2>/dev/null | head -1)
  if [ -n "$LINE" ]; then
    ROOT=$(echo "$LINE" | awk '{print $4}')
    AFTER_DASH=$(echo "$LINE" | sed 's/.* - //')
    DEVICE=$(echo "$AFTER_DASH" | awk '{print $2}')
    if [ -n "$ROOT" ]; then
      if [ -n "$DEVICE" ] && [ "${DEVICE#/dev/}" != "$DEVICE" ]; then
        # Device ist Block-Device (/dev/...): Root ist Pfad im FS, mount point ist /
        PIPELINES_HOST_DIR="/${ROOT#/}"
      else
        # Device ist Verzeichnispfad: Device + Root
        PIPELINES_HOST_DIR="${DEVICE%/}/${ROOT#/}"
      fi
      export PIPELINES_HOST_DIR
      echo "[entrypoint] PIPELINES_HOST_DIR auto-detected: $PIPELINES_HOST_DIR"
    fi
  fi
fi

echo "[entrypoint] Starting Fast-Flow..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
