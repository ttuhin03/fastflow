/**
 * Hook für visibility-aware refetchInterval.
 * Reduziert API-Last wenn Tab im Hintergrund (document.hidden).
 * - Sichtbar: normales Intervall (z.B. 5000ms)
 * - Versteckt: längeres Intervall (z.B. 60000ms) oder kein Polling
 */
import { useState, useEffect } from 'react'

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
  return isVisible ? intervalMs : hiddenIntervalMs
}
