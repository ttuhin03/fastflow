import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import { LuRefreshCw } from 'react-icons/lu'
import RunStatusCircles from '../components/RunStatusCircles'
import StorageStats from '../components/StorageStats'
import CalendarHeatmap from '../components/CalendarHeatmap'
import WarningsBox from '../components/WarningsBox'
import SystemStatus from '../components/SystemStatus'
import ConcurrencyStatus from '../components/ConcurrencyStatus'
import SummaryStatsCard from '../components/SummaryStatsCard'
import Sparkline from '../components/Sparkline'
import './Dashboard.css'

interface Pipeline {
  name: string
  has_requirements: boolean
  last_cache_warmup: string | null
  total_runs: number
  successful_runs: number
  failed_runs: number
  enabled: boolean
  metadata: {
    cpu_hard_limit?: number
    mem_hard_limit?: string
    description?: string
    tags?: string[]
  }
}

interface SyncStatus {
  branch: string
  last_sync: string | null
  status: string
}

interface DailyStat {
  date: string
  total_runs: number
  successful_runs: number
  failed_runs: number
  success_rate: number
}

export default function Dashboard() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const pipelinesInterval = useRefetchInterval(30_000, 120_000)
  const syncInterval = useRefetchInterval(15_000, 120_000)
  const dailyStatsInterval = useRefetchInterval(60_000, 120_000)

  const { data: pipelines, isLoading } = useQuery<Pipeline[]>({
    queryKey: ['pipelines'],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines')
      return response.data
    },
    refetchInterval: pipelinesInterval,
    staleTime: 30_000,
  })

  useQuery<SyncStatus>({
    queryKey: ['sync-status'],
    queryFn: async () => {
      const response = await apiClient.get('/sync/status')
      return response.data
    },
    refetchInterval: syncInterval,
  })

  const { data: allPipelinesDailyStats } = useQuery({
    queryKey: ['all-pipelines-daily-stats'],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines/daily-stats/all?days=365')
      return response.data as { daily_stats?: DailyStat[] }
    },
    refetchInterval: dailyStatsInterval,
    staleTime: 120_000,
  })

  const syncMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/sync', {})
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      showSuccess(t('dashboard.syncSuccess'))
    },
    onError: (error: any) => {
      showError(t('dashboard.syncError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const handleSync = async () => {
    if (syncMutation.isPending) return
    const confirmed = await showConfirm(t('dashboard.syncConfirm'))
    if (confirmed) syncMutation.mutate()
  }

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner" />
        <p>{t('common.loading')}</p>
      </div>
    )
  }

  const totalRuns = pipelines?.reduce((sum, p) => sum + p.total_runs, 0) || 0
  const totalSuccessful = pipelines?.reduce((sum, p) => sum + p.successful_runs, 0) || 0
  const successRate = totalRuns > 0 ? ((totalSuccessful / totalRuns) * 100).toFixed(1) : '—'

  // Sparkline data: last ~10 days from daily stats
  const dailyStats = allPipelinesDailyStats?.daily_stats
  const recentDays = dailyStats?.slice(-10) ?? []
  const sparkRuns    = recentDays.map(d => d.total_runs)
  const sparkSuccess = recentDays.map(d => d.successful_runs)
  const sparkRate    = recentDays.map(d => d.success_rate)

  // Trend: compare last day vs 7-day average
  const lastDay = recentDays[recentDays.length - 1]
  const prev7   = recentDays.slice(0, -1)
  const avgRunsPrev = prev7.length ? prev7.reduce((s, d) => s + d.total_runs, 0) / prev7.length : null

  const runsTrend = avgRunsPrev != null && lastDay
    ? lastDay.total_runs > avgRunsPrev ? 'up' : 'down'
    : null
  const runsDelta = avgRunsPrev != null && lastDay
    ? Math.abs(Math.round(((lastDay.total_runs - avgRunsPrev) / Math.max(avgRunsPrev, 1)) * 100))
    : null

  return (
    <div className="dashboard">
      {!isReadonly && (
        <div className="dashboard-header">
          <button
            type="button"
            onClick={handleSync}
            disabled={syncMutation.isPending}
            className="btn btn-primary dashboard-sync-btn"
          >
            <LuRefreshCw size={15} style={syncMutation.isPending ? { animation: 'ff-spin 0.8s linear infinite' } : undefined} />
            {syncMutation.isPending ? t('dashboard.syncRunning') : t('dashboard.gitSync')}
          </button>
        </div>
      )}

      <WarningsBox />

      {/* KPI cards — minimal: label + trend chip / big mono number + sparkline */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-card__top">
            <p className="stat-label">{t('nav.pipelines')}</p>
          </div>
          <div className="stat-card__bottom">
            <p className="stat-value">{pipelines?.length || 0}</p>
            {sparkRuns.length > 1 && <Sparkline data={sparkRuns} color="var(--chart-1)" />}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__top">
            <p className="stat-label">{t('dashboard.totalRuns')}</p>
            {runsTrend && runsDelta != null && (
              <span className={`stat-trend ${runsTrend}`}>
                {runsTrend === 'up' ? '↑' : '↓'} {runsTrend === 'up' ? '+' : '-'}{runsDelta}%
              </span>
            )}
          </div>
          <div className="stat-card__bottom">
            <p className="stat-value">{totalRuns.toLocaleString()}</p>
            {sparkRuns.length > 1 && <Sparkline data={sparkRuns} color="var(--chart-3)" />}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__top">
            <p className="stat-label">{t('dashboard.successful')}</p>
            {sparkSuccess.length > 1 && (
              <span className="stat-trend up">↑</span>
            )}
          </div>
          <div className="stat-card__bottom">
            <p className="stat-value success">{totalSuccessful.toLocaleString()}</p>
            {sparkSuccess.length > 1 && <Sparkline data={sparkSuccess} color="var(--color-success)" />}
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__top">
            <p className="stat-label">{t('dashboard.successRate') || 'Success rate'}</p>
            {sparkRate.length > 1 && (
              <span className="stat-trend up">↑</span>
            )}
          </div>
          <div className="stat-card__bottom">
            <p className="stat-value">{successRate}{typeof successRate === 'string' && successRate !== '—' ? '%' : ''}</p>
            {sparkRate.length > 1 && <Sparkline data={sparkRate} color="var(--chart-2)" />}
          </div>
        </div>
      </div>

      {/* Row 2: Heatmap (1.6fr) + System Status (1fr) */}
      {allPipelinesDailyStats?.daily_stats && allPipelinesDailyStats.daily_stats.length > 0 && (
        <div className="dashboard-row-2">
          <div className="panel">
            <div className="panel__head">
              <h3 className="section-title">{t('dashboard.runHistory')}</h3>
            </div>
            <CalendarHeatmap dailyStats={allPipelinesDailyStats.daily_stats} days={365} showTitle={false} />
          </div>
          <div className="panel">
            <div className="panel__head">
              <h3 className="section-title">{t('dashboard.systemStatus')}</h3>
            </div>
            <SystemStatus />
          </div>
        </div>
      )}

      {/* If no daily stats yet, show system status alone */}
      {(!allPipelinesDailyStats?.daily_stats || allPipelinesDailyStats.daily_stats.length === 0) && (
        <div className="dashboard-system-section">
          <h3 className="section-title">{t('dashboard.systemStatus')}</h3>
          <SystemStatus />
        </div>
      )}

      {/* Row 3: Summary + Concurrency + Storage */}
      <div className="dashboard-row-3">
        <SummaryStatsCard />
        <ConcurrencyStatus />
        <StorageStats />
      </div>

      {/* Pipeline grid */}
      <div className="pipelines-section">
        <h3 className="section-title">{t('nav.pipelines')}</h3>
        {pipelines && pipelines.length > 0 ? (
          <div className="pipeline-grid">
            {pipelines.map((pipeline, index) => {
              const successPct =
                pipeline.total_runs > 0
                  ? Math.round((pipeline.successful_runs / pipeline.total_runs) * 100)
                  : 0
              const barClass = successPct >= 90 ? 'success' : successPct >= 70 ? 'warning' : 'error'
              const dotState = !pipeline.enabled
                ? 'disabled'
                : successPct >= 90 || pipeline.total_runs === 0
                  ? 'success'
                  : successPct >= 70
                    ? 'degraded'
                    : 'error'
              return (
                <div
                  key={pipeline.name}
                  className="pipeline-card"
                  style={{ animationDelay: `${index * 0.04}s` }}
                  onClick={() => navigate(`/pipelines/${encodeURIComponent(pipeline.name)}`)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      navigate(`/pipelines/${encodeURIComponent(pipeline.name)}`)
                    }
                  }}
                >
                  <div className="pipeline-card__head">
                    <div className="pipeline-card__title">
                      <span className={`status-dot ${dotState}`} aria-hidden />
                      <span className="pipeline-name">{pipeline.name}</span>
                    </div>
                    {/* TODO(redesign): needs backend — no per-pipeline enable/disable endpoint yet */}
                    <label
                      className="toggle"
                      onClick={(e) => e.stopPropagation()}
                      title={t('dashboard.pipelineActiveTooltip')}
                    >
                      <input
                        type="checkbox"
                        checked={pipeline.enabled}
                        readOnly
                        disabled={isReadonly}
                        aria-label={t('dashboard.pipelineActiveTooltip')}
                      />
                      <span className="track" />
                      <span className="knob" />
                    </label>
                  </div>

                  <div className="pipeline-card__rate">
                    <div className="progress">
                      <div
                        className={`progress__fill ${barClass}`}
                        style={{ width: `${successPct}%` }}
                      />
                    </div>
                    <span className="pipeline-card__pct mono">{successPct}%</span>
                  </div>

                  <RunStatusCircles pipelineName={pipeline.name} variant="strip" count={12} />

                  <div className="pipeline-card__foot">
                    {/* TODO(redesign): needs backend — cron/next-run not in pipeline list API */}
                    <span className="mono">{t('dashboard.scheduleUnknown', '—')}</span>
                    <span className="mono pipeline-card__next">
                      {t('dashboard.nextRunUnknown', 'next —')}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="empty-state">
            <p>{t('dashboard.noPipelines')}</p>
          </div>
        )}
      </div>
    </div>
  )
}
