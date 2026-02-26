import { useQuery } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { MdTrendingUp } from 'react-icons/md'
import './ConcurrencyStatus.css'

interface ConcurrencyResponse {
  active_runs: number
  concurrency_limit: number
  utilization: number
  executor: string
}

export default function ConcurrencyStatus() {
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

  const pct = Math.round(data.utilization * 100)
  const isHigh = data.utilization >= 0.9
  const isMedium = data.utilization >= 0.6 && data.utilization < 0.9

  return (
    <div className="concurrency-status card">
      <div className="concurrency-icon">
        <MdTrendingUp />
      </div>
      <div className="concurrency-content">
        <h4 className="concurrency-label">Concurrency</h4>
        <p className="concurrency-value">
          {data.active_runs} / {data.concurrency_limit} aktive Runs
        </p>
        <div className="concurrency-bar">
          <div
            className={`concurrency-bar-fill ${isHigh ? 'high' : isMedium ? 'medium' : ''}`}
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
        {data.utilization >= 0.9 && (
          <p className="concurrency-hint">Limit oft erreicht – ggf. erhöhen oder Last prüfen.</p>
        )}
      </div>
    </div>
  )
}
