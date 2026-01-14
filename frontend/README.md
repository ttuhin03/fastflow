# Fast-Flow Frontend

React + TypeScript Frontend für Fast-Flow Orchestrator.

## Development

```bash
cd frontend
npm install
npm run dev
```

Das Frontend läuft auf http://localhost:3000 und nutzt einen Proxy für API-Requests.

## Build

```bash
npm run build
```

Der Build wird in `../static` erstellt und wird vom FastAPI-Backend serviert.

## Production

Im Docker-Container wird das Frontend automatisch gebaut und vom Backend serviert.
