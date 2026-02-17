---
sidebar_position: 3
---

# 🚀 Deployment Guide

Dieser Guide beschreibt Best Practices für das Deployment von Fast-Flow in einer Produktionsumgebung.

## ⚠️ Sicherheits-Checkliste

Vor dem Go-Live sicherstellen:

- [ ] **HTTPS nutzen** (via Reverse Proxy)
- [ ] **OAuth** (`GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET` und/oder `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`), `INITIAL_ADMIN_EMAIL` in `.env` setzen
- [ ] **JWT Key setzen**: Einen langen, zufälligen `JWT_SECRET_KEY` setzen.
- [ ] **Encryption Key setzen**: `ENCRYPTION_KEY` sicher generieren und speichern.
- [ ] **Environment**: Setze `ENVIRONMENT=production` in der `.env`.
- [ ] **PostgreSQL für Produktion** (siehe Abschnitt Datenbank).

## Datenbank: PostgreSQL für Produktion

**Für den Enterprise-Einsatz wird PostgreSQL dringend empfohlen.** SQLite eignet sich für lokale Entwicklung und sehr kleine Einzelplatz-Setups, ist aber für produktiven Mehrnutzer-Betrieb nicht geeignet:

| Aspekt | SQLite | PostgreSQL |
|--------|--------|------------|
| **Concurrency** | Ein Writer, "database is locked" bei Last | Echte parallele Schreibzugriffe |
| **Skalierung** | Begrenzt | Skalierbar |
| **Enterprise-Tauglichkeit** | Entwicklung/Prototyping | Produktion, Multi-User |

**Setup:** Setze `DATABASE_URL=postgresql://user:password@host:5432/fastflow` in der `.env` (oder als Secret in Kubernetes). Der Orchestrator verwendet dann automatisch PostgreSQL inklusive Connection-Pool.

## Reverse Proxy Setup (Nginx)

In Produktion sollte der Orchestrator niemals direkt dem Internet ausgesetzt werden. Nutzen Sie Nginx als Reverse Proxy für SSL-Terminierung und zusätzliche Sicherheit.

### Beispiel Nginx Config

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

> **Wichtig**: Die `Upgrade` und `Connection` Header sind notwendig für Server-Sent Events (SSE), die für Live-Logs genutzt werden.

## Docker Compose für Produktion

Die Standard-`docker-compose.yaml` ist bereits produktionsorientiert:

- **Docker-Proxy**: Port 2375 wird nicht auf den Host gemappt (nur intern erreichbar, geringere Angriffsfläche).
- **Orchestrator**: `ENVIRONMENT=production`, Logging (json-file, max-size/max-file), Restart-Policy.

Starten mit:
```bash
docker-compose up -d
```

## Backup Strategie

Sichern Sie regelmäßig folgende Verzeichnisse:

1. `data/fastflow.db` (SQLite Datenbank)
2. `.env` (Konfiguration)
3. `pipelines/` (Pipeline-Code, falls nicht in einem externen Git-Repo gehostet)

## Siehe auch

- [Konfiguration](/docs/deployment/CONFIGURATION) – Environment-Variablen
- [Docker Socket Proxy](/docs/deployment/DOCKER_PROXY) – Sicherheitslayer
- [Git-Deployment](/docs/deployment/GIT_DEPLOYMENT) – Push-to-Deploy
