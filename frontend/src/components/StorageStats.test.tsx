/**
 * Component-Tests für StorageStats.
 *
 * Die Seite zeigte nur ein Volume: "Gesamtspeicher" kommt aus
 * shutil.disk_usage(LOGS_DIR), also vom fastflow-storage-PVC. Das shared PVC des
 * Kubernetes-Backends — dort liegen Pipeline-Kopien, uv-Cache und die
 * Python-Installationen, und dort scheitert jeder Run, wenn es volläuft — kam in
 * diesen Statistiken nicht vor. Beim Blick auf die Seite sah alles gesund aus,
 * während /shared bei 0.00 GB stand.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import StorageStats from './StorageStats'

const get = vi.fn()
vi.mock('../api/client', () => ({
  default: { get: (...args: unknown[]) => get(...args) },
}))

const BASIS = {
  log_files_count: 1442,
  log_files_size_mb: 79.95,
  total_disk_space_gb: 15.66,
  used_disk_space_gb: 7.81,
  free_disk_space_gb: 7.83,
  log_files_percentage: 0.5,
}

const VOLL = {
  shared_volume_dir: '/shared',
  shared_volume_total_gb: 9.77,
  shared_volume_used_gb: 9.77,
  shared_volume_free_gb: 0.0,
  shared_volume_used_percent: 100.0,
}

function renderStats(
  extra: Record<string, unknown> = {},
  breakdown?: Record<string, unknown>,
) {
  get.mockImplementation((url: string) =>
    url.includes('shared-breakdown')
      ? Promise.resolve({ data: breakdown })
      : Promise.resolve({ data: { ...BASIS, ...extra } }),
  )
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <StorageStats />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  get.mockReset()
})

describe('StorageStats', () => {
  it('zeigt das shared Volume getrennt vom Gesamtspeicher', async () => {
    renderStats({
      shared_volume_dir: '/shared',
      shared_volume_total_gb: 9.77,
      shared_volume_used_gb: 9.77,
      shared_volume_free_gb: 0.0,
      shared_volume_used_percent: 100.0,
    })

    expect(await screen.findByText('9.77 GB')).toBeInTheDocument()
    // Der Gesamtspeicher des anderen Volumes steht unverändert daneben.
    expect(screen.getByText('15.66 GB')).toBeInTheDocument()
    expect(screen.getByText('9.77 GB verwendet, 0.00 GB frei')).toBeInTheDocument()
  })

  it('markiert das volle Volume mit den Klassen, die das CSS auch trifft', async () => {
    // Die Regeln greifen nur in Kombination (.stat-icon.shared-icon.shared-warn,
    // .disk-usage-fill.shared.shared-warn). Ein erster Versuch benutzte die
    // Inode-Klassen mit und setzte nur inode-warn — wirkungslos, ohne dass etwas
    // aufgefallen wäre. Der Test hängt deshalb an den Klassen, nicht am Aussehen.
    const { container } = renderStats({
      shared_volume_total_gb: 9.77,
      shared_volume_used_gb: 9.77,
      shared_volume_free_gb: 0.0,
      shared_volume_used_percent: 100.0,
    })
    await screen.findByText('9.77 GB')

    expect(container.querySelector('.stat-icon.shared-icon.shared-warn')).not.toBeNull()
    expect(container.querySelector('.disk-usage-fill.shared.shared-warn')).not.toBeNull()
  })

  it('markiert ein Volume mit Luft nicht als Problem', async () => {
    const { container } = renderStats({
      shared_volume_total_gb: 9.77,
      shared_volume_used_gb: 4.0,
      shared_volume_free_gb: 5.77,
      shared_volume_used_percent: 41.0,
    })
    await screen.findByText('9.77 GB')

    expect(container.querySelector('.stat-icon.shared-icon')).not.toBeNull()
    expect(container.querySelector('.shared-warn')).toBeNull()
  })

  it('fragt die Aufschlüsselung nicht von selbst ab', async () => {
    // Der Durchlauf liest das ganze Volume. Läge er im 30-Sekunden-Polling der
    // Statistiken, würde die Seite das Volume alle 30 Sekunden durchharken.
    renderStats(VOLL)
    await screen.findByText('9.77 GB')

    const urls = get.mock.calls.map((call) => String(call[0]))
    expect(urls.some((url) => url.includes('shared-breakdown'))).toBe(false)
  })

  it('zeigt die Aufschlüsselung nach dem Klick, mit zweiter Ebene', async () => {
    renderStats(VOLL, {
      dir: '/shared',
      available: true,
      total_gb: 9.5,
      file_count: 162959,
      duration_seconds: 4.7,
      entries: [
        {
          path: 'uv_cache',
          size_mb: 8000,
          size_gb: 7.81,
          file_count: 101948,
          percent_of_volume: 80.0,
          children: [
            {
              path: 'uv_cache/archive-v0',
              size_mb: 2595.2,
              size_gb: 2.53,
              file_count: 86071,
              percent_of_volume: 26.0,
            },
          ],
          children_omitted: 3,
          children_omitted_bytes: 41943040,
        },
      ],
    })
    await screen.findByText('9.77 GB')

    await userEvent.click(screen.getByRole('button', { name: /Aufschlüsselung berechnen/i }))

    expect(await screen.findByText('uv_cache')).toBeInTheDocument()
    expect(screen.getByText('uv_cache/archive-v0')).toBeInTheDocument()
    expect(screen.getByText('7.81 GB')).toBeInTheDocument()
    expect(screen.getByText(/3 weitere/)).toBeInTheDocument()
  })

  it('sagt es, wenn unter dem Pfad kein Volume liegt', async () => {
    renderStats(VOLL, { dir: '/shared', available: false, entries: [] })
    await screen.findByText('9.77 GB')

    await userEvent.click(screen.getByRole('button', { name: /Aufschlüsselung berechnen/i }))

    expect(
      await screen.findByText(/kein Volume gemountet/i),
    ).toBeInTheDocument()
  })

  it('lässt die Karte weg, wenn kein shared Volume gemeldet wird', async () => {
    renderStats()

    expect(await screen.findByText('15.66 GB')).toBeInTheDocument()
    expect(screen.queryByText(/Shared Volume/i)).not.toBeInTheDocument()
  })
})
