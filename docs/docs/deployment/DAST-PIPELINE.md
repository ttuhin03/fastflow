---
sidebar_position: 12
---

# DAST-Pipeline: ZAP + sqlmap

Der Workflow [`.github/workflows/dast-pipeline.yml`](https://github.com/ttuhin03/fastflow/blob/main/.github/workflows/dast-pipeline.yml)
baut das echte Orchestrator-Image, startet es als Container und prüft die
laufende App automatisiert auf Schwachstellen (Dynamic Application Security
Testing).

## Ablauf

1. **Build**: Das Image wird aus dem regulären [`Dockerfile`](https://github.com/ttuhin03/fastflow/blob/main/Dockerfile)
   gebaut (`fastflow-dast:latest`).
2. **Run + Healthcheck**: Der Container startet auf Port `8000` und wird über
   den `GET /health`-Endpoint abgewartet (Liveness-Check ohne externe
   Abhängigkeiten – SQLite wird beim Start automatisch angelegt).
3. **zap-scan**: Führt einen ZAP Baseline Scan gegen die laufende App aus.
   Läuft bei jedem Push auf `main` und bei jedem PR.
4. **sqlmap-scan**: Läuft nur bei manuellem Trigger (Checkbox `run_sqlmap`) oder
   beim wöchentlichen Scheduled Run (Montag 03:00 UTC) — sqlmap-Scans dauern
   länger und sind für jeden PR meist zu viel.

Build, Start und Scan laufen bewusst **pro Job auf demselben Runner**. Ein
`services:`-Container mit lokal gebautem Image funktioniert in GitHub Actions
nicht, weil Jobs auf getrennten Runnern laufen und dort nur Images aus einer
Registry verfügbar sind.

## Konfiguration

- **Port / Healthcheck**: Der Workflow ist auf Fast-Flow abgestimmt (Port `8000`,
  `GET /health`). Wird der Port im Image geändert, muss er hier ebenfalls
  angepasst werden.
- **`.zap/rules.tsv`**: Legt fest, welche ZAP-Findings nur als Warnung gelten
  (`WARN`), ignoriert (`IGNORE`) oder den Build brechen (`FAIL`) sollen. Die
  Alert-IDs stehen im HTML-Report nach einem ersten Lauf bzw. in der
  ZAP-Dokumentation. Kritisches (SQLi/XSS) bleibt auf den ZAP-Defaults.
- **sqlmap-Zielparameter**: `http://localhost:8000/api/health?q=test` ist nur ein
  Platzhalter. Fast-Flow hat keinen offenen `/search?q=`-Endpoint, und die meisten
  API-Routen liegen hinter Auth. Für einen sinnvollen Scan einen echten
  parametrisierten Endpoint eintragen – idealerweise über eine gespeicherte
  Request mit Session-Cookie/Token (`-r request.txt`).
- **GitHub-Issues**: Die ZAP-Action legt bewusst **keine** automatischen Issues
  an (`allow_issue_writing: false`), damit der Workflow mit `contents: read`
  auskommt. Findings landen im `zap-report`-Artifact.

## Sicherheits-/Rechtliche Hinweise

- Nur gegen Systeme scannen, die man selbst kontrolliert – hier läuft der
  Container im selben CI-Runner, ist also unproblematisch.
- Bei echten Staging-Umgebungen sicherstellen, dass die Ziel-URL nicht
  versehentlich auf Produktion zeigt.
- sqlmap kann ab `--risk=2` destructive Payloads senden. Für CI reicht i.d.R.
  `--risk=1 --level=2` (so im Workflow gesetzt).

## Lokal testen, bevor es in CI läuft

```bash
docker build -t fastflow-dast:latest .
docker run -d --name fastflow-dast -p 8000:8000 -e ENVIRONMENT=development fastflow-dast:latest
curl http://localhost:8000/health

docker run -t ghcr.io/zaproxy/zaproxy:stable zap-baseline.py \
  -t http://host.docker.internal:8000

docker rm -f fastflow-dast
```

So sieht man Findings sofort, ohne jedes Mal eine Pipeline anzustoßen.
