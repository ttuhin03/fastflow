---
sidebar_position: 4
---

# Docker Socket Proxy - Sicherheitsarchitektur

## Übersicht

Fast-Flow nutzt einen **Docker Socket Proxy** (`tecnativa/docker-socket-proxy`) als Sicherheitsschicht zwischen dem Orchestrator und dem Docker-Daemon. Dies verhindert direkten Root-Zugriff auf den Docker-Socket und schränkt die verfügbaren Docker-API-Operationen ein.

## Warum ein Proxy?

Der Docker-Socket (`/var/run/docker.sock`) gibt effektiv **Root-Zugriff auf das gesamte Host-System**. Ein kompromittierter Orchestrator könnte:

- Privilegierte Container starten und das Host-System manipulieren
- Alle Container auf dem System sehen, stoppen oder deren Daten stehlen
- Volumes und Netzwerke manipulieren

Der Docker Socket Proxy **filtert und erlaubt nur konfigurierte Operationen**, wodurch das Risiko erheblich reduziert wird.

## Architektur

```
┌─────────────────┐
│   Orchestrator  │
│   (FastAPI)     │
└────────┬────────┘
         │ HTTP (http://docker-proxy:2375)
         │
         ▼
┌─────────────────┐
│  Docker Proxy   │
│ (tecnativa/...) │
└────────┬────────┘
         │ Unix Socket
         │ (/var/run/docker.sock:ro)
         ▼
┌─────────────────┐
│  Docker Daemon  │
│   (Host)        │
└─────────────────┘
```

**Wichtig**: Nur der Proxy-Service hat direkten Zugriff auf den Docker-Socket. Der Orchestrator kommuniziert über HTTP mit dem Proxy.

## Konfiguration

### Docker Compose Setup

Der Proxy wird automatisch in `docker-compose.yaml` konfiguriert:

```yaml
services:
  docker-proxy:
    image: tecnativa/docker-socket-proxy:latest
    container_name: fastflow-docker-proxy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      # Erlaubte Ressourcen
      - CONTAINERS=1    # Container-Operationen (create, start, stop, remove, logs, stats)
      - IMAGES=1        # Image-Pulls und -Inspektion
      - VOLUMES=1       # Volume-Mounts (für Pipeline-Code und UV-Cache)
      - BUILD=1         # Build-Operationen (optional, für zukünftige Features)
      - EXEC=1           # Exec-Operationen (für Container-Inspektion)
      
      # HTTP-Verb-Berechtigungen (KRITISCH)
      - POST=1           # Erlaubt Container-Erstellung (/containers/create)
      - DELETE=1         # Erlaubt Container-Entfernung
      - STATS=1          # Erlaubt Resource-Monitoring (/containers/{id}/stats)
      
      # Deaktivierte Operationen (Sicherheit)
      - NETWORKS=0       # Netzwerk-Management blockiert
      - SYSTEM=0         # System-Operationen blockiert
    networks:
      - fastflow-network
    restart: unless-stopped

  orchestrator:
    # ...
    environment:
      - DOCKER_PROXY_URL=http://docker-proxy:2375  # Proxy-URL statt direkter Socket
    networks:
      - fastflow-network
    # KEIN Docker-Socket-Mount mehr!
```

### Orchestrator-Konfiguration

Der Orchestrator verbindet sich mit dem Proxy über die Environment-Variable `DOCKER_PROXY_URL`:

```python
# app/config.py
DOCKER_PROXY_URL: str = os.getenv("DOCKER_PROXY_URL", "http://docker-proxy:2375")
```

```python
# app/executor.py
_docker_client = docker.DockerClient(base_url=config.DOCKER_PROXY_URL)
```

## Erlaubte Operationen

Der Proxy erlaubt folgende Docker-API-Operationen:

### ✅ Erlaubt

- **Container-Management**:
  - Container erstellen (`POST /containers/create`)
  - Container starten (`POST /containers/{id}/start`)
  - Container stoppen (`POST /containers/{id}/stop`)
  - Container entfernen (`DELETE /containers/{id}`)
  - Container-Status abfragen (`GET /containers/{id}/json`)
  - Container-Liste abrufen (`GET /containers/json`)

- **Logs & Monitoring**:
  - Logs streamen (`GET /containers/{id}/logs`)
  - Resource-Stats abrufen (`GET /containers/{id}/stats`)

- **Images**:
  - Images pullen (`POST /images/create`)
  - Image-Informationen abrufen (`GET /images/{name}/json`)

- **Volumes**:
  - Volume-Mounts in Container-Konfiguration (für Pipeline-Code und UV-Cache)

### ❌ Blockiert

- **Netzwerk-Management**: Netzwerke erstellen, löschen oder modifizieren
- **System-Operationen**: System-Informationen abrufen oder konfigurieren
- **Privilegierte Container**: Container mit `--privileged` Flag
- **Host-Netzwerk**: Container mit `--net=host`

## Fehlerbehandlung

### 403 Forbidden

Wenn der Proxy eine Operation blockiert, erhält der Orchestrator einen `403 Forbidden` Fehler:

```
docker.errors.APIError: 403 Client Error for http://docker-proxy:2375/v1.49/containers/create: Forbidden
```

**Häufige Ursachen:**

1. **POST=1 fehlt**: Container-Erstellung erfordert `POST=1` in der Proxy-Konfiguration
2. **VOLUMES=0**: Volume-Mounts erfordern `VOLUMES=1`
3. **STATS=0**: Resource-Monitoring erfordert `STATS=1`

**Lösung**: Prüfe die Proxy-Konfiguration in `docker-compose.yaml` und stelle sicher, dass alle benötigten Flags gesetzt sind.

### Proxy nicht erreichbar

Wenn der Orchestrator den Proxy nicht erreichen kann:

```
RuntimeError: Docker-Proxy ist nicht erreichbar (http://docker-proxy:2375)
```

**Prüfungen:**

1. Proxy-Service läuft: `docker-compose ps docker-proxy`
2. Netzwerk-Konnektivität: Beide Services müssen im gleichen Docker-Netzwerk sein
3. Proxy-Logs: `docker-compose logs docker-proxy`

## Fehlerklassifizierung

Fast-Flow unterscheidet zwischen zwei Fehlertypen:

### Infrastructure Error

Fehler, die auf Probleme mit dem Docker-Proxy oder der Infrastruktur hinweisen:

- Proxy nicht erreichbar
- 403 Forbidden vom Proxy
- Docker-Daemon nicht verfügbar

**Frontend-Anzeige**: Orange Badge "Infrastructure Error"

### Pipeline Error

Fehler, die auf Probleme mit dem Pipeline-Skript hinweisen:

- Exit-Code != 0
- OOM (Out of Memory)
- Script-Crash

**Frontend-Anzeige**: Rotes Badge "Pipeline Error"

## Best Practices

### Produktion

1. **HTTPS**: Nutze einen Reverse-Proxy (Nginx/Traefik) mit HTTPS vor dem Orchestrator
2. **Authentifizierung**: Stelle sicher, dass die UI immer mit Login geschützt ist
3. **Minimale Berechtigungen**: Aktiviere nur die benötigten Proxy-Flags
4. **Monitoring**: Überwache Proxy-Logs auf verdächtige Aktivitäten

### Entwicklung

1. **Proxy-Logs**: Nutze `docker-compose logs -f docker-proxy` für Debugging
2. **Health-Check**: Der Orchestrator führt beim Start einen Health-Check durch (`client.ping()`)
3. **Fehlermeldungen**: Detaillierte Fehlermeldungen helfen bei der Diagnose

## Troubleshooting

### Container-Erstellung schlägt fehl

```bash
# 1. Prüfe Proxy-Konfiguration
docker-compose exec docker-proxy env | grep -E "CONTAINERS|POST|VOLUMES"

# 2. Prüfe Proxy-Logs
docker-compose logs docker-proxy | grep -i "403\|forbidden"

# 3. Prüfe Orchestrator-Logs
docker-compose logs orchestrator | grep -i "infrastructure\|403"
```

### Metrics kommen nicht an

```bash
# Prüfe ob STATS=1 gesetzt ist
docker-compose exec docker-proxy env | grep STATS

# Prüfe Stats-Requests in Proxy-Logs
docker-compose logs docker-proxy | grep -i "stats"
```

### Proxy startet nicht

```bash
# Prüfe Docker-Socket-Berechtigungen
ls -la /var/run/docker.sock

# Prüfe ob Docker läuft
docker ps

# Prüfe Proxy-Logs
docker-compose logs docker-proxy
```

## Weitere Informationen

- [tecnativa/docker-socket-proxy auf Docker Hub](https://hub.docker.com/r/tecnativa/docker-socket-proxy)
- [Docker Engine API Dokumentation](https://docs.docker.com/engine/api/)
