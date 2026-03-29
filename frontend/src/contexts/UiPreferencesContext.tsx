import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'

export const UI_DISPLAY_QUERY_KEY = ['ui-display'] as const

type UiDisplayApi = {
  ui_show_attribution: boolean
  ui_show_version: boolean
}

type UiPrefs = {
  showAttribution: boolean
  showVersion: boolean
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
    }),
    [data?.ui_show_attribution, data?.ui_show_version]
  )

  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useUiPreferences(): UiPrefs {
  const c = useContext(Context)
  if (!c) throw new Error('useUiPreferences must be used within UiPreferencesProvider')
  return c
}
