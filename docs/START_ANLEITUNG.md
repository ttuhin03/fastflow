# Fast-Flow Orchestrator - Start-Anleitung

Diese Anleitung erklärt, wie du die Fast-Flow Orchestrator Anwendung startest und die UI testest.

## Voraussetzungen

1. **Docker** muss installiert und laufen
   ```bash
   docker ps  # Sollte ohne Fehler funktionieren
   ```

2. **Python 3.11+** muss installiert sein
   ```bash
   python3 --version
   ```

3. **Git** (optional, für Git-Sync)

## Schnellstart

### 1. Virtuelles Environment erstellen (empfohlen)

```bash
cd /Users/tuhin/cursor_repos/fastflow
python3 -m venv venv
source venv/bin/activate  # Auf Windows: venv\Scripts\activate
```

### 2. Dependencies installieren

```bash
pip install -r requirements.txt
```

### 3. .env-Datei erstellen

Die `.env`-Datei sollte bereits existieren. Falls nicht, kopiere `.env.example` zu `.env`:

```bash
cp .env.example .env
```

**WICHTIG:** Der `ENCRYPTION_KEY` muss gesetzt werden! Generiere einen neuen Key:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Füge den generierten Key in die `.env`-Datei ein:
```
ENCRYPTION_KEY=dein-generierter-key-hier
```

### 4. Verzeichnisse erstellen

Die Verzeichnisse werden automatisch erstellt, aber du kannst sie auch manuell erstellen:

```bash
mkdir -p pipelines logs data data/uv_cache
```

### 5. Datenbank initialisieren (Alembic Migrationen)

```bash
alembic upgrade head
```

### 6. Anwendung starten

**Option A: Mit Docker Compose (empfohlen für Produktion)**

```bash
# Automatisches Setup und Start
./start-docker.sh

# Oder manuell:
docker-compose up -d

# Logs ansehen
docker-compose logs -f orchestrator

# Container stoppen
docker-compose down
```

**Option B: Direkt mit Python (für Entwicklung)**

```bash
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Vorteile Docker:**
- ✅ Isolierte Umgebung
- ✅ Keine lokalen Dependencies nötig
- ✅ Einfaches Deployment
- ✅ Automatischer Restart bei Fehlern

**Vorteile Lokal:**
- ✅ Hot-Reload für Entwicklung
- ✅ Einfacheres Debugging
- ✅ Schnellere Startzeit

### 7. UI öffnen

Öffne deinen Browser und gehe zu:
```
http://localhost:8000
```

**Standard-Login:**
- Benutzername: `admin`
- Passwort: `admin`

⚠️ **WICHTIG:** Ändere die Standard-Credentials in Produktion!

## Test-Pipelines

Es gibt bereits Test-Pipelines im `pipelines/` Verzeichnis:

- `test_simple/` - Einfache Pipeline ohne Dependencies
- `test_with_requirements/` - Pipeline mit requirements.txt
- `test_failing/` - Pipeline die fehlschlägt (für Tests)

## UI-Funktionen testen

### 1. Dashboard (Hauptseite)

- **URL:** `http://localhost:8000/`
- **Funktionen:**
  - Pipeline-Übersicht mit Statistiken
  - Pipeline-Start-Button
  - Git-Sync-Button
  - Quick-Actions (Details, Runs)

**Test:**
1. Öffne das Dashboard
2. Klicke auf "Starten" bei einer Pipeline
3. Beobachte den Run-Status

### 2. Run-Historie

- **URL:** `http://localhost:8000/runs`
- **Funktionen:**
  - Tabelle mit allen Runs
  - Filterung nach Pipeline-Name und Status
  - Klick auf Run öffnet Details

**Test:**
1. Öffne die Run-Historie
2. Filtere nach einer Pipeline
3. Klicke auf einen Run für Details

### 3. Run-Details

- **URL:** `http://localhost:8000/runs/{run_id}`
- **Funktionen:**
  - Alle Run-Informationen
  - Live-Logs (für laufende Runs)
  - Metrics (CPU/RAM)
  - Cancel-Button (für laufende Runs)
  - Retry-Button (für fehlgeschlagene Runs)

**Test:**
1. Starte eine Pipeline
2. Öffne die Run-Details
3. Beobachte Live-Logs
4. Prüfe Metrics

### 4. Secrets Management

- **URL:** `http://localhost:8000/secrets`
- **Funktionen:**
  - Secrets auflisten
  - Neues Secret hinzufügen
  - Secret bearbeiten
  - Secret löschen

**Test:**
1. Öffne Secrets-Seite
2. Füge ein neues Secret hinzu (z.B. `API_KEY` = `test123`)
3. Bearbeite das Secret
4. Lösche das Secret

### 5. Scheduler

- **URL:** `http://localhost:8000/scheduler`
- **Funktionen:**
  - Jobs auflisten
  - Neuen Job erstellen
  - Job bearbeiten/löschen

**Test:**
1. Öffne Scheduler-Seite
2. Erstelle einen neuen Job:
   - Pipeline: `test_simple`
   - Trigger-Typ: `CRON`
   - Trigger-Wert: `*/5 * * * *` (alle 5 Minuten)
3. Prüfe ob der Job in der Liste erscheint

### 6. Git Sync

- **URL:** `http://localhost:8000/sync`
- **Funktionen:**
  - Git-Status anzeigen
  - Manueller Sync-Trigger
  - Sync-Status

**Test:**
1. Öffne Git-Sync-Seite
2. Klicke auf "Sync ausführen"
3. Beobachte den Sync-Status

### 7. Pipeline-Management

- **URL:** `http://localhost:8000/pipelines`
- **Funktionen:**
  - Pipeline-Übersicht
  - Pipeline-Details
  - Statistiken anzeigen/zurücksetzen

**Test:**
1. Öffne Pipelines-Seite
2. Klicke auf "Details" bei einer Pipeline
3. Prüfe Statistiken
4. Setze Statistiken zurück

## Troubleshooting

### Problem: "Docker-Socket nicht erreichbar"

**Lösung:**
```bash
# Prüfe ob Docker läuft
docker ps

# Falls nicht, starte Docker
# Auf macOS: Öffne Docker Desktop
```

### Problem: "ENCRYPTION_KEY nicht gesetzt"

**Lösung:**
1. Generiere einen neuen Key:
   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
2. Füge den Key in `.env` ein:
   ```
   ENCRYPTION_KEY=dein-key-hier
   ```

### Problem: "ModuleNotFoundError"

**Lösung:**
```bash
# Aktiviere virtuelles Environment
source venv/bin/activate

# Installiere Dependencies
pip install -r requirements.txt
```

### Problem: "Port 8000 bereits belegt"

**Lösung:**
```bash
# Ändere Port in .env
PORT=8001

# Oder beende den Prozess auf Port 8000
lsof -ti:8000 | xargs kill
```

### Problem: "Datenbank-Fehler"

**Lösung:**
```bash
# Führe Migrationen aus
alembic upgrade head

# Falls das nicht hilft, lösche die Datenbank und starte neu
rm -f data/fastflow.db
alembic upgrade head
```

### Problem: "UI lädt nicht / Login funktioniert nicht"

**Lösung:**
1. Prüfe ob die Anwendung läuft:
   ```bash
   curl http://localhost:8000/health
   ```
2. Prüfe die Logs:
   ```bash
   # Im Terminal wo die App läuft
   # Oder in Docker:
   docker-compose logs orchestrator
   ```

## Entwicklung

### Hot-Reload aktivieren

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Logs anzeigen

```bash
# Application-Logs (im Terminal)
# Oder in Docker:
docker-compose logs -f orchestrator
```

### Datenbank zurücksetzen

```bash
rm -f data/fastflow.db
alembic upgrade head
```

## Nächste Schritte

1. **Test-Pipelines ausführen:**
   - Starte `test_simple` über die UI
   - Beobachte Logs und Metrics

2. **Eigene Pipeline erstellen:**
   - Erstelle ein neues Verzeichnis in `pipelines/`
   - Füge `main.py` hinzu
   - Optional: `requirements.txt` und `pipeline.json`

3. **Secrets konfigurieren:**
   - Füge Secrets für deine Pipelines hinzu
   - Verwende Secrets in Pipelines via `os.getenv()`

4. **Scheduler einrichten:**
   - Erstelle geplante Jobs für regelmäßige Ausführung

## Support

Bei Problemen:
1. Prüfe die Logs
2. Prüfe die `.env`-Konfiguration
3. Prüfe ob Docker läuft
4. Prüfe ob alle Dependencies installiert sind
