---
sidebar_position: 10
---

# Production-Checkliste

Kurze Checkliste vor dem Go-Live und für den Betrieb.

## Vor dem Go-Live

- [ ] **ENVIRONMENT=production** in `.env` setzen
- [ ] **ENCRYPTION_KEY** setzen (Fernet-Key; siehe `.env.example`)
- [ ] **JWT_SECRET_KEY** auf sicheren, zufälligen Wert setzen (mind. 32 Zeichen)
- [ ] **CORS_ORIGINS** auf tatsächliche Frontend-Origins setzen (kein `*` in Produktion)
- [ ] **BASE_URL** und ggf. **FRONTEND_URL** auf die produktiven URLs setzen
- [ ] OAuth: Mind. ein Provider (GitHub/Google) mit **CLIENT_ID** und **CLIENT_SECRET** konfiguriert
- [ ] **INITIAL_ADMIN_EMAIL** für den ersten Admin setzen
- [ ] HTTPS über Reverse-Proxy (Nginx/Traefik) mit gültigem Zertifikat
- [ ] Datenbank: Für Produktion **DATABASE_URL=postgresql://...** empfohlen (SQLite nur für kleine Setups)

## Optional, empfohlen

- [ ] **LOG_LEVEL** (z. B. `INFO` oder `WARNING`)
- [ ] **LOG_JSON=true** für zentrale Log-Aggregation (ELK, Datadog)
- [ ] **MAX_REQUEST_BODY_MB** (z. B. `10`) gegen große Request-Bodies
- [ ] Regelmäßige Backups der Datenbank und ggf. **S3_LOG_BACKUP** für Logs

## Health & Readiness

- **Liveness**: `GET /health`, `GET /healthz` oder `GET /api/health` – Prozess lebt (für Kubernetes `livenessProbe`, Docker HEALTHCHECK)
- **Readiness**: `GET /ready` oder `GET /api/ready` – DB und Docker erreichbar (für Kubernetes `readinessProbe`)

In Kubernetes:

- **livenessProbe**: `httpGet: path: /health port: 8000`
- **readinessProbe**: `httpGet: path: /ready port: 8000`

## Log-Rotation & Ressourcen

- [ ] Log-Rotation für Container-Logs (z. B. `json-file` mit `max-size`/`max-file`)
- [ ] **LOG_RETENTION_DAYS** / **LOG_RETENTION_RUNS** / **LOG_MAX_SIZE_MB** nach Bedarf setzen
- [ ] **MAX_CONCURRENT_RUNS** und **CONTAINER_TIMEOUT** an Host-Ressourcen anpassen

## Nach dem Start

- [ ] `/health` und `/ready` prüfen
- [ ] Login über OAuth testen
- [ ] Einmal einen Pipeline-Run ausführen und Logs prüfen

Siehe auch: [Deployment Guide (PRODUCTION)](./PRODUCTION.md), [Kubernetes](./K8S.md), [Konfiguration](./CONFIGURATION.md).
