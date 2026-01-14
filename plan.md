# Fast-Flow Orchestrator - Masterplan

Ein eigenes Workflow-Orchestrierungstool ähnlich Apache Airflow und Dagster, aber mit spezifischen Anforderungen für schnelle, isolierte Pipeline-Ausführungen.

## Überblick

Fast-Flow ist ein On-Demand Pipeline-Orchestrator, der jede Pipeline in einem separaten Docker-Container ausführt. Der Fokus liegt auf:
- **Isolation**: Jedes Skript läuft in einem eigenen Container
- **Geschwindigkeit**: Lokale Images ermöglichen Startzeiten < 2s
- **Git-Integration**: Automatische Synchronisierung von Pipeline-Code
- **Live-Logs**: Echtzeit-Log-Streaming über Server-Sent Events (SSE)
- **Historie**: Persistente Log-Speicherung für jeden Run
- **Secrets-Management**: Sichere Verwaltung von Umgebungsvariablen

---

## 1. Infrastruktur-Setup (Docker-in-Docker)

### Konzept
Damit der Orchestrator (FastAPI) andere Docker-Container starten kann, muss der Docker-Socket des Host-Systems in den Orchestrator-Container gemountet werden.

### Docker-Compose Setup
```yaml
services:
  orchestrator:
    build: .
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock # Zugriff auf Docker-Engine
      - ./pipelines:/app/pipelines                # Git-Repo mit Pipelines
      - ./logs:/app/persistent_logs               # Dauerhafte Logs
      - ./data:/app/data                          # SQLite DB
      - ./data/uv_cache:/data/uv_cache            # Shared UV Cache für Dependencies
    ports:
      - "8000:8000"
    environment:
      - WORKER_BASE_IMAGE=ghcr.io/astral-sh/uv:python3.11-bookworm-slim  # UV Worker Image
```

### Feature-Erklärung
- **Docker Socket Mount**: Ermöglicht dem Orchestrator-Container, Docker-Befehle auszuführen und Container zu starten
- **Volume Mounts**: 
  - `pipelines`: Git-Repository mit den Pipeline-Skripten
  - `logs`: Persistente Speicherung von Log-Dateien
  - `data`: SQLite-Datenbank für Metadaten
  - `data/uv_cache`: Shared UV Cache für alle Pipeline-Dependencies (dedupliziert, effizient)
- **UV-basierte Architektur**: Ein einziges Standard-Worker-Image (`fastflow-worker`) mit `uv` vorinstalliert, statt custom Images pro Pipeline

### Docker-in-Docker (DinD) Security-Warnung

**⚠️ WICHTIG: Security-Risiko**

Der Docker-Socket (`/var/run/docker.sock`) gibt effektiv Root-Zugriff auf das gesamte Host-System. Wer Zugriff auf den Socket hat, kann:

- **Privilege Escalation**: Container mit Root-Mounts starten und das Host-System manipulieren
- **Container-Escape**: Alle Container auf dem System sehen, stoppen oder deren Daten (Secrets) stehlen

**Sicherheitsmaßnahmen:**

1. **Authentifizierung (Phase 9) - WICHTIGSTER SCHUTZ**: Die UI muss immer mit Login geschützt sein. Niemals ohne Authentifizierung erreichbar machen!
2. **User Namespaces (Optional)**: Docker kann so konfiguriert werden, dass der User im Container nicht die gleiche ID wie Root auf dem Host hat.

---

## 2. Datenbank-Logik (SQLite/PostgreSQL + SQLModel)

### Konzept
Jeder Pipeline-Run wird in der Datenbank gespeichert, um eine vollständige Historie im Frontend zu ermöglichen.

### Tabelle: Pipeline (Metadaten)
| Feld | Typ | Zweck |
|------|-----|-------|
| `pipeline_name` | String | Name der Pipeline (Primärschlüssel) |
| `has_requirements` | Boolean | Wurde eine requirements.txt gefunden? |
| `last_cache_warmup` | DateTime | Zeitstempel des letzten erfolgreichen `uv pip compile` |

### Tabelle: PipelineRun

| Feld | Typ | Zweck |
|------|-----|-------|
| `id` | UUID | Primärschlüssel für diesen spezifischen Durchlauf |
| `pipeline_name` | String | Name des Skripts (z.B. `cleanup_db.py`) |
| `status` | Enum | `PENDING`, `RUNNING`, `SUCCESS`, `FAILED` |
| `log_file` | String | Pfad zur Datei in `./persistent_logs/{id}.log` |
| `env_vars` | JSON | Secrets/Parameter, die mitgegeben wurden |
| `uv_version` | String | Die genutzte uv-Version für Reproduzierbarkeit |
| `setup_duration` | Float | Zeit in Sekunden, die uv für das Bereitstellen der Umgebung benötigt hat |
| `started_at` | DateTime | Startzeitpunkt |
| `finished_at` | DateTime | Endzeitpunkt (optional) |
| `exit_code` | Integer | Exit-Code des Containers |

### Datenbank-Wahl: SQLite (Standard) oder PostgreSQL (optional)

**Standard**: SQLite wird standardmäßig verwendet.

**PostgreSQL-Option**: Über Environment-Variable `DATABASE_URL` kann auf PostgreSQL gewechselt werden.

**SQLite-Vorteile**:
- **Einfachheit**: Kein separater Datenbank-Server nötig
- **Dateibasiert**: Datenbank ist eine einzelne Datei (einfaches Backup)
- **Perfekt für den Use-Case**: Single-Instance-Deployment, moderate Datenmengen
- **Zero-Configuration**: Funktioniert out-of-the-box

**PostgreSQL-Vorteile**:
- **Multi-Instance**: Unterstützt Multi-Instance-Deployments
- **Skalierbarkeit**: Besser für größere Datenmengen
- **Concurrent Access**: Besserer Zugriff bei mehreren gleichzeitigen Verbindungen

**Konfiguration**:
- **Standard (SQLite)**: Keine `DATABASE_URL` gesetzt → SQLite wird verwendet
- **PostgreSQL**: `DATABASE_URL=postgresql://user:password@host:5432/dbname` → PostgreSQL wird verwendet

### Feature-Erklärung
- **SQLite**: Leichtgewichtige, dateibasierte Datenbank für einfache Deployment
- **SQLModel**: Moderne ORM von SQLAlchemy-Autor, vereint Pydantic-Models mit SQLAlchemy
- **Run-Tracking**: Vollständige Nachverfolgbarkeit jedes Pipeline-Durchlaufs
- **Status-Management**: Klare Statusübergänge für UI-Updates
- **Datenbank-Migrationen**: Alembic wird für Schema-Updates verwendet (automatische DB-Initialisierung beim ersten Start)

---

## 3. Pipeline-Discovery & Validierung

### Konzept
Der Orchestrator scannt das `pipelines`-Verzeichnis, um verfügbare Pipelines zu finden. Vor dem Start wird jede Pipeline validiert.

### Pipeline-Format
- **Unterstützt**: Python-Dateien (`.py`)
- **Erkennung**: Scan des `pipelines`-Verzeichnisses nach `.py`-Dateien
- **Validierung**: Vor dem Start wird geprüft, ob die Datei existiert und ausführbar ist

### Pipeline-Struktur

Python-Pipelines können **einfach von oben nach unten** ausgeführt werden. Es ist **keine `main()`-Funktion erforderlich**.

**Beispiel 1: Einfaches Skript (von oben nach unten)**
```python
# pipeline.py
import os
print("Pipeline gestartet")
data = os.getenv("MY_SECRET")
print(f"Verarbeite Daten: {data}")
# ... weiterer Code ...
```

**Beispiel 2: Mit main() Funktion (optional)**
```python
# pipeline.py
def main():
    print("Pipeline gestartet")
    # ... Logik ...

if __name__ == "__main__":
    main()
```

Beide Varianten funktionieren. Der Container führt einfach `python pipeline.py` aus.

**Error-Handling**: Bei uncaught Exceptions gibt Python automatisch Exit-Code != 0 zurück, was die Pipeline als `FAILED` markiert.

### Feature-Erklärung
- **Automatische Discovery**: Pipelines werden automatisch erkannt, keine manuelle Registrierung nötig
- **Python-only**: Erstmal nur Python-Skripte unterstützt (später erweiterbar)
- **Validierung**: Sicherstellung, dass Pipelines existieren und ausführbar sind
- **Flexible Struktur**: Pipelines können einfach von oben nach unten ausgeführt werden, `main()` ist optional

---

## 4. Executor-Ablauf (Das Herzstück)

### Konzept
UV-basierte On-Demand-Strategie: Container werden mit einem Standard-Worker-Image gestartet, das `uv` enthält. Dependencies werden dynamisch von `uv` verwaltet, mit einem Shared Cache für Speed. Container werden nach dem Lauf automatisch entfernt.

### Ablauf im Python-Code

1. **Container-Start mit UV**
   ```python
   container = client.containers.run(
       image=WORKER_BASE_IMAGE,  # ghcr.io/astral-sh/uv:python3.11-bookworm-slim
       command=f"uv run --with-requirements /app/{pipeline_name}/requirements.txt /app/{pipeline_name}/main.py",
       volumes={
           '/app/pipelines': {'bind': '/app', 'mode': 'ro'},  # Pipelines als /app
           '/data/uv_cache': {'bind': '/root/.cache/uv', 'mode': 'rw'}  # Shared UV Cache
       },
       environment=env_vars,
       labels={'fastflow-run-id': str(run_id)},  # Label für Reconciliation
       detach=True,
       auto_remove=False  # Wird manuell nach Log-Speicherung entfernt
   )
   ```
   
   **UV-Isolation**: Jede Pipeline erhält innerhalb des Containers eine eigene venv, die von `uv` flüchtig erstellt wird. Dependencies werden aus dem Shared Cache geladen (meist < 1 Sekunde, da `uv` nur Hardlinks setzt).

2. **Log-Streaming & Speichern**
   Während der Container läuft, liest ein Hintergrund-Thread die Logs:
   ```python
   log_queue = asyncio.Queue()  # Queue für Frontend
   with open(f"persistent_logs/{run_id}.log", "w") as f:
       for line in container.logs(stream=True, follow=True):
           f.write(line.decode('utf-8'))  # Alle Logs werden in Datei geschrieben
           await log_queue.put(line.decode('utf-8'))  # Rate-Limited für Frontend
   ```
   
   **Backend-Architektur**: 
   - **asyncio.Queue**: Jede neue Log-Zeile wird in eine asyncio.Queue geschoben (pro Run-ID)
   - **Rate-Limiting**: Für das UI-Streaming wird ein Rate-Limiting angewendet (z.B. maximal 100 Zeilen pro Sekunde), um Memory-Probleme bei sehr großen Log-Outputs zu vermeiden
   - **Datei-Speicherung**: Alle Logs werden vollständig in die Datei geschrieben

3. **Container-Wait & Exit-Code**
   Nach dem Log-Streaming wird auf Container-Beendigung gewartet:
   ```python
   exit_code = container.wait()['StatusCode']
   ```

4. **Abschluss & Error-Handling**
   Nach erfolgreichem Log-Speichern und Exit-Code-Abruf:
   - **Exit-Code 0**: Pipeline erfolgreich → Status `SUCCESS`
   - **Exit-Code != 0**: Pipeline fehlgeschlagen (Exception, Fehler) → Status `FAILED`
   - Status wird in der Datenbank aktualisiert, zusammen mit dem `exit_code` und `finished_at` Zeitstempel
   - Container wird manuell entfernt: `container.remove()`

### Container-Management & Ressourcen

**Resource-Limits**: Container können mit CPU- und Memory-Limits gestartet werden (konfigurierbar, optional).

**Parallele Ausführung**: Es gibt ein konfigurierbares Limit für gleichzeitig laufende Container (z.B. max 10 parallel). Wenn das Limit erreicht ist, werden neue Pipeline-Starts abgelehnt (HTTP 429 oder ähnlich).

**Container-Cancellation**: Laufende Container können gestoppt werden über `container.stop()` - der Status wird auf `FAILED` gesetzt.

**Timeouts**: Konfigurierbare Timeouts für Container-Ausführung (optional, Standard: kein Timeout). Bei Timeout wird der Container ge-killt (harter Timeout, nicht graceful shutdown).

**Status-Polling**: Der Executor prüft regelmäßig den Container-Status, um abgestürzte Container zu erkennen.

**Zombie-Reconciliation (Crash-Recovery)**: 
- Problem: Wenn der Orchestrator-Container abstürzt oder neu startet, während Pipeline-Container noch laufen, verliert der Orchestrator die Verbindung zum Log-Stream.
- Lösung: Beim App-Start scannt ein Startup-Reconciler alle laufenden Docker-Container. Container mit Label `fastflow-run-id` werden mit der Datenbank abgeglichen. Wenn ein Container noch läuft, aber in der DB als `RUNNING` steht, wird sich der Orchestrator wieder an den Log-Stream "re-attachen".
- Container-Labels: Jeder Pipeline-Container erhält beim Start das Label `fastflow-run-id={run_id}`, um die Zuordnung zu ermöglichen.

### Retry-Mechanismus
Konfigurierbare Retry-Logik für fehlgeschlagene Runs (optional, Standard: keine Retries).

### Feature-Erklärung
- **On-Demand Container**: Jeder Run bekommt einen frischen Container
- **Auto-Remove**: Container werden automatisch nach Beendigung entfernt (Aufräumen)
- **Live-Log-Streaming**: Logs werden in Echtzeit gelesen und gespeichert
- **Persistente Logs**: Logs werden vor dem Container-Löschvorgang auf Disk gesichert
- **Resource-Control**: CPU/Memory-Limits verhindern Resource-Exhaustion
- **Concurrency-Limits**: Kontrollierte parallele Ausführung
- **Cancellation**: Manuelle Steuerung laufender Container
- **Error-Detection**: Automatische Erkennung von Fehlern via Exit-Code (0 = SUCCESS, != 0 = FAILED)
- **Crash-Recovery**: Zombie-Reconciliation beim App-Start stellt Verbindung zu laufenden Containern wieder her

---

## 5. Git- & Secret-Management

### Git-Synchronisierung

**Manueller Sync**: Ein `/sync` Endpoint führt `git pull` aus.

**Branch-Auswahl**: Der Branch kann konfiguriert werden (Standard: `main` oder `master`).

**Konflikt-Strategie**: Bei Git-Konflikten wird immer die Remote-Version übernommen (`git reset --hard origin/<branch>`).

**Auto-Sync**: Optional konfigurierbares automatisches Sync-Intervall (z.B. alle 5 Minuten).

**UV-basiertes Dependency-Management**: Dependencies werden von `uv` dynamisch verwaltet, kein Docker-Image-Build nötig. Ein Shared Cache (`/data/uv_cache`) wird in alle Container gemountet für schnelle Dependency-Installation.

**Pre-Heating (Warming)**: Beim Git-Sync werden Pipelines "aufgewärmt":
  1. Git Pull (Aktualisierung des Codes)
  2. Discovery (Suche nach allen requirements.txt)
  3. Pre-Heating: Für jede neue/geänderte requirements.txt wird `uv pip compile requirements.txt` ausgeführt (lädt alle Pakete in den Host-Cache)
  4. Status-Update in UI: "Pipeline bereit (Cached)"
  
  **Vorteile**: Eliminiert Cold-Start-Wartezeit, Fehler-Frühwarnsystem (Inkompatibilitäten werden beim Sync erkannt, nicht beim ersten Run)

**Git-Authentifizierung: GitHub Apps**
- **Lösung**: GitHub Apps statt SSH-Keys (professioneller, sicherer, wartungsärmer)
- **Workflow**: 
  1. Setup in GitHub: GitHub App erstellen, Read-only "Contents" Rechte, Private Key (.pem) und IDs notieren
  2. Token-Tausch: JWT mit Private Key erstellen, Installation Access Token von GitHub API anfordern
  3. Git-Befehle: Token als Passwort verwenden (`git clone https://x-access-token:TOKEN@github.com/...`)
- **Konfiguration**: GITHUB_APP_ID, GITHUB_INSTALLATION_ID, GITHUB_PRIVATE_KEY_PATH (aus .env)
- **Vorteile**: Keine privaten User-Keys in Container, kurzlebige Tokens, besserer Security-Standard

### Secrets-Management

**Key-Value-Speicherung**: In der UI können Key-Value-Paare gespeichert werden (z.B. `DB_PASSWORD`).

**Verschlüsselung**: Secrets werden verschlüsselt in der Datenbank gespeichert (cryptography/Fernet).
- **Library**: `cryptography` mit Fernet
- **Key-Management**: ENCRYPTION_KEY aus .env Datei
- **Funktionen**: `encrypt(plain_text)` und `decrypt(cipher_text)` in `app/secrets.py`
- **Wichtig**: Verschlüsselung von Anfang an, um Migrationen zu vermeiden

**Runtime-Injection**: Secrets werden beim Start entschlüsselt und als Environment-Variablen an den `client.containers.run` Befehl übergeben.

**Pipeline-Parameter**: Unterschied zwischen Secrets (sensibel, verschlüsselt) und normalen Parametern (öffentlich, als Environment-Variablen). In der UI wird ein Flag gesetzt, um zwischen Secrets und Parametern zu unterscheiden.

### Feature-Erklärung
- **Git-Sync**: Automatische Synchronisierung des Pipeline-Codes ohne Container-Neustart
- **Branch-Flexibilität**: Unterstützung verschiedener Git-Branches
- **Konflikt-Handling**: Automatische Lösung von Git-Konflikten (Remote-Version gewinnt)
- **Auto-Sync**: Optional automatische Synchronisierung
- **UV-basiertes Dependency-Management**: Dependencies werden dynamisch von `uv` verwaltet, kein Docker-Image-Build nötig
- **GitHub Apps**: Professionelle Authentifizierung für private Repos (keine SSH-Keys nötig)
- **Secrets-UI**: Verwaltung von sensiblen Daten über das Frontend
- **Runtime-Injection**: Secrets und Parameter werden zur Laufzeit als Environment-Variablen injiziert

---

## 6. Scheduler (APScheduler)

### Konzept
Wir nutzen den `BackgroundScheduler` von APScheduler. Jobs werden in der Datenbank gespeichert (persistiert).

### Scheduler-Persistenz
- **Datenbank-Speicherung**: Alle Jobs werden in der DB gespeichert (ScheduledJob-Model)
- **Neustart-Resilienz**: Beim App-Start werden alle aktiven Jobs aus der DB geladen und beim Scheduler registriert
- **Permanenz**: Jobs überleben App-Neustarts

### Trigger-Typen
- **Cron**: Unterstützt Cron-Ausdrücke (z.B. `0 2 * * *` für täglich um 2 Uhr)
- **Interval**: Zeitintervalle (z.B. alle 5 Minuten)

### Task-Ausführung
Der Scheduler ruft einfach die interne `run_pipeline(name)` Funktion auf.

### Pipeline-Validierung bei Scheduled Jobs
- **Beim Job-Start**: Es wird validiert, ob die Pipeline noch existiert
- **Pipeline-Löschung während Lauf**: Wenn eine Pipeline gelöscht wird, während ein geplanter Job läuft:
  - **Warnung**: Der Nutzer wird vor dem Löschen gewarnt (wenn Pipeline läuft oder geplant ist)
  - **Trotzdem löschen**: Wenn die Pipeline trotzdem gelöscht wird, wird der laufende Container gestoppt

### Feature-Erklärung
- **Background-Scheduling**: Läuft asynchron im Hintergrund
- **Flexible Trigger**: Cron und Interval-basierte Ausführungen
- **Datenbank-basiert**: Jobs werden in der DB gespeichert und persistiert
- **Neustart-sicher**: Jobs bleiben nach App-Neustart erhalten
- **Wiederverwendbare Logik**: Nutzt die gleiche Run-Funktion wie manuelle Trigger

---

## 7. Konfiguration

### Konzept
Alle Pfade und Einstellungen sind konfigurierbar über Environment-Variablen, nutzen aber sinnvolle Standardwerte.

### Konfigurierbare Parameter
- **DATABASE_URL**: Datenbank-URL (Standard: nicht gesetzt → SQLite, Format: `postgresql://user:password@host:5432/dbname` für PostgreSQL)
- **PIPELINES_DIR**: Pfad zum Pipelines-Verzeichnis (Standard: `./pipelines`)
- **LOGS_DIR**: Pfad zum Logs-Verzeichnis (Standard: `./logs`)
- **DATA_DIR**: Pfad zum Data-Verzeichnis (Standard: `./data`)
- **WORKER_BASE_IMAGE**: Das UV-Worker-Image (Standard: `ghcr.io/astral-sh/uv:python3.11-bookworm-slim`)
- **UV_CACHE_DIR**: Pfad auf dem Host für den globalen UV-Cache (Standard: `./data/uv_cache`)
- **UV_PRE_HEAT**: Boolean - Sollen Dependencies beim Git-Sync automatisch geladen werden? (Standard: `true`)
- **MAX_CONCURRENT_RUNS**: Maximal gleichzeitige Container (Standard: 10)
- **CONTAINER_TIMEOUT**: Timeout für Container-Ausführung in Sekunden (Standard: kein Timeout)
- **RETRY_ATTEMPTS**: Anzahl Retry-Versuche bei Fehlern (Standard: 0)
- **GIT_BRANCH**: Git-Branch für Sync (Standard: `main`)
- **AUTO_SYNC_INTERVAL**: Auto-Sync-Intervall in Sekunden (Standard: deaktiviert)
- **LOG_RETENTION_RUNS**: Anzahl Runs pro Pipeline, die behalten werden (Standard: unbegrenzt)
- **LOG_RETENTION_DAYS**: Logs älter als X Tage werden gelöscht (Standard: unbegrenzt)
- **LOG_MAX_SIZE_MB**: Maximale Größe einer Log-Datei in MB (Standard: unbegrenzt)
- **LOG_STREAM_RATE_LIMIT**: Maximale Zeilen pro Sekunde für SSE-Streaming (Standard: 100)
- **ENCRYPTION_KEY**: Fernet-Key für Secrets-Verschlüsselung (Standard: Muss gesetzt werden)
- **GITHUB_APP_ID**: GitHub App ID für Authentifizierung (Standard: None)
- **GITHUB_INSTALLATION_ID**: GitHub Installation ID (Standard: None)
- **GITHUB_PRIVATE_KEY_PATH**: Pfad zur GitHub App Private Key (.pem Datei) (Standard: None)

### Feature-Erklärung
- **Flexibilität**: Anpassung an verschiedene Deployment-Umgebungen
- **Standardwerte**: Funktioniert out-of-the-box ohne Konfiguration
- **Environment-basiert**: Konfiguration über `.env`-Dateien oder Environment-Variablen

---

## 8. Security & Authentication

### Konzept
Basis-Authentifizierung für den Zugriff auf die UI, später erweiterbar mit Microsoft OAuth.

### Authentication
- **Basic Login**: Einfache Username/Password-Authentifizierung (erste Version)
- **Session-Management**: Session-basierte Authentifizierung
- **Zukunft**: Microsoft OAuth/Entra ID Integration (später)

### Secrets-Verschlüsselung
- **Implementierung**: Secrets werden von Anfang an verschlüsselt in der DB gespeichert
- **Library**: cryptography (Fernet)
- **Key-Management**: ENCRYPTION_KEY aus Environment-Variablen
- **Funktionen**: `encrypt()` und `decrypt()` in `app/secrets.py`

### Feature-Erklärung
- **Basis-Security**: Grundlegender Schutz der UI
- **Erweiterbar**: Vorbereitet für OAuth-Integration
- **Session-basiert**: Einfaches Session-Management
- **Kritisch für DinD-Security**: Authentifizierung ist der wichtigste Schutz gegen Docker-Socket-Missbrauch (siehe Section 1: Docker-in-Docker Security-Warnung)

---

## 9. API-Endpoints

### REST-API
FastAPI bietet automatische API-Dokumentation unter `/docs`.

### Wichtige Endpoints
- **Health-Check**: `GET /health` - Status des Orchestrators
- **Pipelines**: `GET /pipelines`, `POST /pipelines/{name}/run`
- **Runs**: `GET /runs`, `GET /runs/{run_id}`, `POST /runs/{run_id}/cancel`
- **Logs**: `GET /runs/{run_id}/logs`, `GET /runs/{run_id}/logs/stream` (SSE mit Rate-Limiting)
- **Sync**: `POST /sync`, `GET /sync/status`
- **Secrets**: `GET /secrets`, `POST /secrets`, `PUT /secrets/{key}`, `DELETE /secrets/{key}`
- **Scheduler**: `GET /scheduler/jobs`, `POST /scheduler/jobs`, `PUT /scheduler/jobs/{id}`, `DELETE /scheduler/jobs/{id}`

### Feature-Erklärung
- **RESTful**: Standard REST-API-Design
- **Auto-Dokumentation**: OpenAPI/Swagger-Dokumentation automatisch generiert
- **Health-Check**: Monitoring-freundlicher Endpoint

---

## 10. Frontend mit NiceGUI

### Konzept
NiceGUI ist ein Python-basiertes Web-UI-Framework, das es ermöglicht, moderne Web-Interfaces komplett in Python zu erstellen. Es lässt sich nahtlos in FastAPI integrieren.

### Integration
NiceGUI kann entweder als separater Server laufen oder in FastAPI gemountet werden. Die UI-Komponenten werden in Python definiert, und NiceGUI rendert automatisch eine moderne Web-UI.

### UI-Komponenten

1. **Dashboard**
   - Übersicht aller Pipelines
   - Schnellstart-Buttons
   - Status-Übersicht (laufende/erfolgreiche/fehlgeschlagene Runs)

2. **Run-Historie**
   - Tabelle mit allen Pipeline-Runs
   - Filterung und Sortierung
   - Detailansicht mit Logs

3. **Live-Log-Viewer**
   - Echtzeit-Log-Anzeige für laufende Runs
   - Backend: asyncio.Queue für Log-Zeilen (Docker-Client schiebt Zeilen in Queue)
   - Frontend: NiceGUI `ui.log` Element mit `ui.timer` (z.B. alle 0.5 Sekunden) zum Abrufen aus Queue
   - Auto-Scroll
   - Download-Funktionalität

4. **Secrets-Management**
   - UI zum Verwalten von Key-Value-Paaren
   - Sichere Eingabe (Passwort-Felder)
   - CRUD-Operationen

5. **Scheduler-Konfiguration**
   - Job-Verwaltung
   - Cron-Expression-Editor
   - Enable/Disable-Toggle

### Feature-Erklärung
- **Python-only**: Kein JavaScript/HTML/CSS nötig - alles in Python
- **Reactive UI**: Automatische Updates durch NiceGUI's Reaktivität
- **Modern Design**: Schöne, moderne UI-Komponenten out-of-the-box
- **Einfache Integration**: Läuft im selben Python-Prozess wie FastAPI
- **Real-time Updates**: Kann leicht mit FastAPI-Endpoints verbunden werden
- **Live-Log-Viewer**: Nutzt `ui.log` Element von NiceGUI mit `ui.timer` für optimierte Performance

---

## Zusammenfassung der Features

| Feature | Umsetzung im Plan |
|---------|-------------------|
| **Isolation** | Jedes Skript läuft in eigenem Container (On-Demand). |
| **Geschwindigkeit** | Lokale Images erlauben Startzeiten von < 2s. |
| **Git-Integration** | Volume-Mount + Pull-Befehl via API, Branch-Auswahl, Auto-Sync. |
| **Live-Logs** | SSE (Server-Sent Events) streamen direkt aus dem Docker-Log (mit Rate-Limiting). |
| **Historie** | Logs werden vor Container-Löschung auf Disk gesichert. |
| **Secrets** | Werden zur Laufzeit als Env-Vars injiziert, mit Pipeline-Parametern. |
| **Scheduling** | APScheduler mit Cron/Interval-Triggers, persistiert in DB. |
| **Persistenz** | SQLite für Metadaten, Dateisystem für Logs, DB-Migrationen. |
| **Frontend** | NiceGUI für Python-basierte Web-UI. |
| **Security** | Basic Login, später Microsoft OAuth. |
| **Konfiguration** | Environment-Variablen mit Standardwerten. |
| **Container-Control** | Resource-Limits, Concurrency-Limits, Cancellation, Timeouts. |
| **Pipeline-Discovery** | Automatisches Scannen nach Python-Dateien. |

---

## Technologie-Stack

- **Backend**: FastAPI (Python)
- **Frontend**: NiceGUI (Python-basiertes Web-UI-Framework)
- **Datenbank**: SQLite + SQLModel
- **Container**: Docker (via Docker-Python-Client)
- **Scheduler**: APScheduler
- **Log-Streaming**: Server-Sent Events (SSE)
- **Git-Integration**: Python subprocess/gitpython

---

## Zukunftsplan (Später)

### Error-Handling-Strategien
- Detaillierte Error-Handling-Strategien für verschiedene Fehlerszenarien
- Retry-Strategien mit exponential backoff
- Error-Notifikationen (Email, Slack, etc.)
- Dead-Letter-Queue für wiederholt fehlgeschlagene Pipelines

### Weitere Features
- Microsoft OAuth/Entra ID Integration
- Pipeline-Dependencies (DAG-Support)
- Container-Health-Checks
- Monitoring-Integration (Prometheus, etc.)
- Backup-Strategien für Datenbank
- Queue-System für Concurrency-Limits (wenn Limit erreicht, Jobs in Queue statt ablehnen)

---

## Nächste Schritte

1. Projektstruktur aufsetzen
2. Docker-Compose-Datei erstellen
3. FastAPI-Grundgerüst mit SQLModel-Models
4. Docker-Executor implementieren (mit Container-Management)
5. Pipeline-Discovery implementieren
6. Git-Sync-Endpoint (mit Branch-Auswahl)
7. Secrets-Management (mit Pipeline-Parametern)
8. Scheduler-Integration (mit Persistenz)
9. Configuration-Management
10. Basic Authentication
11. API-Endpoints (inkl. Health-Check)
12. SSE-Log-Streaming
13. Frontend mit NiceGUI
