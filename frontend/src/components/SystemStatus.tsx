import { useQuery } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { MdCheckCircle, MdError, MdStorage, MdFolder, MdDns, MdMemory } from 'react-icons/md'
import './SystemStatus.css'

interface SystemStatusResponse {
  status: 'ready' | 'not_ready'
  checks: Record<string, unknown>
  version?: string
}

const CHECK_LABELS: Record<string, { label: string; icon: React.ReactNode }> = {
  database: { label: 'Datenbank', icon: <MdStorage /> },
  docker: { label: 'Docker', icon: <MdDns /> },
  kubernetes: { label: 'Kubernetes', icon: <MdDns /> },
  uv_cache: { label: 'UV-Cache', icon: <MdFolder /> },
  disk: { label: 'Speicherplatz', icon: <MdStorage /> },
  inodes: { label: 'Inodes', icon: <MdMemory /> },
}

function isOk(value: unknown): boolean {
  return value === 'ok' || value === 'n/a (nur Unix)'
}

export default function SystemStatus() {
  const interval = useRefetchInterval(30000)
  const { data, isLoading } = useQuery<SystemStatusResponse>({
    queryKey: ['system-status'],
    queryFn: async () => {
      const res = await apiClient.get('/settings/system-status')
      return res.data
    },
    refetchInterval: interval,
  })

  if (isLoading) {
    return (
      <div className="system-status loading">
        <div className="spinner"></div>
        <span>System-Status wird geladen…</span>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="system-status error">
        <MdError />
        <span>System-Status konnte nicht geladen werden.</span>
      </div>
    )
  }

  const checks = data.checks as Record<string, string | number>
  const entries = Object.entries(CHECK_LABELS).filter(([key]) => key in checks)

  return (
    <div className={`system-status ${data.status === 'not_ready' ? 'has-errors' : ''}`}>
      <div className="system-status-grid">
        {entries.map(([key, { label }]) => {
          const value = checks[key]
          const ok = isOk(value)
          return (
            <div key={key} className={`system-status-item ${ok ? 'ok' : 'error'}`} title={String(value)}>
              <span className="system-status-icon">{ok ? <MdCheckCircle /> : <MdError />}</span>
              <span className="system-status-label">{label}</span>
              {!ok && <span className="system-status-detail">{String(value).slice(0, 40)}</span>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
