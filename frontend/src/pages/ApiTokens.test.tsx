/**
 * Tests für die API-Token-Verwaltung.
 *
 * Schwerpunkt ist die eine Eigenschaft, die sich nicht nachträglich korrigieren
 * lässt: der Klartext des Tokens wird genau einmal angezeigt. Wird er nach dem
 * Wegklicken erneut sichtbar oder überlebt er ein Neuladen der Liste, ist das
 * ein Fehler mit Sicherheitswirkung, kein Kosmetikproblem.
 *
 * Die Tests laufen gegen die echten Übersetzungen (setup.ts stellt auf 'de'),
 * fehlende i18n-Keys fielen hier also als roher Key-String auf.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => {
  const client = { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: client, apiClient: client }
})

const authState = { isAdmin: false, isReadonly: false, isWrite: true, userRole: 'write' }
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => authState }))

vi.mock('../utils/toast', () => ({
  showError: vi.fn(),
  showSuccess: vi.fn(),
  showConfirm: vi.fn(() => Promise.resolve(true)),
}))

import apiClient from '../api/client'
import { showConfirm } from '../utils/toast'
import ApiTokens from './ApiTokens'

const LIST_EMPTY = {
  tokens: [],
  available_scopes: ['logs', 'read', 'run', 'source'],
  max_expiry_days: 365,
  default_expiry_days: 90,
}

function tokenRow(overrides: Record<string, unknown> = {}) {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    label: 'CI nightly',
    prefix: 'abcd1234',
    scopes: ['read', 'run'],
    created_at: '2026-09-01T10:00:00+00:00',
    expires_at: '2026-12-01T10:00:00+00:00',
    last_used_at: null,
    revoked_at: null,
    expired: false,
    username: null,
    ...overrides,
  }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ApiTokens />
    </QueryClientProvider>,
  )
}

describe('ApiTokens', () => {
  beforeEach(() => {
    vi.mocked(apiClient.get).mockReset()
    vi.mocked(apiClient.post).mockReset()
    vi.mocked(apiClient.delete).mockReset()
    vi.mocked(showConfirm).mockReset().mockResolvedValue(true)
    authState.isAdmin = false
  })

  it('zeigt nur die Scopes, die die Rolle zulässt', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { ...LIST_EMPTY, available_scopes: ['read', 'logs', 'source'] },
    })

    renderPage()

    await waitFor(() => expect(screen.getByLabelText(/^read/)).toBeInTheDocument())
    expect(screen.getByLabelText(/^logs/)).toBeInTheDocument()
    expect(screen.getByLabelText(/^source/)).toBeInTheDocument()
    // run fehlt in available_scopes -> darf nicht anwählbar sein
    expect(screen.queryByLabelText(/^run/)).not.toBeInTheDocument()
  })

  it('sendet Label, gewählte Scopes und Laufzeit', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.get).mockResolvedValue({ data: LIST_EMPTY })
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        token: 'ffp_abcd1234_' + 'x'.repeat(43),
        id: 'id-1',
        label: 'CI nightly',
        prefix: 'abcd1234',
        scopes: ['read', 'run'],
        expires_at: '2026-12-01T10:00:00+00:00',
      },
    })

    renderPage()
    await waitFor(() => expect(screen.getByLabelText(/^run/)).toBeInTheDocument())

    await user.type(screen.getByLabelText('Bezeichnung'), 'CI nightly')
    await user.click(screen.getByLabelText(/^run/))
    await user.click(screen.getByRole('button', { name: /Token erzeugen/ }))

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1))
    expect(apiClient.post).toHaveBeenCalledWith('/tokens', {
      label: 'CI nightly',
      scopes: ['read', 'run'],
      expires_in_days: 90,
    })
  })

  it('zeigt den Klartext genau einmal und gibt ihn nach dem Wegklicken nicht wieder her', async () => {
    const user = userEvent.setup()
    const secret = 'ffp_abcd1234_' + 'y'.repeat(43)
    vi.mocked(apiClient.get).mockResolvedValue({ data: LIST_EMPTY })
    vi.mocked(apiClient.post).mockResolvedValue({
      data: {
        token: secret,
        id: 'id-1',
        label: 'CI nightly',
        prefix: 'abcd1234',
        scopes: ['read'],
        expires_at: '2026-12-01T10:00:00+00:00',
      },
    })

    renderPage()
    await waitFor(() => expect(screen.getByLabelText('Bezeichnung')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Bezeichnung'), 'CI nightly')
    await user.click(screen.getByRole('button', { name: /Token erzeugen/ }))

    const reveal = await screen.findByRole('alert')
    expect(within(reveal).getByText(secret)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Habe ich gespeichert/ }))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.queryByText(secret)).not.toBeInTheDocument()
  })

  it('widerruft erst nach Bestätigung', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { ...LIST_EMPTY, tokens: [tokenRow()] },
    })
    vi.mocked(apiClient.delete).mockResolvedValue({ data: { status: 'revoked' } })
    vi.mocked(showConfirm).mockResolvedValue(false)

    renderPage()
    await user.click(await screen.findByRole('button', { name: /Widerrufen/ }))

    await waitFor(() => expect(showConfirm).toHaveBeenCalledTimes(1))
    expect(apiClient.delete).not.toHaveBeenCalled()

    vi.mocked(showConfirm).mockResolvedValue(true)
    await user.click(screen.getByRole('button', { name: /Widerrufen/ }))

    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith(
        '/tokens/11111111-1111-1111-1111-111111111111',
      ),
    )
  })

  it('bietet für widerrufene Tokens keinen Widerruf mehr an', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        ...LIST_EMPTY,
        tokens: [tokenRow({ revoked_at: '2026-09-05T10:00:00+00:00' })],
      },
    })

    renderPage()

    expect(await screen.findByText('widerrufen')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Widerrufen/ })).not.toBeInTheDocument()
  })

  it('markiert abgelaufene Tokens', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { ...LIST_EMPTY, tokens: [tokenRow({ expired: true })] },
    })

    renderPage()

    expect(await screen.findByText('abgelaufen')).toBeInTheDocument()
  })

  it('zeigt die Besitzer-Spalte nur Admins', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { ...LIST_EMPTY, tokens: [tokenRow({ username: 'alice' })] },
    })

    const { unmount } = renderPage()
    expect(await screen.findByText('CI nightly')).toBeInTheDocument()
    expect(screen.queryByText('alice')).not.toBeInTheDocument()
    unmount()

    authState.isAdmin = true
    renderPage()
    expect(await screen.findByText('alice')).toBeInTheDocument()
  })

  it('fragt widerrufene Tokens erst auf Wunsch nach', async () => {
    const user = userEvent.setup()
    vi.mocked(apiClient.get).mockResolvedValue({ data: LIST_EMPTY })

    renderPage()
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith('/tokens', {
        params: { include_revoked: false },
      }),
    )

    await user.click(screen.getByLabelText('Widerrufene anzeigen'))

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith('/tokens', {
        params: { include_revoked: true },
      }),
    )
  })
})
