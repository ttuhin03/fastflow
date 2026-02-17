/**
 * Hook für visibility-aware refetchInterval.
 * - Sichtbar: normales Intervall (in Produktion verlängert, um parallele API-Last zu reduzieren).
 * - Versteckt: längeres Intervall (z.B. 60000ms) oder kein Polling.
 */
import { useState, useEffect } from 'react'

const isProduction = import.meta.env.PROD
const PRODUCTION_REFETCH_MULTIPLIER = 2
const PRODUCTION_REFETCH_MIN_MS = 10_000

function getVisibleInterval(intervalMs: number): number {
  if (!isProduction) return intervalMs
  return Math.max(intervalMs * PRODUCTION_REFETCH_MULTIPLIER, PRODUCTION_REFETCH_MIN_MS)
}

export function useRefetchInterval(
  intervalMs: number | false,
  hiddenIntervalMs: number | false = 60_000
): number | false {
  const [isVisible, setIsVisible] = useState(() =>
    typeof document !== 'undefined' ? !document.hidden : true
  )

  useEffect(() => {
    if (typeof document === 'undefined') return
    const handler = () => setIsVisible(!document.hidden)
    document.addEventListener('visibilitychange', handler)
    return () => document.removeEventListener('visibilitychange', handler)
  }, [])

  if (!intervalMs) return false
  return isVisible ? getVisibleInterval(intervalMs) : hiddenIntervalMs
}
