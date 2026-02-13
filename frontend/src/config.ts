/**
 * Runtime-Konfiguration für das Frontend.
 * Die API-URL wird nicht mehr zur Build-Zeit (VITE_API_URL) gesetzt,
 * sondern zur Laufzeit: Frontend und API werden immer vom gleichen Origin
 * ausgeliefert, daher reicht window.location.origin. Ein Build funktioniert
 * so in jeder Umgebung (localhost, NodePort, Ingress).
 */
export function getApiOrigin(): string {
  if (typeof window === 'undefined') return ''
  return window.location.origin
}

/** Basis-URL für API-Requests (relativ oder absolut). Relative /api funktioniert, wenn Frontend und API gleicher Origin sind. */
export function getApiBaseUrl(): string {
  const origin = getApiOrigin()
  return origin ? `${origin}/api` : '/api'
}
