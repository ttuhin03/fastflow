# Migration von NiceGUI zu React

Die Anwendung wurde von NiceGUI zu React + TypeScript migriert.

## Änderungen

### Backend
- **NiceGUI entfernt**: `nicegui` wurde aus `requirements.txt` entfernt
- **CORS konfiguriert**: FastAPI hat jetzt CORS-Middleware für React-Frontend
- **Static-Files-Serving**: FastAPI serviert jetzt das gebaute React-Frontend
- **API-Präfix**: Alle API-Endpoints haben jetzt `/api`-Präfix

### Frontend
- **React + TypeScript**: Neues Frontend mit Vite
- **React Router**: Client-side Routing
- **React Query**: Für API-Requests und Caching
- **Axios**: HTTP-Client mit Interceptors für Auth

## Development Setup

### Frontend Development
```bash
cd frontend
npm install
npm run dev
```

Frontend läuft auf http://localhost:3000 mit Proxy zu Backend auf Port 8000.

### Backend Development
```bash
# Backend läuft wie gewohnt
uvicorn app.main:app --reload
```

Backend läuft auf http://localhost:8000

## Production Build

### Frontend bauen
```bash
cd frontend
npm run build
```

Der Build wird in `../static` erstellt.

### Docker Build
Das Dockerfile baut automatisch das Frontend und serviert es vom Backend:

```bash
docker-compose build
docker-compose up
```

## API-Änderungen

Alle API-Endpoints haben jetzt `/api`-Präfix:
- `/api/pipelines` statt `/pipelines`
- `/api/runs` statt `/runs`
- `/api/auth/login` statt `/auth/login`
- etc.

Das Frontend nutzt automatisch den `/api`-Präfix über den konfigurierten API-Client.

## Vorteile

1. **Keine Slot-Kontext-Probleme**: React hat keine Background-Task-Probleme
2. **Bessere Performance**: Client-side Rendering
3. **Modernes Frontend**: React + TypeScript
4. **Bessere Developer Experience**: Hot Reload, TypeScript, etc.
5. **Trennung von Frontend/Backend**: Klare Architektur
