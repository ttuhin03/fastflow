# Dockerfile für Fast-Flow Orchestrator
#
# Dieses Dockerfile erstellt ein Container-Image für den Orchestrator,
# der Pipeline-Container verwaltet und ausführt.
#
# Basis-Image: Python 3.11 (slim)
# Dependencies: Aus requirements.txt installiert
# Entry-Point: uvicorn mit FastAPI-App

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

# Exponiere Port für FastAPI/NiceGUI
EXPOSE 8000

# Health-Check (optional, für Docker Compose)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Entry-Point: uvicorn mit FastAPI-App
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
