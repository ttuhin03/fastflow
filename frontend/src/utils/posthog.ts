/**
 * PostHog Frontend (Phase 2a: Error-Tracking).
 * Lazy-Init: nur wenn Backend enable_error_reporting=true.
 * posthog-js wird erst dann dynamisch geladen (hält es aus dem Initial-Bundle heraus).
 * Exception-Autocapture + manuell captureException (z.B. ErrorBoundary).
 */

import { getApiBaseUrl } from '../config'

type PostHogInstance = typeof import('posthog-js').default

let ph: PostHogInstance | null = null
let initialized = false

function getTelemetryStatusUrl(): string {
  const base = getApiBaseUrl().replace(/\/$/, '')
  return `${base}/settings/telemetry-status`
}

/**
 * Holt Telemetry-Status vom Backend und initialisiert PostHog, falls enable_error_reporting.
 * Bewusst NICHT vor dem ersten Render awaiten (main.tsx ruft es fire-and-forget auf),
 * damit weder der Netzwerk-Call noch posthog-js den initialen Paint blockieren.
 */
export async function initPostHog(): Promise<void> {
  if (typeof window === 'undefined') return
  if (initialized) return
  try {
    const url = getTelemetryStatusUrl()
    const res = await fetch(url, { credentials: 'include' })
    if (!res.ok) return
    const d = await res.json()
    if (!d?.enable_error_reporting || !d?.posthog_api_key) return
    // Erst hier laden — separates Chunk, nur wenn Error-Reporting aktiv ist.
    const mod = await import('posthog-js')
    ph = mod.default
    const apiHost = d.posthog_host || 'https://eu.posthog.com'
    ph.init(d.posthog_api_key, {
      api_host: apiHost,
      defaults: '2025-11-30',
      // Nur Error-Tracking (Phase 2a); Replay/Analytics später
      disable_session_recording: true,
      capture_pageview: false,
    })
    initialized = true
  } catch {
    // still
  }
}

/**
 * Manuell Exception an PostHog senden (z.B. aus ErrorBoundary).
 * No-Op wenn PostHog nicht initialisiert.
 */
export function captureException(error: unknown, props?: Record<string, unknown>): void {
  if (!initialized || !ph) return
  try {
    ph.captureException(error, props)
  } catch {
    // ignore
  }
}
