# FastFlow: Potentielle Bugs & Probleme

> Automatisierte Code-Analyse — erstellt am 2026-03-10, manuell verifiziert
> Drei parallele Analysen: Executor/Core, API/Security, Services/Scheduler

---

## KRITISCH

### 1. Race Condition: Pipeline-Cache ohne Lock ✅ behoben
**Datei:** `app/services/pipeline_discovery.py`
- `_pipeline_cache` und `_cache_timestamp` waren globale Variablen ohne `threading.Lock`
- **Behoben:** `_cache_lock = threading.Lock()` schützt jetzt alle Lese-/Schreibzugriffe

### ~~2. Race Condition: Git-Sync Lock zu früh freigegeben~~ *(kein echtes Problem)*
**Datei:** `app/git_sync/sync.py`
- `invalidate_cache()`, Scheduler-Sync und Pre-Heating laufen nachweislich **innerhalb** des `async with _sync_lock:` Blocks (Zeilen 518–534)

### ~~3. IDOR: Fehlende Berechtigungsprüfung bei Log-Downloads~~ *(kein echtes Problem)*
**Datei:** `app/api/logs.py`
- In FastFlow gibt es kein Ownership-Konzept für Runs — alle authentifizierten User haben ohnehin Zugriff auf alle Runs und Logs

### ~~4. Race Condition: Scheduler-Doppelausführung bei Multi-Instance~~ *(Architektur-Limitierung)*
**Datei:** `app/services/scheduler.py`
- FastFlow ist auf Single-Instance ausgelegt; kein Horizontal Scaling in der Doku vorgesehen
- Grace-Period-Mechanismus deckt den typischen Restart-Fall ab

---

## HOCH

### ~~5. SSH-Key-Datei: Berechtigungen zu spät gesetzt (TOCTOU)~~ *(kein echtes Problem)*
**Datei:** `app/git_sync/sync.py`
- `tempfile.mkstemp()` erstellt Dateien intern via `os.open(..., 0o600)` — Berechtigungen sind von der ersten Nanosekunde korrekt

### ~~6. JWT Token-Typ wird nicht validiert~~ *(kein echtes Problem)*
**Datei:** `app/auth/auth.py`
- `get_current_user` prüft nach `verify_token()` zusätzlich `get_session_by_token()` gegen die DB
- Log-Download-Tokens werden nie in der `SessionModel`-Tabelle gespeichert → kein Missbrauch möglich

### ~~7. Fehlende Rate-Limiting auf Log-Download-Endpoint~~ *(kein echtes Problem)*
**Datei:** `app/api/logs.py`
- Globales `default_limits=["200/minute"]` gilt für alle API-Routen inkl. diesem Endpoint

### 8. SMTP-Verbindung wird bei Exception nicht geschlossen
**Datei:** `app/services/notifications.py` (Zeilen 260–270)
- `smtp.connect()` ohne `async with`-Context-Manager, kein `try/finally` um `smtp.quit()`
- Bei Exception zwischen `login()` und `quit()` bleibt die Verbindung offen
- **Fix:** `async with aiosmtplib.SMTP(...) as smtp:` verwenden

### ~~9. Benachrichtigungen: Fire-and-Forget ohne Fehlerbehandlung~~ *(kein echtes Problem)*
**Datei:** `app/services/notifications.py`
- Intentionales Design (Kommentar: "nicht blockierend")
- `_send_notifications_async` loggt alle Fehler — nichts geht wirklich lautlos verloren

---

## MITTEL

### ~~10. Session-Generator wird nicht geschlossen~~ *(kein echtes Problem)*
**Dateien:** `app/startup.py`, `app/services/scheduler.py`, `app/services/cleanup.py`
- In allen Call-Sites wird `session.close()` im `finally`-Block aufgerufen, was die Verbindung sofort an den Pool zurückgibt
- CPython GC finalisiert den Generator danach deterministisch

### 11. S3-Backup-Fehler hinterlässt verwaiste Runs
**Datei:** `app/services/cleanup.py` (Zeilen 147–164, 197–217)
- Bei dauerhaftem S3-Fehler: `continue` überspringt Löschung → Runs und Log-Dateien akkumulieren unbegrenzt
- Kein Maximal-Alter oder manuelle Override-Möglichkeit im Fehlerfall

### 12. Log-Datei Race Condition in Cleanup *(trivial)*
**Datei:** `app/services/cleanup.py` (Zeilen 241–275)
- `log_file_path.exists()` → `log_file_path.stat().st_size` — theoretisches TOCTOU
- Praktisch unbedenklich: wird vom `except Exception` auf Zeile 278 abgefangen; schlimmstfall: Run beim nächsten Cleanup-Lauf erneut versucht

### ~~13. Dependency-Audit: File-basierter Cache ohne Lock~~ *(kein echtes Problem)*
**Datei:** `app/services/dependency_audit.py`
- APScheduler führt Jobs mit gleicher ID niemals gleichzeitig aus (`max_instances=1` by default)
- Startup-Audit + geplanter Audit zur exakt gleichen Zeit wäre das einzige Szenario — und das Ergebnis wären identische Daten

### 14. Fehlende Validierung: start_date ≤ end_date im Scheduler
**Dateien:** `app/api/scheduler.py` (Zeilen 181–182), `app/services/scheduler.py`
- APScheduler akzeptiert ungültige Datumsbereiche ohne Fehler — der Job wird nie ausgeführt, ohne Hinweis für den User

### ~~15. X-Forwarded-For Rate-Limit Bypass~~ *(Konfigurationsrisiko, kein Code-Bug)*
**Datei:** `app/middleware/rate_limiting.py`
- Der Code ist korrekt und gut dokumentiert — `PROXY_HEADERS_TRUSTED=True` ohne tatsächlichen Proxy ist ein Ops-Fehler

---

## NIEDRIG

### 16. Container-Cleanup: fehlende Container-ID im Warning ✅ behoben
**Datei:** `app/executor/core.py`
- **Behoben:** Warning-Meldung enthält jetzt Container-ID und `docker rm -f <id>` Befehl

### 17. CRON-Validierung unvollständig ✅ behoben
**Dateien:** `app/services/scheduler.py`, `app/services/dependency_audit.py`
- **Behoben:** `_validate_cron_parts()` prüft Wertebereiche vor Übergabe an APScheduler

### 18. Downstream-Trigger prüft Pipeline-Existenz nicht ✅ behoben
**Datei:** `app/services/downstream_triggers.py`
- **Behoben:** Existenzprüfung via `get_pipeline()` in der `add()`-Funktion

---

## Verbleibende echte Probleme

| # | Problem | Aufwand |
|---|---------|---------|
| 8 | SMTP Connection Leak in notifications.py | Klein |
| 11 | S3-Backup-Fehler → verwaiste Runs | Mittel |
| 12 | Log-Datei Race Condition in Cleanup | Trivial |
| 14 | start_date > end_date im Scheduler (stiller Fehler) | Klein |
