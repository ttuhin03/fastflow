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
const post = vi.fn()
vi.mock('../api/client', () => ({
  default: {
    get: (...args: unknown[]) => get(...args),
    post: (...args: unknown[]) => post(...args),
  },
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
  breakdownState?: Record<string, unknown>,
) {
  get.mockImplementation((url: string) =>
    url.includes('shared-breakdown')
      ? Promise.resolve({ data: breakdownState })
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
  post.mockReset()
  post.mockResolvedValue({ data: { status: 'running' } })
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

  it('startet beim Laden keine Rechnung, fragt aber den Zustand ab', async () => {
    // Zwei Anfragen mit sehr unterschiedlichen Kosten. Teuer ist der Durchlauf
    // über das ganze Volume, und der hängt am POST — der darf beim Laden nicht
    // passieren. Das GET liest nur einen Zustand und muss mitlaufen, sonst
    // findet die Anzeige nach einem Reload eine laufende Rechnung nicht wieder.
    renderStats(VOLL, { status: 'never' })
    await screen.findByText('9.77 GB')

    expect(post).not.toHaveBeenCalled()
    const urls = get.mock.calls.map((call) => String(call[0]))
    expect(urls.some((url) => url.includes('shared-breakdown'))).toBe(true)
  })

  it('hängt sich nach einem Reload an eine laufende Rechnung', async () => {
    // Kein Klick in diesem Test: die Anzeige muss den laufenden Durchlauf allein
    // aus dem Zustand erkennen.
    renderStats(VOLL, { status: 'running', elapsed_seconds: 95.2, files_seen: 210000, bytes_seen: 7516192768 })

    expect(await screen.findByText(/Wird berechnet … \(95 s\)/)).toBeInTheDocument()
    expect(screen.getByText(/210.000 Dateien, 7\.00 GB gelesen/)).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
  })

  it('startet die Rechnung per POST und zeigt das Ergebnis, mit zweiter Ebene', async () => {
    // Zweistufig, weil der Durchlauf länger dauern kann als das 30-Sekunden-
    // Timeout von apiClient: POST startet, GET holt den Zustand.
    renderStats(VOLL, {
      status: 'done',
      started_at: '2026-09-21T19:00:00Z',
      finished_at: '2026-09-21T19:00:05Z',
      result: {
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
      },
    })
    await screen.findByText('9.77 GB')

    await userEvent.click(screen.getByRole('button', { name: /Aufschlüsselung berechnen/i }))

    expect(post).toHaveBeenCalledWith('/settings/storage/shared-breakdown')
    expect(await screen.findByText('uv_cache')).toBeInTheDocument()
    expect(screen.getByText('uv_cache/archive-v0')).toBeInTheDocument()
    expect(screen.getByText('7.81 GB')).toBeInTheDocument()
    expect(screen.getByText(/3 weitere/)).toBeInTheDocument()
  })

  it('sperrt den Knopf, solange gerechnet wird', async () => {
    // Ein zweiter Klick würde serverseitig zwar keine zweite Rechnung starten,
    // aber der gesperrte Knopf sagt dem Benutzer, dass es läuft.
    renderStats(VOLL, { status: 'running', elapsed_seconds: 42.3 })
    await screen.findByText('9.77 GB')

    expect(await screen.findByText(/Wird berechnet … \(42 s\)/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Wird berechnet/i })).toBeDisabled()
  })

  it('zeigt die Fehlermeldung des Servers statt eines Sammeltexts', async () => {
    renderStats(VOLL, { status: 'failed', error: 'Volume weg', result: null })
    await screen.findByText('9.77 GB')

    await userEvent.click(screen.getByRole('button', { name: /Aufschlüsselung berechnen/i }))

    expect(await screen.findByText('Volume weg')).toBeInTheDocument()
  })

  it('sagt es, wenn unter dem Pfad kein Volume liegt', async () => {
    renderStats(VOLL, {
      status: 'done',
      result: { dir: '/shared', available: false, entries: [] },
    })
    await screen.findByText('9.77 GB')

    await userEvent.click(screen.getByRole('button', { name: /Aufschlüsselung berechnen/i }))

    expect(await screen.findByText(/kein Volume gemountet/i)).toBeInTheDocument()
  })

  it('lässt die Karte weg, wenn kein shared Volume gemeldet wird', async () => {
    renderStats()

    expect(await screen.findByText('15.66 GB')).toBeInTheDocument()
    expect(screen.queryByText(/Shared Volume/i)).not.toBeInTheDocument()
  })
})
