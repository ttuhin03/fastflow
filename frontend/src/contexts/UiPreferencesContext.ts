/**
 * Context, Konstanten und Hook — ohne Komponente, damit der Provider in einer
 * eigenen Datei stehen kann. Ein Modul, das Komponenten und Nicht-Komponenten
 * mischt, lässt Fast Refresh bei jeder Änderung die ganze App neu laden.
 */
import { createContext, useContext } from 'react'

export const UI_DISPLAY_QUERY_KEY = ['ui-display'] as const

export type UiLoginBackground = 'video' | 'game_of_life'

export type UiDisplayApi = {
  ui_show_attribution: boolean
  ui_show_version: boolean
  ui_login_background?: string
  ui_header_timezone_1?: string
  ui_header_timezone_2?: string
}

type UiPrefs = {
  showAttribution: boolean
  showVersion: boolean
  /** Systemweit (SystemSettings); steuert Login-Hintergrund für alle Clients. */
  loginBackground: UiLoginBackground
  /** Zwei IANA-Zeitzonen für die Header-Uhr (systemweit). */
  headerTimezone1: string
  headerTimezone2: string
}

export function normalizeLoginBackground(raw: string | undefined): UiLoginBackground {
  return raw === 'game_of_life' ? 'game_of_life' : 'video'
}

export const Context = createContext<UiPrefs | null>(null)

export function useUiPreferences(): UiPrefs {
  const c = useContext(Context)
  if (!c) throw new Error('useUiPreferences must be used within UiPreferencesProvider')
  return c
}
