import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { LuCircleX } from 'react-icons/lu'
import './SystemStatus.css'

interface SystemStatusResponse {
  status: 'ready' | 'not_ready'
  checks: Record<string, unknown>
  version?: string
}

const CHECK_ORDER = ['database', 'docker', 'kubernetes', 'uv_cache', 'disk', 'inodes']

function isOk(value: unknown): boolean {
  return value === 'ok' || value === 'n/a (nur Unix)'
}

/** A degraded value is a non-ok string that still looks like a soft warning (n/a, skipped, …) */
function isDegraded(value: unknown): boolean {
  if (isOk(value)) return false
  const v = String(value).toLowerCase()
  return v.includes('n/a') || v.includes('skip') || v.includes('warn') || v.includes('degraded')
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
        <LuCircleX />
        <span>{t('systemStatus.error')}</span>
      </div>
    )
  }

  const checks = data.checks as Record<string, string | number>
  const checkKeys = CHECK_ORDER.filter((key) => key in checks)

  return (
    <div className={`system-status ${data.status === 'not_ready' ? 'has-errors' : ''}`}>
      {checkKeys.map((key) => {
        const value = checks[key]
        const ok = isOk(value)
        const degraded = isDegraded(value)
        const state = ok ? 'success' : degraded ? 'degraded' : 'error'
        const badgeVariant = ok ? 'badge-success' : degraded ? 'badge-warning' : 'badge-error'
        const label = t(`warnings.systemLabels.${key}`, { defaultValue: key })
        const pill = ok
          ? t('systemStatus.operational', 'Operational')
          : degraded
            ? t('systemStatus.degraded', 'Degraded')
            : t('systemStatus.down', 'Down')
        return (
          <div key={key} className="system-status__row">
            <span className={`status-dot ${state}`} aria-hidden />
            <div className="system-status__info">
              <div className="system-status__name">{label}</div>
              <div className="system-status__detail mono" title={String(value)}>
                {String(value)}
              </div>
            </div>
            <span className={`badge ${badgeVariant}`}>{pill}</span>
          </div>
        )
      })}
    </div>
  )
}
