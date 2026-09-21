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

function renderStats(extra: Record<string, unknown> = {}) {
  get.mockResolvedValue({ data: { ...BASIS, ...extra } })
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

  it('lässt die Karte weg, wenn kein shared Volume gemeldet wird', async () => {
    renderStats()

    expect(await screen.findByText('15.66 GB')).toBeInTheDocument()
    expect(screen.queryByText(/Shared Volume/i)).not.toBeInTheDocument()
  })
})
