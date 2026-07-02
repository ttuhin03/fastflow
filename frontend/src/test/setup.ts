// jest-dom-Matcher manuell registrieren statt '@testing-library/jest-dom/vitest' zu
// importieren: jest-dom ist im Workspace-Root gehoistet und kann von dort das im
// frontend-Workspace installierte 'vitest' nicht auflösen. Typen: siehe jest-dom.d.ts.
import * as matchers from '@testing-library/jest-dom/matchers'
import { expect, beforeAll } from 'vitest'
import i18n from '../i18n'

expect.extend(matchers)

// Komponenten-Tests erwarten deutsche UI-Texte (jsdom meldet navigator.language 'en-US').
beforeAll(async () => {
  await i18n.changeLanguage('de')
})
