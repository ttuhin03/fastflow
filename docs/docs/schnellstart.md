---
sidebar_position: 2
---

# Schnellstart

Fast-Flow in wenigen Minuten starten.

## Voraussetzungen

- **Docker** & Docker Compose  
- **Python 3.11+** (nur für lokale Entwicklung)

## Option 1: Docker (empfohlen für Produktion)

```bash
# 1. .env vorbereiten
cp .env.example .env

# 2. Encryption Key generieren (WICHTIG!)
# Füge den ausgegebenen Key unter ENCRYPTION_KEY in .env ein.
# Für Login: GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, INITIAL_ADMIN_EMAIL (siehe Login-Abschnitt).
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 3. Starten
docker-compose up -d

# 4. Logs ansehen
docker-compose logs -f orchestrator
```

**UI:** [http://localhost:8000](http://localhost:8000)

## Option 2: Lokal (für Entwicklung)

```bash
# 1. Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Konfiguration
cp .env.example .env
# -> ENCRYPTION_KEY in .env setzen

# 3. Starten
./start-dev.sh
# oder: uvicorn app.main:app --reload (Backend); cd frontend && npm run dev (Frontend)
```

## Login (GitHub OAuth, Google OAuth)

1. **GitHub:** OAuth-App (Settings → Developer settings → OAuth Apps), Callback `{BASE_URL}/api/auth/github/callback`.  
   **Google:** OAuth-Client (Google Cloud Console), Callback `{BASE_URL}/api/auth/google/callback`.
2. In **`.env`:** `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` und/oder `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`; `INITIAL_ADMIN_EMAIL` (E-Mail für ersten Admin).
3. **Docker (alles :8000):** `FRONTEND_URL` weglassen oder `=http://localhost:8000`, `BASE_URL=http://localhost:8000`.  
   **Dev (Frontend :3000, Backend :8000):** `FRONTEND_URL=http://localhost:3000`, `BASE_URL=http://localhost:8000`.

:::tip
Ausführliche Schritte, Einladung, Konto verknüpfen: [OAuth (GitHub & Google)](https://github.com/ttuhin03/fastflow/blob/main/docs/oauth/README.md) im Haupt-Repo.
:::

## Nächste Schritte

- Pipelines über `pipelines/` (Volume) oder Git-Sync hinzufügen
- [Pipeline-Template](https://github.com/ttuhin03/fastflow-pipeline-template) für eine vorgefertigte Struktur nutzen
