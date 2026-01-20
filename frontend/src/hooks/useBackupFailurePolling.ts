import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNotifications } from '../contexts/NotificationContext'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'

const SEEN_KEY = 'fastflow-backup-failure-seen'
const MAX_SEEN = 100

function getSeen(): string[] {
  try {
    const raw = localStorage.getItem(SEEN_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function markSeen(key: string) {
  const seen = getSeen()
  if (!seen.includes(key)) {
    seen.push(key)
    localStorage.setItem(SEEN_KEY, JSON.stringify(seen.slice(-MAX_SEEN)))
  }
}

/**
 * Pollt /api/settings/backup-failures und zeigt für neue S3-Backup-Fehler
 * eine UI-Benachrichtigung (NotificationCenter + Toast).
 */
export function useBackupFailurePolling() {
  const { addNotification } = useNotifications()
  const { isAuthenticated } = useAuth()

  const { data } = useQuery({
    queryKey: ['settings', 'backup-failures'],
    queryFn: async () => {
      const r = await apiClient.get<{ failures: { run_id: string; pipeline_name: string; error_message: string; created_at: string }[] }>('/settings/backup-failures')
      return r.data
    },
    refetchInterval: 90 * 1000, // 90s
    enabled: isAuthenticated,
  })

  useEffect(() => {
    if (!data?.failures?.length) return
    const seen = getSeen()
    for (const f of data.failures) {
      const key = `${f.run_id}:${f.created_at}`
      if (seen.includes(key)) continue
      addNotification({
        type: 'error',
        title: 'S3 Log-Backup fehlgeschlagen',
        message: `${f.pipeline_name} (Run ${f.run_id}): ${f.error_message}`,
        actionUrl: `/runs/${f.run_id}`,
        actionLabel: 'Run anzeigen',
      })
      markSeen(key)
    }
  }, [data, addNotification])
}
