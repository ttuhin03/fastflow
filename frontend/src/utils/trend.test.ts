import { describe, it, expect } from 'vitest'
import { computeTrend } from './trend'

describe('computeTrend', () => {
  it('gibt null zurück, wenn die Datenlage nicht reicht', () => {
    expect(computeTrend([])).toBeNull()
    expect(computeTrend([5])).toBeNull()
  })

  it('erkennt einen Anstieg gegenüber dem Durchschnitt', () => {
    // Durchschnitt der ersten vier = 10, letzter Wert = 15 → +50 %
    expect(computeTrend([10, 10, 10, 10, 15])).toEqual({ dir: 'up', label: '+50%' })
  })

  it('erkennt einen Rückgang gegenüber dem Durchschnitt', () => {
    expect(computeTrend([10, 10, 10, 10, 5])).toEqual({ dir: 'down', label: '−50%' })
  })

  it('meldet flat ohne Label, wenn sich nichts bewegt', () => {
    expect(computeTrend([10, 10, 10])).toEqual({ dir: 'flat', label: null })
  })

  it('zeigt bei Nullbasis nur die Richtung, keinen Prozentwert', () => {
    expect(computeTrend([0, 0, 3])).toEqual({ dir: 'up', label: null })
    expect(computeTrend([0, 0, 0])).toEqual({ dir: 'flat', label: null })
  })

  it('rechnet Prozentwerte in Prozentpunkten', () => {
    // Erfolgsquote 50 % → 55 % ist +5 pp, nicht +10 %
    expect(computeTrend([50, 50, 50, 55], 'points')).toEqual({ dir: 'up', label: '+5 pp' })
    expect(computeTrend([90, 90, 90, 80], 'points')).toEqual({ dir: 'down', label: '−10 pp' })
    expect(computeTrend([90, 90, 90], 'points')).toEqual({ dir: 'flat', label: null })
  })

  it('verschluckt sich nicht an unbrauchbaren Werten', () => {
    expect(computeTrend([NaN, 10])).toBeNull()
    expect(computeTrend([10, Infinity])).toBeNull()
  })

  it('richtet sich nie ohne Deckung nach oben', () => {
    // Regression: die Karten zeigten früher einen festen ↑, sobald mehr als ein
    // Datenpunkt existierte — auch bei fallender Reihe.
    const falling = [100, 80, 60, 40, 20]
    expect(computeTrend(falling)?.dir).toBe('down')
    expect(computeTrend(falling, 'points')?.dir).toBe('down')
  })
})
