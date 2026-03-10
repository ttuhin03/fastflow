# FastFlow: Potentielle Bugs & Probleme

> Automatisierte Code-Analyse — erstellt am 2026-03-10
> Drei parallele Analysen: Executor/Core, API/Security, Services/Scheduler

---

## KRITISCH

### 1. Race Condition: Pipeline-Cache ohne Lock
**Datei:** `app/services/pipeline_discovery.py` (Zeilen 448–731)
- `_pipeline_cache` und `_cache_timestamp` sind globale Variablen **ohne** Mutex/Lock
- Gleichzeitige Aufrufe von `discover_pipelines()` und `invalidate_cache()` können inkonsistente Pipeline-Listen erzeugen
- Besonders kritisch bei Git-Sync + laufenden Runs

### 2. Race Condition: Git-Sync Lock zu früh freigegeben
**Datei:** `app/git_sync/sync.py` (Zeilen 473–518)
- `async with _sync_lock:` wird freigegeben **bevor** `invalidate_cache()`, Scheduler-Sync und Pre-Heating aufgerufen werden
- Zwischen Lock-Release und Cache-Invalidierung können Runs mit veralteten Pipeline-Daten starten

### 3. IDOR: Fehlende Berechtigungsprüfung bei Log-Downloads
**Datei:** `app/api/logs.py` (Zeilen 63–77)
- `get_logs_download_url` erstellt ein Download-Token für jede `run_id`, ohne zu prüfen, ob der anfragende User Zugriff auf diesen Run hat
- Jeder authentifizierte User kann Logs von beliebigen Runs anderer User herunterladen
- Angriffsszenario: Run-IDs durchnummerieren → alle Logs lesen

### 4. Race Condition: Scheduler-Doppelausführung bei Multi-Instance
**Datei:** `app/services/scheduler.py` (Zeilen 55–61, 135–166)
- Grace-Period-Mechanismus ist pro-Instanz lokal (`_scheduler_started_at`)
- Bei Rolling Restarts oder mehreren Instanzen können Jobs mehrfach parallel ausgeführt werden
- APSchedulers SQLAlchemyJobStore verhindert dies nicht automatisch

---

## HOCH

### 5. SSH-Key-Datei: Berechtigungen zu spät gesetzt (TOCTOU)
**Datei:** `app/git_sync/sync.py` (Zeilen 36–64)
- `os.mkstemp()` erstellt die Datei → Inhalt wird geschrieben → Datei geschlossen → **erst dann** `chmod 0o600`
- Zeitfenster, in dem der SSH-Key von anderen Prozessen lesbar ist
- Fix: `os.open()` mit `O_CREAT | O_WRONLY` und `mode=0o600` verwenden

### 6. JWT Token-Typ wird nicht validiert
**Datei:** `app/auth/auth.py` (Zeilen 88–112)
- `verify_token()` prüft **nicht** `payload.get("type")`
- Ein Log-Download-Token (`type: "log_download"`) könnte zur allgemeinen Authentifizierung missbraucht werden

### 7. Fehlende Rate-Limiting auf Log-Download-Endpoint
**Datei:** `app/api/logs.py`
- `GET /{run_id}/logs/download-url` hat **kein** `@limiter.limit()`-Decorator
- Andere sensible Endpoints sind geschützt (`/dependencies`: 15/min, `/webhooks/...`: 30/min)
- Erlaubt Enumeration aller Run-IDs ohne Gegenwehr

### 8. SMTP-Verbindung wird bei Exception nicht geschlossen
**Datei:** `app/services/notifications.py` (Zeilen 260–270)
- `smtp.connect()` wird aufgerufen, aber ohne `async with`-Context-Manager
- Bei Exception zwischen `connect()` und `quit()` bleibt die Verbindung offen (Connection Leak)
- Fix: `async with aiosmtplib.SMTP(...) as smtp:` verwenden

### 9. Benachrichtigungen: Fire-and-Forget ohne Fehlerbehandlung
**Datei:** `app/services/notifications.py` (Zeile 197)
- `asyncio.create_task(_send_notifications_async(...))` wird nicht awaited
- Fehlschläge (SMTP-Timeout, Teams-Webhook down) gehen lautlos verloren
- Kein Retry-Mechanismus für transiente Fehler

---

## MITTEL

### 10. Session-Generator wird nicht geschlossen (Resource Leak)
**Dateien:** `app/startup.py`, `app/services/scheduler.py`, `app/services/cleanup.py`
- Muster: `session_gen = get_session(); session = next(session_gen)` — Generator wird nie mit `.close()` beendet
- Kumulativer Datenbankressourcen-Leak über die Laufzeit

### 11. S3-Backup-Fehler hinterlässt verwaiste Runs
**Datei:** `app/services/cleanup.py` (Zeilen 147–164, 197–217)
- Bei S3-Fehler: `continue` überspringt Löschung → Run und Log-Dateien bleiben dauerhaft bestehen
- Notification via `asyncio.create_task` (fire-and-forget) → kann ebenfalls verloren gehen

### 12. Log-Datei Race Condition in Cleanup
**Datei:** `app/services/cleanup.py` (Zeilen 241–275)
- `log_file_path.exists()` → danach `log_file_path.stat().st_size`
- Zwischen beiden Calls kann die Datei von einem anderen Prozess gelöscht werden → `FileNotFoundError`

### 13. Dependency-Audit: File-basierter Cache ohne Lock
**Datei:** `app/services/dependency_audit.py` (Zeilen 58–69, 100–105)
- `_save_audit_to_file()` öffnet die Datei im Write-Mode **ohne** File-Lock
- Gleichzeitige Writes überschreiben sich gegenseitig

### 14. Fehlende Validierung: start_date ≤ end_date im Scheduler
**Dateien:** `app/api/scheduler.py` (Zeilen 181–182), `app/services/scheduler.py` (Zeilen 619–622)
- Ungültige Datumsbereiche (start > end) werden akzeptiert und erst von APScheduler zur Laufzeit abgelehnt

### 15. X-Forwarded-For Rate-Limit Bypass
**Datei:** `app/middleware/rate_limiting.py` (Zeilen 27–45)
- Bei `PROXY_HEADERS_TRUSTED=True` ohne tatsächlichen Proxy kann Angreifer den Header fälschen
- Rate-Limit wird effektiv umgangen

---

## NIEDRIG

### 16. Container-Cleanup unterdrückt Exceptions
**Datei:** `app/executor/core.py` (Zeilen 1080–1085)
- Fehler beim Docker-Container-Löschen werden ignoriert (`pass`-equivalent)
- Verwaiste Container akkumulieren sich über Zeit

### 17. CRON-Validierung unvollständig
**Dateien:** `app/services/scheduler.py`, `app/services/dependency_audit.py`
- Nur die Anzahl der Parts (5) wird geprüft, nicht die Wertebereiche
- `"0 99 * * *"` (ungültige Stunde) wird durchgelassen → APScheduler-Fehler erst zur Laufzeit

### 18. Downstream-Trigger prüft Pipeline-Existenz nicht
**Datei:** `app/services/downstream_triggers.py` (Zeilen 48–68)
- Wenn eine in `pipeline.json` referenzierte Pipeline nicht existiert, schlägt der Trigger mit vager Fehlermeldung fehl

---

## Empfohlene Fix-Reihenfolge

| Priorität | Bug | Aufwand |
|-----------|-----|---------|
| 1 | IDOR Log-Download (#3) | Klein |
| 2 | SSH-Key TOCTOU (#5) | Klein |
| 3 | JWT Token-Typ-Validierung (#6) | Klein |
| 4 | Rate-Limit auf Log-Endpoints (#7) | Klein |
| 5 | SMTP Context-Manager (#8) | Klein |
| 6 | CRON-Validierung verbessern (#17) | Klein |
| 7 | Pipeline-Cache Lock (#1) | Mittel |
| 8 | Git-Sync Lock-Scope erweitern (#2) | Mittel |
| 9 | Session-Generator schließen (#10) | Mittel |
| 10 | Scheduler Multi-Instance Grace Period (#4) | Groß |
