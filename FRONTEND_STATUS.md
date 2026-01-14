# React-Frontend Status

## ✅ Implementiert

### Grundstruktur
- ✅ React + TypeScript Setup mit Vite
- ✅ React Router für Navigation
- ✅ React Query für API-Requests
- ✅ Axios-Client mit Auth-Interceptors
- ✅ Auth-Context für Login/Logout
- ✅ Layout-Komponente mit Navigation

### Seiten (Basis)
- ✅ Login-Seite
- ✅ Dashboard (Pipeline-Übersicht mit Statistiken)
- ✅ Pipelines-Seite (Liste)
- ✅ Runs-Seite (Tabelle)
- ✅ Run-Detail-Seite (Basis)
- ✅ Scheduler-Seite (Platzhalter)
- ✅ Secrets-Seite (Platzhalter)
- ✅ Sync-Seite (Platzhalter)

## ❌ Noch zu implementieren

### Dashboard (Phase 13.2)
- ❌ Pipeline-Start-Button für jede Pipeline
- ❌ Pipeline-Status mit Details (letzter Run, Cache-Status, etc.)
- ❌ Pipeline-An/Ausschalten-Toggle
- ❌ Git-Sync-Button
- ❌ Git-Sync-Status-Anzeige
- ❌ Quick-Actions (Pipeline starten, Logs ansehen, Details)

### Runs (Phase 13.3)
- ❌ Filterung nach Pipeline-Name, Status, Zeitraum
- ❌ Sortierung nach Datum
- ❌ Vollständige Run-Detailansicht:
  - ❌ Exit-Code, UV-Version, Setup-Duration
  - ❌ Environment-Variablen (Secrets ausgeblendet)
  - ❌ Container-Status, Health-Status
  - ❌ Cancel-Button für laufende Runs
  - ❌ Retry-Button für fehlgeschlagene Runs

### Live-Log-Viewer (Phase 13.4)
- ❌ SSE-Streaming für Live-Logs
- ❌ Log-Anzeige mit Auto-Scroll
- ❌ Log-Filterung/Suche
- ❌ Log-Download-Button
- ❌ Re-Connect-Handling

### Metrics-Monitoring (Phase 13.4)
- ❌ Live-Metrics-Streaming (SSE)
- ❌ CPU/RAM Charts (Line-Charts)
- ❌ Soft-Limit-Warnungen
- ❌ Metrics-Download

### Secrets-Management (Phase 13.5)
- ❌ Tabelle mit allen Secrets
- ❌ Formular zum Hinzufügen/Bearbeiten
- ❌ Secret vs. Parameter Flag
- ❌ Delete mit Bestätigung

### Scheduler (Phase 13.6)
- ❌ Liste aller Jobs
- ❌ Formular zum Erstellen (Cron/Interval)
- ❌ Enable/Disable-Toggle
- ❌ Job-Edit/Delete
- ❌ Job-Details (nächste Ausführung, Historie)

### Git-Sync (Phase 13.8)
- ❌ Sync-Status-Anzeige
- ❌ Manueller Sync-Trigger
- ❌ Sync-Einstellungen
- ❌ Sync-Logs

### Pipeline-Management (Phase 13.9)
- ❌ Pipeline-Details-Seite
- ❌ Pipeline-Statistiken mit Reset
- ❌ Resource-Limits-Anzeige
- ❌ Pipeline-Aktionen (starten, logs, stats)

### Allgemeine Features (Phase 13.7)
- ❌ Auto-Refresh für Run-Status
- ❌ Toast-Notifications
- ❌ Loading-States
- ❌ Responsive Design

## Nächste Schritte

1. **Priorität 1**: Pipeline-Start-Funktionalität im Dashboard
2. **Priorität 2**: Live-Log-Viewer mit SSE
3. **Priorität 3**: Run-Detailansicht vollständig
4. **Priorität 4**: Secrets-Management-UI
5. **Priorität 5**: Scheduler-UI
6. **Priorität 6**: Git-Sync-UI
