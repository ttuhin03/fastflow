# Datenbank-Schema

Fast-Flow verwendet **SQLModel** (basierend auf SQLAlchemy) als ORM. Standardmäßig wird **SQLite** verwendet, aber **PostgreSQL** wird vollständig unterstützt.

## Tables (Modelle)

### 1. `Pipeline` (Metadaten)

Speichert statische Informationen über entdeckte Pipelines.

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `pipeline_name` | String (PK) | Einzigartiger Name der Pipeline (entspricht Verzeichnisname). |
| `has_requirements` | Boolean | Gibt an, ob eine `requirements.txt` gefunden wurde. |
| `last_cache_warmup` | DateTime | Zeitstempel des letzten erfolgreichen `uv pip compile`. |
| `total_runs` | Integer | Gesamtanzahl der Runs. |
| `successful_runs` | Integer | Anzahl erfolgreicher Runs. |
| `failed_runs` | Integer | Anzahl fehlgeschlagener Runs. |
| `enabled` | Boolean | Ob die Pipeline aktiviert ist (aus `pipeline.json`). |
| `metadata` | JSON | Zusätzliche Metadaten aus `pipeline.json` (Limits, Description, Tags). |
| `webhook_runs` | Integer | Anzahl der durch Webhooks ausgelösten Runs. |

### 2. `PipelineRun` (Historie)

Speichert jeden einzelnen Ausführungsversuch einer Pipeline.

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `id` | UUID (PK) | Eindeutige ID des Runs. |
| `pipeline_name` | String (FK) | Referenz zur `Pipeline`. |
| `status` | Enum | `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `CANCELLED`. |
| `started_at` | DateTime | Startzeitpunkt. |
| `finished_at` | DateTime | Endzeitpunkt. |
| `exit_code` | Integer | Exit-Code des Containers (0 = Erfolg). |
| `log_file` | String | Pfad zur Log-Datei im Dateisystem. |
| `metrics_file` | String | Pfad zur Metrics-Datei im Dateisystem. |
| `env_vars` | JSON | Gesetzte Environment-Variablen (Secrets maskiert). |
| `parameters` | JSON | Übergebene Parameter. |
| `uv_version` | String | Verwendete Version von `uv`. |
| `setup_duration` | Float | Dauer des Environment-Setups in Sekunden. |
| `triggered_by` | String | Auslöser des Runs (z.B. "manual", "scheduler", "webhook"). |

### 3. `ScheduledJob` (Scheduler)

Speichert geplante Ausführungen für den APScheduler via `SQLAlchemyJobStore`.

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `id` | UUID (PK) | Eindeutige Job-ID. |
| `pipeline_name` | String (FK) | Die auszuführende Pipeline. |
| `trigger_type` | Enum | `CRON` oder `INTERVAL`. |
| `trigger_value` | String | Der Cron-String (z.B. `0 0 * * *`) oder Interval-Sekunden. |
| `enabled` | Boolean | Ob der Job aktiv ist. |
| `created_at` | DateTime | Erstellungsdatum. |

### 4. `Secret` (Konfiguration)

Speichert sensible Daten und Parameter.

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `key` | String (PK) | Name des Secrets/Parameters (z.B. `API_KEY`). |
| `value` | String | Der Wert. **WICHTIG**: Wird verschlüsselt gespeichert (Fernet). |
| `is_parameter` | Boolean | `true` = Parameter (unverschlüsselt/sichtbar), `false` = Secret (verschlüsselt). |
| `created_at` | DateTime | Erstellungsdatum. |
| `updated_at` | DateTime | Änderungsdatum. |

### 5. `User` (Authentifizierung)

Speichert Benutzer. Login via GitHub OAuth, Google OAuth (und Einladung).

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `id` | UUID (PK) | Eindeutige User-ID. |
| `username` | String | Benutzername (eindeutig, indexiert). |
| `email` | String | (Optional) E-Mail (von GitHub/Google oder manuell). |
| `role` | Enum | `ADMIN`, `WRITE`, `READONLY`. |
| `blocked` | Boolean | Ob der Benutzer gesperrt ist. |
| `github_id` | String | (Optional) GitHub OAuth ID (unique). |
| `google_id` | String | (Optional) Google OAuth ID (unique). |
| `avatar_url` | String | (Optional) Profilbild-URL von OAuth-Provider. |
| `microsoft_id` | String | (Optional) für zukünftige Microsoft-Auth (unique). |
| `created_at` | DateTime | Erstellungsdatum. |

### 6. `Invitation` (Einladungen)

Token-Einladungen für neue User (Einlösung via GitHub OAuth oder Google OAuth).

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `id` | UUID (PK) | Eindeutige ID. |
| `recipient_email` | String | E-Mail des Empfängers. |
| `token` | String | Einmal-Token (unique, in URL: `/invite?token=...`). |
| `is_used` | Boolean | Ob die Einladung bereits eingelöst wurde. |
| `expires_at` | DateTime | Ablauf der Gültigkeit. |
| `role` | Enum | Rolle des neuen Users. |
| `created_at` | DateTime | Erstellungsdatum. |

### 7. `Session` (Sessions)

Persistente Sessions (JWT-Token in DB).

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `id` | UUID (PK) | Eindeutige Session-ID. |
| `token` | String | JWT-Token (unique). |
| `user_id` | UUID (FK) | Referenz auf `users.id`. |
| `expires_at` | DateTime | Ablauf der Session. |
| `created_at` | DateTime | Erstellungsdatum. |

---

## Beziehungen

- Eine **Pipeline** kann viele **PipelineRuns** haben (1:n).
- Eine **Pipeline** kann viele **ScheduledJobs** haben (1:n).
- **Secrets** sind global verfügbar und werden bei Bedarf in Runs injiziert.
- Ein **User** kann viele **Sessions** haben (1:n).
- **Invitation** steht für sich; nach Einlösung wird ein neuer **User** mit der hinterlegten Rolle angelegt.

## Hinweise

- Alle Zeitstempel werden als **UTC** gespeichert.
- SQLite verwendet **WAL-Mode** (Write-Ahead Logging) für bessere Concurrency.
- JSON-Felder werden in SQLite als TEXT und in PostgreSQL als JSONB gespeichert.
