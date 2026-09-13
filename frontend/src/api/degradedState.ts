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

/**
 * Wann die Beobachtung gemacht wurde, die `current` traegt - auf der monotonen
 * Uhr der Seite.
 *
 * Bewusst nicht Teil von DegradedState: Das Banner rendert den Wert nicht, und
 * `current` muss referenzstabil bleiben, solange sich sichtbar nichts aendert
 * (useSyncExternalStore vergleicht per Referenz).
 *
 * performance.now() statt Date.now(), weil hier ausschliesslich Zeitpunkte
 * derselben Seite verglichen werden: Eine NTP-Korrektur oder eine vom Benutzer
 * verstellte Uhr koennte eine frische Beobachtung sonst aelter aussehen lassen
 * als die bereits gespeicherte - und das Banner damit dauerhaft einfrieren.
 *
 * Startwert -Infinity, nicht 0: performance.now() zaehlt ab Seitenaufruf, in den
 * ersten Sekunden ist `now - age` also negativ. Mit 0 als Startwert wuerde
 * ausgerechnet die erste Meldung nach dem Laden verworfen.
 */
let currentObservedAt = Number.NEGATIVE_INFINITY

const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((l) => l())
}

function isSame(a: DegradedState, b: DegradedState): boolean {
  return a.reason === b.reason && a.requestId === b.requestId && a.cause === b.cause
}

/**
 * Meldet einen gestörten Zustand. Mehrfachaufrufe mit gleichem Inhalt sind No-Ops.
 *
 * `observedAt` ist der Zeitpunkt, zu dem der Zustand *beobachtet* wurde, nicht
 * der des Aufrufs. Für den Interceptor sind beide gleich (er sieht die Antwort
 * live); der Poll muss das Alter aus age_seconds herausrechnen, weil der Server
 * den Status cacht.
 */
export function reportDegraded(
  state: DegradedState,
  observedAt: number = performance.now(),
): void {
  if (!accept(observedAt)) return
  if (isSame(current, state)) return
  current = state
  emit()
}

/**
 * Hebt die Störungsmeldung auf (z. B. wenn /api/system/status wieder "ok" liefert).
 *
 * Siehe reportDegraded zu `observedAt` — gerade hier zählt es: Ein "ok" aus dem
 * Server-Cache ist der Normalfall direkt nach Beginn einer Störung.
 */
export function clearDegraded(observedAt: number = performance.now()): void {
  if (!accept(observedAt)) return
  if (current.reason === null) return
  current = OK
  emit()
}

/**
 * Verwirft Beobachtungen, die älter sind als die bereits gespeicherte.
 *
 * Der Grund ist der Cache in /api/system/status: Meldet der Interceptor einen
 * 503 (live beobachtet), liefert der naechste Poll womoeglich noch ein "ok",
 * das vor dem Ausfall gemessen wurde. Ohne diese Pruefung wuerde es das Banner
 * ausblenden — bis zum uebernaechsten Poll, also genau in dem Moment, in dem
 * der Benutzer gerade einen Fehler gesehen hat. Umgekehrt genauso: Ein
 * gecachtes "degraded" darf ein juengeres "ok" nicht zurueckdrehen.
 *
 * Gleiches Alter wird akzeptiert — zwei Beobachtungen im selben Millisekunden-
 * Tick sind nicht unterscheidbar, und die spaetere ist dann die genauere.
 */
function accept(observedAt: number): boolean {
  if (observedAt < currentObservedAt) return false
  currentObservedAt = observedAt
  return true
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
  currentObservedAt = Number.NEGATIVE_INFINITY
  listeners.clear()
}
