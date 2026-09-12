/**
 * Trend-Berechnung für die KPI-Karten.
 *
 * Bewusst getrennt von der Darstellung: die Karten zeigten vorher teils fest
 * verdrahtete Aufwärtspfeile, unabhängig von den tatsächlichen Daten.
 */

export type TrendDirection = 'up' | 'down' | 'flat'

export interface Trend {
  dir: TrendDirection
  /** Formatierte Differenz, oder null wenn kein sinnvoller Wert existiert. */
  label: string | null
}

/**
 * Vergleicht den letzten Wert der Reihe mit dem Durchschnitt der vorangegangenen
 * Werte.
 *
 * Gibt null zurück, wenn die Datenlage für eine Aussage nicht reicht — dann
 * sollte auch kein Chip gerendert werden. Lieber nichts anzeigen als einen
 * Pfeil, der nichts misst.
 *
 * @param series   Werte in zeitlicher Reihenfolge, ältester zuerst.
 * @param mode     'points' für Prozentwerte: eine Erfolgsquote von 50 % auf
 *                 55 % ist "+5 pp", nicht "+10 %".
 */
export function computeTrend(
  series: number[],
  mode: 'relative' | 'points' = 'relative',
): Trend | null {
  if (!Array.isArray(series) || series.length < 2) return null

  const last = series[series.length - 1]
  const previous = series.slice(0, -1)
  if (!previous.length) return null
  if (!previous.every((v) => Number.isFinite(v)) || !Number.isFinite(last)) return null

  const avg = previous.reduce((sum, v) => sum + v, 0) / previous.length
  if (!Number.isFinite(avg)) return null

  const diff = last - avg

  if (mode === 'points') {
    const points = Math.round(diff)
    if (points === 0) return { dir: 'flat', label: null }
    return { dir: points > 0 ? 'up' : 'down', label: `${points > 0 ? '+' : '−'}${Math.abs(points)} pp` }
  }

  // Ohne Vergleichsbasis ist ein Prozentwert nicht definiert — nur Richtung.
  if (avg === 0) {
    if (diff === 0) return { dir: 'flat', label: null }
    return { dir: diff > 0 ? 'up' : 'down', label: null }
  }

  const pct = Math.round((diff / Math.abs(avg)) * 100)
  if (pct === 0) return { dir: 'flat', label: null }
  return { dir: pct > 0 ? 'up' : 'down', label: `${pct > 0 ? '+' : '−'}${Math.abs(pct)}%` }
}
