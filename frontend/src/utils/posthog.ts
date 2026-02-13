/**
 * PostHog Frontend (Phase 2a: Error-Tracking).
 * Lazy-Init: nur wenn Backend enable_error_reporting=true.
 * Exception-Autocapture + manuell captureException (z.B. ErrorBoundary).
 */

import posthog from 'posthog-js'
import { getApiBaseUrl } from '../config'

let initialized = false

function getTelemetryStatusUrl(): string {
  const base = getApiBaseUrl().replace(/\/$/, '')
  return `${base}/settings/telemetry-status`
}

/**
 * Holt Telemetry-Status vom Backend und initialisiert PostHog, falls enable_error_reporting.
 * Sollte vor dem ersten Render aufgerufen werden (z.B. in main.tsx).
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
    const apiHost = d.posthog_host || 'https://eu.posthog.com'
    posthog.init(d.posthog_api_key, {
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
  if (!initialized) return
  try {
    posthog.captureException(error, props)
  } catch {
    // ignore
  }
}

export { posthog }
