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
- [ ] **PostgreSQL for production** (see Database section).

## Database: PostgreSQL for Production

**For enterprise use, PostgreSQL is strongly recommended.** SQLite is suitable for local development and very small single-user setups, but is not appropriate for production multi-user operation:

| Aspect | SQLite | PostgreSQL |
|--------|--------|------------|
| **Concurrency** | Single writer, "database is locked" under load | True parallel write access |
| **Scaling** | Limited | Scalable |
| **Enterprise readiness** | Development/prototyping | Production, multi-user |

**Setup:** Set `DATABASE_URL=postgresql://user:password@host:5432/fastflow` in `.env` (or as a secret in Kubernetes). The orchestrator then automatically uses PostgreSQL including a connection pool.

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
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

> **Important**: The `Upgrade` and `Connection` headers are required for Server-Sent Events (SSE), which are used for live logs.

## Docker Compose for Production

The default `docker-compose.yaml` is already production-oriented:

- **Docker proxy**: Port 2375 is not mapped to the host (only reachable internally, smaller attack surface).
- **Orchestrator**: `ENVIRONMENT=production`, logging (json-file, max-size/max-file), restart policy.

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
