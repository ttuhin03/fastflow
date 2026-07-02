// Test-Stub: react-i18next importiert 'use-sync-external-store/shim' (CJS).
// Dessen internes require('react') läuft per Node-Resolution und würde im
// npm-Workspace das Root-React 19 laden (→ "Invalid hook call"). React 18 hat
// den Hook eingebaut — direkt re-exportieren, damit dieselbe React-Instanz
// wie im restlichen Test-Setup verwendet wird.
export { useSyncExternalStore } from 'react'
