import { useQuery } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { MdTimeline, MdWarning } from 'react-icons/md'
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
  const lowRate = data.last_7d.total_runs > 0 && rate7 < SUCCESS_RATE_WARN

  return (
    <div className={`summary-stats-card card ${lowRate ? 'low-rate' : ''}`}>
      <div className="summary-stats-icon">
        <MdTimeline />
      </div>
      <div className="summary-stats-content">
        <h4 className="summary-stats-label">Lauf-Statistik</h4>
        <p className="summary-stats-value">
          Letzte 24h: {data.last_24h.failed_runs} Fehler von {data.last_24h.total_runs} Runs
        </p>
        <p className={`summary-stats-rate ${lowRate ? 'warn' : ''}`}>
          Success Rate (7 Tage): {data.last_7d.success_rate_pct.toFixed(1)}%
          {lowRate && (
            <span className="summary-stats-warn">
              <MdWarning /> Unter {SUCCESS_RATE_WARN}%
            </span>
          )}
        </p>
      </div>
    </div>
  )
}
