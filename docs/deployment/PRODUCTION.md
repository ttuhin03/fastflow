# 🚀 Deployment Guide

Dieser Guide beschreibt Best Practices für das Deployment von Fast-Flow in einer Produktionsumgebung.

## ⚠️ Sicherheits-Checkliste

Vor dem Go-Live sicherstellen:

- [ ] **HTTPS nutzen** (via Reverse Proxy)
- [ ] **Standard-Credentials ändern** (`ADMIN_PASSWORD`, `AUTH_USERNAME`) in `.env`
- [ ] **JWT Key setzen**: Einen langen, zufälligen `JWT_SECRET_KEY` setzen.
- [ ] **Encryption Key setzen**: `ENCRYPTION_KEY` sicher generieren und speichern.
- [ ] **Environment**: Setze `ENVIRONMENT=production` in der `.env`.

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

Für Produktion empfiehlt es sich, eine `docker-compose.prod.yaml` zu nutzen, um Restart-Policies und Logging zu konfigurieren.

```yaml
version: '3.8'

services:
  orchestrator:
    restart: always
    environment:
      - ENVIRONMENT=production
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  docker-proxy:
    restart: always
```

Starten mit:
```bash
docker-compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d
```

## Backup Strategie

Sichern Sie regelmäßig folgende Verzeichnisse:

1. `data/fastflow.db` (SQLite Datenbank)
2. `.env` (Konfiguration)
3. `pipelines/` (Pipeline-Code, falls nicht in einem externen Git-Repo gehostet)
