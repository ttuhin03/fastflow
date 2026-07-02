---
sidebar_position: 10
---

# Production Checklist

A short checklist before go-live and for ongoing operation.

## Before Go-Live

- [ ] Set **ENVIRONMENT=production** in `.env`
- [ ] Set **ENCRYPTION_KEY** (Fernet key; see `.env.example`)
- [ ] Set **JWT_SECRET_KEY** to a secure, random value (min. 32 characters)
- [ ] Set **CORS_ORIGINS** to actual frontend origins (no `*` in production)
- [ ] Set **BASE_URL** and, if needed, **FRONTEND_URL** to production URLs
- [ ] OAuth: At least one provider (GitHub/Google) with **CLIENT_ID** and **CLIENT_SECRET** configured
- [ ] Set **INITIAL_ADMIN_EMAIL** for the first admin
- [ ] HTTPS via reverse proxy (Nginx/Traefik) with a valid certificate
- [ ] Database: For production, **DATABASE_URL=postgresql://...** recommended (SQLite only for small setups)

## Optional, Recommended

- [ ] **LOG_LEVEL** (e.g. `INFO` or `WARNING`)
- [ ] **LOG_JSON=true** for centralized log aggregation (ELK, Datadog)
- [ ] **MAX_REQUEST_BODY_MB** (e.g. `10`) against large request bodies
- [ ] Regular database backups and optionally **S3_LOG_BACKUP** for logs

## Health & Readiness

- **Liveness**: `GET /health`, `GET /healthz`, or `GET /api/health` – process is alive (for Kubernetes `livenessProbe`, Docker HEALTHCHECK)
- **Readiness**: `GET /ready` or `GET /api/ready` – DB and Docker reachable (for Kubernetes `readinessProbe`)

In Kubernetes:

- **livenessProbe**: `httpGet: path: /health port: 8000`
- **readinessProbe**: `httpGet: path: /ready port: 8000`

## Log Rotation & Resources

- [ ] Log rotation for container logs (e.g. `json-file` with `max-size`/`max-file`)
- [ ] Set **LOG_RETENTION_DAYS** / **LOG_RETENTION_RUNS** / **LOG_MAX_SIZE_MB** as needed
- [ ] Adjust **MAX_CONCURRENT_RUNS** and **CONTAINER_TIMEOUT** to host resources

## After Startup

- [ ] Check `/health` and `/ready`
- [ ] Test login via OAuth
- [ ] Run a pipeline once and verify logs

See also: [Deployment Guide (PRODUCTION)](./PRODUCTION.md), [Kubernetes](./K8S.md), [Configuration](./CONFIGURATION.md).
