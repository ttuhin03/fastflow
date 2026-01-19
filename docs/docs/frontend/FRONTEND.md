# Frontend-Dokumentation

Diese Dokumentation beschreibt die Frontend-Struktur, Komponenten und Seiten des Fast-Flow Orchestrators.

## Technologie-Stack

- **React 18**: UI-Framework
- **TypeScript**: Typsicherheit
- **Vite**: Build-Tool und Dev-Server
- **React Router**: Routing
- **Axios**: HTTP-Client für API-Kommunikation
- **CSS Modules**: Styling

## Projektstruktur

```
frontend/
├── src/
│   ├── api/
│   │   └── client.ts          # Axios-Client mit Auth-Interceptors
│   ├── components/            # Wiederverwendbare Komponenten
│   │   ├── CalendarHeatmap.tsx
│   │   ├── Layout.tsx
│   │   ├── ProgressBar.tsx
│   │   ├── RunStatusCircles.tsx
│   │   ├── Skeleton.tsx
│   │   ├── StorageStats.tsx
│   │   ├── SystemMetrics.tsx
│   │   └── Tooltip.tsx
│   ├── contexts/
│   │   └── AuthContext.tsx     # Authentication Context
│   ├── pages/                 # Seiten-Komponenten
│   │   ├── AuthCallback.tsx
│   │   ├── Dashboard.tsx
│   │   ├── Invite.tsx
│   │   ├── Login.tsx
│   │   ├── PipelineDetail.tsx
│   │   ├── Pipelines.tsx
│   │   ├── RunDetail.tsx
│   │   ├── Runs.tsx
│   │   ├── Scheduler.tsx
│   │   ├── Secrets.tsx
│   │   ├── Settings.tsx
│   │   ├── Sync.tsx
│   │   └── Users.tsx
│   ├── styles/
│   │   ├── design-system.css  # Design-System (Farben, Typografie)
│   │   └── variables.css      # CSS-Variablen
│   ├── App.tsx                # Haupt-App-Komponente
│   └── main.tsx               # Entry-Point
```

## API-Client

### `src/api/client.ts`

Der API-Client ist ein konfigurierter Axios-Instanz mit automatischer Authentifizierung.

**Features:**
- Automatisches Hinzufügen des Authorization-Headers aus sessionStorage
- Automatische Weiterleitung zum Login bei 401-Fehlern
- Basis-URL konfigurierbar über `VITE_API_URL` (Standard: `http://localhost:8000/api`)

**Verwendung:**
```typescript
import apiClient from '@/api/client'

// GET-Request
const response = await apiClient.get('/pipelines')

// POST-Request
const response = await apiClient.post('/pipelines/pipeline_a/run', {
  env_vars: { API_KEY: 'secret' }
})
```

## Komponenten

### Layout

#### `Layout.tsx`

Haupt-Layout-Komponente mit Navigation und Sidebar.

**Features:**
- Responsive Sidebar mit Navigation
- Logout-Funktionalität
- Aktive Route-Hervorhebung

**Props:** Keine (verwendet React Router für Navigation)

### RunStatusCircles

#### `RunStatusCircles.tsx`

Visualisiert Run-Status mit farbigen Kreisen.

**Props:**
```typescript
interface RunStatusCirclesProps {
  runs: Array<{
    status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED'
  }>
}
```

**Status-Farben:**
- `PENDING`: Grau
- `RUNNING`: Blau
- `SUCCESS`: Grün
- `FAILED`: Rot
- `CANCELLED`: Orange

### ProgressBar

#### `ProgressBar.tsx`

Fortschrittsbalken-Komponente.

**Props:**
```typescript
interface ProgressBarProps {
  value: number        // 0-100
  max?: number         // Standard: 100
  label?: string       // Optionales Label
  color?: string       // Optional: CSS-Farbe
}
```

### CalendarHeatmap

#### `CalendarHeatmap.tsx`

Kalender-Heatmap zur Visualisierung von Run-Aktivitäten über die Zeit.

**Props:**
```typescript
interface CalendarHeatmapProps {
  data: Array<{
    date: string        // ISO-Format: YYYY-MM-DD
    value: number       // Anzahl Runs
  }>
  startDate?: string   // Optional: Startdatum
  endDate?: string     // Optional: Enddatum
}
```

**Features:**
- Farbcodierung basierend auf Aktivität
- Tooltip mit Details beim Hover
- Responsive Design

### SystemMetrics

#### `SystemMetrics.tsx`

Zeigt System-Metriken (CPU, RAM, Container) an.

**Props:**
```typescript
interface SystemMetricsProps {
  metrics: {
    active_containers: number
    containers_ram_mb: number
    containers_cpu_percent: number
    api_ram_mb: number
    api_cpu_percent: number
    system_ram_total_mb: number
    system_ram_used_mb: number
    system_ram_percent: number
    system_cpu_percent: number
    container_details: Array<{
      run_id: string
      pipeline_name: string
      ram_mb: number
      cpu_percent: number
    }>
  }
}
```

**Features:**
- Echtzeit-Updates (polling)
- Grafische Darstellung von CPU/RAM
- Container-Details-Tabelle

### StorageStats

#### `StorageStats.tsx`

Zeigt Speicherplatz-Statistiken an.

**Props:**
```typescript
interface StorageStatsProps {
  stats: {
    log_files_count: number
    log_files_size_mb: number
    total_disk_space_gb: number
    used_disk_space_gb: number
    free_disk_space_gb: number
    log_files_percentage: number
    database_size_mb?: number
  }
}
```

### Skeleton

#### `Skeleton.tsx`

Loading-Skeleton-Komponente für bessere UX während des Ladens.

**Props:**
```typescript
interface SkeletonProps {
  width?: string       // CSS-Breite (z.B. "100%", "200px")
  height?: string      // CSS-Höhe
  className?: string   // Zusätzliche CSS-Klassen
}
```

### Tooltip

#### `Tooltip.tsx`

Tooltip-Komponente für zusätzliche Informationen.

**Props:**
```typescript
interface TooltipProps {
  content: string | React.ReactNode
  children: React.ReactNode
  position?: 'top' | 'bottom' | 'left' | 'right'
}
```

## Seiten

### Dashboard

#### `pages/Dashboard.tsx`

Haupt-Dashboard mit Übersicht über alle Pipelines und System-Status.

**Features:**
- Pipeline-Übersicht mit Statistiken
- System-Metriken (CPU, RAM, Container)
- Speicherplatz-Statistiken
- Kalender-Heatmap für Run-Aktivitäten
- Quick-Actions (Pipeline starten, Sync ausführen)

**API-Endpoints:**
- `GET /api/pipelines` - Pipeline-Liste
- `GET /api/pipelines/daily-stats/all` - Tägliche Statistiken
- `GET /api/settings/system-metrics` - System-Metriken
- `GET /api/settings/storage` - Speicherplatz-Statistiken

### Pipelines

#### `pages/Pipelines.tsx`

Übersicht aller Pipelines mit Filtern und Aktionen.

**Features:**
- Pipeline-Liste mit Statistiken
- Filter nach Tags
- Pipeline starten
- Pipeline-Details öffnen
- Statistiken anzeigen

**API-Endpoints:**
- `GET /api/pipelines` - Pipeline-Liste
- `POST /api/pipelines/{name}/run` - Pipeline starten

### Pipeline Detail

#### `pages/PipelineDetail.tsx`

Detaillierte Ansicht einer einzelnen Pipeline.

**Features:**
- Pipeline-Informationen und Metadaten
- Run-Historie
- Tägliche Statistiken (Grafik)
- Pipeline starten mit Environment-Variablen
- Statistiken zurücksetzen

**API-Endpoints:**
- `GET /api/pipelines/{name}` - Pipeline-Details
- `GET /api/pipelines/{name}/runs` - Run-Historie
- `GET /api/pipelines/{name}/stats` - Statistiken
- `GET /api/pipelines/{name}/daily-stats` - Tägliche Statistiken
- `POST /api/pipelines/{name}/run` - Pipeline starten
- `POST /api/pipelines/{name}/stats/reset` - Statistiken zurücksetzen

### Runs

#### `pages/Runs.tsx`

Übersicht aller Runs mit Filtern und Pagination.

**Features:**
- Run-Liste mit Status
- Filter nach Pipeline, Status, Datum
- Pagination
- Run-Details öffnen
- Run abbrechen (für laufende Runs)

**API-Endpoints:**
- `GET /api/runs` - Run-Liste (mit Filtern)
- `POST /api/runs/{run_id}/cancel` - Run abbrechen

### Run Detail

#### `pages/RunDetail.tsx`

Detaillierte Ansicht eines einzelnen Runs.

**Features:**
- Run-Informationen (Status, Exit-Code, Dauer)
- Live-Logs (Server-Sent Events)
- Live-Metriken (CPU, RAM)
- Log-Download
- Run abbrechen (für laufende Runs)

**API-Endpoints:**
- `GET /api/runs/{run_id}` - Run-Details
- `GET /api/runs/{run_id}/logs` - Logs aus Datei
- `GET /api/runs/{run_id}/logs/stream` - Live-Logs (SSE)
- `GET /api/runs/{run_id}/metrics` - Metrics aus Datei
- `GET /api/runs/{run_id}/metrics/stream` - Live-Metrics (SSE)
- `POST /api/runs/{run_id}/cancel` - Run abbrechen

**Live-Updates:**
- Logs werden über Server-Sent Events (SSE) gestreamt
- Metrics werden alle 2 Sekunden aktualisiert
- Status wird regelmäßig gepollt

### Scheduler

#### `pages/Scheduler.tsx`

Verwaltung von geplanten Jobs.

**Features:**
- Job-Liste mit nächstem Ausführungszeitpunkt
- Job erstellen (CRON oder Interval)
- Job bearbeiten
- Job löschen
- Job aktivieren/deaktivieren
- Run-Historie pro Job

**API-Endpoints:**
- `GET /api/scheduler/jobs` - Job-Liste
- `POST /api/scheduler/jobs` - Job erstellen
- `PUT /api/scheduler/jobs/{job_id}` - Job aktualisieren
- `DELETE /api/scheduler/jobs/{job_id}` - Job löschen
- `GET /api/scheduler/jobs/{job_id}/runs` - Run-Historie

**Trigger-Typen:**
- **CRON**: Cron-Expression (z.B. `"0 0 * * *"` für täglich um Mitternacht)
- **INTERVAL**: Interval in Sekunden (z.B. `"3600"` für stündlich)

### Secrets

#### `pages/Secrets.tsx`

Verwaltung von Secrets und Parametern.

**Features:**
- Secret-Liste
- Secret erstellen/bearbeiten/löschen
- Unterscheidung zwischen Secrets (verschlüsselt) und Parametern (unverschlüsselt)
- Secret-Werte anzeigen/verstecken

**API-Endpoints:**
- `GET /api/secrets` - Secret-Liste
- `POST /api/secrets` - Secret erstellen
- `PUT /api/secrets/{key}` - Secret aktualisieren
- `DELETE /api/secrets/{key}` - Secret löschen

**Hinweise:**
- Secrets werden verschlüsselt gespeichert
- Parameter werden unverschlüsselt gespeichert
- Secret-Werte können in der UI angezeigt/versteckt werden

### Settings

#### `pages/Settings.tsx`

System-Einstellungen und Konfiguration.

**Features:**
- Einstellungen anzeigen (Log-Retention, Timeouts, etc.)
- E-Mail-Konfiguration
- Teams-Webhook-Konfiguration
- Test-E-Mails/Teams-Nachrichten senden
- Speicherplatz-Statistiken
- System-Metriken
- Manueller Cleanup

**API-Endpoints:**
- `GET /api/settings` - Einstellungen abrufen
- `PUT /api/settings` - Einstellungen aktualisieren (nur Warnung)
- `GET /api/settings/storage` - Speicherplatz-Statistiken
- `GET /api/settings/system-metrics` - System-Metriken
- `POST /api/settings/test-email` - Test-E-Mail senden
- `POST /api/settings/test-teams` - Test-Teams-Nachricht senden
- `POST /api/settings/cleanup/force` - Manueller Cleanup

**Hinweis:** Einstellungen werden aktuell nur aus Environment-Variablen geladen. Für persistente Änderungen muss die `.env`-Datei bearbeitet werden.

### Sync

#### `pages/Sync.tsx`

Git-Synchronisation und Repository-Verwaltung.

**Features:**
- Git-Status anzeigen
- Manueller Git-Pull
- Sync-Logs anzeigen
- Auto-Sync-Einstellungen
- GitHub Apps Konfiguration
- GitHub App Manifest Flow

**API-Endpoints:**
- `GET /api/sync/status` - Git-Status
- `POST /api/sync` - Git-Pull ausführen
- `GET /api/sync/logs` - Sync-Logs
- `GET /api/sync/settings` - Sync-Einstellungen
- `PUT /api/sync/settings` - Sync-Einstellungen aktualisieren
- `GET /api/sync/github-config` - GitHub Config abrufen
- `POST /api/sync/github-config` - GitHub Config speichern
- `POST /api/sync/github-config/test` - GitHub Config testen
- `DELETE /api/sync/github-config` - GitHub Config löschen

**GitHub Apps:**
- Unterstützung für GitHub Apps Authentifizierung
- Manifest Flow für einfache App-Erstellung
- Installation Flow für Repository-Zugriff

### Login

#### `pages/Login.tsx`

Login-Seite. Anmeldung **nur via GitHub OAuth**.

**Features:**
- Button „Login mit GitHub“ (Redirect zu `/api/auth/github/authorize`)
- Fehlerbehandlung
- Nach Autorisierung: Redirect zu `/auth/callback#token=...`, dann zu `/`

**Weitere Seiten:**
- `pages/AuthCallback.tsx` – verarbeitet `#token=...` nach OAuth, speichert Token in sessionStorage, leitet zu `/` weiter
- `pages/Invite.tsx` – Einladungs-Landing (`/invite?token=...`), Button „Mit GitHub registrieren“ startet OAuth mit Token im `state`

**API-Endpoints:**
- `GET /api/auth/github/authorize` – Login (Redirect zu GitHub)

## Authentication Context

### `contexts/AuthContext.tsx`

Verwaltet den Authentifizierungs-Status der Anwendung.

**Features:**
- Token-Verwaltung in sessionStorage (auth_token)
- Automatische Token-Validierung
- Logout-Funktionalität
- Protected Routes

**Verwendung:**
```typescript
import { useAuth } from '@/contexts/AuthContext'

function MyComponent() {
  const { user, isAuthenticated, logout } = useAuth()
  
  if (!isAuthenticated) {
    return <div>Bitte einloggen</div>
  }
  
  return <div>Willkommen, {user?.username}</div>
}
```

## Routing

Die Routing-Konfiguration befindet sich in `App.tsx`:

- `/` - Dashboard
- `/login` - Login (GitHub OAuth)
- `/auth/callback` - OAuth-Callback (verarbeitet `#token=...`)
- `/invite` - Einladungs-Seite (`?token=...`)
- `/pipelines` - Pipeline-Übersicht
- `/pipelines/:name` - Pipeline-Details
- `/runs` - Run-Übersicht
- `/runs/:id` - Run-Details
- `/scheduler` - Scheduler
- `/secrets` - Secrets
- `/settings` - Settings
- `/sync` - Git-Sync
- `/users` - Nutzerverwaltung (nur für Admins, GitHub-Einladungen)

**Protected Routes:**
Alle Routen außer `/login`, `/auth/callback` und `/invite` sind geschützt und erfordern Authentifizierung.

## Styling

### Design-System

Das Design-System ist in `styles/design-system.css` definiert und enthält:
- Farbpalette (Primary, Secondary, Success, Error, Warning)
- Typografie (Schriftarten, Größen)
- Spacing (Abstände)
- Border-Radius
- Shadows

### CSS-Variablen

CSS-Variablen sind in `styles/variables.css` definiert und können für Theming verwendet werden.

### CSS Modules

Jede Komponente hat eine zugehörige `.css`-Datei für komponentenspezifische Styles.

## Entwicklung

### Lokale Entwicklung

```bash
cd frontend
npm install
npm run dev
```

Die Anwendung läuft dann auf `http://localhost:3000`.

### Build

```bash
npm run build
```

Der Build wird im `static/`-Verzeichnis erstellt und kann vom Backend serviert werden.

### Environment-Variablen

- `VITE_API_URL`: API-Basis-URL (Standard: `http://localhost:8000/api`)

## Best Practices

1. **API-Calls**: Immer über `apiClient` aus `src/api/client.ts`
2. **Error-Handling**: Fehler sollten benutzerfreundlich angezeigt werden
3. **Loading-States**: Verwende `Skeleton`-Komponente während des Ladens
4. **TypeScript**: Nutze TypeScript für Typsicherheit
5. **Responsive Design**: Alle Komponenten sollten responsive sein
