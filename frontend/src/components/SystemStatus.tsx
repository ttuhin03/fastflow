import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { MdCheckCircle, MdError, MdStorage, MdFolder, MdDns, MdMemory } from 'react-icons/md'
import './SystemStatus.css'

interface SystemStatusResponse {
  status: 'ready' | 'not_ready'
  checks: Record<string, unknown>
  version?: string
}

const CHECK_ICONS: Record<string, React.ReactNode> = {
  database: <MdStorage />,
  docker: <MdDns />,
  kubernetes: <MdDns />,
  uv_cache: <MdFolder />,
  disk: <MdStorage />,
  inodes: <MdMemory />,
}

function isOk(value: unknown): boolean {
  return value === 'ok' || value === 'n/a (nur Unix)'
}

export default function SystemStatus() {
  const { t } = useTranslation()
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
        <span>{t('systemStatus.loading')}</span>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="system-status error">
        <MdError />
        <span>{t('systemStatus.error')}</span>
      </div>
    )
  }

  const checks = data.checks as Record<string, string | number>
  const checkKeys = Object.keys(CHECK_ICONS).filter((key) => key in checks)

  return (
    <div className={`system-status ${data.status === 'not_ready' ? 'has-errors' : ''}`}>
      <div className="system-status-grid">
        {checkKeys.map((key) => {
          const value = checks[key]
          const ok = isOk(value)
          const label = t(`warnings.systemLabels.${key}`, { defaultValue: key })
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
