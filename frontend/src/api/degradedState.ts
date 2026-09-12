/**
 * Globaler Zustand "Backend gestört".
 *
 * Gespeist aus zwei Quellen, die sich ergänzen:
 *  - dem Response-Interceptor, sobald ein Request mit 503/DATABASE_UNAVAILABLE
 *    zurückkommt (sofort, und mit der request_id zum Nachschlagen im Log)
 *  - dem Polling auf /api/system/status (erkennt den Zustand auch dann, wenn
 *    die Seite gerade gar keine anderen Requests absetzt, und merkt, wenn sich
 *    die Lage wieder normalisiert hat)
 *
 * Bewusst außerhalb von React gehalten: Der Interceptor ist kein Hook und muss
 * den Zustand melden können, ohne dass eine Komponente ihn aufruft.
 */

export type DegradedReason = 'database' | 'unreachable' | 'sqlite_fallback'

export interface DegradedState {
  /** null = alles in Ordnung. */
  reason: DegradedReason | null
  /** request_id der Antwort, die den Zustand gemeldet hat (für die Log-Suche). */
  requestId?: string
  /** Redigierte Ursache aus dem Backend, nur außerhalb von production gesetzt. */
  cause?: string
}

const OK: DegradedState = { reason: null }

let current: DegradedState = OK
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((l) => l())
}

function isSame(a: DegradedState, b: DegradedState): boolean {
  return a.reason === b.reason && a.requestId === b.requestId && a.cause === b.cause
}

/** Meldet einen gestörten Zustand. Mehrfachaufrufe mit gleichem Inhalt sind No-Ops. */
export function reportDegraded(state: DegradedState): void {
  if (isSame(current, state)) return
  current = state
  emit()
}

/** Hebt die Störungsmeldung auf (z. B. wenn /api/system/status wieder "ok" liefert). */
export function clearDegraded(): void {
  if (current.reason === null) return
  current = OK
  emit()
}

export function getDegradedState(): DegradedState {
  return current
}

export function subscribeDegraded(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Nur für Tests: setzt den Modulzustand zurück. */
export function __resetDegradedState(): void {
  current = OK
  listeners.clear()
}
