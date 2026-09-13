/**
 * Die Palette hielt zwei Zustände in Effects nach: das Leeren des Suchfelds beim
 * Öffnen und das Zurücksetzen des markierten Eintrags, wenn die Trefferliste
 * kürzer wird als der Index. Beides passiert jetzt beim Öffnen bzw. beim
 * Rendern — diese Tests halten das Verhalten fest.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const navigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: true, isAdmin: false }),
}))

vi.mock('../api/client', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [] }) },
}))

import CommandPalette from './CommandPalette'

function renderPalette() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function openPalette() {
  act(() => {
    window.dispatchEvent(new Event('open-command-palette'))
  })
}

describe('CommandPalette', () => {
  beforeEach(() => {
    navigate.mockReset()
  })

  it('ist zunächst geschlossen und öffnet auf das Fenster-Event', () => {
    renderPalette()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    openPalette()

    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('startet beim erneuten Öffnen mit leerem Suchfeld', async () => {
    const user = userEvent.setup()
    renderPalette()
    openPalette()

    const input = screen.getByRole('textbox')
    await user.type(input, 'sett')
    expect(input).toHaveValue('sett')

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    openPalette()
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('klemmt den markierten Eintrag, wenn die Liste darunter kürzer wird', async () => {
    const user = userEvent.setup()
    renderPalette()
    openPalette()

    // Pfeiltasten hängen am Eingabefeld; den Fokus setzt die Komponente sonst
    // erst nach einem Timeout.
    const input = screen.getByRole('textbox')
    await user.click(input)

    // Vierten Eintrag markieren …
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')
    const items = document.querySelectorAll('.cmdk-item')
    expect(items[3]).toHaveClass('active')

    // … dann so filtern, dass nur noch einer übrig bleibt.
    await user.type(input, 'dashboard')
    const filtered = document.querySelectorAll('.cmdk-item')
    expect(filtered).toHaveLength(1)
    expect(filtered[0]).toHaveClass('active')

    // Enter darf jetzt den sichtbaren Treffer auslösen, nicht ins Leere greifen.
    await user.keyboard('{Enter}')
    expect(navigate).toHaveBeenCalledWith('/')
  })

  it('schließt per Escape und leert dabei die Eingabe', async () => {
    const user = userEvent.setup()
    renderPalette()
    openPalette()

    await user.type(screen.getByRole('textbox'), 'runs')
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    openPalette()
    expect(screen.getByRole('textbox')).toHaveValue('')
  })
})
