# Dockerfile für Fast-Flow Orchestrator
#
# Dieses Dockerfile erstellt ein Container-Image für den Orchestrator,
# der Pipeline-Container verwaltet und ausführt.
#
# Multi-Stage Build:
# 1. Stage: React-Frontend bauen
# 2. Stage: Python-Backend mit statischem Frontend

# Stage 1: React-Frontend Build
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

# Frontend-Dependencies installieren
COPY frontend/package.json frontend/package-lock.json* ./
COPY VERSION /app/VERSION

# Verwende npm ci wenn package-lock.json vorhanden, sonst npm install
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Frontend-Code kopieren und bauen
COPY frontend/ ./
RUN npm run build

# Stage 2: Python-Backend
FROM python:3.11-slim

# Metadaten
LABEL maintainer="Fast-Flow Orchestrator"
LABEL description="Workflow-Orchestrierungstool für schnelle, isolierte Pipeline-Ausführungen"

# Arbeitsverzeichnis setzen
WORKDIR /app

# System-Dependencies installieren (für Docker-Client, Git, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python-Dependencies installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# App-Code kopieren
COPY app/ ./app/
COPY alembic.ini .
COPY alembic/ ./alembic/
COPY VERSION .

# Static-Files vom Frontend-Build kopieren
COPY --from=frontend-builder /app/frontend/dist ./static

# Entrypoint: Migrationen, dann uvicorn
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Exponiere Port für FastAPI
EXPOSE 8000

# Health-Check (optional, für Docker Compose)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Zuerst alembic upgrade head, dann uvicorn
CMD ["./entrypoint.sh"]
