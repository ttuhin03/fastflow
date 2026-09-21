/**
 * Component-Tests für SystemStatus.
 *
 * CHECK_ORDER ist eine Whitelist: Ein Check, der dort fehlt, steht zwar in der
 * API-Antwort, wird aber nicht gerendert. Für shared_cache hängt daran mehr als
 * eine Zeile — der Check kippt ``ok`` bewusst nicht (ein NotReady nähme bei
 * replicas: 1 den einzigen Pod aus dem Service und damit die UI mit), also ist
 * diese Anzeige der Ort, an dem ein volles /shared überhaupt sichtbar wird.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SystemStatus from './SystemStatus'

const get = vi.fn()
vi.mock('../api/client', () => ({
  default: { get: (...args: unknown[]) => get(...args) },
}))

function renderStatus(checks: Record<string, unknown>, status = 'ready') {
  get.mockResolvedValue({ data: { status, checks } })
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <SystemStatus />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  get.mockReset()
})

describe('SystemStatus', () => {
  it('zeigt das volle shared Volume an, obwohl die Probe ready bleibt', async () => {
    renderStatus({
      database: 'ok',
      kubernetes: 'ok',
      uv_cache: 'ok',
      shared_cache: 'kritisch: nur 0.02 GB frei',
      shared_cache_free_gb: 0.02,
      disk: 'ok',
      inodes: 'ok',
    })

    expect(await screen.findByText('Shared Volume')).toBeInTheDocument()
    expect(screen.getByText('kritisch: nur 0.02 GB frei')).toBeInTheDocument()
    expect(screen.getByText('Ausgefallen')).toBeInTheDocument()
  })

  it('rendert Messwerte nicht als eigene Zeile', async () => {
    renderStatus({ database: 'ok', disk: 'ok', disk_free_gb: 42.5 })

    await screen.findByText('Datenbank')
    expect(screen.queryByText('42.5')).not.toBeInTheDocument()
    expect(screen.queryByText('disk_free_gb')).not.toBeInTheDocument()
  })

  it('wertet einen n/a-Check als in Ordnung, nicht als Ausfall', async () => {
    // "n/a (Dateisystem meldet keine Inode-Zahlen)" kommt auf btrfs/ZFS/NFS —
    // dort gibt es nichts zu prüfen, kaputt ist deshalb nichts.
    renderStatus({
      database: 'ok',
      inodes: 'n/a (Dateisystem meldet keine Inode-Zahlen)',
    })

    await screen.findByText('Inodes')
    expect(screen.queryByText('Ausgefallen')).not.toBeInTheDocument()
    expect(screen.getAllByText('Betriebsbereit')).toHaveLength(2)
  })
})
