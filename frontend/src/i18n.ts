/**
 * i18n setup for DE/EN UI.
 * Language persisted in localStorage (key: fastflow_lang).
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import de from './locales/de.json'
import en from './locales/en.json'

const STORAGE_KEY = 'fastflow_lang'

function getInitialLanguage(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'de' || stored === 'en') return stored
  } catch {
    // ignore
  }
  const browser = navigator.language?.toLowerCase()
  if (browser?.startsWith('de')) return 'de'
  return 'en'
}

i18n.use(initReactI18next).init({
  resources: {
    de: { translation: de },
    en: { translation: en },
  },
  lng: getInitialLanguage(),
  fallbackLng: 'de',
  interpolation: {
    escapeValue: false,
  },
})

i18n.on('languageChanged', (lng) => {
  try {
    localStorage.setItem(STORAGE_KEY, lng)
  } catch {
    // ignore
  }
})

export default i18n
