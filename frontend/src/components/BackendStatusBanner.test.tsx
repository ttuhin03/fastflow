/**
 * Component-Tests für BackendStatusBanner.
 *
 * Deckt die Zustände ab, die sich lokal nur schwer live herstellen lassen —
 * insbesondere "Datenbank nicht erreichbar", für das sonst eine echte,
 * abschaltbare Postgres-Instanz nötig wäre.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import BackendStatusBanner from './BackendStatusBanner'
import { __resetDegradedState, reportDegraded } from '../api/degradedState'

// Node stellt in dieser Umgebung ein localStorage-Objekt ohne funktionierende
// Methoden bereit (Warnung "--localstorage-file was provided without a valid
// path"). Der Produktivcode faengt das per try/catch ab; fuer den Test brauchen
// wir aber einen echten Speicher.
const storage = new Map<string, string>()
Object.defineProperty(window, 'localStorage', {
  configurable: true,
  value: {
    getItem: (k: string) => storage.get(k) ?? null,
    setItem: (k: string, v: string) => void storage.set(k, v),
    removeItem: (k: string) => void storage.delete(k),
    clear: () => storage.clear(),
  },
})

const get = vi.fn()
vi.mock('../api/client', () => ({
  default: { get: (...args: unknown[]) => get(...args) },
}))

function renderBanner() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <BackendStatusBanner />
      </QueryClientProvider>,
    ),
  }
}

function respond(data: Record<string, unknown>) {
  get.mockResolvedValue({ data })
}

beforeEach(() => {
  __resetDegradedState()
  get.mockReset()
  storage.clear()
})

describe('BackendStatusBanner', () => {
  it('rendert nichts, solange das Backend "ok" meldet', async () => {
    respond({ status: 'ok', failing: [] })
    const { container } = renderBanner()
    await waitFor(() => expect(get).toHaveBeenCalledWith('/system/status'))
    expect(container.querySelector('.backend-status-banner')).toBeNull()
  })

  it('meldet einen DB-Ausfall samt Hinweis auf die Logs', async () => {
    respond({ status: 'degraded', failing: ['database'], detail: null })
    renderBanner()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('Datenbank nicht erreichbar')).toBeInTheDocument()
    expect(screen.getByText(/Logs des Orchestrators/)).toBeInTheDocument()
  })

  it('verlinkt den Log-Viewer, wenn LOG_VIEWER_URL gesetzt ist', async () => {
    respond({
      status: 'degraded',
      failing: ['database'],
      log_viewer_url: 'https://grafana.example/explore',
    })
    renderBanner()
    const link = await screen.findByRole('link', { name: /Logs öffnen/ })
    expect(link).toHaveAttribute('href', 'https://grafana.example/explore')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('zeigt keinen Link, wenn keine LOG_VIEWER_URL konfiguriert ist', async () => {
    respond({ status: 'degraded', failing: ['database'], log_viewer_url: null })
    renderBanner()
    await screen.findByRole('alert')
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('faellt auf die zuletzt bekannte Log-URL zurueck, wenn das Backend schweigt', async () => {
    // Erst ein gesunder Poll, der die URL bekannt macht ...
    respond({ status: 'ok', failing: [], log_viewer_url: 'https://grafana.example/explore' })
    const first = renderBanner()
    await waitFor(() =>
      expect(window.localStorage.getItem('fastflow.logViewerUrl')).toBe(
        'https://grafana.example/explore',
      ),
    )
    first.unmount()

    // ... danach ist das Backend weg und liefert gar nichts mehr.
    get.mockRejectedValue(new Error('Network Error'))
    renderBanner()
    const link = await screen.findByRole('link', { name: /Logs öffnen/ })
    expect(link).toHaveAttribute('href', 'https://grafana.example/explore')
  })

  it('kennzeichnet den SQLite-Fallback als Warnung, nicht als Ausfall', async () => {
    respond({ status: 'degraded', failing: ['sqlite_fallback'] })
    const { container } = renderBanner()
    await screen.findByRole('alert')
    expect(screen.getByText('Läuft auf lokaler SQLite-Datenbank')).toBeInTheDocument()
    expect(
      container.querySelector('.backend-status-banner--warning'),
    ).toBeInTheDocument()
  })

  it('meldet ein nicht erreichbares Backend, wenn die Statusabfrage scheitert', async () => {
    get.mockRejectedValue(new Error('Network Error'))
    renderBanner()
    expect(await screen.findByText('Backend nicht erreichbar')).toBeInTheDocument()
  })

  it('übernimmt eine Meldung des Interceptors samt request_id', async () => {
    respond({ status: 'ok', failing: [] })
    renderBanner()
    act(() => reportDegraded({ reason: 'database', requestId: 'abc-123' }))
    expect(await screen.findByText('abc-123')).toBeInTheDocument()
  })

  it('behaelt die request_id des Interceptors, wenn der Poll nachzieht', async () => {
    // Reihenfolge wie im echten Ausfall: Der Interceptor sieht den 503 zuerst
    // (nur er kennt die request_id), der Poll meldet den Ausfall erst mit dem
    // naechsten Intervall. Zieht er nach, darf er die Kennung nicht loeschen -
    // sonst verschwindet genau das aus dem Banner, womit man den Vorfall im Log
    // wiederfindet.
    // Der gesunde Poll muss vollstaendig durch sein, bevor der Interceptor
    // meldet - sonst raeumt dessen Effekt die Meldung gleich wieder weg. Das
    // Schreiben der Log-URL ist der beobachtbare Beleg, dass er gelaufen ist.
    respond({ status: 'ok', failing: [], log_viewer_url: 'https://grafana.example/explore' })
    const { queryClient } = renderBanner()
    await waitFor(() =>
      expect(window.localStorage.getItem('fastflow.logViewerUrl')).toBe(
        'https://grafana.example/explore',
      ),
    )

    act(() => reportDegraded({ reason: 'database', requestId: 'abc-123' }))
    expect(await screen.findByText('abc-123')).toBeInTheDocument()

    respond({ status: 'degraded', failing: ['database'], detail: 'connection refused' })
    await queryClient.refetchQueries({ queryKey: ['backend-status'] })

    await screen.findByText('connection refused')
    expect(screen.getByText('abc-123')).toBeInTheDocument()
  })

  it('blendet das Banner wieder aus, sobald sich das Backend erholt', async () => {
    respond({ status: 'degraded', failing: ['database'] })
    const { container, queryClient } = renderBanner()
    await screen.findByRole('alert')

    // Statt das Poll-Intervall abzuwarten: denselben Refetch ausloesen, den der
    // Timer spaeter ohnehin ausfuehren wuerde.
    respond({ status: 'ok', failing: [] })
    await queryClient.refetchQueries({ queryKey: ['backend-status'] })

    await waitFor(() =>
      expect(container.querySelector('.backend-status-banner')).toBeNull(),
    )
  })
})
