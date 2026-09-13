import { useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'
import {
  Context,
  UI_DISPLAY_QUERY_KEY,
  normalizeLoginBackground,
  type UiDisplayApi,
} from './UiPreferencesContext'

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

