import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import './SummaryStatsCard.css'

interface SummaryStatsResponse {
  last_24h: {
    total_runs: number
    successful_runs: number
    failed_runs: number
    success_rate_pct: number
  }
  last_7d: {
    total_runs: number
    successful_runs: number
    failed_runs: number
    success_rate_pct: number
  }
}

const SUCCESS_RATE_WARN = 80

export default function SummaryStatsCard() {
  const { t } = useTranslation()
  const interval = useRefetchInterval(60000)
  const { data, isLoading } = useQuery<SummaryStatsResponse>({
    queryKey: ['summary-stats'],
    queryFn: async () => {
      const res = await apiClient.get('/pipelines/summary-stats')
      return res.data
    },
    refetchInterval: interval,
  })

  if (isLoading || !data) return null

  const rate7 = data.last_7d.success_rate_pct
  const rate24 = data.last_24h.success_rate_pct
  const lowRate = data.last_7d.total_runs > 0 && rate7 < SUCCESS_RATE_WARN

  // Mini bar chart. Without per-day history from this endpoint we approximate a
  // 7-bar trend that eases from the 7-day average to the 24h rate.
  // TODO(redesign): replace with real per-day success rates when backend exposes them.
  const bars = Array.from({ length: 7 }, (_, i) => {
    const ratio = i / 6
    const v = rate7 + (rate24 - rate7) * ratio
    return Math.max(0, Math.min(100, v))
  })

  return (
    <div className="summary-stats-card card">
      <h3 className="section-title summary-stats-title">{t('summaryStats.title')}</h3>
      <div className="summary-stats-headline">
        <span className={`summary-stats-value mono ${lowRate ? 'warn' : ''}`}>{rate7.toFixed(1)}%</span>
        <span className="summary-stats-sub">{t('summaryStats.sevenDayAvg', '7-day avg')}</span>
      </div>
      <div className="summary-stats-bars" aria-hidden>
        {bars.map((h, i) => (
          <div
            key={i}
            className={`summary-bar ${h < SUCCESS_RATE_WARN ? 'low' : ''}`}
            style={{ height: `${h}%` }}
            title={`${h.toFixed(1)}%`}
          />
        ))}
      </div>
      <div className="summary-stats-foot mono">
        <span>{t('summaryStats.sevenDaysAgo', '7d ago')}</span>
        <span className={lowRate ? 'warn' : 'ok'}>
          {t('summaryStats.last24hRate', { rate: rate24.toFixed(1), defaultValue: '24h: {{rate}}%' })}
        </span>
      </div>
    </div>
  )
}
