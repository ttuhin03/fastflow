---
sidebar_position: 6
---

# Log-Backup (S3/MinIO)

Pipeline-Logs und Metrics werden vor der **lokalen Löschung** (Cleanup) auf einen S3-kompatiblen Speicher (z.B. MinIO) hochgeladen. Lokale Dateien und DB-Einträge werden **nur bei erfolgreichem S3-Upload** gelöscht. Der Upload nutzt Streams (`upload_fileobj`), um den Speicherverbrauch gering zu halten.

## Wann wird was gesichert?

### Was wird hochgeladen?

- **Log-Datei** (`run.log_file`) → `{S3_PREFIX}/{pipeline_name}/{run_id}/run.log`
- **Metrics-Datei** (`run.metrics_file`), falls vorhanden → `{S3_PREFIX}/{pipeline_name}/{run_id}/metrics.jsonl`

Zusätzlich werden Metadaten (z.B. `pipeline_name`, `run_id`, `started_at`, `status`, `triggered_by`) als S3-Objekt-Metadaten mitgegeben.

### Wann läuft das Backup?

Backup (und danach lokales Löschen) erfolgt **nur**, wenn der Cleanup einen Run zur **Löschung** vorsieht – nicht beim bloßen Kürzen (Truncate) von Dateien.

| Szenario | Bedingung | Ablauf |
|----------|-----------|--------|
| **Retention: Anzahl Runs** (`LOG_RETENTION_RUNS`) | Pro Pipeline gibt es mehr Runs als erlaubt; die **ältesten** (nach `started_at`) sollen gelöscht werden. | Pro betroffenem Run: 1) S3-Backup von Log (+ ggf. Metrics), 2) bei Erfolg: lokale Dateien löschen und DB-Eintrag entfernen. |
| **Retention: Alter in Tagen** (`LOG_RETENTION_DAYS`) | Run ist **älter als X Tage** (`started_at` vor Cutoff). | Wie oben: Backup → bei Erfolg löschen. |
| **Oversized Logs** (`LOG_MAX_SIZE_MB`) | Log-Datei ist **größer als X MB** und das **Kürzen (Truncate)** schlägt mit einer Exception fehl. | 1) S3-Backup, 2) bei Erfolg: lokale Dateien löschen, `log_file`/`metrics_file` in der DB auf `NULL` setzen (Run bleibt). |

**Kein Backup** (Löschung wie bisher ohne S3):

- S3-Backup ist **deaktiviert** oder nicht konfiguriert (`S3_BACKUP_ENABLED=false` oder fehlende Endpoint/Bucket/Keys).
- Es gibt **weder Log- noch Metrics-Datei** (nichts zu sichern).
- Beim **Oversized-Logs**-Fall: Wenn das **Truncate gelingt**, wird nur gekürzt, nicht gelöscht → kein Backup.

### Wann wird der Cleanup ausgeführt?

- **Geplant:** z.B. täglich um 2:00 Uhr (Scheduler).
- **Manuell:** `POST /api/settings/cleanup/force`.

## Fall 4: S3-Upload schlägt fehl

Wenn S3-Backup **aktiv und konfiguriert** ist, mindestens eine Log- oder Metrics-Datei existiert und der **S3-Upload fehlschlägt** (Netzwerk, Credentials, Bucket, 4xx/5xx):

- **Löschung wird nicht durchgeführt:** Weder `_delete_run_files` noch DB-Delete/Update für diesen Run. Die lokalen Dateien und der Run bleiben erhalten. Beim nächsten Cleanup-Lauf wird ein erneuter Backup-Versuch gemacht.
- **UI-Benachrichtigung:** Die Fehlermeldung erscheint im **Benachrichtigungszentrum** (Glocke) und als **Toast**. Die Einträge stammen von `GET /api/settings/backup-failures`; die Einstellungsseite pollt diesen Endpoint in regelmäßigen Abständen.
- **E-Mail:** Es wird eine **E-Mail an alle `EMAIL_RECIPIENTS`** gesendet (falls `EMAIL_ENABLED`, SMTP und `EMAIL_RECIPIENTS` konfiguriert sind).
- **Microsoft Teams:** Dieselbe Meldung wird an den konfigurierten **Teams-Webhook** gesendet (falls `TEAMS_ENABLED` und `TEAMS_WEBHOOK_URL` gesetzt sind).

Damit E-Mails bei Backup-Fehlern an alle gehen: `EMAIL_ENABLED`, `SMTP_HOST`, `SMTP_FROM`, `EMAIL_RECIPIENTS` (und ggf. `SMTP_USER`/`SMTP_PASSWORD`). Für Teams: `TEAMS_ENABLED`, `TEAMS_WEBHOOK_URL` (siehe [Konfiguration – Benachrichtigungen](CONFIGURATION.md#benachrichtigungen-optional)).

## Konfiguration

Siehe [Konfiguration – Log-Backup (S3/MinIO)](CONFIGURATION.md#log-backup-s3minio-optional).

MinIO-Beispiel in `.env`:

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

- **`GET /api/settings/backup-failures`** (auth. erforderlich): Liefert die letzten S3-Backup-Fehler (`run_id`, `pipeline_name`, `error_message`, `created_at`). Wird vom Frontend für die UI-Benachrichtigungen genutzt. Die Liste ist in-memory, begrenzt und geht beim Neustart verloren.
