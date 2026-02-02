---
sidebar_position: 5
---

# Architektur: Runner-Cache & Container-Lifecycle

Im Gegensatz zu klassischen Orchestratoren, die oft "Dependency Hell" in ihren Worker-Umgebungen erleben, nutzt Fast-Flow eine moderne JIT-Environment-Architektur.

## Das "Runner-Cache"-Prinzip

- **The Singleton Brain**: Ein einzelner FastAPI-Prozess verwaltet den Zustand, den Scheduler und den Git-Sync.
- **Ephemeral Workers**: Jede Pipeline startet in einem isolierten Docker-Container. Keine Seiteneffekte, keine Rückstände.
- **uv-Acceleration**: Der globale uv-Cache und die uv-Python-Installationen (z.B. 3.11, 3.12) werden als persistente Volumes in den Container gemountet. Dependencies und die **pro Pipeline wählbare** Python-Version (aus `pipeline.json` oder `DEFAULT_PYTHON_VERSION`) sind so in Millisekunden verfügbar – ohne festes Python im Basis-Image.
- **Live-Streaming**: Logs und Ressourcen-Metriken (CPU/RAM) werden per SSE (Server-Sent Events) in Echtzeit direkt aus dem Docker-Socket an das React-Frontend gestreamt.

## Der Container-Prozess & Lifecycle

Fast-Flow nutzt ein **"Disposable Worker"**-Modell. Für jede Ausführung wird ein frischer, isolierter Container erzeugt.

### 1. Trigger & Initialisierung

Sobald ein Run über das React-Frontend (manuell) oder den APScheduler (geplant) ausgelöst wird:

- Die API validiert die Pipeline-Struktur und lädt die verschlüsselten Secrets.
- Ein neuer Eintrag in der Datenbank wird mit dem Status `PENDING` erstellt.

### 2. Die "Zero-Build" Execution

Statt ein Docker-Image zu bauen, wird ein generisches Basis-Image (nur uv, optional mit vorinstalliertem Python) gestartet:

- **Mounting**: Pipeline-Verzeichnis (read-only), uv-Cache und uv-Python-Installationen (`/data/uv_python`) werden vom Host in den Container gemountet.
- **Just-In-Time Environment**: `uv run --python {version}` – die Version ist **beliebig pro Pipeline** konfigurierbar (`python_version` in pipeline.json, z.B. 3.10, 3.11, 3.12) oder `DEFAULT_PYTHON_VERSION`. Python stammt aus `uv python install` (Preheating), nicht aus dem Image.
  - **Abhängigkeiten im Cache?** → In Millisekunden per Hardlink verknüpft.
  - **Neue Abhängigkeiten?** → Einmalig geladen und im Host-Cache für zukünftige Runs gesichert.
- **Preheating**: Beim Start und nach Git-Sync führt der Orchestrator `uv python install {version}` und `uv pip compile --python {version}` aus, damit der erste Run nicht auf Python- oder Paket-Downloads warten muss.

### 3. Monitoring & Kommunikation (Headless Architecture)

Während der Container läuft:

- **Logs**: Die API liest stdout/stderr asynchron und stellt ihn über einen SSE-Endpunkt bereit.
- **Metrics**: Die Docker-Stats-API liefert CPU- und RAM-Werte in Echtzeit an das React-Dashboard.
- **Security**: Die API kommuniziert über einen [Docker-Socket-Proxy](/docs/deployment/DOCKER_PROXY) (`tecnativa/docker-socket-proxy`), nicht direkt mit dem Docker-Socket.

### 4. Terminierung & Cleanup

Nach Abschluss des Python-Skripts:

- Exit-Code wird erfasst (z.B. 137 für OOM-Fehler).
- Der Container wird automatisch entfernt (`--rm`).
- Die Logs werden für die Langzeitarchivierung persistiert.

## Architektur-Diagramm (Datenfluss)

```mermaid
flowchart TB
    subgraph Client["Client Layer"]
        A["React Frontend\nTypeScript + Vite"]
    end

    subgraph App["Application Layer"]
        B["FastAPI Orchestrator\nPython 3.11+"]
        C["Database (SQLite/PostgreSQL)"]
        D["Auth & Secrets\nGitHub App / Fernet"]
    end

    subgraph Security["Security Layer"]
        E["Docker Socket Proxy\ntecnativa/docker-socket-proxy"]
    end

    subgraph Infra["Infrastructure Layer"]
        F["Docker Daemon\nHost System"]
    end

    subgraph Exec["Execution Layer"]
        G["Pipeline Container\nuv run --python {version}"]
        H["uv-Cache\n/data/uv_cache"]
        J["uv-Python-Installationen\n/data/uv_python"]
        I["Pipeline Code\n/app:ro"]
    end

    A -->|"REST / SSE\nLive Updates"| B
    B -->|"SQLModel ORM"| C
    B -->|"JWT & Encryption"| D
    B -->|"HTTP API\ndocker-proxy:2375"| E
    E -->|"Unix Socket\n/var/run/docker.sock"| F
    F -->|"Creates & Manages"| G
    G -.->|"Read/Write"| H
    G -.->|"Read-Only"| J
    G -.->|"Read-Only"| I
    B -.->|"Logs & Stats\nvia Proxy"| G
```

## Warum dieser Ansatz?

- **Geschwindigkeit**: Kein `docker build` – eine Pipeline startet so schnell wie ein lokaler Prozess.
- **Isolation**: Ein Fehler in `pipeline_a` kann die Umgebung von `pipeline_b` nicht beeinflussen.
- **Skalierbarkeit**: Controller und Worker sind entkoppelt; das System kann mit Message-Queues (z.B. Redis) auf mehrere Server verteilt werden.

## Startup & API-Struktur

### App-Start (Lifecycle)

Der FastAPI-Lifecycle wird in **`app/startup`** gebündelt:

- **`run_startup_tasks()`**: Logging, Sicherheits- und OAuth-Validierung, Verzeichnisse, Datenbank, Docker-Client, Zombie-Reconciliation, Scheduler, Cleanup, Dependency-Audit, Version-Check, Telemetry, UV Pre-Heat. Kritische Schritte werfen bei Fehler; optionale werden geloggt und übersprungen.
- **`run_shutdown_tasks()`**: Scheduler stoppen, Graceful Shutdown (laufende Runs beenden), PostHog Flush.

Die eigentliche **`lifespan`**-Funktion in `app.main` ruft nur noch diese beiden Funktionen auf.

### API-Router

Alle REST-Endpoints liegen unter dem Präfix **`/api`**. Die Router werden zentral in **`app.api`** in der Liste **`ROUTERS`** geführt und in `main.py` in einer Schleife mit `prefix="/api"` registriert. Neue API-Module werden in `app.api.__init__.py` zu `ROUTERS` hinzugefügt.

### Module-Überblick

- **`app/executor`**: Container-Ausführung, Log- und Metrics-Streaming, Zombie-Reconciliation, Graceful Shutdown.
- **`app/git_sync`**: Git-Sync des Pipeline-Repos, GitHub-App-Token, Sync-Log, Pre-Heat.
- **`app/startup`**: Startup-/Shutdown-Logik, OAuth- und Sicherheits-Validierung.
- **`app/logging_config`**: Log-Level und optionales JSON-Log-Format.

## Nächste Schritte

- [**Konzepte & Glossar**](/docs/konzepte) – Runner-Cache, uv, JIT, Disposable Worker kurz erklärt
- [Pipelines – Übersicht](/docs/pipelines/uebersicht) – Wie du Pipelines strukturierst
- [Git-Deployment](/docs/deployment/GIT_DEPLOYMENT) – Push-to-Deploy
- [Docker Socket Proxy](/docs/deployment/DOCKER_PROXY) – Sicherheitslayer
