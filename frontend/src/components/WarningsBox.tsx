import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { MdWarning } from 'react-icons/md'
import './WarningsBox.css'

interface SystemStatusResponse {
  status: string
  checks: Record<string, unknown>
}

interface StorageStats {
  free_disk_space_gb?: number
  inode_used_percent?: number
}

interface SyncStatus {
  status?: string
  last_sync?: string
  error?: string
}

interface ConcurrencyResponse {
  utilization: number
}

interface SummaryStatsResponse {
  last_7d: { success_rate_pct: number; total_runs: number }
}

const SYNC_STALE_HOURS = 24
const SUCCESS_RATE_THRESHOLD = 80
const DISK_WARN_GB = 1
const INODE_WARN_PCT = 90

function useWarnings(): string[] {
  const { t } = useTranslation()
  const interval = useRefetchInterval(30000)
  const refetch = { refetchInterval: interval }

  const { data: systemStatus } = useQuery<SystemStatusResponse>({
    queryKey: ['system-status'],
    queryFn: async () => (await apiClient.get('/settings/system-status')).data,
    ...refetch,
  })
  const { data: storage } = useQuery<StorageStats>({
    queryKey: ['storage-stats'],
    queryFn: async () => (await apiClient.get('/settings/storage')).data,
    ...refetch,
  })
  const { data: syncStatus } = useQuery<SyncStatus>({
    queryKey: ['sync-status'],
    queryFn: async () => (await apiClient.get('/sync/status')).data,
    ...refetch,
  })
  const { data: concurrency } = useQuery<ConcurrencyResponse>({
    queryKey: ['concurrency'],
    queryFn: async () => (await apiClient.get('/settings/concurrency')).data,
    ...refetch,
  })
  const { data: summaryStats } = useQuery<SummaryStatsResponse>({
    queryKey: ['summary-stats'],
    queryFn: async () => (await apiClient.get('/pipelines/summary-stats')).data,
    ...refetch,
  })

  const warnings: string[] = []

  if (systemStatus?.status === 'not_ready') {
    const failed = Object.entries(systemStatus.checks || {}).filter(
      ([k, v]) => k !== 'disk_free_gb' && k !== 'inode_total' && k !== 'inode_free' && v !== 'ok' && v !== 'n/a (nur Unix)'
    )
    failed.forEach(([key]) => {
      const label = t(`warnings.systemLabels.${key}`, { defaultValue: key })
      warnings.push(t('warnings.systemProblem', { label }))
    })
  }

  if (storage) {
    if (storage.free_disk_space_gb != null && storage.free_disk_space_gb < DISK_WARN_GB) {
      warnings.push(t('warnings.diskLow', { gb: storage.free_disk_space_gb.toFixed(1) }))
    }
    if (storage.inode_used_percent != null && storage.inode_used_percent > INODE_WARN_PCT) {
      warnings.push(t('warnings.inodeLow', { pct: storage.inode_used_percent.toFixed(0) }))
    }
  }

  if (syncStatus) {
    if (syncStatus.status === 'failed') {
      warnings.push(t('warnings.gitSyncFailed'))
    } else if (syncStatus.last_sync) {
      const last = new Date(syncStatus.last_sync).getTime()
      const hours = (Date.now() - last) / (1000 * 60 * 60)
      if (hours > SYNC_STALE_HOURS) {
        warnings.push(t('warnings.gitSyncStale', { hours: Math.round(hours) }))
      }
    }
  }

  if (concurrency != null && (concurrency.utilization ?? 0) >= 1) {
    warnings.push(t('warnings.concurrencyFull'))
  }

  if (
    summaryStats?.last_7d &&
    summaryStats.last_7d.total_runs > 0 &&
    summaryStats.last_7d.success_rate_pct < SUCCESS_RATE_THRESHOLD
  ) {
    warnings.push(
      t('warnings.successRateLow', {
        threshold: SUCCESS_RATE_THRESHOLD,
        rate: summaryStats.last_7d.success_rate_pct.toFixed(1),
      })
    )
  }

  return warnings
}

export default function WarningsBox() {
  const { t } = useTranslation()
  const warnings = useWarnings()

  if (warnings.length === 0) return null

  return (
    <div className="warnings-box">
      <div className="warnings-box-header">
        <MdWarning className="warnings-box-icon" />
        <h3 className="warnings-box-title">{t('warnings.title')}</h3>
      </div>
      <ul className="warnings-box-list">
        {warnings.map((text, i) => (
          <li key={i}>{text}</li>
        ))}
      </ul>
    </div>
  )
}
