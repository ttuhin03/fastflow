# Quick Start Guide

## Zwei Start-Optionen

### Option 1: Docker (empfohlen für Produktion)

```bash
# 1. .env-Datei erstellen (falls nicht vorhanden)
cp .env.example .env
# ENCRYPTION_KEY in .env setzen!

# 2. Mit Docker Compose starten
# Startet automatisch: Orchestrator + Docker Socket Proxy
docker-compose up -d

# 3. Logs ansehen
docker-compose logs -f orchestrator
# Oder Proxy-Logs:
docker-compose logs -f docker-proxy
```

**Hinweis**: Fast-Flow nutzt einen Docker Socket Proxy für sichere Docker-API-Kommunikation. Der Proxy-Service läuft automatisch mit und filtert Docker-Operationen.

**UI öffnen:** `http://localhost:8000`

### Option 2: Lokal (für Entwicklung)

```bash
# 1. Setup ausführen
./start.sh

# 2. Anwendung starten
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**UI öffnen:** `http://localhost:8000`

**Login (beide Optionen):**
- Benutzername: `admin`
- Passwort: `admin`

## Test-Pipelines ausführen

1. **Dashboard öffnen** (`http://localhost:8000/`)
2. **Pipeline starten:**
   - Klicke auf "Starten" bei `test_simple`
   - Beobachte den Run-Status
3. **Run-Details ansehen:**
   - Klicke auf den Run
   - Sieh dir Live-Logs an
   - Prüfe Metrics (CPU/RAM)

## UI-Funktionen testen

### Dashboard
- Pipeline-Übersicht mit Statistiken
- Pipeline-Start-Button
- Git-Sync-Button

### Run-Historie (`/runs`)
- Alle Runs anzeigen
- Nach Pipeline/Status filtern
- Run-Details öffnen

### Run-Details (`/runs/{id}`)
- Live-Logs (für laufende Runs)
- CPU/RAM Metrics
- Cancel-Button (laufende Runs)
- Retry-Button (fehlgeschlagene Runs)

### Secrets (`/secrets`)
- Secrets hinzufügen/bearbeiten/löschen
- Secret vs. Parameter-Flag

### Scheduler (`/scheduler`)
- Jobs erstellen/bearbeiten/löschen
- Cron- oder Interval-Trigger

### Git Sync (`/sync`)
- Manueller Sync-Trigger
- Git-Status anzeigen

### Pipelines (`/pipelines`)
- Pipeline-Details
- Statistiken anzeigen/zurücksetzen
- Resource-Limits anzeigen

## Troubleshooting

### "Docker läuft nicht"
```bash
# Starte Docker Desktop (macOS/Windows)
# Oder: sudo systemctl start docker (Linux)
```

### "Docker-Proxy nicht erreichbar" / "403 Forbidden"
```bash
# Prüfe ob docker-proxy Service läuft:
docker-compose ps docker-proxy

# Prüfe Proxy-Logs:
docker-compose logs docker-proxy

# Stelle sicher, dass Proxy-Konfiguration korrekt ist:
# CONTAINERS=1, POST=1, VOLUMES=1 müssen gesetzt sein
# Siehe docker-compose.yaml für Details
```

### "Container-Erstellung fehlgeschlagen"
```bash
# Prüfe Proxy-Konfiguration in docker-compose.yaml
# WICHTIG: POST=1 muss gesetzt sein für Container-Erstellung
# Prüfe Orchestrator-Logs für detaillierte Fehlermeldungen:
docker-compose logs orchestrator | grep -i "infrastructure\|403\|forbidden"
```

### "Port 8000 belegt"
```bash
# Ändere Port in .env:
PORT=8001
```

### "ModuleNotFoundError"
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### "ENCRYPTION_KEY fehlt"
```bash
# Generiere neuen Key:
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Füge ihn in .env ein
```

## Weitere Hilfe

Siehe `START_ANLEITUNG.md` für detaillierte Anleitung.
