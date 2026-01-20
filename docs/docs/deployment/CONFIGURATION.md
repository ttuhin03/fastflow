---
sidebar_position: 1
---

# ⚙️ Konfiguration

Fast-Flow wird primär über Environment-Variablen in einer `.env` Datei konfiguriert. Diese Datei sollte im Root-Verzeichnis des Projekts liegen (basierend auf `.env.example`).

## Globale Einstellungen

| Variable | Standardwert | Beschreibung |
|----------|--------------|--------------|
| `ENVIRONMENT` | `development` | Setzt den Modus (`development` oder `production`). In `production` werden unsichere Standardwerte (z.B. `JWT_SECRET_KEY`) blockiert. |

## Datenbank

| Variable | Standardwert | Beschreibung |
|----------|--------------|--------------|
| `DATABASE_URL` | *Leer* (SQLite) | Verbindungs-String für die Datenbank. Wenn leer, wird SQLite (`./data/fastflow.db`) verwendet. Für PostgreSQL: `postgresql://user:password@host:5432/dbname`. |

## Verzeichnisse

| Variable | Standardwert | Beschreibung |
|----------|--------------|--------------|
| `PIPELINES_DIR` | `./pipelines` | Pfad zum Git-Repository mit den Pipeline-Skripten. |
| `LOGS_DIR` | `./logs` | Pfad für persistente Log-Dateien. |
| `DATA_DIR` | `./data` | Pfad für SQLite-DB und andere Daten. |
| `UV_CACHE_DIR` | `./data/uv_cache` | Pfad für den globalen `uv` Cache (shared zwischen Containern). |

## Docker & Executor

| Variable | Standardwert | Beschreibung |
|----------|--------------|--------------|
| `WORKER_BASE_IMAGE` | `ghcr.io/astral-sh/uv...` | Das Basis-Image für alle Pipeline-Container (muss `uv` enthalten). |
| `MAX_CONCURRENT_RUNS` | `10` | Maximale Anzahl gleichzeitig laufender Pipelines. |
| `CONTAINER_TIMEOUT` | *Leer* (Kein Timeout) | Globales Timeout für Pipeline-Runs in Sekunden. |
| `RETRY_ATTEMPTS` | `0` | Standard-Anzahl an Wiederholungsversuchen bei Fehlschlag. |

## Git Sync

| Variable | Standardwert | Beschreibung |
|----------|--------------|--------------|
| `GIT_BRANCH` | `main` | Der Git-Branch, der synchronisiert werden soll. |
| `AUTO_SYNC_ENABLED` | `false` | Ob Pipelines automatisch synchronisiert werden sollen. |
| `AUTO_SYNC_INTERVAL` | *Leer* | Intervall in Sekunden für den automatischen Sync. |
| `UV_PRE_HEAT` | `true` | Ob Dependencies beim Sync automatisch vorinstalliert ("aufgewärmt") werden sollen. |

## Logs & Retention

| Variable | Standardwert | Beschreibung |
|----------|--------------|--------------|
| `LOG_RETENTION_RUNS` | *Leer* (Unbegrenzt) | Maximale Anzahl an Runs, die pro Pipeline behalten werden. Ältere werden gelöscht. |
| `LOG_RETENTION_DAYS` | *Leer* (Unbegrenzt) | Logs, die älter als X Tage sind, werden gelöscht. |
| `LOG_MAX_SIZE_MB` | *Leer* (Unbegrenzt) | Maximale Größe einer Log-Datei in MB. |
| `LOG_STREAM_RATE_LIMIT`| `100` | Maximale Anzahl an Log-Zeilen pro Sekunde für das Live-Streaming (SSE). |

## Log-Backup (S3/MinIO, optional)

Pipeline-Logs werden vor der lokalen Löschung (Cleanup) auf S3/MinIO gesichert. Details: [S3 Log-Backup](S3_LOG_BACKUP.md).

| Variable | Standardwert | Beschreibung |
|----------|--------------|--------------|
| `S3_BACKUP_ENABLED` | `false` | Aktiviert S3-Backup vor lokaler Löschung. |
| `S3_ENDPOINT_URL` | *Leer* | S3-Endpoint (z.B. `http://minio:9000`). |
| `S3_BUCKET` | *Leer* | Bucket-Name. |
| `S3_ACCESS_KEY` | *Leer* | Access Key. |
| `S3_SECRET_ACCESS_KEY` | *Leer* | Secret Access Key. |
| `S3_REGION` | `us-east-1` | Region (MinIO oft egal). |
| `S3_PREFIX` | `pipeline-logs` | Prefix für Objektkeys. |
| `S3_USE_PATH_STYLE` | `true` | Path-Style-URLs (für MinIO typisch). |

## Sicherheit & Authentifizierung

> [!IMPORTANT]
> Diese Werte sind KRITISCH für die Sicherheit, besonders bei Docker-Socket Zugriff.

| Variable | Standardwert | Beschreibung | Produktion |
|----------|--------------|--------------|------------|
| `ENCRYPTION_KEY` | *Muss gesetzt werden* | Fernet-Key zur Verschlüsselung von Secrets in der DB. Generieren mit: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | **Pflicht** |
| `JWT_SECRET_KEY` | `change-me-in-production` | Secret Key zum Signieren und Verifizieren der JWT-Tokens. Muss lang und zufällig sein (mind. 32 Zeichen). In Produktion: eigener Wert, `change-me-in-production` wird blockiert. | **Pflicht** |
| `JWT_ALGORITHM` | `HS256` | Algorithmus für die JWT-Signatur (typisch: HS256). | HS256 |
| `JWT_ACCESS_TOKEN_MINUTES` | `15` | Gültigkeitsdauer des Access-Tokens in Minuten (Laufzeit des JWT, `exp`-Claim). Kürzere Laufzeit reduziert das Risiko bei kompromittierten Tokens. | 15 |
| `JWT_EXPIRATION_HOURS` | `24` | Gültigkeitsdauer der Session in der DB in Stunden. Nach Ablauf erscheint „Sitzung abgelaufen“; Re-Login nötig. | 24 |
| `GITHUB_CLIENT_ID` | *Leer* | OAuth App Client ID (GitHub). | **Pflicht** (oder Google) |
| `GITHUB_CLIENT_SECRET` | *Leer* | OAuth App Client Secret (GitHub). | **Pflicht** (oder Google) |
| `GOOGLE_CLIENT_ID` | *Leer* | OAuth 2.0 Client ID (Google). Callback: `{BASE_URL}/api/auth/google/callback`. | Optional |
| `GOOGLE_CLIENT_SECRET` | *Leer* | OAuth 2.0 Client Secret (Google). | Optional |
| `SKIP_OAUTH_VERIFICATION` | *Leer* | `1`/`true`: HTTP-Verifizierung der OAuth-Credentials beim Start überspringen (z.B. CI/Tests). Die Prüfung „mind. ein Provider vollständig“ bleibt aktiv. | Optional |
| `INITIAL_ADMIN_EMAIL` | *Leer* | E-Mail des ersten Admins (Zutritt ohne Einladung, GitHub oder Google). | **Empfohlen** |
| `FRONTEND_URL` / `BASE_URL` | s. [OAuth (GitHub & Google)](/docs/oauth/readme) | Für OAuth-Callback und Einladungs-Links. | Anpassen |

**OAuth beim Start:** Es muss mindestens ein OAuth-Provider (GitHub oder Google) vollständig konfiguriert sein (jeweils `CLIENT_ID` und `CLIENT_SECRET`). Ohne dies startet die App nicht. Beim Start werden die gesetzten Credentials per Request an den jeweiligen Anbieter verifiziert; bei ungültigen Werten oder Redirect-URI-Mismatch startet die App ebenfalls nicht.

## GitHub Apps (Optional)

Für die Authentifizierung bei privaten GitHub Repositories via GitHub App.

| Variable | Beschreibung |
|----------|--------------|
| `GITHUB_APP_ID` | Die App ID der GitHub App. |
| `GITHUB_INSTALLATION_ID`| Die Installations-ID der App (siehe URL nach Installation). |
| `GITHUB_PRIVATE_KEY_PATH`| Pfad zur `.pem` Datei mit dem Private Key der App. |

## Benachrichtigungen (Optional)

| Variable | Beschreibung |
|----------|--------------|
| `EMAIL_ENABLED` | `true` oder `false` |
| `SMTP_HOST` | SMTP Server Hostname |
| `SMTP_PORT` | SMTP Port (z.B. 587) |
| `EMAIL_RECIPIENTS` | Kommagetrennte Liste der Empfänger |
| `TEAMS_ENABLED` | `true` oder `false` |
| `TEAMS_WEBHOOK_URL`| Webhook URL für Microsoft Teams Channel |
