# Dockerfile für Fast-Flow Orchestrator
#
# Dieses Dockerfile erstellt ein Container-Image für den Orchestrator,
# der Pipeline-Container verwaltet und ausführt.
#
# Multi-Stage Build:
# 1. Stage: React-Frontend bauen
# 2. Stage: Python-Backend mit statischem Frontend

# Stage 1: React-Frontend Build
# Nutzt npm workspaces (Root package-lock.json) für konsistente Dependencies
FROM node:20-slim AS frontend-builder

WORKDIR /app
COPY package.json package-lock.json ./
COPY frontend/package.json ./frontend/
COPY VERSION ./VERSION

# VITE_DOCS_URL für Doku-Link (default: Doku auf Port 3001)
ARG VITE_DOCS_URL=http://localhost:3001
ENV VITE_DOCS_URL=$VITE_DOCS_URL

# Frontend-Workspace installieren (inkl. Test-Deps für Build-Toolchain)
RUN npm ci --workspace=fastflow-frontend

# Frontend-Code kopieren und bauen
COPY frontend/ ./frontend/
RUN npm run build --workspace=fastflow-frontend

# Stage 2: Python-Backend (Bookworm = stable Debian, zuverlässigere Mirrors als trixie)
FROM python:3.11-slim-bookworm

# Metadaten
LABEL maintainer="Fast-Flow Orchestrator"
LABEL description="Workflow-Orchestrierungstool für schnelle, isolierte Pipeline-Ausführungen"

# Arbeitsverzeichnis setzen
WORKDIR /app

# System-Dependencies installieren (mit Retry bei transienten Netzwerkfehlern)
RUN for i in 1 2 3; do \
    (apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*) && break; \
    sleep 10; \
    done

# Python-Dependencies installieren (inkl. uv für Pre-Heating: uv pip compile)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir uv


# App-Code kopieren
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY alembic.ini .
COPY alembic/ ./alembic/
COPY VERSION .

# Static-Files vom Frontend-Build kopieren
COPY --from=frontend-builder /app/frontend/dist ./static

# Pipelines (werden bei ENVIRONMENT=development in leeres /app/pipelines kopiert)
COPY pipelines/ ./pipelines-seed/

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
