---
sidebar_position: 12
---

# DAST-Pipeline: ZAP + sqlmap

Der Workflow [`.github/workflows/dast-pipeline.yml`](https://github.com/ttuhin03/fastflow/blob/main/.github/workflows/dast-pipeline.yml)
baut den Fast-Flow Orchestrator, startet ihn samt benötigtem Backend und prüft
die laufende App automatisiert auf Schwachstellen (Dynamic Application Security
Testing).

## Warum der Orchestrator nicht per nacktem `docker run` scanbar ist

Anders als eine triviale Web-App bootet der Orchestrator nur, wenn ein
vollständiger Stack bereitsteht. Der Workflow stellt genau das her:

1. **Orchestrator-Image** bauen (`./Dockerfile`).
2. **Worker-Image** bauen (`./Dockerfile.worker`, `fastflow-worker:latest`) —
   der Orchestrator prüft/pullt es beim Start, sonst bricht die Executor-Init ab.
3. **docker-proxy** starten (`tecnativa/docker-socket-proxy`). Die
   Pipeline-Executor-Initialisierung verlangt ein erreichbares Container-Backend
   (`DOCKER_PROXY_URL`, Default `http://docker-proxy:2375`).
4. **Beschreibbares Daten-Verzeichnis** nach `/app/data` mounten. Das Image legt
   `/app/data` nicht selbst an (normalerweise ein Volume), und SQLite erstellt
   keine Elternverzeichnisse → sonst `unable to open database file`.
5. **OAuth-Dummy + `SKIP_OAUTH_VERIFICATION=true`** setzen. Der Start erzwingt
   mindestens einen konfigurierten OAuth-Provider und verifiziert dessen
   Credentials sonst live gegen den Provider. Die Dummy-Werte im Workflow sind
   durch das Skip-Flag wirkungslos — **keine echten Secrets nötig**.

Danach wartet der Workflow per `GET /health`-Gate (Liveness, Port `8000`) auf die
App und scannt sie.

## Ablauf

- **ZAP Baseline Scan**: läuft bei jedem Push auf `main` und bei jedem PR.
  `fail_action: true` lässt den Job bei nicht-ignorierten Findings fehlschlagen.
- **sqlmap-Scan**: läuft nur bei manuellem Trigger (Checkbox `run_sqlmap`) oder
  beim wöchentlichen Scheduled Run (Montag 03:00 UTC).

Alles läuft in **einem** Job, damit der Stack nur einmal gebaut/gestartet wird.

## Konfiguration

- **`.zap/rules.tsv`**: Legt fest, welche ZAP-Findings nur Warnung (`WARN`),
  ignoriert (`IGNORE`) oder Build-brechend (`FAIL`) sind. Alert-IDs stehen im
  HTML-Report nach einem ersten Lauf. Kritisches (SQLi/XSS) bleibt auf den
  ZAP-Defaults.
- **sqlmap-Zielparameter**: `http://localhost:8000/api/health?q=test` ist nur ein
  Platzhalter. Fast-Flow hat keinen offenen `?q=`-Endpoint, und die echten
  API-Routen liegen hinter Auth. Für einen sinnvollen Scan einen echten
  parametrisierten Endpoint eintragen — idealerweise über eine gespeicherte
  Request mit Session-Cookie/Token (`-r request.txt`).
- **GitHub-Issues**: Die ZAP-Action legt bewusst **keine** Issues an
  (`allow_issue_writing: false`), damit der Workflow mit `contents: read`
  auskommt. Findings landen im `zap-report`-Artifact.

## Sicherheits-/Rechtliche Hinweise

- Nur gegen selbst kontrollierte Systeme scannen — hier läuft alles im selben
  CI-Runner, ist also unproblematisch.
- Die gesetzten OAuth-/JWT-Werte sind reine Dummies für den Scan-Boot, **nicht**
  für Produktion.
- sqlmap kann ab `--risk=2` destructive Payloads senden. Für CI reicht
  `--risk=1 --level=2` (so gesetzt).

## Lokal testen

```bash
# Images bauen
docker build -t fastflow-dast:latest .
docker build -f Dockerfile.worker -t fastflow-worker:latest .

# Backend + App starten
docker network create dast-net
docker run -d --name docker-proxy --network dast-net \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e CONTAINERS=1 -e IMAGES=1 -e VOLUMES=1 -e EXEC=1 -e NETWORKS=1 \
  -e POST=1 -e DELETE=1 -e STATS=1 -e INFO=1 -e VERSION=1 -e BUILD=1 \
  tecnativa/docker-socket-proxy:latest

mkdir -p /tmp/dast-data && chmod 777 /tmp/dast-data
docker run -d --name fastflow-dast --network dast-net -p 8000:8000 \
  -e ENVIRONMENT=development -e JWT_SECRET_KEY=dummy \
  -e SKIP_OAUTH_VERIFICATION=true \
  -e GITHUB_CLIENT_ID=dummy -e GITHUB_CLIENT_SECRET=dummy \
  -e DOCKER_PROXY_URL=http://docker-proxy:2375 \
  -e WORKER_BASE_IMAGE=fastflow-worker:latest \
  -v /tmp/dast-data:/app/data \
  fastflow-dast:latest

curl http://localhost:8000/health

# ZAP-Scan
docker run -t --network host ghcr.io/zaproxy/zaproxy:stable zap-baseline.py \
  -t http://localhost:8000

# Aufräumen
docker rm -f fastflow-dast docker-proxy && docker network rm dast-net
```
