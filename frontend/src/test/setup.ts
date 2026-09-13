// jest-dom-Matcher manuell registrieren statt '@testing-library/jest-dom/vitest' zu
// importieren: jest-dom ist im Workspace-Root gehoistet und kann von dort das im
// frontend-Workspace installierte 'vitest' nicht auflösen. Typen: siehe jest-dom.d.ts.
import * as matchers from '@testing-library/jest-dom/matchers'
import { expect, beforeAll } from 'vitest'
import i18n from '../i18n'

expect.extend(matchers)

// jsdom stellt hier kein localStorage bereit (das Global ist ein leeres Objekt),
// Zugriffe darauf würden mit "getItem is not a function" sterben. Minimale
// In-Memory-Variante, damit Komponenten mit Speicherzugriff testbar sind.
if (typeof localStorage?.getItem !== 'function') {
  const store = new Map<string, string>()
  const memoryStorage: Storage = {
    get length() {
      return store.size
    },
    clear: () => store.clear(),
    getItem: (key) => (store.has(key) ? (store.get(key) as string) : null),
    key: (index) => Array.from(store.keys())[index] ?? null,
    removeItem: (key) => {
      store.delete(key)
    },
    setItem: (key, value) => {
      store.set(key, String(value))
    },
  }
  Object.defineProperty(globalThis, 'localStorage', {
    value: memoryStorage,
    configurable: true,
    writable: true,
  })
}


// Komponenten-Tests erwarten deutsche UI-Texte (jsdom meldet navigator.language 'en-US').
beforeAll(async () => {
  await i18n.changeLanguage('de')
})
