---
sidebar_position: 3
---

# 🚀 Deployment Guide

This guide describes best practices for deploying Fast-Flow in a production environment.

## ⚠️ Security Checklist

Before go-live, ensure:

- [ ] **Use HTTPS** (via reverse proxy)
- [ ] **OAuth** (at least one provider: `GITHUB_*`, `GOOGLE_*`, `MICROSOFT_*`, or `CUSTOM_OAUTH_*`), set `INITIAL_ADMIN_EMAIL` in `.env`
- [ ] **Set JWT key**: Set a long, random `JWT_SECRET_KEY`.
- [ ] **Set encryption key**: Generate and store `ENCRYPTION_KEY` securely.
- [ ] **Environment**: Set `ENVIRONMENT=production` in `.env`.
- [ ] **Set `DATABASE_URL`** — mandatory under `ENVIRONMENT=production`; PostgreSQL recommended (see Database section).

## Database: PostgreSQL for Production

**For enterprise use, PostgreSQL is strongly recommended.** SQLite is suitable for local development and very small single-user setups, but is not appropriate for production multi-user operation:

| Aspect | SQLite | PostgreSQL |
|--------|--------|------------|
| **Concurrency** | Single writer, "database is locked" under load | True parallel write access |
| **Scaling** | Limited | Scalable |
| **Enterprise readiness** | Development/prototyping | Production, multi-user |

**Setup:** Set `DATABASE_URL=postgresql://user:password@host:5432/fastflow` in `.env` (or as a secret in Kubernetes). The orchestrator then automatically uses PostgreSQL including a connection pool.

**`DATABASE_URL` is mandatory under `ENVIRONMENT=production`.** Without it, startup
aborts with an error instead of falling back to local SQLite. The reason is that the
silent fallback is dangerous in production: if the value is missing — because a
secret injector has not written it yet, for example — the app would come up on a
freshly stamped, empty SQLite database, report itself healthy via `/ready`, and
process runs against the wrong data. Failing fast is the safer outcome.

If you knowingly want SQLite in production (small single-user setups), set it
explicitly — the guard is aimed at the silent fallback, not at a deliberate choice:

```bash
DATABASE_URL=sqlite:////app/data/fastflow.db
```

## Reverse Proxy Setup (Nginx)

In production, the orchestrator should never be exposed directly to the internet. Use Nginx as a reverse proxy for SSL termination and additional security.

### Example Nginx Config

```nginx
server {
    listen 80;
    server_name fastflow.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name fastflow.example.com;

    ssl_certificate /etc/letsencrypt/live/fastflow.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/fastflow.example.com/privkey.pem;

    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-XSS-Protection "1; mode=block";

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
    }
}
```

> **Important**: Live logs and metrics use Server-Sent Events (SSE). The app sends `X-Accel-Buffering: no`, which Nginx honors — do not force `proxy_buffering on`. A generous `proxy_read_timeout` prevents long-lived SSE connections from being cut off.

> **Tip**: When running behind a trusted reverse proxy, set `PROXY_HEADERS_TRUSTED=true` in `.env` so rate limiting and the audit log use the real client IP from `X-Forwarded-For`.

## Docker Compose for Production

The default `docker-compose.yaml` is already production-oriented:

- **Docker proxy**: Port 2375 is not mapped to the host (only reachable internally, smaller attack surface).
- **Orchestrator**: logging (json-file, max-size/max-file), restart policy, health check.

**Important:** `ENVIRONMENT=production` is **not** set by the compose file — set it in `.env` (the compose file loads `.env` via `env_file`). Only then are insecure defaults (e.g. `JWT_SECRET_KEY`) blocked at startup. Set `DATABASE_URL` in the same `.env`: the compose file does not ship a database either, and under `production` a missing value aborts startup (see the Database section).

Start with:
```bash
docker compose up -d
```

## Backup Strategy

Back up the following directories regularly:

1. `data/fastflow.db` (SQLite database)
2. `.env` (configuration)
3. `pipelines/` (pipeline code, if not hosted in an external Git repo)

## See Also

- [Configuration](/docs/deployment/CONFIGURATION) – environment variables
- [Docker Socket Proxy](/docs/deployment/DOCKER_PROXY) – security layer
- [Git Deployment](/docs/deployment/GIT_DEPLOYMENT) – push-to-deploy
