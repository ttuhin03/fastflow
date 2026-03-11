import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNotifications } from '../contexts/NotificationContext'
import { useAuth } from '../contexts/AuthContext'
import { useRefetchInterval } from './useRefetchInterval'
import apiClient from '../api/client'

interface Run {
  id: string
  pipeline_name: string
  status: string
  exit_code: number | null
}

/**
 * Hook zum Überwachen von Run-Status-Änderungen und Anzeigen von Notifications.
 * 
 * Wird automatisch in der App verwendet, um bei Pipeline-Fehlern, 
 * Soft-Limit-Überschreitungen etc. Notifications anzuzeigen.
 */
export function useRunNotifications() {
  const { t } = useTranslation()
  const { addNotification } = useNotifications()
  const { isAuthenticated } = useAuth()
  const previousRunsRef = useRef<Map<string, string>>(new Map())
  const runsInterval = useRefetchInterval(5000)
  const recentInterval = useRefetchInterval(10000)

  // Überwache laufende Runs
  const { data: runsData } = useQuery({
    queryKey: ['runs', 'notifications'],
    queryFn: async () => {
      const response = await apiClient.get('/runs?limit=100&status_filter=RUNNING')
      return response.data as { runs: Run[] }
    },
    refetchInterval: runsInterval,
    enabled: isAuthenticated,
  })

  // Überwache kürzlich abgeschlossene Runs (für Fehler-Notifications)
  const { data: recentRuns } = useQuery({
    queryKey: ['runs', 'recent'],
    queryFn: async () => {
      const response = await apiClient.get('/runs?limit=50')
      return response.data as { runs: Run[] }
    },
    refetchInterval: recentInterval,
    enabled: isAuthenticated,
  })

  useEffect(() => {
    if (!runsData?.runs && !recentRuns?.runs) return

    const allRuns = [
      ...(runsData?.runs || []),
      ...(recentRuns?.runs || []),
    ]

    allRuns.forEach((run) => {
      const previousStatus = previousRunsRef.current.get(run.id)
      const currentStatus = run.status

      // Nur bei Status-Änderung Notifications
      if (previousStatus && previousStatus !== currentStatus) {
        // Run wurde fehlgeschlagen
        if (currentStatus === 'FAILED' && (previousStatus === 'RUNNING' || previousStatus === 'PENDING')) {
          const exitCodeSuffix = run.exit_code !== null
            ? t('runNotifications.exitCode', { code: run.exit_code })
            : ''
          addNotification({
            type: 'error',
            title: t('runNotifications.pipelineFailed'),
            message: t('runNotifications.pipelineFailedMsg', { name: run.pipeline_name, exitCode: exitCodeSuffix }),
            actionUrl: `/runs/${run.id}`,
            actionLabel: t('runNotifications.viewDetails'),
          })
        }

        // Run wurde erfolgreich (optional, nur wenn vorher fehlgeschlagen war)
        if (currentStatus === 'SUCCESS' && previousStatus === 'FAILED') {
          addNotification({
            type: 'success',
            title: t('runNotifications.pipelineSuccessAfterRetry'),
            message: t('runNotifications.pipelineSuccessAfterRetryMsg', { name: run.pipeline_name }),
            actionUrl: `/runs/${run.id}`,
            actionLabel: t('runNotifications.viewDetails'),
          })
        }
      }

      // Status speichern
      previousRunsRef.current.set(run.id, currentStatus)
    })

    // Alte Runs werden automatisch durch Map-Größen-Limit behandelt
    // (Map wird bei jedem neuen Run aktualisiert)
  }, [runsData, recentRuns, addNotification, t])
}
