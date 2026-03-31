import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'

export interface AuthProviders {
  github?: boolean
  google?: boolean
  microsoft?: boolean
  custom?: boolean
  login_branding_logo_url?: string
  custom_oauth_icon_url?: string
  custom_display_name?: string
  /** false = nur konfigurierte Provider auf der Login-Seite */
  show_unconfigured_oauth_on_login?: boolean
}

export const PROVIDER_ORDER = ['github', 'google', 'microsoft', 'custom'] as const
export type ProviderId = (typeof PROVIDER_ORDER)[number]

/**
 * Gleiche Logik wie Login: sichtbare OAuth-Provider aus /auth/providers,
 * sortiert (aktivierte zuerst).
 */
export function useAuthProviders() {
  const { data: providers = {} } = useQuery<AuthProviders>({
    queryKey: ['auth/providers'],
    queryFn: async () => {
      try {
        const r = await apiClient.get('/auth/providers')
        return r.data
      } catch {
        return {}
      }
    },
    staleTime: 60_000,
  })

  const orderedProviderIds = useMemo(() => {
    const showUnconfigured = providers.show_unconfigured_oauth_on_login !== false
    const candidates = PROVIDER_ORDER.filter((id) => {
      if (showUnconfigured) return true
      return providers[id] === true
    })
    return [...candidates].sort((a, b) => {
      const aOn = providers[a] === true
      const bOn = providers[b] === true
      if (aOn !== bOn) return aOn ? -1 : 1
      return PROVIDER_ORDER.indexOf(a) - PROVIDER_ORDER.indexOf(b)
    })
  }, [providers])

  return { providers, orderedProviderIds }
}
