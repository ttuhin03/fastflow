---
sidebar_position: 4
---

# Docker Socket Proxy - Security Architecture

## Overview

Fast-Flow uses a **Docker Socket Proxy** (`tecnativa/docker-socket-proxy`) as a security layer between the orchestrator and the Docker daemon. This prevents direct root access to the Docker socket and restricts available Docker API operations.

## Why a Proxy?

The Docker socket (`/var/run/docker.sock`) effectively grants **root access to the entire host system**. A compromised orchestrator could:

- Start privileged containers and manipulate the host system
- View, stop, or steal data from all containers on the system
- Manipulate volumes and networks

The Docker Socket Proxy **filters and allows only configured operations**, significantly reducing risk.

## Architecture

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

**Important**: Only the proxy service has direct access to the Docker socket. The orchestrator communicates with the proxy over HTTP.

## Configuration

### Docker Compose Setup

The proxy is configured automatically in `docker-compose.yaml`:

```yaml
services:
  docker-proxy:
    image: tecnativa/docker-socket-proxy:latest
    container_name: fastflow-docker-proxy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      # Allowed resources
      - CONTAINERS=1    # Container operations (create, start, stop, remove, logs, stats)
      - IMAGES=1        # Image pulls and inspection
      - VOLUMES=1       # Volume mounts (for pipeline code and UV cache)
      - BUILD=1         # Build operations (optional, for future features)
      - EXEC=1           # Exec operations (for container inspection)
      
      # HTTP verb permissions (CRITICAL)
      - POST=1           # Allows container creation (/containers/create)
      - DELETE=1         # Allows container removal
      - STATS=1          # Allows resource monitoring (/containers/{id}/stats)
      
      # Disabled operations (security)
      - NETWORKS=0       # Network management blocked
      - SYSTEM=0         # System operations blocked
    networks:
      - fastflow-network
    restart: unless-stopped

  orchestrator:
    # ...
    environment:
      - DOCKER_PROXY_URL=http://docker-proxy:2375  # Proxy URL instead of direct socket
    networks:
      - fastflow-network
    # NO Docker socket mount anymore!
```

### Orchestrator Configuration

The orchestrator connects to the proxy via the `DOCKER_PROXY_URL` environment variable:

```python
# app/core/config.py
DOCKER_PROXY_URL: str = os.getenv("DOCKER_PROXY_URL", "http://docker-proxy:2375")
```

```python
# app/executor/core.py
_docker_client = docker.DockerClient(base_url=config.DOCKER_PROXY_URL)
```

## Allowed Operations

The proxy allows the following Docker API operations:

### ✅ Allowed

- **Container management**:
  - Create containers (`POST /containers/create`)
  - Start containers (`POST /containers/{id}/start`)
  - Stop containers (`POST /containers/{id}/stop`)
  - Remove containers (`DELETE /containers/{id}`)
  - Query container status (`GET /containers/{id}/json`)
  - List containers (`GET /containers/json`)

- **Logs & monitoring**:
  - Stream logs (`GET /containers/{id}/logs`)
  - Fetch resource stats (`GET /containers/{id}/stats`)

- **Images**:
  - Pull images (`POST /images/create`)
  - Fetch image information (`GET /images/{name}/json`)

- **Volumes**:
  - Volume mounts in container configuration (for pipeline code and UV cache)

### ❌ Blocked

- **Network management**: Create, delete, or modify networks
- **System operations**: Fetch or configure system information
- **Privileged containers**: Containers with `--privileged` flag
- **Host network**: Containers with `--net=host`

## Error Handling

### 403 Forbidden

When the proxy blocks an operation, the orchestrator receives a `403 Forbidden` error:

```
docker.errors.APIError: 403 Client Error for http://docker-proxy:2375/v1.49/containers/create: Forbidden
```

**Common causes:**

1. **POST=1 missing**: Container creation requires `POST=1` in the proxy configuration
2. **VOLUMES=0**: Volume mounts require `VOLUMES=1`
3. **STATS=0**: Resource monitoring requires `STATS=1`

**Solution**: Check the proxy configuration in `docker-compose.yaml` and ensure all required flags are set.

### Proxy unreachable

When the orchestrator cannot reach the proxy:

```
RuntimeError: Docker proxy is unreachable (http://docker-proxy:2375)
```

**Checks:**

1. Proxy service running: `docker compose ps docker-proxy`
2. Network connectivity: Both services must be on the same Docker network
3. Proxy logs: `docker compose logs docker-proxy`

## Error Classification

Fast-Flow distinguishes between two error types:

### Infrastructure Error

Errors indicating problems with the Docker proxy or infrastructure:

- Proxy unreachable
- 403 Forbidden from proxy
- Docker daemon unavailable

**Frontend display**: Orange badge "Infrastructure Error"

### Pipeline Error

Errors indicating problems with the pipeline script:

- Exit code != 0
- OOM (Out of Memory)
- Script crash

**Frontend display**: Red badge "Pipeline Error"

## Best Practices

### Production

1. **HTTPS**: Use a reverse proxy (Nginx/Traefik) with HTTPS in front of the orchestrator
2. **Authentication**: Ensure the UI is always protected with login
3. **Minimal permissions**: Enable only the required proxy flags
4. **Monitoring**: Monitor proxy logs for suspicious activity

### Development

1. **Proxy logs**: Use `docker compose logs -f docker-proxy` for debugging
2. **Health check**: The orchestrator runs a health check on startup (`client.ping()`)
3. **Error messages**: Detailed error messages help with diagnosis

## Troubleshooting

### Container creation fails

```bash
# 1. Prüfe Proxy-Konfiguration
docker compose exec docker-proxy env | grep -E "CONTAINERS|POST|VOLUMES"

# 2. Prüfe Proxy-Logs
docker compose logs docker-proxy | grep -i "403\|forbidden"

# 3. Prüfe Orchestrator-Logs
docker compose logs orchestrator | grep -i "infrastructure\|403"
```

### Metrics not arriving

```bash
# Prüfe ob STATS=1 gesetzt ist
docker compose exec docker-proxy env | grep STATS

# Prüfe Stats-Requests in Proxy-Logs
docker compose logs docker-proxy | grep -i "stats"
```

### Proxy won't start

```bash
# Prüfe Docker-Socket-Berechtigungen
ls -la /var/run/docker.sock

# Prüfe ob Docker läuft
docker ps

# Prüfe Proxy-Logs
docker compose logs docker-proxy
```

## Further Information

- [tecnativa/docker-socket-proxy on Docker Hub](https://hub.docker.com/r/tecnativa/docker-socket-proxy)
- [Docker Engine API Documentation](https://docs.docker.com/engine/api/)
