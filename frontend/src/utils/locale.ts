/**
 * Date/number formatting using current i18n language.
 */

import i18n from '../i18n'

export function getFormatLocale(): string {
  const lang = i18n.language?.split('-')[0] || 'de'
  return lang === 'de' ? 'de-DE' : 'en-US'
}

/** Parst einen ISO-String aus der API; null bei fehlendem oder ungültigem Wert. */
function parseDate(value?: string | null): Date | null {
  if (!value) return null
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

/**
 * Datum + Uhrzeit in der Sprache der Oberfläche (Ortszeit des Browsers).
 * Gibt null zurück, wenn kein verwertbarer Zeitstempel vorliegt – die
 * aufrufende Komponente entscheidet dann über den Platzhalter.
 */
export function formatDateTime(value?: string | null): string | null {
  const d = parseDate(value)
  return d ? d.toLocaleString(getFormatLocale()) : null
}

/**
 * Kurzform (Datum + Uhrzeit ohne Sekunden) für Tabellenzellen, in denen
 * die volle Angabe die Spalte unnötig breit macht.
 */
export function formatDateTimeShort(value?: string | null): string | null {
  const d = parseDate(value)
  return d
    ? d.toLocaleString(getFormatLocale(), { dateStyle: 'short', timeStyle: 'short' })
    : null
}

/**
 * Relative Angabe wie „vor 3 Stunden“ / „3 hours ago“ für kompakte Stellen
 * (z. B. die Sidebar). Null, wenn der Wert unbrauchbar ist.
 */
export function formatRelativeTime(value?: string | null): string | null {
  const d = parseDate(value)
  if (!d) return null
  let seconds = Math.round((d.getTime() - Date.now()) / 1000)
  // Server- und Browser-Uhr laufen selten exakt synchron. Ohne diese Toleranz
  // stünde direkt nach der Anmeldung „in 4 Sekunden“ statt „gerade eben“.
  // Echte Zukunfts-Zeitpunkte (> 1 Minute) bleiben unverändert.
  if (seconds > 0 && seconds < 60) seconds = 0
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['year', 60 * 60 * 24 * 365],
    ['month', 60 * 60 * 24 * 30],
    ['day', 60 * 60 * 24],
    ['hour', 60 * 60],
    ['minute', 60],
  ]
  const rtf = new Intl.RelativeTimeFormat(getFormatLocale(), { numeric: 'auto' })
  for (const [unit, secondsPerUnit] of units) {
    if (Math.abs(seconds) >= secondsPerUnit) {
      return rtf.format(Math.round(seconds / secondsPerUnit), unit)
    }
  }
  return rtf.format(Math.round(seconds), 'second')
}
