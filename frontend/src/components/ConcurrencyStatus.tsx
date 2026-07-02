import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import './ConcurrencyStatus.css'

interface ConcurrencyResponse {
  active_runs: number
  concurrency_limit: number
  utilization: number
  executor: string
  queued_runs?: number
}

export default function ConcurrencyStatus() {
  const { t } = useTranslation()
  const interval = useRefetchInterval(15000)
  const { data, isLoading } = useQuery<ConcurrencyResponse>({
    queryKey: ['concurrency'],
    queryFn: async () => {
      const res = await apiClient.get('/settings/concurrency')
      return res.data
    },
    refetchInterval: interval,
  })

  if (isLoading || !data) return null

  const limit = Math.max(data.concurrency_limit, 1)
  const active = Math.min(data.active_runs, limit)
  const isHigh = data.utilization >= 0.9
  const isMedium = data.utilization >= 0.6 && data.utilization < 0.9
  const fillClass = isHigh ? 'high' : isMedium ? 'medium' : ''

  const slots = Array.from({ length: limit }, (_, i) => i < active)

  return (
    <div className="concurrency-status card">
      <h3 className="section-title concurrency-title">{t('concurrency.label')}</h3>
      <div className="concurrency-headline">
        <span className="concurrency-value mono">
          {active}
          <span className="concurrency-limit"> / {limit}</span>
        </span>
        <span className="concurrency-sub">{t('concurrency.activeSlots', 'active slots')}</span>
      </div>
      <div className="concurrency-slots" aria-hidden>
        {slots.map((filled, i) => (
          <div key={i} className={`concurrency-slot ${filled ? `filled ${fillClass}` : ''}`} />
        ))}
      </div>
      <div className="concurrency-foot mono">
        <span>
          {data.queued_runs != null
            ? t('concurrency.queuedCount', { count: data.queued_runs, defaultValue: '{{count}} queued' })
            : t('concurrency.executor', { executor: data.executor, defaultValue: '{{executor}}' })}
        </span>
        <span>{t('concurrency.limitN', { limit, defaultValue: 'limit {{limit}}' })}</span>
      </div>
      {isHigh && <p className="concurrency-hint">{t('concurrency.hintHigh')}</p>}
    </div>
  )
}
