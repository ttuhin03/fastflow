/**
 * Der Provider lädt die gespeicherten Notifications im useState-Initializer und
 * verwirft dabei alles älter als 7 Tage. Vorher taten das zwei Mount-Effects.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { NotificationProvider, useNotifications } from './NotificationContext'

const KEY = 'fastflow-notifications'
const DAY = 24 * 60 * 60 * 1000

function storedEntry(id: string, ageMs: number) {
  return {
    id,
    type: 'info',
    title: id,
    message: id,
    timestamp: new Date(Date.now() - ageMs).toISOString(),
    read: false,
  }
}

function Probe() {
  const { notifications } = useNotifications()
  return <div data-testid="ids">{notifications.map((n) => n.id).join(',')}</div>
}

function renderProvider() {
  return render(
    <NotificationProvider>
      <Probe />
    </NotificationProvider>,
  )
}

describe('NotificationProvider', () => {
  beforeEach(() => {
    // localStorage.clear() gibt es in dieser Node-Variante nicht; die App nutzt
    // ohnehin nur get/set/removeItem.
    localStorage.removeItem(KEY)
  })

  it('liest gespeicherte Einträge und wandelt timestamp zurück in ein Date', () => {
    localStorage.setItem(KEY, JSON.stringify([storedEntry('frisch', 1 * DAY)]))

    renderProvider()

    expect(screen.getByTestId('ids')).toHaveTextContent('frisch')
  })

  it('verwirft Einträge älter als 7 Tage', () => {
    localStorage.setItem(
      KEY,
      JSON.stringify([storedEntry('alt', 8 * DAY), storedEntry('frisch', 1 * DAY)]),
    )

    renderProvider()

    const ids = screen.getByTestId('ids').textContent
    expect(ids).toBe('frisch')
  })

  it('überschreibt den Speicher nicht mit der leeren Startliste', () => {
    // Regression: der Speicher-Effect lief im ersten Commit noch mit der leeren
    // useState-Vorgabe und hat den Eintrag gelöscht, bevor der geladene State
    // ankam. Nach dem Rendern muss der Eintrag noch dastehen.
    localStorage.setItem(KEY, JSON.stringify([storedEntry('frisch', 1 * DAY)]))

    renderProvider()

    const raw = localStorage.getItem(KEY)
    expect(raw).not.toBeNull()
    expect(JSON.parse(raw as string)).toHaveLength(1)
  })

  it('startet leer bei kaputtem JSON statt zu werfen', () => {
    localStorage.setItem(KEY, '{nicht json')

    expect(() => renderProvider()).not.toThrow()
    expect(screen.getByTestId('ids')).toHaveTextContent('')
  })

  it('räumt den Speicher, wenn die letzte Notification verschwindet', () => {
    localStorage.setItem(KEY, JSON.stringify([storedEntry('frisch', 1 * DAY)]))

    // Aktion über einen Button statt über eine Zuweisung beim Rendern — letztere
    // ist genau das, was react-hooks/globals zu Recht bemängelt.
    function ClearButton() {
      const { clearAll } = useNotifications()
      return <button onClick={clearAll}>leeren</button>
    }
    render(
      <NotificationProvider>
        <Probe />
        <ClearButton />
      </NotificationProvider>,
    )

    act(() => {
      screen.getByRole('button', { name: 'leeren' }).click()
    })

    expect(screen.getByTestId('ids')).toHaveTextContent('')
    expect(localStorage.getItem(KEY)).toBeNull()
  })

  it('überlebt einen gesperrten localStorage beim Schreiben', () => {
    // Privater Modus / Speicherrichtlinie: setItem wirft. Ungefangen im Effect
    // landete die App dadurch in der ErrorBoundary.
    localStorage.setItem(KEY, JSON.stringify([storedEntry('frisch', 1 * DAY)]))
    const setItem = vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError')
    })
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    try {
      expect(() => renderProvider()).not.toThrow()
      expect(screen.getByTestId('ids')).toHaveTextContent('frisch')
    } finally {
      setItem.mockRestore()
      consoleError.mockRestore()
    }
  })
})
