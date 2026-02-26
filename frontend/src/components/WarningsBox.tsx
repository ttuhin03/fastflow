import { useQuery } from '@tanstack/react-query'
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
      const labels: Record<string, string> = {
        database: 'Datenbank',
        docker: 'Docker',
        kubernetes: 'Kubernetes',
        uv_cache: 'UV-Cache',
        disk: 'Speicherplatz',
        inodes: 'Inodes',
      }
      warnings.push(`${labels[key] || key}: Problem`)
    })
  }

  if (storage) {
    if (storage.free_disk_space_gb != null && storage.free_disk_space_gb < DISK_WARN_GB) {
      warnings.push(`Wenig Speicherplatz: nur ${storage.free_disk_space_gb.toFixed(1)} GB frei`)
    }
    if (storage.inode_used_percent != null && storage.inode_used_percent > INODE_WARN_PCT) {
      warnings.push(`Inodes stark belegt: ${storage.inode_used_percent.toFixed(0)}%`)
    }
  }

  if (syncStatus) {
    if (syncStatus.status === 'failed') {
      warnings.push('Letzter Git-Sync ist fehlgeschlagen')
    } else if (syncStatus.last_sync) {
      const last = new Date(syncStatus.last_sync).getTime()
      const hours = (Date.now() - last) / (1000 * 60 * 60)
      if (hours > SYNC_STALE_HOURS) {
        warnings.push(`Seit über ${Math.round(hours)} Stunden kein erfolgreicher Git-Sync`)
      }
    }
  }

  if (concurrency != null && (concurrency.utilization ?? 0) >= 1) {
    warnings.push('Concurrency-Limit erreicht – Runs warten')
  }

  if (
    summaryStats?.last_7d &&
    summaryStats.last_7d.total_runs > 0 &&
    summaryStats.last_7d.success_rate_pct < SUCCESS_RATE_THRESHOLD
  ) {
    warnings.push(
      `Success Rate (7 Tage) unter ${SUCCESS_RATE_THRESHOLD}%: ${summaryStats.last_7d.success_rate_pct.toFixed(1)}%`
    )
  }

  return warnings
}

export default function WarningsBox() {
  const warnings = useWarnings()

  if (warnings.length === 0) return null

  return (
    <div className="warnings-box">
      <div className="warnings-box-header">
        <MdWarning className="warnings-box-icon" />
        <h3 className="warnings-box-title">Hinweise zur Stabilität</h3>
      </div>
      <ul className="warnings-box-list">
        {warnings.map((text, i) => (
          <li key={i}>{text}</li>
        ))}
      </ul>
    </div>
  )
}
