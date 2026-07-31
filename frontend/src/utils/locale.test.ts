/**
 * Tests für die Datums-Helfer (formatDateTime, formatRelativeTime).
 * Sie rendern u.a. den letzten Login in Nutzerliste, Konto-Einstellungen und Sidebar.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { formatDateTime, formatRelativeTime } from './locale'

vi.mock('../i18n', () => ({
  default: { language: 'en' },
}))

describe('formatDateTime', () => {
  it('formatiert einen ISO-Zeitstempel mit UTC-Offset', () => {
    const out = formatDateTime('2026-07-31T09:12:00+00:00')
    expect(out).toBeTruthy()
    expect(out).toContain('2026')
  })

  it('liefert null für null/undefined/leer', () => {
    expect(formatDateTime(null)).toBeNull()
    expect(formatDateTime(undefined)).toBeNull()
    expect(formatDateTime('')).toBeNull()
  })

  it('liefert null für unbrauchbare Werte statt "Invalid Date"', () => {
    expect(formatDateTime('nicht-ein-datum')).toBeNull()
  })
})

describe('formatRelativeTime', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-31T12:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('gibt Stunden für einen Zeitpunkt am selben Tag zurück', () => {
    expect(formatRelativeTime('2026-07-31T09:00:00+00:00')).toBe('3 hours ago')
  })

  it('gibt Tage für weiter zurückliegende Zeitpunkte zurück', () => {
    expect(formatRelativeTime('2026-07-29T12:00:00+00:00')).toBe('2 days ago')
  })

  it('gibt Sekunden für gerade eben zurück', () => {
    expect(formatRelativeTime('2026-07-31T11:59:50+00:00')).toBe('10 seconds ago')
  })

  it('zeigt bei leichter Uhr-Abweichung „jetzt“ statt einer Zukunftsangabe', () => {
    // Server-Uhr wenige Sekunden vor der Browser-Uhr: direkt nach dem Login
    // darf dort nicht „in 4 Sekunden“ stehen.
    expect(formatRelativeTime('2026-07-31T12:00:04+00:00')).toBe('now')
  })

  it('lässt echte Zukunfts-Zeitpunkte unverändert', () => {
    expect(formatRelativeTime('2026-08-02T12:00:00+00:00')).toBe('in 2 days')
  })

  it('liefert null für fehlende oder unbrauchbare Werte', () => {
    expect(formatRelativeTime(null)).toBeNull()
    expect(formatRelativeTime('nicht-ein-datum')).toBeNull()
  })
})
