#!/bin/bash
set -e

echo "[entrypoint] Initializing database and running migrations..."
python scripts/init_db_for_migrations.py

echo "[entrypoint] Starting Fast-Flow..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
