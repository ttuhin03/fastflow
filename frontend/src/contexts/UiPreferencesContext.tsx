import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'

export const UI_DISPLAY_QUERY_KEY = ['ui-display'] as const

export type UiLoginBackground = 'video' | 'game_of_life'

type UiDisplayApi = {
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

function normalizeLoginBackground(raw: string | undefined): UiLoginBackground {
  return raw === 'game_of_life' ? 'game_of_life' : 'video'
}

const Context = createContext<UiPrefs | null>(null)

export function UiPreferencesProvider({ children }: { children: ReactNode }) {
  const { data } = useQuery({
    queryKey: UI_DISPLAY_QUERY_KEY,
    queryFn: async () => {
      const r = await apiClient.get<UiDisplayApi>('/settings/ui-display')
      return r.data
    },
    staleTime: 60_000,
    retry: 1,
  })

  const value = useMemo(
    () => ({
      showAttribution: data?.ui_show_attribution ?? true,
      showVersion: data?.ui_show_version ?? true,
      loginBackground: normalizeLoginBackground(data?.ui_login_background),
      headerTimezone1: data?.ui_header_timezone_1 ?? 'UTC',
      headerTimezone2: data?.ui_header_timezone_2 ?? 'Europe/Berlin',
    }),
    [
      data?.ui_show_attribution,
      data?.ui_show_version,
      data?.ui_login_background,
      data?.ui_header_timezone_1,
      data?.ui_header_timezone_2,
    ]
  )

  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useUiPreferences(): UiPrefs {
  const c = useContext(Context)
  if (!c) throw new Error('useUiPreferences must be used within UiPreferencesProvider')
  return c
}
