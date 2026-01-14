# Fast-Flow Orchestrator - Implementierungsplan

## Phase 1: Projekt-Grundgerüst

### 1.1 Projektstruktur
```
fastflow/
├── README.md
├── plan.md
├── docker-compose.yaml
├── Dockerfile
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI App + NiceGUI Integration
│   ├── database.py          # SQLModel Setup
│   ├── models.py            # PipelineRun, ScheduledJob, Secret Models
│   ├── config.py            # Konfiguration (Environment-Variablen)
│   ├── executor.py          # Docker Container Execution
│   ├── scheduler.py         # APScheduler Integration
│   ├── git_sync.py          # Git Synchronization
│   ├── secrets.py           # Secrets Management
│   ├── pipeline_discovery.py # Pipeline Discovery & Validierung
│   ├── auth.py              # Authentication (Basic Login)
│   ├── ui.py                # NiceGUI UI Components
│   └── api/
│       ├── __init__.py
│       ├── pipelines.py     # Pipeline Endpoints
│       ├── runs.py          # Run Management
│       ├── logs.py          # Log Streaming (SSE)
│       ├── sync.py          # Git Sync Endpoint
│       ├── scheduler.py     # Scheduler Endpoints
│       └── auth.py          # Auth Endpoints
├── pipelines/               # Git-Repo (wird gemountet)
│   └── .git/
├── logs/                    # Persistent Logs
└── data/                    # SQLite DB
```

### 1.2 Dependencies (requirements.txt)
- fastapi
- uvicorn
- sqlmodel
- docker
- apscheduler
- pydantic
- python-multipart
- nicegui
- alembic (für DB-Migrationen)
- python-dotenv (für .env Konfiguration)
- passlib[bcrypt] (für Password-Hashing)
- python-jose[cryptography] (für JWT/Sessions)
- cryptography (für Secrets-Verschlüsselung mit Fernet)
- PyJWT (für GitHub Apps Authentifizierung)
- requests (für GitHub API-Calls)
- psycopg2-binary (optional, für PostgreSQL-Support)

---

## Phase 2: Datenbank & Models

### 2.1 SQLModel Setup
- [ ] `app/database.py`: SQLModel Engine & Session erstellen
- [ ] **Datenbank-Verbindung** konfigurieren (aus config.py)
  - Standard: SQLite (wenn DATABASE_URL nicht gesetzt)
  - Optional: PostgreSQL (wenn DATABASE_URL gesetzt ist, Format: `postgresql://user:password@host:5432/dbname`)
  - SQLModel unterstützt beide via Connection-String
- [ ] **SQLite Concurrency**: WAL-Mode (Write-Ahead Logging) aktivieren
  - `connect_args={"check_same_thread": False}` für FastAPI setzen
  - WAL-Mode: `PRAGMA journal_mode=WAL` nach Verbindungsaufbau
  - Verhindert "database is locked" Fehler bei parallelen Schreibzugriffen
- [ ] Session-Dependency für FastAPI
- [ ] Alembic Setup für Migrationen (funktioniert mit SQLite und PostgreSQL)
- [ ] Datenbank-Initialisierung beim ersten Start

### 2.2 Models
- [ ] `app/models.py`: Alle Models definieren
  - **Pipeline Model** (Metadaten):
    - pipeline_name (String, Primary Key)
    - has_requirements (Boolean) - Wurde eine requirements.txt gefunden?
    - last_cache_warmup (DateTime, optional) - Zeitstempel des letzten erfolgreichen `uv pip compile`
    - total_runs (Integer, default: 0) - Gesamtanzahl Runs (Zähler, resetbar)
    - successful_runs (Integer, default: 0) - Anzahl erfolgreicher Runs (resetbar)
    - failed_runs (Integer, default: 0) - Anzahl fehlgeschlagener Runs (resetbar)
  - **PipelineRun Model**:
    - id (UUID, Primary Key)
    - pipeline_name (String)
    - status (Enum: PENDING, RUNNING, SUCCESS, FAILED)
    - log_file (String)
    - metrics_file (String, optional) - Pfad zur Metrics-Datei (CPU/RAM über Zeit)
    - env_vars (JSON)
    - parameters (JSON) - normale Parameter
    - uv_version (String, optional) - Die genutzte uv-Version für Reproduzierbarkeit
    - setup_duration (Float, optional) - Zeit in Sekunden, die uv für das Bereitstellen der Umgebung benötigt hat
    - started_at (DateTime)
    - finished_at (DateTime, optional)
    - exit_code (Integer, optional)
  - **ScheduledJob Model**:
    - id (UUID, Primary Key)
    - pipeline_name (String)
    - trigger_type (Enum: CRON, INTERVAL)
    - trigger_value (String) - Cron-Expression oder Interval
    - enabled (Boolean)
    - created_at (DateTime)
  - **Secret Model**:
    - id (UUID, Primary Key)
    - key (String, unique)
    - value (String) - verschlüsselt in DB gespeichert
    - created_at (DateTime)
    - updated_at (DateTime)

---

## Phase 3: Konfiguration

### 3.1 Config-Setup
- [ ] `app/config.py`: Konfiguration aus Environment-Variablen
- [ ] Standardwerte für alle konfigurierbaren Parameter
- [ ] `.env`-File-Support (python-dotenv)
- [ ] Konfigurierbare Parameter:
  - DATABASE_URL (Standard: None → SQLite, Format: postgresql://... für PostgreSQL)
  - PIPELINES_DIR (Standard: ./pipelines)
  - LOGS_DIR (Standard: ./logs)
  - DATA_DIR (Standard: ./data)
  - WORKER_BASE_IMAGE (Standard: ghcr.io/astral-sh/uv:python3.11-bookworm-slim)
  - UV_CACHE_DIR (Standard: ./data/uv_cache)
  - UV_PRE_HEAT (Standard: true - Dependencies beim Git-Sync automatisch laden)
  - MAX_CONCURRENT_RUNS (Standard: 10)
  - CONTAINER_TIMEOUT (Standard: None)
  - RETRY_ATTEMPTS (Standard: 0)
  - GIT_BRANCH (Standard: main)
  - AUTO_SYNC_INTERVAL (Standard: None)
  - LOG_RETENTION_RUNS (Standard: None - unbegrenzt)
  - LOG_RETENTION_DAYS (Standard: None - unbegrenzt)
  - LOG_MAX_SIZE_MB (Standard: None - unbegrenzt)
  - LOG_STREAM_RATE_LIMIT (Standard: 100 - Zeilen pro Sekunde für SSE)
  - ENCRYPTION_KEY (Standard: Muss gesetzt werden - Fernet Key für Secrets-Verschlüsselung)
  - GITHUB_APP_ID (Standard: None - für GitHub Apps Authentifizierung)
  - GITHUB_INSTALLATION_ID (Standard: None - für GitHub Apps Authentifizierung)
  - GITHUB_PRIVATE_KEY_PATH (Standard: None - Pfad zur .pem Datei für GitHub Apps)

---

## Phase 4: Pipeline-Discovery

### 4.1 Pipeline-Discovery
- [ ] `app/pipeline_discovery.py`: Scan des Pipelines-Verzeichnisses
- [ ] Erkennung von Python-Dateien (.py)
- [ ] Pipeline-Validierung (Existenz, Ausführbarkeit)
- [ ] Cache für Pipeline-Liste
- [ ] **Pipeline-Metadaten-JSON**: Erkennung von `pipeline.json` oder `{pipeline_name}.json` im Pipeline-Verzeichnis
  - JSON-Format: `{"cpu_hard_limit": 1.0, "mem_hard_limit": "1g", "cpu_soft_limit": 0.8, "mem_soft_limit": "800m"}`
  - Hard Limits: Werden beim Container-Start gesetzt (mem_limit, nano_cpus)
  - Soft Limits: Werden überwacht, Überschreitung wird im Frontend angezeigt
  - Optional: Falls keine Metadaten-JSON vorhanden, Standard-Limits verwenden
- [ ] **Pipeline-Struktur**: Pipelines werden einfach mit `python pipeline.py` ausgeführt
  - Keine `main()`-Funktion erforderlich (kann aber verwendet werden)
  - Code wird von oben nach unten ausgeführt
  - Bei uncaught Exceptions → Exit-Code != 0 → Status FAILED

---

## Phase 5: Docker Executor

### 5.1 Docker Client Setup (UV-basiert)
- [ ] `app/executor.py`: Docker Client initialisieren
- [ ] Container-Start-Logik mit UV-Worker-Image (`auto_remove=False` - wird manuell entfernt)
- [ ] Container-Befehl: `uv run --with-requirements /app/{pipeline}/requirements.txt /app/{pipeline}/main.py`
- [ ] Container-Labels setzen: `fastflow-run-id={run_id}` für Reconciliation
- [ ] Volume-Mounts konfigurieren:
  - Pipelines-Verzeichnis als `/app` (read-only)
  - UV-Cache-Verzeichnis als `/root/.cache/uv` (read-write, shared)
- [ ] Environment-Variablen-Injection (Secrets + Parameter)
- [ ] **Resource-Limits aus Metadaten-JSON**: Hard Limits (mem_limit, nano_cpus) beim Container-Start setzen
- [ ] UV-Version erfassen und in DB speichern
- [ ] Setup-Duration messen (Zeit für uv-Setup)

### 5.2 Container-Management & Resource-Limits
- [ ] **Hard Limits (Container-Start)**:
  - Resource-Limits aus Pipeline-Metadaten-JSON lesen (oder Standardwerte)
  - Container-Start mit `mem_limit` (z.B. "1g") und `nano_cpus` (CPU * 1e9)
  - `memswap_limit=mem_limit` setzen (verhindert Swapping)
  - Beispiel: `container.run(..., mem_limit="1g", nano_cpus=int(1.0 * 1e9), memswap_limit="1g")`
- [ ] **Soft Limits (Monitoring)**:
  - Soft Limits aus Pipeline-Metadaten-JSON lesen (optional)
  - Soft-Limit-Überschreitung überwachen (CPU/RAM-Usage vs. Soft-Limit)
  - Überschreitung in Metrics-Queue markieren (für UI-Warnung)
- [ ] Concurrency-Limits (max gleichzeitige Container)
  - Wenn Limit erreicht: Neue Pipeline-Starts ablehnen (HTTP 429)
- [ ] Container-Cancellation (`container.stop()`)
- [ ] Timeout-Handling (optional, harter Timeout - Container killen)
- [ ] Status-Polling für Container-Status

### 5.3 Log-Streaming & Persistenz
- [ ] Log-Streaming aus Container
- [ ] Log-Datei-Schreibung in konfiguriertem Logs-Verzeichnis (alle Logs werden geschrieben)
- [ ] Rate-Limited Queue für SSE-Streaming (konfigurierbar, Standard: 100 Zeilen/Sekunde)
- [ ] `container.wait()` für Exit-Code-Abruf
- [ ] Container manuell entfernen nach Log-Speicherung (`container.remove()`)
- [ ] Status-Updates in Datenbank
- [ ] Exit-Code-Erfassung

### 5.4 Container-Metrics-Monitoring (CPU & RAM)
- [ ] Container-Stats-Monitoring in `app/executor.py`
- [ ] Hintergrund-Task für `container.stats(stream=True)` während Container läuft
- [ ] CPU-Usage-Berechnung (Delta-Vergleich aus Docker Stats):
  - CPU-Delta und System-Delta berechnen
  - CPU-Prozentsatz: `(cpu_delta / system_delta) * online_cpus * 100.0`
- [ ] RAM-Usage-Erfassung (in MB):
  - `memory_stats['usage'] / (1024 * 1024)`
  - Memory-Limit erfassen (`memory_stats['limit']`)
- [ ] **Soft-Limit-Überwachung**:
  - CPU-Usage vs. CPU-Soft-Limit vergleichen (wenn gesetzt)
  - RAM-Usage vs. RAM-Soft-Limit vergleichen (wenn gesetzt)
  - Soft-Limit-Überschreitung in Metrics markieren (`soft_limit_exceeded: true`)
  - CPU-Throttling-Erkennung: Wenn CPU-Usage konstant am Hard-Limit klebt
- [ ] Metrics-Speicherung in Datei (JSON-Format, Timestamp-basiert):
  - Datei: `logs/{run_id}_metrics.json` oder `logs/{run_id}_metrics.jsonl`
  - Format: `{"timestamp": "...", "cpu_percent": 45.2, "ram_mb": 128.5, "ram_limit_mb": 512, "soft_limit_exceeded": false}`
  - Metrics werden so lange gespeichert wie Logs (gleiche Retention-Policy)
- [ ] Metrics-Queue für Live-UI-Streaming (ähnlich wie Logs)
- [ ] Metrics-Datei-Pfad in Datenbank speichern (`metrics_file` Feld)
- [ ] Metrics-Speicherung stoppen wenn Container beendet wird

### 5.5 Error-Handling
- [ ] Exit-Code-Auswertung nach Container-Beendigung
- [ ] Exit-Code 0 → Status `SUCCESS`
- [ ] Exit-Code != 0 → Status `FAILED` (Python-Exceptions führen zu Exit-Code != 0)
- [ ] **Spezielle Exit-Code-Erkennung**:
  - Exit-Code 137 → OOM (Out of Memory) Error (Docker hat Container wegen Memory-Limit gekillt)
  - Exit-Code 125/126/127 → Docker/Container-Konfigurationsfehler
    - 125: Docker-Fehler (z.B. Image nicht gefunden, Container-Start fehlgeschlagen)
    - 126: Command nicht ausführbar (z.B. `uv` nicht gefunden im Container)
    - 127: Command nicht gefunden (z.B. `uv run` Befehl fehlgeschlagen)
  - Fehler-Typ in DB markieren (zusätzliches Feld oder Status-Detail)
  - UI soll spezifische Error-Messages anzeigen (OOM, Docker-Error, Command-Error), nicht nur "Failed"
- [ ] Exit-Code in Datenbank speichern
- [ ] Fehler-Logs werden in Log-Datei geschrieben
- [ ] **Pipeline-Statistiken aktualisieren**:
  - `total_runs` +1
  - Bei SUCCESS: `successful_runs` +1
  - Bei FAILED: `failed_runs` +1
  - Statistiken in Pipeline Model aktualisieren

### 5.6 Run-Funktion
- [ ] `run_pipeline(name, env_vars=None, parameters=None)` Funktion
- [ ] PipelineRun-Datensatz erstellen
- [ ] Container starten und überwachen (mit Label `fastflow-run-id`)
- [ ] Status-Updates (RUNNING → SUCCESS/FAILED basierend auf Exit-Code)
- [ ] Retry-Mechanismus (konfigurierbar)

### 5.7 Zombie-Reconciliation (Crash-Recovery)
- [ ] Startup-Reconciler-Funktion in `app/executor.py`
- [ ] Beim App-Start: Scan aller laufenden Docker-Container mit Label `fastflow-run-id`
- [ ] Abgleich mit Datenbank: Container mit Label, die in DB als `RUNNING` stehen
- [ ] Re-attach zu laufenden Containern: Log-Stream wieder aufnehmen
- [ ] Integration in FastAPI Startup-Event (in `app/main.py`)

### 5.8 Container-Health-Checks
- [ ] Health-Check-Funktion in `app/executor.py` für laufende Container
- [ ] Periodisches Health-Check-Polling (konfigurierbares Intervall, z.B. alle 30 Sekunden)
- [ ] Container-Status prüfen: `container.status` und `container.attrs['State']['Health']` (falls Health-Check konfiguriert)
- [ ] Erkennung von hängenden/abgestürzten Containern:
  - Container läuft, aber produziert keine Logs mehr (Timeout-basiert)
  - Container-Status ist "unhealthy" (wenn Health-Check konfiguriert)
- [ ] Automatische Behandlung ungesunder Container:
  - Status in DB auf `FAILED` setzen
  - Container stoppen/killen bei Bedarf
  - Fehler-Log erstellen
- [ ] Health-Check-Metriken in Datenbank speichern (optional, für Monitoring)
- [ ] API-Endpoint: `GET /runs/{run_id}/health` für manuelle Health-Check-Abfrage
- [ ] UI-Anzeige: Health-Status in Run-Detailansicht

---

## Phase 6: FastAPI Endpoints

### 6.1 Health-Check
- [ ] `GET /health`: Status-Endpoint für Monitoring

### 6.2 Pipeline Management
- [ ] `GET /pipelines`: Liste aller verfügbaren Pipelines (via Discovery, inkl. Statistiken)
- [ ] `POST /pipelines/{name}/run`: Pipeline manuell starten (mit optionalen Parametern)
- [ ] `GET /pipelines/{name}/runs`: Historie eines Pipeline-Runs
- [ ] `GET /pipelines/{name}/stats`: Pipeline-Statistiken abrufen (total_runs, successful_runs, failed_runs)
- [ ] `POST /pipelines/{name}/stats/reset`: Pipeline-Statistiken zurücksetzen (total_runs, successful_runs, failed_runs auf 0 setzen)

### 6.3 Run Management
- [ ] `GET /runs`: Alle Runs anzeigen (mit Filterung)
- [ ] `GET /runs/{run_id}`: Details eines Runs
- [ ] `POST /runs/{run_id}/cancel`: Run abbrechen (Container stoppen)

### 6.4 Log Streaming (SSE)
- [ ] `GET /runs/{run_id}/logs`: Logs aus Datei lesen
- [ ] `GET /runs/{run_id}/logs/stream`: Server-Sent Events für Live-Logs
- [ ] **Backend: asyncio.Queue** für Log-Zeilen (pro Run-ID eine Queue)
  - Docker-Client schiebt jede neue Log-Zeile in die Queue
- [ ] **Rate-Limiting für SSE**: Maximal X Zeilen pro Sekunde an Frontend senden (konfigurierbar, Standard: 100)
  - Alle Logs werden in Datei geschrieben (vollständig)
  - SSE-Streaming ist rate-limited, um Memory-Probleme bei großen Log-Outputs zu vermeiden
- [ ] Event-Format: `data: {json}\n\n`

### 6.5 Metrics Endpoints (CPU & RAM)
- [ ] `GET /runs/{run_id}/metrics`: Metrics aus Datei lesen (für abgeschlossene Runs)
- [ ] `GET /runs/{run_id}/metrics/stream`: Server-Sent Events für Live-Metrics
- [ ] **Backend: asyncio.Queue** für Metrics (pro Run-ID eine Queue)
  - Container-Stats werden in Queue geschoben (CPU %, RAM MB)
- [ ] Metrics-Format: `{"timestamp": "...", "cpu_percent": 45.2, "ram_mb": 128.5, "ram_limit_mb": 512}`
- [ ] Event-Format für SSE: `data: {json}\n\n`

### 6.6 Git Sync (mit UV Pre-Heating)
- [ ] `POST /sync`: Git Pull ausführen (mit Branch-Auswahl)
- [ ] `GET /sync/status`: Git-Status anzeigen
- [ ] Konflikt-Handling (Remote-Version übernehmen)
- [ ] Branch-Auswahl-Unterstützung
- [ ] Auto-Sync-Setup (optional, konfigurierbar)
- [ ] Requirements.txt-Erkennung (Discovery)
- [ ] **UV Pre-Heating (Warming)** - Wenn UV_PRE_HEAT=true:
  - Step 1: Git Pull (Aktualisierung des Codes)
  - Step 2: Discovery (Suche nach allen requirements.txt)
  - Step 3: Pre-Heating: Für jede neue/geänderte requirements.txt
    - Hintergrund-Job: `uv pip compile requirements.txt` (lädt alle Pakete in Host-Cache)
    - Status-Update in DB: `last_cache_warmup` aktualisieren
    - UI-Status: "Pipeline bereit (Cached)"
  - Fehlerbehandlung: Fehlgeschlagene Pre-Heats in UI anzeigen
- [ ] **Git-Authentifizierung: GitHub Apps**
  - Funktion `get_github_app_token()` in `app/git_sync.py`
  - JWT erstellen (mit Private Key signiert, RS256)
  - Installation Access Token von GitHub API anfordern
  - **Token-Caching**: In-Memory Cache für Installation Access Token (Token ist 1 Stunde gültig)
  - Token nur kurz vor Ablauf erneuern (verhindert Rate-Limit-Throttling bei vielen Syncs)
  - Token in Git-Befehlen verwenden: `git clone https://x-access-token:TOKEN@github.com/...`
  - Konfiguration: GITHUB_APP_ID, GITHUB_INSTALLATION_ID, GITHUB_PRIVATE_KEY_PATH

---

## Phase 7: Secrets Management

### 7.1 Secrets-Verschlüsselung in DB
- [ ] `app/secrets.py`: Verschlüsselungs-Funktionen implementieren
  - `encrypt(plain_text)` - Verschlüsselt Text mit Fernet (cryptography)
  - `decrypt(cipher_text)` - Entschlüsselt Text
  - ENCRYPTION_KEY aus config.py verwenden (aus .env)
- [ ] Fernet-Key aus ENCRYPTION_KEY Environment-Variable generieren
- [ ] Verschlüsselung bei Speicherung, Entschlüsselung bei Abruf
- [ ] **Wichtig**: Secrets werden verschlüsselt in der Datenbank gespeichert (von Anfang an implementiert, keine Migration nötig)

### 7.2 Secrets Storage
- [ ] Secret-Model in Datenbank (bereits in Phase 2.2, value wird verschlüsselt gespeichert)
- [ ] `GET /secrets`: Alle Secrets auflisten (Values entschlüsselt zurückgeben)
- [ ] `POST /secrets`: Secret speichern (Value vor Speicherung verschlüsseln)
- [ ] `PUT /secrets/{key}`: Secret aktualisieren (Value vor Speicherung verschlüsseln)
- [ ] `DELETE /secrets/{key}`: Secret löschen

### 7.3 Pipeline-Parameter
- [ ] Unterschied zwischen Secrets und Parametern
- [ ] Flag in UI zur Unterscheidung (Secret vs. Parameter)
- [ ] Parameter-Übergabe beim Pipeline-Start
- [ ] Secrets und Parameter als Environment-Variablen

### 7.4 Integration in Executor
- [ ] Secrets bei Pipeline-Start abrufen
- [ ] Parameter bei Pipeline-Start abrufen
- [ ] Als Environment-Variablen injizieren

---

## Phase 8: Scheduler

### 8.1 APScheduler Setup
- [ ] `app/scheduler.py`: BackgroundScheduler initialisieren
- [ ] Scheduler beim App-Start starten
- [ ] Scheduler beim App-Shutdown stoppen
- [ ] Job-Persistenz: Jobs beim Start aus DB laden und registrieren

### 8.2 Job-Model
- [ ] ScheduledJob Model (bereits in Phase 2.2 definiert)
- [ ] Job-API-Endpoints in `app/api/scheduler.py`:
  - `GET /scheduler/jobs`: Alle Jobs auflisten
  - `POST /scheduler/jobs`: Job erstellen
  - `PUT /scheduler/jobs/{id}`: Job aktualisieren
  - `DELETE /scheduler/jobs/{id}`: Job löschen

### 8.3 Scheduler-Logik
- [ ] Jobs beim App-Start aus Datenbank laden
- [ ] Aktive Jobs beim Scheduler registrieren
- [ ] Cron-Trigger unterstützen
- [ ] Interval-Trigger unterstützen
- [ ] Job-Ausführung via `run_pipeline()`
- [ ] Job-Enable/Disable-Funktionalität
- [ ] Pipeline-Validierung beim Job-Start (prüfen ob Pipeline existiert)
- [ ] Warnung beim Pipeline-Löschen (wenn Jobs existieren oder Pipeline läuft)
- [ ] Container-Stop bei Pipeline-Löschung während Lauf

---

## Phase 9: Authentication

### 9.1 Basic Authentication
- [ ] `app/auth.py`: Basic Login-Implementierung
- [ ] User-Model (optional, erstmal einfache Konfiguration)
- [ ] Password-Hashing (passlib)
- [ ] Session-Management (JWT oder Session-Cookies)
- [ ] Login-Endpoint: `POST /auth/login`
- [ ] Logout-Endpoint: `POST /auth/logout`
- [ ] Protected Routes (Dependency für FastAPI)
- [ ] **⚠️ KRITISCH**: Authentifizierung ist der wichtigste Schutz gegen Docker-Socket-Missbrauch
  - UI darf NIEMALS ohne Login erreichbar sein (Docker-Socket = Root-Zugriff auf Host)
- [ ] **Sicherheits-Zusatz-Tipp**: Für Internet-Deployment: Reverse-Proxy (Nginx/Traefik) mit HTTPS vor den Orchestrator
  - HTTPS erzwingen (unverschlüsseltes HTTP ist Sicherheitsrisiko bei Docker-Socket-Zugriff)
  - In docker-compose.yaml oder separater Konfiguration dokumentieren

### 9.2 UI-Integration
- [ ] Login-Seite in NiceGUI
- [ ] Session-Persistenz
- [ ] Microsoft OAuth (Zukunftsplan, später)

---

## Phase 10: Docker Setup

### 10.1 Dockerfile
- [ ] Dockerfile für Orchestrator
- [ ] Python 3.11 Base Image
- [ ] Dependencies installieren
- [ ] App-Code kopieren

### 10.2 Docker-Compose
- [ ] `docker-compose.yaml` erstellen
- [ ] Docker-Socket-Mount (`/var/run/docker.sock`)
- [ ] Volume-Mounts (pipelines, logs, data, uv_cache) - konfigurierbar
  - UV-Cache-Verzeichnis: `/data/uv_cache` (shared zwischen allen Containers)
- [ ] Environment-Variablen (aus .env oder direkt)
- [ ] **⚠️ Security-Hinweis dokumentieren**: Docker-Socket gibt Root-Zugriff auf Host-System
  - Authentifizierung (Phase 9) ist KRITISCH für Security
  - User Namespaces als optionaler zusätzlicher Schutz
  - **Für Internet-Deployment**: Reverse-Proxy (Nginx/Traefik) mit HTTPS vor den Orchestrator (siehe Phase 9.1)
- [ ] **Hinweis**: Worker-Image (`WORKER_BASE_IMAGE`) muss nicht gebaut werden, wird von Registry gepullt

---

## Phase 11: Log-Management & Cleanup

### 11.1 Log-Rotation & Cleanup
- [ ] Log-Cleanup-Service (Background-Task)
- [ ] Implementierung von LOG_RETENTION_RUNS (älteste Runs pro Pipeline löschen)
- [ ] Implementierung von LOG_RETENTION_DAYS (Logs älter als X Tage löschen)
- [ ] Implementierung von LOG_MAX_SIZE_MB (Log-Dateien größer als X MB kürzen/löschen)
- [ ] Cleanup beim Pipeline-Run-Abschluss oder periodisch
- [ ] **Metrics-Cleanup**: Metrics-Dateien zusammen mit Log-Dateien löschen (gleiche Retention-Policy)
- [ ] **Datenbank-Cleanup**: Beim Löschen von Log-Dateien auch Datenbank-Einträge bereinigen
  - `log_file` und `metrics_file` Felder auf NULL setzen (oder Einträge löschen)
  - Verhindert "Broken Links" in der UI (UI versucht auf nicht-existierende Dateien zuzugreifen)

---

## Phase 12: Testing & Validation

### 12.1 Test-Pipelines
- [ ] Beispiel-Pipeline erstellen
- [ ] Requirements.txt-Beispiel
- [ ] Verschiedene Pipeline-Typen testen

### 12.2 Integration Tests
- [ ] Pipeline-Start testen
- [ ] Log-Streaming testen
- [ ] Git-Sync testen
- [ ] Scheduler testen
- [ ] Container-Cancellation testen
- [ ] Concurrency-Limits testen
- [ ] Log-Cleanup testen

---

## Phase 13: Frontend mit NiceGUI

### 13.1 NiceGUI Integration
- [ ] NiceGUI in FastAPI integrieren (Mount oder separater Server)
- [ ] `app/ui.py`: Haupt-UI-Struktur erstellen
- [ ] Navigation/Layout-Setup (Header, Sidebar, Content)

### 13.2 Dashboard-Seite
- [ ] Pipeline-Übersicht mit Liste aller verfügbaren Pipelines
- [ ] Pipeline-Start-Button für jede Pipeline
- [ ] Pipeline-Status-Anzeige mit Details:
  - Anzahl Runs (gesamt, erfolgreich, fehlgeschlagen) - aus Pipeline-Statistiken
  - Erfolgsrate (successful_runs / total_runs)
  - Letzter Run-Status und Zeitstempel
  - Laufende Runs (Live-Status)
  - Cache-Status (UV Pre-Heating: "Cached" oder "Nicht cached")
  - Pipeline aktiv/inaktiv Status
  - Resource-Limits (Hard Limits: CPU, RAM) - kompakt angezeigt
- [ ] Pipeline-An/Ausschalten-Toggle (Pipeline aktivieren/deaktivieren)
- [ ] Git-Sync-Button (manueller Sync-Trigger)
- [ ] Git-Sync-Status-Anzeige (letzter Sync-Zeitpunkt, Sync-Status)
- [ ] Quick-Actions: Pipeline starten, Logs ansehen, Details anzeigen

### 13.3 Run-Historie & Details
- [ ] Tabelle mit allen Runs (Pipeline-Name, Status, Zeitstempel, Dauer)
- [ ] Filterung nach Pipeline-Name, Status, Zeitraum
- [ ] Sortierung nach Datum (aufsteigend/absteigend)
- [ ] Run-Detailansicht auf Klick mit allen wichtigen Informationen:
  - Pipeline-Name, Run-ID, Status
  - Start- und Endzeitpunkt, Dauer
  - Exit-Code, UV-Version, Setup-Duration
  - Environment-Variablen (Secrets ausgeblendet)
  - Container-Status, Health-Status (falls verfügbar)
  - CPU & RAM Metrics (Live für laufende Runs, historisch für abgeschlossene)
  - Log-Viewer-Integration (siehe 13.4)
  - Metrics-Viewer-Integration (CPU/RAM Charts, siehe 13.4)
  - Cancel-Button für laufende Runs
  - Retry-Button für fehlgeschlagene Runs

### 13.4 Live-Log-Viewer & Metrics-Monitoring
- [ ] **NiceGUI ui.log Element** für optimierte Log-Anzeige
  - `max_lines` Attribut setzen (z.B. 1000 Zeilen) - verhindert DOM-Überfüllung bei High-Frequency-Logs
  - Alte Zeilen werden automatisch entfernt (Ring-Buffer-Verhalten)
- [ ] **Frontend-Pattern**: ui.timer (z.B. alle 0.5 Sekunden) zum Abrufen von Log-Zeilen aus asyncio.Queue
  - Alternative: ui.context.client.download für direkten Zugriff
- [ ] Log-Anzeige für laufende Runs (Live-Streaming aus Backend-Queue)
- [ ] Log-Anzeige für abgeschlossene Runs (aus Log-Datei)
- [ ] Auto-Scroll-Funktionalität (mit Toggle zum Ein/Ausschalten)
- [ ] Syntax-Highlighting (optional)
- [ ] Log-Filterung/Suche (Text-Suche in Logs)
- [ ] Log-Download-Button (Download als .txt oder .log)
- [ ] Log-Anzeige in Run-Detailansicht integriert
- [ ] Separate Log-Viewer-Seite für bessere Übersicht bei großen Logs
- [ ] **CPU & RAM Live-Monitoring**:
  - Live-Metrics-Streaming aus Backend-Queue (ähnlich wie Logs)
  - CPU-Usage-Anzeige: `ui.linear_progress` oder `ui.chart` (Prozentsatz)
  - RAM-Usage-Anzeige: `ui.linear_progress` oder `ui.chart` (MB, mit Limit)
  - Grafische Darstellung: Line-Chart für CPU/RAM über Zeit (NiceGUI `ui.chart`)
  - Aktuelle Werte: CPU %, RAM MB / Limit MB
  - **Soft-Limit-Warnung**: Visuelle Warnung (z.B. gelber/oranger Indikator) wenn Soft-Limit überschritten
  - Hard-Limit-Anzeige: Rote Warnung wenn Hard-Limit erreicht
  - CPU-Throttling-Erkennung: Warnung wenn CPU konstant am Hard-Limit klebt
  - Metrics-Anzeige in Run-Detailansicht (neben/unter Logs)
  - Metrics für abgeschlossene Runs: Aus Metrics-Datei laden und anzeigen
  - Metrics-Download: Metrics als JSON exportieren

### 13.5 Secrets-Management-UI
- [ ] Tabelle mit allen Secrets (Key-Anzeige, Value versteckt)
- [ ] Formular zum Hinzufügen neuer Secrets/Parameter
- [ ] Flag zur Unterscheidung zwischen Secret und Parameter
- [ ] Edit/Delete-Funktionalität
- [ ] Bestätigung vor Löschen

### 13.6 Scheduler-Konfiguration-UI
- [ ] Liste aller geplanten Jobs (mit Status: aktiv/inaktiv)
- [ ] Formular zum Erstellen neuer Jobs (Pipeline, Cron-Expression/Interval)
- [ ] Enable/Disable-Toggle für Jobs
- [ ] Job-Edit und Delete-Funktionalität
- [ ] Job-Details: Nächste Ausführung, Letzte Ausführung, Ausführungs-Historie
- [ ] Warnung beim Pipeline-Löschen (wenn Jobs existieren)
- [ ] Job-Historie anzeigen (verknüpfte Runs)

### 13.8 Git-Sync-UI & Konfiguration
- [ ] Git-Sync-Seite mit Status-Übersicht
- [ ] Manueller Sync-Trigger (Button)
- [ ] Sync-Status-Anzeige:
  - Letzter Sync-Zeitpunkt
  - Sync-Status (erfolgreich/fehlgeschlagen)
  - Aktueller Branch
  - Git-Status (commits ahead/behind)
  - Pre-Heating-Status (welche Pipelines sind gecached)
- [ ] Sync-Einstellungen konfigurieren:
  - Auto-Sync aktivieren/deaktivieren
  - Auto-Sync-Intervall einstellen (in Sekunden/Minuten)
  - Branch-Auswahl
  - Pre-Heating-Einstellungen (UV_PRE_HEAT)
- [ ] Sync-Logs anzeigen (Git-Pull-Ausgabe, Pre-Heating-Ergebnisse)
- [ ] Fehler-Anzeige bei Sync-Fehlern (z.B. Konflikte, Pre-Heating-Fehler)

### 13.9 Pipeline-Management-UI
- [ ] Pipeline-Status-Seite mit detaillierter Übersicht:
  - Pipeline-Name, Pfad, Discovery-Zeitpunkt
  - Requirements.txt vorhanden? (has_requirements)
  - Cache-Status (last_cache_warmup)
  - Pipeline aktiv/inaktiv Status
  - Anzahl geplanter Jobs
  - Pipeline aktivieren/deaktivieren (Toggle)
- [ ] **Pipeline-Statistiken-Anzeige**:
  - Total Runs (gesamt)
  - Successful Runs (erfolgreich)
  - Failed Runs (fehlgeschlagen)
  - Erfolgsrate (successful_runs / total_runs * 100)
  - Reset-Button für Statistiken (mit Bestätigung)
- [ ] **Resource-Limits-Anzeige**:
  - Hard Limits: CPU (nano_cpus), RAM (mem_limit) - aus Metadaten-JSON
  - Soft Limits: CPU, RAM (wenn gesetzt) - aus Metadaten-JSON
  - Limits-Anzeige beim Pipeline-Start-Button (sofort sichtbar)
  - Soft-Limit-Überschreitung-Warnung (wenn Soft-Limit überschritten)
- [ ] Pipeline-Details:
  - Alle Metadaten (aus Pipeline Model)
  - Run-Statistiken (Erfolgsrate, Durchschnittliche Dauer)
  - Resource-Limits (Hard/Soft)
  - Zuletzt gelaufene Runs
  - Verknüpfte Scheduled Jobs
- [ ] Pipeline-Aktionen:
  - Pipeline starten (mit Parameter-Eingabe)
  - Pipeline-Logs ansehen
  - Pipeline-Statistiken anzeigen und zurücksetzen

### 13.7 NiceGUI-spezifische Features
- [ ] Auto-Refresh für Run-Status-Updates (konfigurierbares Intervall)
- [ ] Toast-Notifications für Erfolg/Fehler (Pipeline-Start, Sync, etc.)
- [ ] Loading-States für async Operationen (Buttons, Spinner)
- [ ] Responsive Design (Mobile/Desktop-freundlich)
- [ ] Navigation zwischen verschiedenen Seiten (Dashboard, Runs, Logs, Settings)
- [ ] Breadcrumb-Navigation für bessere Orientierung
- [ ] Kontext-Menüs für schnelle Aktionen
- [ ] Keyboard-Shortcuts (optional, z.B. für häufige Aktionen)

---

## Reihenfolge der Implementierung

1. **Phase 1 & 10**: Projektstruktur + Docker-Setup (Basis)
2. **Phase 3**: Konfiguration (früh, wird überall gebraucht)
3. **Phase 2**: Datenbank & Models (Datenstruktur)
4. **Phase 4**: Pipeline-Discovery
5. **Phase 5**: Docker Executor (Kern-Funktionalität mit Container-Management)
6. **Phase 6.1-6.3**: Basis-API-Endpoints (Health, Pipeline & Run Management)
7. **Phase 6.4**: Log-Streaming (SSE)
8. **Phase 6.5**: Metrics-Endpoints (CPU & RAM)
9. **Phase 6.6**: Git-Sync (mit Branch-Auswahl)
10. **Phase 7**: Secrets Management (mit Pipeline-Parametern)
11. **Phase 8**: Scheduler (mit Persistenz, Pipeline-Validierung)
11. **Phase 9**: Authentication (Basic Login)
12. **Phase 11**: Log-Management & Cleanup
13. **Phase 12**: Testing
14. **Phase 13**: Frontend mit NiceGUI
15. **Phase 5.8**: Container-Health-Checks (Erweiterung von Phase 5)

## Zukunftsplan (Später)

- Error-Handling-Strategien (detailliert)
- Microsoft OAuth/Entra ID Integration
- Monitoring-Integration (Prometheus, etc.)
- Backup-Strategien für Datenbank
- Queue-System für Concurrency-Limits (wenn Limit erreicht, Jobs in Queue statt ablehnen)