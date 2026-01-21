---
sidebar_position: 20
---

# Troubleshooting

Häufige Fehler und schnelle Lösungen.

## "Docker läuft nicht" / "Connection refused"

- **Ursache:** Docker Daemon nicht erreichbar.
- **Lösung:**
  - Docker Desktop starten (bzw. auf Linux: `sudo systemctl start docker`).
  - Prüfen: `docker ps`

## "Docker-Proxy / 403 Forbidden"

Der Orchestrator spricht nur über den [Docker-Socket-Proxy](/docs/deployment/DOCKER_PROXY). Nicht erlaubte Operationen führen zu 403.

- **Logs prüfen:**  
  `docker-compose logs docker-proxy`
- **Sicherstellen:** In der Proxy-Konfiguration muss z.B. `POST=1` für Container-Erstellung gesetzt sein. Siehe [Docker Socket Proxy](/docs/deployment/DOCKER_PROXY).

## "Port 8000 belegt"

- **Lösung:** In der `.env` die Variable `PORT` auf einen freien Port setzen (z.B. `PORT=8001`).

## "ENCRYPTION_KEY fehlt"

Die Anwendung startet ohne gültigen `ENCRYPTION_KEY` nicht.

- **Lösung:**
  1. Key erzeugen:  
     `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  2. In `.env` eintragen: `ENCRYPTION_KEY=<generierter Key>`

## OAuth / Login funktioniert nicht

- **Callbacks:** GitHub `{BASE_URL}/api/auth/github/callback`, Google `{BASE_URL}/api/auth/google/callback`. `BASE_URL` in `.env` muss exakt der erreichbaren URL entsprechen (inkl. Port, ohne Trailing Slash).
- **Docker vs. Dev:**  
  - Alles auf :8000: `FRONTEND_URL` weglassen oder `=http://localhost:8000`, `BASE_URL=http://localhost:8000`.  
  - Frontend :3000, Backend :8000: `FRONTEND_URL=http://localhost:3000`, `BASE_URL=http://localhost:8000`.

Ausführlich: [OAuth (GitHub & Google)](/docs/oauth/readme).

## Pipeline erscheint nicht / wird nicht erkannt

- **`main.py`:** Der Ordner muss eine `main.py` enthalten.
- **Pfad:** `PIPELINES_DIR` in `.env` muss auf das richtige Verzeichnis zeigen (Volume oder geklontes Repo).
- **Git-Sync:** Bei Git-Sync nach Änderungen einen manuellen Sync auslösen oder auf den nächsten Auto-Sync warten.

**Sync/Webhook: Pipeline erscheint nach Push nicht**

- **Auto-Sync:** `AUTO_SYNC_ENABLED=true` und `AUTO_SYNC_INTERVAL` prüfen; nach Push ggf. bis zum nächsten Lauf warten oder **manuellen Sync** in der UI auslösen.
- **Webhook:** Webhook-URL in GitHub/GitLab etc. korrekt eingetragen? Repo-URL und `GIT_BRANCH` in `.env` stimmen mit dem gepushten Branch überein.
- **Manueller Sync:** In der UI Sync ausführen und Logs/Fehlermeldungen prüfen.

## `pipeline.json`-Fehler (ungültiges JSON)

Wenn die UI Fehler zu den Pipeline-Metadaten anzeigt:

- **Syntax:** `pipeline.json` (oder `{pipeline_name}.json`) muss gültiges JSON sein. Typische Fehler: fehlende Klammer, **trailing comma** (z.B. `"tags": ["a", ]`), Anführungszeichen um Keys.
- **Prüfen:** `python3 -c "import json; json.load(open('pipelines/meine_pipeline/pipeline.json'))"` – liefert keine Ausgabe bei gültigem JSON, sonst Fehlermeldung mit Zeile/Position.
- **Fallback:** Datei vorübergehend umbenennen oder löschen; Fast-Flow läuft auch ohne `pipeline.json` (alle Metadaten optional).

## Run schlägt mit Exit-Code 137 fehl

- **Häufig:** Out-of-Memory (OOM). Der Container wurde vom System beendet.
- **Lösung:** `mem_hard_limit` in `pipeline.json` erhöhen oder globale Memory-Limits anpassen.

## Pipeline läuft lokal, schlägt im Orchestrator fehl {#pipeline-lokal-orchestrator-fehlt}

Fast-Flow zielt auf **„Wenn es lokal läuft, läuft es in Fast-Flow“** – gleiche Laufzeit (uv), keine eigenen Pipeline-Images. Tritt trotzdem ein Unterschied auf, zuerst prüfen:

- **Lokaler Lauf wie im Orchestrator:**  
  `uv run --python {version} --with-requirements requirements.txt main.py` (oder `pip install -r requirements.txt` und `python main.py`). `{version}` aus `pipeline.json` (`python_version`, beliebig pro Pipeline) – Python-Version und Pakete sollten vergleichbar sein.
- **`requirements.txt`:** Alle genutzten externen Pakete müssen drinstehen.
- **Pfade:** Im Container ist das Arbeitsverzeichnis der Pipeline-Ordner. Relative Pfade von `main.py` aus ansetzen.
- **Secrets/Env:** In der UI gesetzte Werte werden als Umgebungsvariablen übergeben. Fehlt z.B. `API_KEY`, kann `os.getenv("API_KEY")` `None` liefern.

**Beim Melden eines Bugs** (z.B. [Fast-Flow Issues](https://github.com/ttuhin03/fastflow/issues)) angeben:

- `main.py`, `pipeline.json`, `requirements.txt`
- Logs aus der Orchestrator-UI (Run-Logs)
- Kurzbeschreibung: Was erwartest du, was passiert?

Damit lassen sich Kompatibilitätsprobleme gezielt nachvollziehen und beheben.

## Weitere Hilfe

- [Konfiguration](/docs/deployment/CONFIGURATION) – alle Env-Variablen
- [Schnellstart](/docs/schnellstart) – Grundaufbau nochmal durchgehen
