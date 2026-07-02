---
sidebar_position: 6
---

# Log Backup (S3/MinIO)

Pipeline logs and metrics are uploaded to S3-compatible storage (e.g. MinIO) before **local deletion** (cleanup). Local files and DB entries are **only deleted after a successful S3 upload**. The upload uses streams (`upload_fileobj`) to keep memory usage low.

## When is what backed up?

### What is uploaded?

- **Log file** (`run.log_file`) → `{S3_PREFIX}/{pipeline_name}/{run_id}/run.log`
- **Metrics file** (`run.metrics_file`), if present → `{S3_PREFIX}/{pipeline_name}/{run_id}/metrics.jsonl`

Additionally, metadata (e.g. `pipeline_name`, `run_id`, `started_at`, `status`, `triggered_by`) is attached as S3 object metadata.

### When does backup run?

Backup (and subsequent local deletion) happens **only** when cleanup schedules a run for **deletion**—not when files are merely truncated.

| Scenario | Condition | Flow |
|----------|-----------|------|
| **Retention: number of runs** (`LOG_RETENTION_RUNS`) | A pipeline has more runs than allowed; the **oldest** (by `started_at`) should be deleted. | Per affected run: 1) S3 backup of log (+ metrics if present), 2) on success: delete local files and remove DB entry. |
| **Retention: age in days** (`LOG_RETENTION_DAYS`) | Run is **older than X days** (`started_at` before cutoff). | As above: backup → delete on success. |
| **Oversized logs** (`LOG_MAX_SIZE_MB`) | Log file is **larger than X MB** and **truncation** fails with an exception. | 1) S3 backup, 2) on success: delete local files, set `log_file`/`metrics_file` to `NULL` in DB (run remains). |

**No backup** (deletion as before without S3):

- S3 backup is **disabled** or not configured (`S3_BACKUP_ENABLED=false` or missing endpoint/bucket/keys).
- There is **neither a log nor a metrics file** (nothing to back up).
- In the **oversized logs** case: if **truncation succeeds**, only truncation occurs, no deletion → no backup.

### When is cleanup executed?

- **Scheduled:** e.g. daily at 2:00 AM (scheduler).
- **Manual:** `POST /api/settings/cleanup/force`.

## Case 4: S3 upload fails

When S3 backup is **active and configured**, at least one log or metrics file exists, and the **S3 upload fails** (network, credentials, bucket, 4xx/5xx):

- **Deletion is not performed:** Neither `_delete_run_files` nor DB delete/update for that run. Local files and the run remain. On the next cleanup run, backup is retried.
- **UI notification:** The error message appears in the **notification center** (bell) and as a **toast**. Entries come from `GET /api/settings/backup-failures`; the settings page polls this endpoint at regular intervals.
- **Email:** An **email is sent to all `EMAIL_RECIPIENTS`** (if `EMAIL_ENABLED`, SMTP, and `EMAIL_RECIPIENTS` are configured).
- **Microsoft Teams:** The same message is sent to the configured **Teams webhook** (if `TEAMS_ENABLED` and `TEAMS_WEBHOOK_URL` are set).

For emails on backup failures to reach everyone: `EMAIL_ENABLED`, `SMTP_HOST`, `SMTP_FROM`, `EMAIL_RECIPIENTS` (and optionally `SMTP_USER`/`SMTP_PASSWORD`). For Teams: `TEAMS_ENABLED`, `TEAMS_WEBHOOK_URL` (see [Configuration – Notifications](CONFIGURATION.md#benachrichtigungen-optional)).

## Configuration

See [Configuration – Log Backup (S3/MinIO)](CONFIGURATION.md#log-backup-s3minio-optional).

### Via the Settings UI

Under **Settings → Pipeline & Runs**, you can set endpoint, bucket, region, prefix, path-style, and credentials (secrets are stored encrypted in the database). There is an **object path preview**, display of the last manual connection test, and optionally **"Automatically test connection after saving"**. The API endpoint for the test is `POST /api/settings/s3/test` (admin only).

### Via `.env` / deployment

MinIO example in `.env`:

```env
S3_BACKUP_ENABLED=true
S3_ENDPOINT_URL=http://minio:9000
S3_BUCKET=fastflow-logs
S3_ACCESS_KEY=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_PREFIX=pipeline-logs
S3_USE_PATH_STYLE=true
```

## API

- **`GET /api/settings/backup-failures`** (auth required): Returns recent S3 backup failures (`run_id`, `pipeline_name`, `error_message`, `created_at`). Used by the frontend for UI notifications. The list is in-memory, bounded, and lost on restart.
- **`POST /api/settings/s3/test`** (admin only): Tests the current S3 configuration (e.g. `HeadBucket`) and stores timestamp/status of the last test in `orchestrator_settings`.
