import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate } from 'react-router-dom'
import { useState, lazy, Suspense } from 'react'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { getFormatLocale } from '../utils/locale'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import { LuExternalLink } from 'react-icons/lu'
import Tooltip from '../components/Tooltip'
import InfoIcon from '../components/InfoIcon'
import CalendarHeatmap from '../components/CalendarHeatmap'
// recharts-basierte Charts lazy laden — hält die schwere recharts-Lib (~108kB gzip)
// aus dem PipelineDetail-Hauptchunk; Header/Stats/Tabs werden sofort interaktiv.
const SuccessRateTrendChart = lazy(() => import('../components/SuccessRateTrendChart'))
const AverageRuntimeChart = lazy(() => import('../components/AverageRuntimeChart'))
import './PipelineDetail.css'

interface PipelineStats {
  pipeline_name: string
  total_runs: number
  successful_runs: number
  failed_runs: number
  success_rate: number
  webhook_runs: number
  /** Webhook-Runs pro Run-Konfiguration: '' = Pipeline-Level, sonst schedules[].id */
  webhook_runs_by_config?: Record<string, number>
}

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
    cpu_soft_limit?: number
    mem_soft_limit?: string
    description?: string
    tags?: string[]
    timeout?: number
    retry_attempts?: number
    max_instances?: number
    webhook_key?: string
    python_version?: string
    cron?: string
    /** GitHub edit URL for the repo's pipeline.json, when the API exposes it (GitOps). */
    pipeline_json_edit_url?: string | null
    downstream_triggers?: Array<{ pipeline: string; on_success: boolean; on_failure: boolean; run_config_id?: string }>
    schedules?: Array<{
      id?: string
      webhook_key?: string
      schedule_cron?: string
      schedule_interval_seconds?: number
      enabled?: boolean
      default_env?: Record<string, string>
      encrypted_env?: Record<string, string>
    }>
  }
}

interface DownstreamTriggerItem {
  id: string | null
  downstream_pipeline: string
  on_success: boolean
  on_failure: boolean
  on_route?: string | null
  run_config_id?: string | null
  source: 'pipeline_json' | 'api'
}

interface PipelineSourceFiles {
  main_py: string | null
  requirements_txt: string | null
  pipeline_json: string | null
}

type MainTab = 'overview' | 'runs' | 'configuration' | 'environment'

/** Parse a memory string like "512M" / "2G" / "2048" into a number of GB (best-effort, for bar scaling). */
function memToGb(mem?: string): number | null {
  if (!mem) return null
  const m = String(mem).trim().match(/^([\d.]+)\s*([a-zA-Z]*)$/)
  if (!m) return null
  const val = parseFloat(m[1])
  if (isNaN(val)) return null
  const unit = m[2].toUpperCase()
  if (unit.startsWith('G')) return val
  if (unit.startsWith('M')) return val / 1024
  if (unit.startsWith('K')) return val / (1024 * 1024)
  // bare bytes
  return val / (1024 * 1024 * 1024)
}

export default function PipelineDetail() {
  const { t } = useTranslation()
  const { name } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const [mainTab, setMainTab] = useState<MainTab>('overview')
  const [sourceTab, setSourceTab] = useState<'python' | 'requirements' | 'json'>('python')
  const dailyStatsInterval = useRefetchInterval(30000, 60000)

  const { data: pipeline, isLoading: pipelineLoading } = useQuery<Pipeline>({
    queryKey: ['pipeline', name],
    queryFn: async () => {
      // Cached pipeline list reuse — avoids a duplicate /pipelines request when navigating from the list page
      const cached = queryClient.getQueryData<Pipeline[]>(['pipelines'])
      if (cached) {
        return cached.find((p) => p.name === name) ?? null
      }
      const response = await apiClient.get('/pipelines')
      return response.data.find((p: Pipeline) => p.name === name) ?? null
    },
    enabled: !!name,
  })

  const { data: stats, isLoading: statsLoading } = useQuery<PipelineStats>({
    queryKey: ['pipeline-stats', name],
    queryFn: async () => {
      const response = await apiClient.get(`/pipelines/${name}/stats`)
      return response.data
    },
    enabled: !!name,
  })

  const { data: runs } = useQuery({
    queryKey: ['pipeline-runs', name],
    queryFn: async () => {
      const response = await apiClient.get(`/pipelines/${name}/runs?limit=10`)
      return response.data
    },
    enabled: !!name,
  })

  const { data: dailyStats } = useQuery({
    queryKey: ['pipeline-daily-stats', name],
    queryFn: async () => {
      const response = await apiClient.get(`/pipelines/${name}/daily-stats?days=365`)
      return response.data as {
        daily_stats?: Array<{
          date: string
          total_runs: number
          successful_runs: number
          failed_runs: number
          success_rate: number
        }>
      }
    },
    enabled: !!name,
    refetchInterval: dailyStatsInterval,
    staleTime: 60_000,
  })

  const { data: downstreamTriggers } = useQuery<DownstreamTriggerItem[]>({
    queryKey: ['downstream-triggers', name],
    queryFn: async () => {
      const response = await apiClient.get(`/pipelines/${name}/downstream-triggers`)
      return response.data
    },
    enabled: !!name,
  })

  const { data: sourceFiles, isLoading: sourceFilesLoading } = useQuery<PipelineSourceFiles>({
    queryKey: ['pipeline-source', name],
    queryFn: async () => {
      const response = await apiClient.get(`/pipelines/${name}/source`)
      return response.data
    },
    enabled: !!name,
  })

  const resetStatsMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post(`/pipelines/${name}/stats/reset`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipeline-stats', name] })
      queryClient.invalidateQueries({ queryKey: ['pipeline', name] })
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      showSuccess(t('pipelineDetail.statsResetSuccess'))
    },
    onError: (error: any) => {
      showError(t('pipelineDetail.statsResetError', { detail: error.response?.data?.detail || error.message }))
    },
  })


  const handleResetStats = async () => {
    const confirmed = await showConfirm(t('pipelineDetail.confirmResetStats'))
    if (confirmed) {
      resetStatsMutation.mutate()
    }
  }

  // Manual trigger — optionally with a specific schedule's run config (applies that
  // schedule's env/limit overrides, exactly like the scheduler would).
  const runMutation = useMutation({
    mutationFn: async (runConfigId?: string) => {
      const response = await apiClient.post(`/pipelines/${name}/run`, runConfigId ? { run_config_id: runConfigId } : {})
      return response.data as { id: string }
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['pipeline-runs', name] })
      showSuccess(t('pipelineDetail.runStarted', 'Run started'))
      if (data?.id) navigate(`/runs/${data.id}`)
    },
    onError: (error: any) => {
      const status = error?.response?.status
      if (status === 429) {
        showError(t('pipelineDetail.runConcurrencyLimit', 'Concurrency limit reached — try again later.'))
      } else {
        showError(error?.response?.data?.detail || error.message)
      }
    },
  })
  const handleRunPipeline = (runConfigId?: string) => {
    if (isReadonly || !pipeline?.enabled || runMutation.isPending) return
    runMutation.mutate(runConfigId)
  }


  const { data: allPipelines } = useQuery<Pipeline[]>({
    queryKey: ['pipelines'],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines')
      return response.data
    },
    enabled: !!name && !isReadonly,
  })

  const createDownstreamTriggerMutation = useMutation({
    mutationFn: async (body: { downstream_pipeline: string; on_success: boolean; on_failure: boolean; on_route?: string | null; run_config_id?: string | null }) => {
      const response = await apiClient.post(`/pipelines/${name}/downstream-triggers`, body)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downstream-triggers', name] })
      showSuccess(t('pipelineDetail.downstreamAdded'))
    },
    onError: (error: any) => {
      showError(error.response?.data?.detail || error.message)
    },
  })

  const deleteDownstreamTriggerMutation = useMutation({
    mutationFn: async (triggerId: string) => {
      await apiClient.delete(`/pipelines/${name}/downstream-triggers/${triggerId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downstream-triggers', name] })
      showSuccess(t('pipelineDetail.downstreamRemoved'))
    },
    onError: (error: any) => {
      showError(error.response?.data?.detail || error.message)
    },
  })

  const [newTriggerPipeline, setNewTriggerPipeline] = useState('')
  const [newTriggerOnSuccess, setNewTriggerOnSuccess] = useState(true)
  const [newTriggerOnFailure, setNewTriggerOnFailure] = useState(false)
  const [newTriggerOnRoute, setNewTriggerOnRoute] = useState('')
  const [newTriggerRunConfigId, setNewTriggerRunConfigId] = useState<string>('')

  const handleAddDownstreamTrigger = () => {
    if (!newTriggerPipeline.trim()) return
    createDownstreamTriggerMutation.mutate({
      downstream_pipeline: newTriggerPipeline.trim(),
      on_success: newTriggerOnSuccess,
      on_failure: newTriggerOnFailure,
      on_route: newTriggerOnRoute.trim() || null,
      run_config_id: newTriggerRunConfigId || null,
    })
    setNewTriggerPipeline('')
    setNewTriggerOnSuccess(true)
    setNewTriggerOnFailure(false)
    setNewTriggerOnRoute('')
    setNewTriggerRunConfigId('')
  }

  const selectedDownstreamPipeline = allPipelines?.find((p) => p.name === newTriggerPipeline)
  const availableSchedules = selectedDownstreamPipeline?.metadata?.schedules?.filter((s) => s.id) ?? []

  const handleCopyWebhookUrl = (webhookKey: string) => {
    const baseUrl = window.location.origin
    const webhookUrl = `${baseUrl}/api/webhooks/${name}/${webhookKey}`
    navigator.clipboard.writeText(webhookUrl)
    showSuccess(t('pipelineDetail.webhookUrlCopied'))
  }

  if (pipelineLoading || statsLoading) {
    return <div>{t('common.loading')}</div>
  }

  if (!pipeline) {
    return <div>{t('pipelineDetail.pipelineNotFound')}</div>
  }

  const md = pipeline.metadata
  const isHealthy = pipeline.enabled
  const pythonVersion = md.python_version || t('pipelineDetail.pythonVersionDefault')

  // Build the list of schedules to render as cards. Each schedule from pipeline.json
  // carries its own cron/interval plus env overrides (default_env = plain, encrypted_env
  // = secret values, keys visible). These overrides are layered on top of the base env
  // and can be triggered individually via run_config_id.
  const rawSchedules = md.schedules ?? []
  interface EnvChip { key: string; value: string; secret: boolean }
  const scheduleCards: Array<{
    id: string
    cron: string
    enabled: boolean
    env: EnvChip[]
    runnable: boolean
  }> = []

  const buildEnvChips = (s: { default_env?: Record<string, string>; encrypted_env?: Record<string, string> }): EnvChip[] => {
    const chips: EnvChip[] = []
    Object.entries(s.default_env ?? {}).forEach(([key, value]) => chips.push({ key, value, secret: false }))
    Object.keys(s.encrypted_env ?? {}).forEach((key) => chips.push({ key, value: '••••••', secret: true }))
    return chips
  }
  const scheduleCron = (s: { schedule_cron?: string; schedule_interval_seconds?: number }): string => {
    if (s.schedule_cron) return s.schedule_cron
    if (s.schedule_interval_seconds) return t('pipelineDetail.everyNSeconds', 'every {{n}}s', { n: s.schedule_interval_seconds })
    return md.cron || '—'
  }

  if (rawSchedules.length > 0) {
    rawSchedules.forEach((s, i) => {
      const id = s.id || `schedule-${i + 1}`
      scheduleCards.push({
        id,
        cron: scheduleCron(s),
        enabled: s.enabled ?? pipeline.enabled,
        env: buildEnvChips(s),
        runnable: !!s.id,
      })
    })
  } else if (md.cron) {
    // Single pipeline-level cron, no schedule objects → runs with base env.
    scheduleCards.push({
      id: pipeline.name,
      cron: md.cron,
      enabled: pipeline.enabled,
      env: [],
      runnable: false,
    })
  }

  // Resource limit values (with placeholders where the backend has none).
  // TODO(redesign): needs backend — soft/hard scale is an assumption for bar widths.
  const cpuSoft = md.cpu_soft_limit
  const cpuHard = md.cpu_hard_limit
  const memSoft = md.mem_soft_limit
  const memHard = md.mem_hard_limit
  const cpuHardN = cpuHard ?? (cpuSoft ? cpuSoft * 2 : null)
  const cpuSoftPct = cpuHardN && cpuSoft ? Math.min(100, (cpuSoft / cpuHardN) * 100) : cpuSoft ? 50 : 0
  const cpuHardPct = 100
  const memHardGb = memToGb(memHard)
  const memSoftGb = memToGb(memSoft)
  const memSoftPct = memHardGb && memSoftGb ? Math.min(100, (memSoftGb / memHardGb) * 100) : memSoftGb ? 25 : 0
  const hasResourceLimits =
    cpuHard !== undefined || cpuSoft !== undefined || memHard !== undefined || memSoft !== undefined ||
    md.timeout !== undefined || md.retry_attempts !== undefined || (md.max_instances ?? 0) > 0

  const cron = md.cron || rawSchedules[0]?.schedule_cron

  const renderHealthBadge = () => (
    <span className={`badge ${isHealthy ? 'badge-success' : 'badge-secondary'}`}>
      <span className={`status-dot ${isHealthy ? 'success' : 'disabled'}`} style={{ width: 6, height: 6 }} />
      {isHealthy ? t('pipelineDetail.healthHealthy', 'Healthy') : t('common.inactive')}
    </span>
  )

  return (
    <div className="pipeline-detail">
      {/* ── Ghost back-link ─────────────────────────────────────────── */}
      <button type="button" onClick={() => navigate('/pipelines')} className="pd-back">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M15 6l-6 6 6 6" /></svg>
        {t('pipelines.title', 'Pipelines')}
      </button>

      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="pd-header">
        <div className="pd-header-main">
          <div className="pd-title-row">
            <span className="pd-glow-dot">
              <span className={`status-dot ${isHealthy ? 'success' : 'disabled'}`} />
            </span>
            <h1 className="pd-title mono">{pipeline.name}</h1>
            {renderHealthBadge()}
          </div>
          {md.description && <p className="pd-description">{md.description}</p>}
          <div className="pd-meta-chips">
            <span className="pd-chip mono">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="6" cy="6" r="2.2" /><circle cx="6" cy="18" r="2.2" /><path d="M6 8v8M6 18c8 0 6-12 14-12" /><circle cx="20" cy="6" r="2.2" /></svg>
              pipelines/{pipeline.name}.py
            </span>
            <span className="pd-chip mono">py {pythonVersion}</span>
            {/* TODO(redesign): needs backend — git branch@commit not exposed by the API */}
            <span className="pd-chip mono">main@—</span>
            {md.tags?.map((tag) => (
              <span key={tag} className="pd-chip mono">{tag}</span>
            ))}
          </div>
        </div>
        <div className="pd-header-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => handleRunPipeline()}
            disabled={isReadonly || !pipeline.enabled || runMutation.isPending}
            title={
              !pipeline.enabled
                ? t('pipelineDetail.triggerRunDisabledHint', 'Pipeline is disabled')
                : t('pipelineDetail.triggerRunHint', 'Trigger a run with the base configuration')
            }
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 5l12 7-12 7z" /></svg>
            {runMutation.isPending ? t('pipelineDetail.runStarting', 'Starting…') : t('pipelineDetail.triggerRun', 'Trigger run')}
          </button>
          {/* Pipelines are defined in pipeline.json (GitOps). If the API exposes a
              GitHub edit URL, link out to it; otherwise keep a disabled control whose
              label/title makes the GitOps intent clear instead of looking dead. */}
          {md.pipeline_json_edit_url ? (
            <a
              href={md.pipeline_json_edit_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-secondary"
              title={t('pipelineDetail.editInGithubHint', 'Edit pipeline.json on GitHub')}
            >
              {t('pipelineDetail.editInGithub', 'Edit in GitHub')}
              <LuExternalLink className="icon-external" aria-hidden />
            </a>
          ) : (
            <button
              type="button"
              className="btn btn-secondary"
              disabled
              title={t('pipelineDetail.editInPipelineJson')}
            >
              {t('pipelineDetail.editInPipelineJsonLabel', 'Edit in pipeline.json')}
            </button>
          )}
          <button type="button" className="btn-icon" disabled aria-label={t('pipelineDetail.moreSettings')}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg>
          </button>
        </div>
      </div>

      {/* ── Main tabs ───────────────────────────────────────────────── */}
      <div className="tab-strip pd-tabs">
        <button type="button" className={`tab-strip__tab${mainTab === 'overview' ? ' active' : ''}`} onClick={() => setMainTab('overview')}>
          {t('pipelineDetail.tabOverview', 'Overview')}
        </button>
        <button type="button" className={`tab-strip__tab${mainTab === 'runs' ? ' active' : ''}`} onClick={() => setMainTab('runs')}>
          {t('pipelineDetail.tabRuns', 'Runs')}
        </button>
        <button type="button" className={`tab-strip__tab${mainTab === 'configuration' ? ' active' : ''}`} onClick={() => setMainTab('configuration')}>
          {t('pipelineDetail.tabConfiguration', 'Configuration')}
        </button>
        <button type="button" className={`tab-strip__tab${mainTab === 'environment' ? ' active' : ''}`} onClick={() => setMainTab('environment')}>
          {t('pipelineDetail.tabEnvironment', 'Environment')}
        </button>
      </div>

      {/* ══ OVERVIEW ══ */}
      {mainTab === 'overview' && (
        <div className="pd-overview">
          {stats && (
            <div className="card pd-stats-card">
              <div className="pd-card-head">
                <h3>{t('pipelineDetail.statistics')}</h3>
                {!isReadonly && (
                  <Tooltip content={t('pipelineDetail.resetStatsTooltip')}>
                    <button
                      type="button"
                      onClick={handleResetStats}
                      disabled={resetStatsMutation.isPending}
                      className="btn btn-warning btn-sm"
                    >
                      {resetStatsMutation.isPending ? t('pipelineDetail.resetting') : t('pipelineDetail.resetStats')}
                    </button>
                  </Tooltip>
                )}
              </div>
              <div className="pd-stats-grid">
                <div className="pd-stat">
                  <span className="pd-stat-label">{t('pipelineDetail.totalRuns')}</span>
                  <span className="pd-stat-value mono">{stats.total_runs}</span>
                </div>
                <div className="pd-stat success">
                  <span className="pd-stat-label">{t('pipelineDetail.successful')}</span>
                  <span className="pd-stat-value mono">{stats.successful_runs}</span>
                </div>
                <div className="pd-stat error">
                  <span className="pd-stat-label">{t('pipelineDetail.failed')}</span>
                  <span className="pd-stat-value mono">{stats.failed_runs}</span>
                </div>
                <div className="pd-stat">
                  <span className="pd-stat-label">{t('pipelineDetail.successRate')}</span>
                  <span className="pd-stat-value mono">{stats.success_rate.toFixed(1)}%</span>
                </div>
                {stats.webhook_runs > 0 && (
                  <div className="pd-stat">
                    <span className="pd-stat-label">{t('pipelineDetail.webhookRuns')}</span>
                    <span className="pd-stat-value mono">{stats.webhook_runs}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {dailyStats && dailyStats.daily_stats && dailyStats.daily_stats.length > 0 && (
            <>
              <Suspense fallback={<div className="pd-charts-grid"><div className="pd-chart-loading" /><div className="pd-chart-loading" /></div>}>
                <div className="pd-charts-grid">
                  <SuccessRateTrendChart dailyStats={dailyStats.daily_stats} days={30} />
                  {runs && runs.length > 0 && (
                    <AverageRuntimeChart runs={runs} days={30} />
                  )}
                </div>
              </Suspense>
              <CalendarHeatmap dailyStats={dailyStats.daily_stats} days={365} />
            </>
          )}

          {/* Recent runs preview */}
          {runs && runs.length > 0 && (
            <div className="card pd-recent-card">
              <div className="pd-card-head">
                <h3>{t('pipelineDetail.lastRuns')}</h3>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMainTab('runs')}>
                  {t('pipelineDetail.viewAll', 'View all →')}
                </button>
              </div>
              <div className="pd-recent-list">
                {runs.slice(0, 5).map((run: any) => (
                  <div
                    key={run.id}
                    className="pd-recent-row clickable"
                    onClick={() => navigate(`/runs/${run.id}`)}
                  >
                    <span className="mono pd-recent-id">{run.id.substring(0, 8)}…</span>
                    <span className={`badge dot badge-${statusBadge(run.status)}`}>{run.status}</span>
                    <span className="mono pd-recent-time">
                      {new Date(run.started_at).toLocaleString(getFormatLocale(), { timeZone: 'UTC' })}
                    </span>
                    <svg className="pd-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M9 6l6 6-6 6" /></svg>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ══ RUNS ══ */}
      {mainTab === 'runs' && (
        runs && runs.length > 0 ? (
          <div className="table pd-runs-table">
            <div className="table__head pd-runs-row">
              <span>{t('pipelineDetail.id')}</span>
              <span>{t('pipelineDetail.status')}</span>
              <span>{t('pipelineDetail.started')}</span>
              <span>{t('pipelineDetail.finished')}</span>
              <span>{t('pipelineDetail.exitCode')}</span>
              <span>{t('pipelineDetail.actions')}</span>
            </div>
            {runs.map((run: any) => (
              <div
                key={run.id}
                className="table__row pd-runs-row clickable"
                onClick={() => navigate(`/runs/${run.id}`)}
              >
                <span className="mono">{run.id.substring(0, 8)}…</span>
                <span>
                  <span className={`badge dot badge-${statusBadge(run.status)}`}>{run.status}</span>
                </span>
                <span className="mono pd-muted">{new Date(run.started_at).toLocaleString(getFormatLocale(), { timeZone: 'UTC' })} UTC</span>
                <span className="mono pd-muted">
                  {run.finished_at
                    ? `${new Date(run.finished_at).toLocaleString(getFormatLocale(), { timeZone: 'UTC' })} UTC`
                    : '-'}
                </span>
                <span className="mono">
                  {run.exit_code !== null ? (
                    <span className={run.exit_code === 0 ? 'pd-exit-success' : 'pd-exit-error'}>{run.exit_code}</span>
                  ) : (
                    '-'
                  )}
                </span>
                <span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); navigate(`/runs/${run.id}`) }}
                    className="btn btn-outlined btn-sm"
                  >
                    {t('pipelineDetail.details')}
                  </button>
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="card pd-empty">{t('pipelineDetail.noRuns', 'No runs yet.')}</div>
        )
      )}

      {/* ══ CONFIGURATION ══ */}
      {mainTab === 'configuration' && (
        <div className="pd-config">
          {/* General information */}
          <div className="card">
            <h3>{t('pipelineDetail.information')}</h3>
            <div className="pd-info-grid">
              <div className="pd-info-item">
                <span className="pd-info-label">{t('pipelineDetail.status')}:</span>
                <span className="pd-info-value-row">
                  <span className={`badge ${pipeline.enabled ? 'badge-success' : 'badge-secondary'}`}>
                    {pipeline.enabled ? t('common.active') : t('common.inactive')}
                  </span>
                  <InfoIcon content={t('pipelineDetail.infoStatusHint')} />
                </span>
              </div>
              <div className="pd-info-item">
                <span className="pd-info-label">{t('pipelineDetail.requirementsLabel')}</span>
                <span className="pd-info-value">
                  {pipeline.has_requirements ? t('common.yes') : t('common.no')}
                  <InfoIcon content={t('pipelineDetail.requirementsInfoHint')} />
                </span>
              </div>
              <div className="pd-info-item">
                <span className="pd-info-label">{t('pipelineDetail.pythonVersionLabel')}</span>
                <span className="pd-info-value mono">
                  {pythonVersion}
                  <InfoIcon content={t('pipelineDetail.infoPythonVersionHint')} />
                </span>
              </div>
              {pipeline.last_cache_warmup && (
                <div className="pd-info-item">
                  <span className="pd-info-label">{t('pipelineDetail.lastCacheWarmupLabel')}</span>
                  <span className="pd-info-value mono">
                    {new Date(pipeline.last_cache_warmup).toLocaleString(getFormatLocale())}
                    <InfoIcon content={t('pipelineDetail.lastCacheWarmupTooltip')} />
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Schedules as cards */}
          <div className="card">
            <div className="pd-card-head">
              <div>
                <h3>
                  {t('pipelineDetail.schedules', 'Schedules')}{' '}
                  <span className="pd-count mono">{scheduleCards.length}</span>
                </h3>
                <p className="pd-card-sub">{t('pipelineDetail.schedulesSub', 'A pipeline can run on multiple schedules — each carries its own environment overrides on top of the base config.')}</p>
              </div>
            </div>
            {scheduleCards.length > 0 ? (
              <div className="pd-schedule-list">
                {scheduleCards.map((sc) => (
                  <div key={sc.id} className="pd-schedule">
                    <div className="pd-schedule-head">
                      <span className={`status-dot ${sc.enabled ? 'success' : 'disabled'} pd-schedule-dot`} />
                      <span className="mono pd-schedule-name">{sc.id}</span>
                      <span className="mono pd-cron-pill">{sc.cron}</span>
                      <div className="pd-schedule-spacer" />
                      {!isReadonly && sc.runnable && (
                        <button
                          type="button"
                          className="btn btn-sm btn-secondary pd-schedule-run"
                          onClick={() => handleRunPipeline(sc.id)}
                          disabled={!pipeline.enabled || runMutation.isPending}
                          title={t('pipelineDetail.runScheduleHint', 'Run now with this schedule’s environment overrides')}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M7 5l12 7-12 7z" /></svg>
                          {t('pipelineDetail.runSchedule', 'Run')}
                        </button>
                      )}
                      <label className="toggle" title={t('pipelineDetail.scheduleEnabledHint', 'Enabled (configured in pipeline.json)')}>
                        <input type="checkbox" checked={sc.enabled} readOnly disabled />
                        <span className="track" />
                        <span className="knob" />
                      </label>
                    </div>
                    <div className="pd-schedule-body">
                      <div className="pd-override-head">
                        <span className="pd-override-eyebrow">{t('pipelineDetail.envOverrides', 'Env overrides')}</span>
                        <span className="pd-override-count mono">{sc.env.length}</span>
                        <span className="pd-override-note">{t('pipelineDetail.envOverridesNote', 'on top of base variables')}</span>
                      </div>
                      {sc.env.length > 0 ? (
                        <div className="pd-override-chips">
                          {sc.env.map((chip) => (
                            <span key={chip.key} className={`pd-override-chip mono ${chip.secret ? 'pd-override-chip--secret' : ''}`}>
                              <span className="pd-override-key">{chip.key}</span>
                              <span className="pd-override-eq">=</span>
                              <span className="pd-override-val">{chip.value}</span>
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="pd-override-empty">{t('pipelineDetail.noEnvOverrides', 'No overrides — uses the base environment.')}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="pd-card-sub">{t('pipelineDetail.noSchedules', 'No schedules configured. Add a cron expression in pipeline.json.')}</p>
            )}
          </div>

          {/* Resource limits as bars */}
          {hasResourceLimits && (
            <div className="card">
              <h3>{t('pipelineDetail.resourceLimits', 'Resource limits')}</h3>
              <p className="pd-card-sub">{t('pipelineDetail.resourceLimitsSub', 'Soft limits warn; hard limits terminate the container.')}</p>

              {(cpuSoft !== undefined || cpuHard !== undefined) && (
                <div className="pd-limit">
                  <div className="pd-limit-head">
                    <span className="pd-limit-label">{t('pipelineDetail.cpuCores', 'CPU cores')}</span>
                    <span className="mono pd-limit-meta">
                      {cpuSoft !== undefined && `soft ${cpuSoft}`}
                      {cpuSoft !== undefined && cpuHard !== undefined && ' · '}
                      {cpuHard !== undefined && `hard ${cpuHard}`}
                    </span>
                  </div>
                  <div className="pd-bar">
                    <div className="pd-bar-fill" style={{ width: `${cpuSoftPct}%`, background: 'var(--color-primary)' }} />
                    {cpuHard !== undefined && <div className="pd-bar-marker" style={{ left: `${cpuHardPct}%` }} />}
                  </div>
                </div>
              )}

              {(memSoft !== undefined || memHard !== undefined) && (
                <div className="pd-limit">
                  <div className="pd-limit-head">
                    <span className="pd-limit-label">{t('pipelineDetail.memory', 'Memory')}</span>
                    <span className="mono pd-limit-meta">
                      {memSoft !== undefined && `soft ${memSoft}`}
                      {memSoft !== undefined && memHard !== undefined && ' · '}
                      {memHard !== undefined && `hard ${memHard}`}
                    </span>
                  </div>
                  <div className="pd-bar">
                    <div className="pd-bar-fill" style={{ width: `${memSoftPct}%`, background: 'var(--color-running)' }} />
                    {memHard !== undefined && <div className="pd-bar-marker" style={{ left: '100%' }} />}
                  </div>
                </div>
              )}

              <div className="pd-limit-extras">
                {md.timeout !== undefined && (
                  <div className="pd-limit-extra">
                    <span className="pd-limit-label">
                      {t('pipelineDetail.timeout')}
                      <InfoIcon content={t('pipelineDetail.timeoutInfo')} />
                    </span>
                    <span className="mono pd-limit-value">{md.timeout}s</span>
                  </div>
                )}
                {md.retry_attempts !== undefined && (
                  <div className="pd-limit-extra">
                    <span className="pd-limit-label">
                      {t('pipelineDetail.retryAttempts')}
                      <InfoIcon content={t('pipelineDetail.retryAttemptsInfo')} />
                    </span>
                    <span className="mono pd-limit-value">{md.retry_attempts}</span>
                  </div>
                )}
                {md.max_instances !== undefined && md.max_instances > 0 && (
                  <div className="pd-limit-extra">
                    <span className="pd-limit-label">
                      {t('pipelineDetail.maxInstances')}
                      <InfoIcon content={t('pipelineDetail.maxInstancesInfo')} />
                    </span>
                    <span className="mono pd-limit-value">{md.max_instances}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Webhooks */}
          <div className="card">
            <h3>{t('pipelineDetail.webhooks')}</h3>
            {(() => {
              const hasPipelineKey = !!pipeline?.metadata?.webhook_key
              const scheduleWebhooks = (pipeline?.metadata?.schedules ?? []).filter(
                (s): s is { id?: string; webhook_key: string } => !!(s.id && s.webhook_key)
              )
              const hasAnyWebhook = hasPipelineKey || scheduleWebhooks.length > 0
              if (!hasAnyWebhook) {
                return (
                  <div className="pd-webhook-disabled">
                    <p>{t('pipelineDetail.webhooksDisabled')}</p>
                    <p className="pd-card-sub">{t('pipelineDetail.webhooksEnableHint')}</p>
                  </div>
                )
              }
              const byConfig = stats?.webhook_runs_by_config
              const runCountFor = (configKey: string) => (byConfig && byConfig[configKey]) ?? 0
              return (
                <div className="pd-webhook-enabled">
                  <div className="pd-webhook-status">
                    <span className="badge badge-success">{t('pipelineDetail.webhooksEnabled')}</span>
                    <span className="pd-card-sub">{t('pipelineDetail.webhooksConfiguredIn')}</span>
                  </div>
                  {hasPipelineKey && (
                    <div className="pd-webhook-url-section">
                      <label className="pd-info-label">
                        {t('pipelineDetail.pipelineStandard')}
                        <InfoIcon content={t('pipelineDetail.webhookStandardInfo')} />
                      </label>
                      <div className="pd-webhook-url-container">
                        <code className="mono pd-webhook-url">
                          {typeof window !== 'undefined' && `${window.location.origin}/api/webhooks/${name}/${pipeline!.metadata.webhook_key}`}
                        </code>
                        <Tooltip content={t('pipelineDetail.copyWebhookUrl')}>
                          <button
                            type="button"
                            onClick={() => handleCopyWebhookUrl(pipeline!.metadata.webhook_key!)}
                            className="btn btn-secondary btn-sm"
                            title={t('pipelineDetail.copyUrl')}
                          >
                            {t('pipelineDetail.copyUrl')}
                          </button>
                        </Tooltip>
                      </div>
                      {runCountFor('') > 0 && (
                        <div className="pd-webhook-stat">
                          <span className="pd-info-label">{t('pipelineDetail.trigger')}</span>
                          <span className="mono">{runCountFor('')}</span>
                        </div>
                      )}
                    </div>
                  )}
                  {scheduleWebhooks.map((s) => (
                    <div key={s.id!} className="pd-webhook-url-section">
                      <label className="pd-info-label">
                        {t('pipelineDetail.scheduleLabel', { id: s.id })}
                        <InfoIcon content={t('pipelineDetail.webhookRunConfigInfo', { id: s.id })} />
                      </label>
                      <div className="pd-webhook-url-container">
                        <code className="mono pd-webhook-url">
                          {typeof window !== 'undefined' && `${window.location.origin}/api/webhooks/${name}/${s.webhook_key}`}
                        </code>
                        <Tooltip content={t('pipelineDetail.copyWebhookUrl')}>
                          <button
                            type="button"
                            onClick={() => handleCopyWebhookUrl(s.webhook_key)}
                            className="btn btn-secondary btn-sm"
                            title={t('pipelineDetail.copyUrl')}
                          >
                            {t('pipelineDetail.copyUrl')}
                          </button>
                        </Tooltip>
                      </div>
                      {runCountFor(s.id!) > 0 && (
                        <div className="pd-webhook-stat">
                          <span className="pd-info-label">{t('pipelineDetail.trigger')}</span>
                          <span className="mono">{runCountFor(s.id!)}</span>
                        </div>
                      )}
                    </div>
                  ))}
                  {stats && stats.webhook_runs > 0 && (
                    <div className="pd-webhook-stat">
                      <span className="pd-info-label">{t('pipelineDetail.webhookTriggerTotal')}</span>
                      <span className="mono">{stats.webhook_runs}</span>
                    </div>
                  )}
                </div>
              )
            })()}
          </div>

          {/* Downstream trigger chaining */}
          <div className="card">
            <h3>
              {t('pipelineDetail.downstreamChaining')}
              <InfoIcon content={t('pipelineDetail.downstreamTooltip')} />
            </h3>
            {downstreamTriggers && downstreamTriggers.length > 0 ? (
              <div className="table pd-downstream-table">
                <div className="table__head pd-downstream-row">
                  <span>{t('pipelineDetail.downstreamPipeline')}</span>
                  <span>{t('pipelineDetail.schedule')}</span>
                  <span>{t('pipelineDetail.onSuccess')}</span>
                  <span>{t('pipelineDetail.onFailure')}</span>
                  <span>{t('pipelineDetail.onRoute')}</span>
                  <span>{t('pipelineDetail.source')}</span>
                  {!isReadonly && <span></span>}
                </div>
                {downstreamTriggers.map((tr) => (
                  <div className="table__row pd-downstream-row" key={tr.id || `json-${tr.downstream_pipeline}-${tr.run_config_id ?? ''}`}>
                    <span className="mono">{tr.downstream_pipeline}</span>
                    <span className="mono pd-muted">{tr.run_config_id ?? '–'}</span>
                    <span>{tr.on_success ? '✓' : '–'}</span>
                    <span>{tr.on_failure ? '✓' : '–'}</span>
                    <span>{tr.on_route ? <code className="code-inline">{tr.on_route}</code> : '–'}</span>
                    <span>
                      <span className={`badge ${tr.source === 'pipeline_json' ? 'badge-success' : 'badge-primary'}`}>
                        {tr.source === 'pipeline_json' ? t('pipelineDetail.sourcePipelineJson') : t('pipelineDetail.sourceUi')}
                      </span>
                    </span>
                    {!isReadonly && (
                      <span>
                        {tr.source === 'api' && tr.id ? (
                          <button
                            type="button"
                            className="btn btn-error btn-sm"
                            onClick={() => deleteDownstreamTriggerMutation.mutate(tr.id!)}
                            disabled={deleteDownstreamTriggerMutation.isPending}
                          >
                            {t('pipelineDetail.remove')}
                          </button>
                        ) : (
                          <span className="pd-card-sub">{t('pipelineDetail.editInPipelineJson')}</span>
                        )}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="pd-card-sub">{t('pipelineDetail.noDownstreamTriggered')}</p>
            )}
            {!isReadonly && allPipelines && (
              <div className="pd-add-downstream">
                <h4>{t('pipelineDetail.addTrigger')}</h4>
                <div className="pd-add-trigger-form">
                  <select
                    value={newTriggerPipeline}
                    onChange={(e) => {
                      setNewTriggerPipeline(e.target.value)
                      setNewTriggerRunConfigId('')
                    }}
                    className="form-select pd-trigger-select"
                  >
                    <option value="">{t('pipelineDetail.selectPipeline')}</option>
                    {allPipelines
                      .filter((p) => p.name !== name)
                      .map((p) => (
                        <option key={p.name} value={p.name}>
                          {p.name}
                        </option>
                      ))}
                  </select>
                  {availableSchedules.length > 0 && (
                    <select
                      value={newTriggerRunConfigId}
                      onChange={(e) => setNewTriggerRunConfigId(e.target.value)}
                      className="form-select pd-trigger-select"
                      title={t('pipelineDetail.scheduleDownstreamTitle')}
                    >
                      <option value="">{t('pipelineDetail.standard')}</option>
                      {availableSchedules.map((s) => (
                        <option key={s.id!} value={s.id!}>
                          {s.id}
                        </option>
                      ))}
                    </select>
                  )}
                  <label className="pd-checkbox">
                    <input
                      type="checkbox"
                      checked={newTriggerOnSuccess}
                      onChange={(e) => setNewTriggerOnSuccess(e.target.checked)}
                    />
                    {t('pipelineDetail.startOnSuccess')}
                  </label>
                  <label className="pd-checkbox">
                    <input
                      type="checkbox"
                      checked={newTriggerOnFailure}
                      onChange={(e) => setNewTriggerOnFailure(e.target.checked)}
                    />
                    {t('pipelineDetail.startOnFailure')}
                  </label>
                  <input
                    type="text"
                    value={newTriggerOnRoute}
                    onChange={(e) => setNewTriggerOnRoute(e.target.value)}
                    placeholder={t('pipelineDetail.onRoutePlaceholder')}
                    className="form-input pd-trigger-route"
                    maxLength={128}
                    title={t('pipelineDetail.onRouteTooltip')}
                  />
                  <button
                    type="button"
                    className="btn btn-success btn-sm"
                    onClick={handleAddDownstreamTrigger}
                    disabled={!newTriggerPipeline.trim() || createDownstreamTriggerMutation.isPending}
                  >
                    {createDownstreamTriggerMutation.isPending ? t('pipelineDetail.adding') : t('pipelineDetail.add')}
                  </button>
                </div>
                <p className="pd-card-sub">{t('pipelineDetail.downstreamAltHint')}</p>
              </div>
            )}
          </div>

          {/* Source files */}
          <div className="card">
            <h3>{t('pipelineDetail.sourceFiles')}</h3>
            <div className="tab-strip pd-source-tabs">
              <button
                type="button"
                className={`tab-strip__tab${sourceTab === 'python' ? ' active' : ''}`}
                onClick={() => setSourceTab('python')}
              >
                {t('pipelineDetail.tabPython')}
              </button>
              <button
                type="button"
                className={`tab-strip__tab${sourceTab === 'requirements' ? ' active' : ''}`}
                onClick={() => setSourceTab('requirements')}
              >
                {t('pipelineDetail.tabRequirements')}
              </button>
              <button
                type="button"
                className={`tab-strip__tab${sourceTab === 'json' ? ' active' : ''}`}
                onClick={() => setSourceTab('json')}
              >
                {t('pipelineDetail.tabJson')}
              </button>
            </div>
            <div className="pd-source-content">
              {sourceFilesLoading ? (
                <div className="pd-code-empty">{t('pipelineDetail.codeLoading')}</div>
              ) : (
                <>
                  {sourceTab === 'python' && (
                    <div className="pd-code-container">
                      {sourceFiles?.main_py ? (
                        <pre className="pd-code-block"><code>{sourceFiles.main_py}</code></pre>
                      ) : (
                        <div className="pd-code-empty">{t('pipelineDetail.mainPyNotFound')}</div>
                      )}
                    </div>
                  )}
                  {sourceTab === 'requirements' && (
                    <div className="pd-code-container">
                      {sourceFiles?.requirements_txt ? (
                        <pre className="pd-code-block"><code>{sourceFiles.requirements_txt}</code></pre>
                      ) : (
                        <div className="pd-code-empty">{t('pipelineDetail.requirementsNotFound')}</div>
                      )}
                    </div>
                  )}
                  {sourceTab === 'json' && (
                    <div className="pd-code-container">
                      {sourceFiles?.pipeline_json ? (
                        <pre className="pd-code-block"><code>{(() => {
                          try {
                            return JSON.stringify(JSON.parse(sourceFiles.pipeline_json), null, 2)
                          } catch {
                            return sourceFiles.pipeline_json
                          }
                        })()}</code></pre>
                      ) : (
                        <div className="pd-code-empty">{t('pipelineDetail.pipelineJsonNotFound')}</div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ══ ENVIRONMENT ══ */}
      {mainTab === 'environment' && (
        <div className="card">
          <div className="pd-card-head">
            <div>
              <h3>{t('pipelineDetail.environmentVariables', 'Environment variables')}</h3>
              <p className="pd-card-sub">{t('pipelineDetail.environmentSub', 'Injected into the container at runtime. Secrets are encrypted at rest.')}</p>
            </div>
          </div>
          {/* TODO(redesign): needs backend — base environment variables are not yet
              exposed by the API. Schedules carry their own overrides (Configuration tab).
              Showing tags + cron as the available environment-level metadata for now. */}
          {md.tags && md.tags.length > 0 ? (
            <div className="pd-env-meta">
              <span className="pd-info-label">{t('pipelineDetail.tagsLabel')}</span>
              <div className="pd-override-chips">
                {md.tags.map((tag) => (
                  <span key={tag} className="pd-override-chip mono"><span className="pd-override-key">{tag}</span></span>
                ))}
              </div>
            </div>
          ) : null}
          <p className="pd-card-sub">
            {cron
              ? t('pipelineDetail.environmentCronHint', 'Schedule-level environment overrides are listed in the Configuration tab.')
              : t('pipelineDetail.environmentEmpty', 'No environment variables exposed by the API yet.')}
          </p>
        </div>
      )}
    </div>
  )
}

/** Map a run status string to a badge color variant. */
function statusBadge(status: string): string {
  const s = (status || '').toLowerCase()
  if (s === 'success' || s === 'succeeded') return 'success'
  if (s === 'failed' || s === 'error') return 'error'
  if (s === 'running') return 'running'
  if (s === 'pending' || s === 'queued') return 'warning'
  return 'secondary'
}
