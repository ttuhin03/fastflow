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
- aiofiles (für asynchrones Datei-I/O)
- alembic (für DB-Migrationen)
- python-dotenv (für .env Konfiguration)
- passlib[bcrypt] (für Password-Hashing)
- python-jose[cryptography] (für JWT/Sessions)
- cryptography (für Secrets-Verschlüsselung mit Fernet)
- PyJWT (für GitHub Apps Authentifizierung)
- requests (für GitHub API-Calls)
- psycopg2-binary (optional, für PostgreSQL-Support)

### 1.3 App-Lifecycle & Signal-Handling
- [ ] `app/main.py`: FastAPI-App mit Lifecycle-Management
- [ ] **Graceful Shutdown-Handler**: SIGTERM/SIGINT Handler implementieren
  - Wenn Orchestrator gestoppt wird (z.B. für Update):
    - Scheduler pausieren (Scheduler.shutdown())
    - Status der laufenden Runs auf INTERRUPTED oder WARNING setzen
    - (Optional) Versuch, Docker-Container sauber herunterzufahren (nicht hart killen)
  - Verhindert Zombie-Container und Datenbank-Inkonsistenzen
- [ ] Startup-Event: Datenbank-Initialisierung, Scheduler-Start, Zombie-Reconciliation
- [ ] Shutdown-Event: Scheduler-Stop, Cleanup-Tasks

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
- [ ] **SQLite WAL-Checkpointing**: Periodisches Checkpointing implementieren
  - WAL-Dateien können unbegrenzt wachsen ohne Checkpoint
  - Periodisches `PRAGMA wal_checkpoint(TRUNCATE)` (z.B. alle 100 Transaktionen oder alle 10 Minuten)
  - Optional: Background-Task für automatisches Checkpointing
- [ ] Session-Dependency für FastAPI
- [ ] Alembic Setup für Migrationen (funktioniert mit SQLite und PostgreSQL)
  - **SQLite-Migrationen**: `render_as_batch=True` für Alembic konfigurieren
  - Verwendet "Tabelle kopieren, ändern, Original löschen"-Strategie bei SQLite
  - Verhindert Fehler bei Spalten-Löschen/Umbenennen (SQLite-Limitation)
- [ ] Datenbank-Initialisierung beim ersten Start
- [ ] **Timezone-Handling**: Alle Zeitstempel in UTC in der Datenbank speichern
  - DateTime-Felder immer als UTC speichern (keine lokale Zeit)
  - Konvertierung zur lokalen Zeit erst im Frontend (NiceGUI)
  - Verhindert Probleme bei Zeitzonen-Unterschieden (Host vs. Container vs. DB)

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
- [ ] **Pipeline-Repository-Struktur** (siehe README.md für Details):
  - Verzeichnisstruktur: Jede Pipeline in eigenem Unterverzeichnis (z.B. `pipelines/pipeline_a/`)
  - **`main.py`** (erforderlich): Haupt-Pipeline-Skript, wird mit `uv run --with-requirements` ausgeführt
  - **`requirements.txt`** (optional): Python-Dependencies für die Pipeline
  - **`pipeline.json` oder `{pipeline_name}.json`** (optional): Metadaten für Resource-Limits
- [ ] Pipeline-Name-Erkennung: Pipeline-Name = Verzeichnisname (z.B. `pipeline_a/` → Name: `pipeline_a`)
- [ ] Pipeline-Validierung: Pipeline muss `main.py` enthalten, sonst wird sie ignoriert
- [ ] Cache für Pipeline-Liste
- [ ] **Pipeline-Metadaten-JSON**: Erkennung von `pipeline.json` oder `{pipeline_name}.json` im Pipeline-Verzeichnis
  - JSON-Format (alle Felder optional):
    ```json
    {
      "cpu_hard_limit": 1.0,
      "mem_hard_limit": "1g",
      "cpu_soft_limit": 0.8,
      "mem_soft_limit": "800m",
      "timeout": 3600,
      "retry_attempts": 3,
      "description": "Beschreibung der Pipeline",
      "tags": ["tag1", "tag2"],
      "enabled": true,
      "default_env": {"LOG_LEVEL": "INFO"}
    }
    ```
  - **Felder (alle optional)**:
    - Resource-Limits:
      - `cpu_hard_limit` (Float): CPU-Limit in Kernen (z.B. 1.0 = 1 Kern)
      - `mem_hard_limit` (String): Memory-Limit (z.B. "512m", "1g")
      - `cpu_soft_limit` (Float): CPU-Soft-Limit für Monitoring (wird überwacht, keine Limitierung)
      - `mem_soft_limit` (String): Memory-Soft-Limit für Monitoring (wird überwacht, keine Limitierung)
    - Pipeline-Konfiguration:
      - `timeout` (Integer): Timeout in Sekunden (pipeline-spezifisch, überschreibt CONTAINER_TIMEOUT)
      - `retry_attempts` (Integer): Retry-Versuche bei Fehlern (pipeline-spezifisch, überschreibt RETRY_ATTEMPTS)
      - `enabled` (Boolean): Pipeline aktiviert/deaktiviert (Standard: true)
    - Dokumentation:
      - `description` (String): Beschreibung (wird in UI angezeigt)
      - `tags` (Array[String]): Tags für Kategorisierung/Filterung in UI
    - Environment-Variablen:
      - `default_env` (Object): Pipeline-spezifische Default-Env-Vars (werden bei jedem Start gesetzt, können in UI ergänzt werden)
  - Hard Limits: Werden beim Container-Start gesetzt (mem_limit, nano_cpus)
  - Soft Limits: Werden überwacht, Überschreitung wird im Frontend angezeigt
  - Timeout & Retry: Pipeline-spezifische Werte überschreiben globale Konfiguration
  - Default-Env-Vars: Werden mit UI-spezifischen Env-Vars zusammengeführt (UI-Werte haben Vorrang)
  - Optional: Falls keine Metadaten-JSON vorhanden, Standard-Werte verwenden
- [ ] **Pipeline-Struktur**: Pipelines werden mit `uv run --with-requirements {requirements.txt} {main.py}` ausgeführt
  - Code kann von oben nach unten ausgeführt werden (keine `main()`-Funktion erforderlich)
  - Optional: `main()`-Funktion mit `if __name__ == "__main__"` Block
  - Bei uncaught Exceptions → Exit-Code != 0 → Status FAILED

---

## Phase 5: Docker Executor

### 5.1 Docker Client Setup (UV-basiert)
- [ ] `app/executor.py`: Docker Client initialisieren
- [ ] **Docker-Daemon-Error-Handling**: Retry-Logik mit Exponential Backoff für Docker-Operationen
  - Health-Check für Docker-Socket-Verbindung
  - Klare Fehlermeldungen wenn Docker-Daemon nicht erreichbar
  - Graceful Degradation: Pipeline-Starts ablehnen wenn Docker nicht verfügbar
- [ ] **Worker-Image-Pull**: Worker-Image (`WORKER_BASE_IMAGE`) beim App-Start prüfen/pullen
  - Falls Image nicht vorhanden: Versuch es zu pullen
  - Fehler-Handling: Klare Fehlermeldung wenn Registry nicht erreichbar
- [ ] **System-Library-Dokumentation**: "Goldene Regel" für Basis-Image dokumentieren
  - Basis-Image muss gängige System-Dependencies vorinstalliert haben (Build-Essentials, DB-Clients, etc.)
  - UV isoliert Python-Pakete, aber keine System-Bibliotheken (z.B. libpq-dev, libgl1)
  - Falls Pipeline etwas Spezielles braucht: Entweder im Skript via apt-get nachinstallieren (langsam) oder Basis-Image erweitern
- [ ] Container-Start-Logik mit UV-Worker-Image (`auto_remove=False` - wird manuell entfernt)
- [ ] Container-Befehl: `uv run --with-requirements /app/{pipeline}/requirements.txt /app/{pipeline}/main.py`
- [ ] Container-Labels setzen: `fastflow-run-id={run_id}` für Reconciliation
- [ ] Volume-Mounts konfigurieren:
  - Pipelines-Verzeichnis als `/app` (read-only)
  - UV-Cache-Verzeichnis als `/root/.cache/uv` (read-write, shared)
- [ ] **Environment-Variablen-Injection**:
  - Default-Env-Vars aus Pipeline-Metadaten-JSON lesen (`default_env`)
  - Secrets und Parameter aus UI/Datenbank abrufen
  - Env-Vars zusammenführen: Default-Env-Vars + UI-Env-Vars (UI-Werte haben Vorrang bei Duplikaten)
  - Als Environment-Variablen an Container übergeben
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
  - **Race-Condition-Prevention**: Locking-Mechanismus (`asyncio.Lock`) oder atomare DB-Transaktionen für Zähler-Updates
  - Verhindert, dass mehrere gleichzeitige Requests das Limit überschreiten
- [ ] Container-Cancellation (`container.stop()`)
- [ ] Timeout-Handling (optional, harter Timeout - Container killen)
- [ ] Status-Polling für Container-Status

### 5.3 Log-Streaming & Persistenz
- [ ] Log-Streaming aus Container
- [ ] **File-Handle-Management**: Context-Manager für Log-Streams verwenden
  - Handles explizit schließen in `finally`-Blocks
  - Verhindert File-Handle-Leaks bei vielen gleichzeitigen Runs
- [ ] **Asynchrones Datei-I/O**: Nutze `aiofiles` oder `run_in_executor` für alle Datei-Operationen
  - Verhindert Blocking des Event-Loops bei großen Log-Dateien (z.B. 500 MB)
  - Beim Lesen: `contents = await run_in_executor(None, file.read)` oder `aiofiles.open()`
  - Beim Schreiben: Asynchrones Schreiben mit `aiofiles.open()` oder `run_in_executor`
  - Verhindert, dass FastAPI/Scheduler während Datei-Operationen blockiert
- [ ] Log-Datei-Schreibung in konfiguriertem Logs-Verzeichnis (alle Logs werden geschrieben)
- [ ] **Log-Spam-Schutz (Dateisystem)**: Dateigröße beim Schreiben prüfen
  - Dateigröße regelmäßig prüfen (z.B. alle 1000 Zeilen oder alle 10 Sekunden)
  - Wenn Datei größer als LOG_MAX_SIZE_MB: Stream kappen oder Warnung ausgeben
  - Zusätzlich zu Docker Log-Limits (zusätzliche Sicherheitsschicht)
- [ ] Rate-Limited Queue für SSE-Streaming (konfigurierbar, Standard: 100 Zeilen/Sekunde)
- [ ] `container.wait()` für Exit-Code-Abruf
- [ ] **Container-Cleanup mit Error-Handling**:
  - `container.remove()` in Try-Except-Block
  - Fehler loggen wenn Container bereits entfernt oder Docker-Daemon nicht erreichbar
  - Graceful Degradation: Fehler nicht an Aufrufer weitergeben (Container ist bereits weg)
- [ ] Status-Updates in Datenbank
- [ ] Exit-Code-Erfassung

### 5.4 Container-Metrics-Monitoring (CPU & RAM)
- [ ] Container-Stats-Monitoring in `app/executor.py`
- [ ] Hintergrund-Task für `container.stats(stream=True)` während Container läuft
- [ ] **Container-Stats-Stream-Cleanup**: Streams explizit beenden in `finally`-Blocks
  - Context-Manager für Stats-Streams verwenden
  - Verhindert Ressourcen-Leaks wenn Container beendet wird
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
  - **I/O-Error-Handling**: Try-Except beim Schreiben, Fehler loggen
  - Optional: Metrics in DB statt Datei wenn Disk voll ist
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
  - **Race-Condition-Prevention**: Atomare DB-Updates verwenden
    - `UPDATE Pipeline SET total_runs = total_runs + 1 WHERE pipeline_name = ?`
    - Verhindert verlorene Updates bei gleichzeitigen Runs
  - Statistiken in Pipeline Model aktualisieren

### 5.6 Run-Funktion
- [ ] `run_pipeline(name, env_vars=None, parameters=None)` Funktion
- [ ] **Pipeline-Metadaten laden**: Metadaten-JSON aus Pipeline-Verzeichnis lesen
  - Timeout (pipeline-spezifisch oder global CONTAINER_TIMEOUT)
  - Retry-Attempts (pipeline-spezifisch oder global RETRY_ATTEMPTS)
  - Enabled-Status prüfen (wenn `enabled: false`, Pipeline-Start ablehnen)
  - Default-Env-Vars aus Metadaten (`default_env`)
- [ ] **Pre-Heating-Lock-Mechanismus**: Lock pro Pipeline für Pre-Heating-Operationen
  - Wenn Pre-Heating für Pipeline läuft: Start-Befehl warten oder Meldung "Warte auf Abschluss der Dependency-Installation"
  - Verhindert Race-Conditions: Zwei Container greifen nicht gleichzeitig schreibend auf uv-Cache zu
  - Lock wird freigegeben wenn Pre-Heating abgeschlossen ist
- [ ] **Environment-Variablen zusammenführen**:
  - Default-Env-Vars aus Metadaten (`default_env`)
  - UI-spezifische Env-Vars (Secrets + Parameter)
  - Zusammenführen: Default + UI (UI-Werte haben Vorrang bei Duplikaten)
- [ ] PipelineRun-Datensatz erstellen
- [ ] Container starten und überwachen (mit Label `fastflow-run-id`)
- [ ] **Docker-Log-Limits**: Log-Limits beim Container-Start setzen
  - `log_config={'type': 'json-file', 'config': {'max-size': '10m', 'max-file': '3'}}`
  - Verhindert "Silent Death" durch Amok-laufende Pipelines, die Terabytes an Log-Text produzieren
  - Zusätzlich zur Dateispeicherung (Docker-Limits als zusätzliche Sicherheit)
- [ ] **Pipeline-spezifisches Timeout**: Timeout aus Metadaten verwenden (falls gesetzt)
- [ ] Status-Updates (RUNNING → SUCCESS/FAILED basierend auf Exit-Code)
- [ ] **Pipeline-spezifischer Retry-Mechanismus**: Retry-Attempts aus Metadaten verwenden (falls gesetzt)

### 5.7 Zombie-Reconciliation (Crash-Recovery)
- [ ] Startup-Reconciler-Funktion in `app/executor.py`
- [ ] Beim App-Start: Scan aller laufenden Docker-Container mit Label `fastflow-run-id`
- [ ] Abgleich mit Datenbank: Container mit Label, die in DB als `RUNNING` stehen
- [ ] Re-attach zu laufenden Containern: Log-Stream wieder aufnehmen
- [ ] **Zombie-Container-Cleanup**: Periodischer Cleanup-Job für orphaned Container
  - Container ohne `fastflow-run-id` Label, die aber Pipeline-Containern ähneln
  - Optional: Cleanup alter/beendeter Container die nicht entfernt wurden
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
  - **Asynchrones Datei-Lesen**: `aiofiles` oder `run_in_executor` verwenden
  - Verhindert Blocking des Event-Loops bei großen Log-Dateien (z.B. 500 MB)
  - Beispiel: `contents = await run_in_executor(None, lambda: open(path).read())` oder `aiofiles.open()`
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
- [ ] **Git-Sync-Race-Condition-Prevention**: Lock für Git-Sync-Operationen
  - Verhindert gleichzeitige Git-Syncs (können zu Inkonsistenzen führen)
  - Pipeline-Discovery-Cache nach Sync invalidieren
- [ ] **Git-Atomarität (Atomic Switch)**: Verhindert "Halbe-Datei"-Fehler
  - Problem: Race Condition beim Git-Sync (git pull während Pipeline-Start kann zu halbgeschriebenen Dateien führen)
  - Lösung: Atomic Switch-Pattern
    - Option 1 (Empfohlen): Git-Sync in temporäres Verzeichnis, dann atomarer Symlink-Austausch
      - Sync in `/tmp/pipelines_new` durchführen
      - Nach erfolgreichem Sync: Symlink `/app/pipelines` auf neues Verzeichnis umsetzen (atomare Operation)
      - Altes Verzeichnis nach kurzer Verzögerung entfernen
    - Option 2 (Alternative): Lock-Datei während Git-Sync (Pipelines warten auf Lock-Freigabe)
  - Verhindert, dass Pipeline-Container Dateien lesen, die gerade geschrieben werden
- [ ] Requirements.txt-Erkennung (Discovery)
- [ ] **UV Pre-Heating (Warming)** - Wenn UV_PRE_HEAT=true:
  - Step 1: Git Pull (Aktualisierung des Codes)
  - Step 2: Discovery (Suche nach allen requirements.txt)
  - Step 3: Pre-Heating: Für jede neue/geänderte requirements.txt
    - Hintergrund-Job: `uv pip compile requirements.txt` (lädt alle Pakete in Host-Cache)
    - Status-Update in DB: `last_cache_warmup` aktualisieren
    - UI-Status: "Pipeline bereit (Cached)"
  - Fehlerbehandlung: Fehlgeschlagene Pre-Heats in UI anzeigen
- [ ] **UV-Cache-Disk-Space-Management** (Optional, für Produktion):
  - UV-Cache kann unbegrenzt wachsen (`uv pip compile` lädt alle Pakete)
  - Optional: Cache-Größen-Limit konfigurierbar (ENV-Variable)
  - Optional: Cleanup-Job für alte/unbenutzte Pakete (`uv cache clean`)
  - Dokumentation: Cache-Größe überwachen in Produktion
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
- [ ] Default-Env-Vars aus Pipeline-Metadaten (`default_env`) lesen
- [ ] Environment-Variablen zusammenführen: Default-Env-Vars + Secrets + Parameter (UI-Werte haben Vorrang bei Duplikaten)
- [ ] Als Environment-Variablen an Container injizieren

---

## Phase 8: Scheduler

### 8.1 APScheduler Setup
- [ ] `app/scheduler.py`: BackgroundScheduler initialisieren
- [ ] **Job-Store: SQLAlchemyJobStore** (statt MemoryJobStore)
  - Job-Store auf SQLite/PostgreSQL-Datenbank (gleiche DB wie SQLModel)
  - Vorteil: Geplante Jobs überleben Orchestrator-Neustarts ohne manuelles Neuladen
  - Vorteil: Scheduler "erinnert" sich selbst an verpasste Jobs (Misfire-Handling)
  - Vorteil: Wenn Orchestrator 5 Minuten offline war, werden verpasste Jobs automatisch nachgeholt
  - Konfiguration: `SQLAlchemyJobStore(url=DATABASE_URL)` in Scheduler initialisieren
- [ ] Scheduler beim App-Start starten
- [ ] Scheduler beim App-Shutdown stoppen
- [ ] **Hinweis**: Jobs werden automatisch aus Job-Store geladen (kein manuelles Laden aus DB nötig)

### 8.2 Job-Model
- [ ] ScheduledJob Model (bereits in Phase 2.2 definiert)
- [ ] Job-API-Endpoints in `app/api/scheduler.py`:
  - `GET /scheduler/jobs`: Alle Jobs auflisten
  - `POST /scheduler/jobs`: Job erstellen
  - `PUT /scheduler/jobs/{id}`: Job aktualisieren
  - `DELETE /scheduler/jobs/{id}`: Job löschen

### 8.3 Scheduler-Logik
- [ ] **Hinweis**: Mit SQLAlchemyJobStore werden Jobs automatisch aus der Datenbank geladen (kein manuelles Laden nötig)
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
  - **Session-Persistenz**: Sessions in Datenbank speichern (nicht nur in Memory)
  - Verhindert Session-Verlust bei App-Neustart
  - Alternative: Redis für Session-Storage (für Multi-Instance-Deployments)
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

### 11.2 Docker Garbage Collection (Janitor-Service)
- [ ] **Docker Garbage Collection Background-Task** (Janitor-Service)
- [ ] Periodischer Cleanup-Job (z.B. einmal pro Woche) für Docker-Metadaten
- [ ] **Label-basierte Cleanup-Strategie**: Gezieltes Aufräumen mit Label-Filterung
  - Container: Nur Container mit Label `fastflow-run-id` aufräumen (verwaiste Container)
  - Volumes: Nur Volumes mit `fastflow-run-id` Label löschen (wenn Pipelines Volumes nutzen)
  - Problem: `docker system prune` löscht oft nicht alle verwaisten Volumes (wenn noch referenziert)
  - Lösung: Spezifisch nach Labels suchen (`docker container prune --filter "label=fastflow-run-id"`)
  - Vorteil: Gezieltes Aufräumen ohne andere Container/Volumes auf dem Host zu stören
- [ ] `docker system prune -f` ausführen (oder spezifischer: `docker image prune`, `docker volume prune`)
- [ ] Problem: Docker-Metadaten sammeln sich über Zeit an (fehlgeschlagene Builds, ungenutzte Netzwerke, verwaiste Volumes)
- [ ] Lösung: Automatischer Cleanup verhindert, dass Host-Server schleichend voll läuft
- [ ] Konfigurierbares Intervall (optional, Standard: wöchentlich)
- [ ] Error-Handling: Fehler loggen, aber Orchestrator nicht crashen lassen
- [ ] Optional: Nur spezifische Ressourcen bereinigen (z.B. nur Images, nur Volumes)

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
  - `max_lines` Attribut setzen (z.B. 500 Zeilen) - **KRITISCH für Browser-Memory-Leak-Prevention**
  - Verhindert DOM-Überfüllung bei High-Frequency-Logs (z.B. 50.000 Zeilen)
  - Verhindert Browser-Tab-Crash nach mehreren Stunden Dauerbetrieb
  - Alte Zeilen werden automatisch entfernt (Ring-Buffer-Verhalten)
  - Vollständige Logs über Download-Button verfügbar (aus Log-Datei)
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
- [ ] **NiceGUI-Verbindungsstabilität (Re-Connect-Handling)**:
  - Problem: WebSocket-Verbindung bricht ab (Tab in Ruhezustand, WLAN-Wechsel)
  - Lösung: Re-Connect-Mechanismus implementieren
    - Re-Connect-Button in UI (manuelle Wiederherstellung)
    - Automatisches Nachladen beim Wiederverbinden: Letzte 50-100 Zeilen aus Log-Datei nachladen
    - Verhindert, dass User denkt, Pipeline hängt (tatsächlich ist nur Frontend getrennt)
    - Log-Stream automatisch fortsetzen nach Re-Connect
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