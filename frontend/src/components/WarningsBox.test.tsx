/**
 * Component-Tests für WarningsBox.
 *
 * Der Kasten liest dasselbe checks-Dict wie SystemStatus, und dieses Dict mischt
 * zwei Sorten Werte: Befunde als String ("ok" oder Fehlermeldung) und Messwerte
 * als Zahl (disk_free_gb, inode_free, shared_cache_free_gb …). Wer die Messwerte
 * über eine Liste ihrer Namen aussortiert, hängt hinter jedem neuen Messwert
 * hinterher — und ein Messwert, der durchrutscht, steht als "Problem" im Kasten,
 * weil eine Zahl nun mal nicht 'ok' ist.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import WarningsBox from './WarningsBox'

const get = vi.fn()
vi.mock('../api/client', () => ({
  default: { get: (...args: unknown[]) => get(...args) },
}))

/** Nur der System-Status trägt Inhalt; die übrigen Queries bleiben unauffällig. */
function respondWith(checks: Record<string, unknown>, status = 'not_ready') {
  get.mockImplementation(async (url: string) => {
    if (url === '/settings/system-status') return { data: { status, checks } }
    if (url === '/settings/storage') return { data: {} }
    if (url === '/sync/status') return { data: { status: 'success' } }
    if (url === '/settings/concurrency') return { data: { utilization: 0 } }
    if (url === '/pipelines/summary-stats') {
      return { data: { last_7d: { success_rate_pct: 100, total_runs: 0 } } }
    }
    return { data: {} }
  })
}

function renderBox() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <WarningsBox />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  get.mockReset()
})

describe('WarningsBox', () => {
  it('nennt den ausgefallenen Check, nicht die Messwerte daneben', async () => {
    respondWith({
      database: 'connection refused',
      kubernetes: 'ok',
      uv_cache: 'ok',
      shared_cache: 'ok',
      shared_cache_free_gb: 4.2,
      shared_cache_inode_free: 500000,
      disk: 'ok',
      disk_free_gb: 12.5,
      inode_total: 1000000,
      inode_free: 900000,
    })

    renderBox()

    expect(await screen.findByText('Datenbank: Problem')).toBeInTheDocument()
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(1)
  })

  it('meldet das volle shared Volume, wenn die Probe aus anderem Grund rot ist', async () => {
    respondWith({
      database: 'connection refused',
      shared_cache: 'kritisch: nur 0.02 GB frei',
      shared_cache_free_gb: 0.02,
    })

    renderBox()

    expect(await screen.findByText('Shared Volume: Problem')).toBeInTheDocument()
  })

  it('nimmt einen n/a-Check nicht als Problem', async () => {
    respondWith({
      database: 'connection refused',
      inodes: 'n/a (Dateisystem meldet keine Inode-Zahlen)',
    })

    renderBox()

    await screen.findByText('Datenbank: Problem')
    expect(screen.queryByText('Inodes: Problem')).not.toBeInTheDocument()
  })
})
