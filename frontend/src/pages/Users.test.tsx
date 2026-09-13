/**
 * Regressionstest für die Hook-Reihenfolge in Users.
 *
 * Die Seite prüft Adminrechte, indem sie /users lädt und ein 403 abfängt. Der
 * frühe return für diesen Fall stand vor acht useMutation-Aufrufen: im ersten
 * Render (Query noch am Laden) liefen alle Hooks, im Render nach dem 403 nur
 * noch die davor stehenden. React bricht bei so einem Sprung mit "Rendered
 * fewer hooks than expected" ab — statt der Hinweisbox sah ein Nicht-Admin
 * die ErrorBoundary.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => {
  const get = vi.fn()
  return { default: { get, post: vi.fn(), put: vi.fn(), delete: vi.fn() }, apiClient: { get } }
})

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ isAdmin: false, isReadonly: true, isWrite: false, userRole: 'readonly' }),
}))

import apiClient from '../api/client'
import Users from './Users'

function forbidden() {
  return Object.assign(new Error('Request failed with status code 403'), {
    response: { status: 403, data: { detail: 'Admin-Rechte erforderlich' } },
  })
}

function renderUsers() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <Users />
    </QueryClientProvider>,
  )
}

describe('Users – Zugriff ohne Adminrechte', () => {
  let consoleError: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    // React protokolliert den Hook-Order-Fehler über console.error, bevor es
    // wirft — im Test nur stummschalten, nicht verstecken (siehe Assertion).
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.mocked(apiClient.get).mockReset()
  })

  afterEach(() => {
    consoleError.mockRestore()
  })

  it('zeigt die Hinweisbox statt an der Hook-Reihenfolge zu scheitern', async () => {
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url === '/auth/providers') return Promise.resolve({ data: {} })
      return Promise.reject(forbidden())
    })

    renderUsers()

    expect(await screen.findByText('Zugriff verweigert')).toBeInTheDocument()
    expect(screen.getByText('Admin-Rechte erforderlich')).toBeInTheDocument()

    await waitFor(() => {
      const logged = consoleError.mock.calls.map((c) => String(c[0])).join('\n')
      expect(logged).not.toMatch(/Rendered fewer hooks than expected/)
      expect(logged).not.toMatch(/change in the order of Hooks/)
    })
  })
})
