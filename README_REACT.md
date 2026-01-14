# React-Frontend Migration

Das Frontend wurde von NiceGUI zu React + TypeScript migriert.

## Quick Start

### Development (Frontend + Backend getrennt)

```bash
# Terminal 1: Backend
docker-compose up orchestrator

# Terminal 2: Frontend
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:3000  
Backend: http://localhost:8000

### Production (Alles in einem Container)

```bash
# Frontend bauen
cd frontend
npm run build

# Docker bauen und starten
docker-compose build
docker-compose up
```

Frontend + Backend: http://localhost:8000

## Development mit Docker Compose

```bash
# Startet Backend + Frontend (Development)
docker-compose -f docker-compose.dev.yaml up
```

Frontend: http://localhost:3000  
Backend: http://localhost:8000

## Status

Siehe `FRONTEND_STATUS.md` für detaillierte Feature-Übersicht.

Grundlegende Struktur ist fertig, aber viele Features aus Phase 13 fehlen noch.
