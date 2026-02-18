import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { getFormatLocale } from '../utils/locale'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import Tooltip from '../components/Tooltip'
import InfoIcon from '../components/InfoIcon'
import CalendarHeatmap from '../components/CalendarHeatmap'
import SuccessRateTrendChart from '../components/SuccessRateTrendChart'
import AverageRuntimeChart from '../components/AverageRuntimeChart'
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
    downstream_triggers?: Array<{ pipeline: string; on_success: boolean; on_failure: boolean; run_config_id?: string }>
    schedules?: Array<{ id?: string; webhook_key?: string }>
  }
}

interface DownstreamTriggerItem {
  id: string | null
  downstream_pipeline: string
  on_success: boolean
  on_failure: boolean
  run_config_id?: string | null
  source: 'pipeline_json' | 'api'
}

interface PipelineSourceFiles {
  main_py: string | null
  requirements_txt: string | null
  pipeline_json: string | null
}

export default function PipelineDetail() {
  const { t } = useTranslation()
  const { name } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const [activeTab, setActiveTab] = useState<'python' | 'requirements' | 'json'>('python')
  const dailyStatsInterval = useRefetchInterval(30000, 60000)

  const { data: pipeline, isLoading: pipelineLoading } = useQuery<Pipeline>({
    queryKey: ['pipeline', name],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines')
      const pipelines = response.data
      return pipelines.find((p: Pipeline) => p.name === name)
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
      showSuccess('Statistiken wurden zurückgesetzt')
    },
    onError: (error: any) => {
      showError(`Fehler beim Zurücksetzen: ${error.response?.data?.detail || error.message}`)
    },
  })


  const handleResetStats = async () => {
    const confirmed = await showConfirm('Möchten Sie die Statistiken wirklich zurücksetzen?')
    if (confirmed) {
      resetStatsMutation.mutate()
    }
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
    mutationFn: async (body: { downstream_pipeline: string; on_success: boolean; on_failure: boolean; run_config_id?: string | null }) => {
      const response = await apiClient.post(`/pipelines/${name}/downstream-triggers`, body)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downstream-triggers', name] })
      showSuccess('Downstream-Trigger wurde hinzugefügt')
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
      showSuccess('Downstream-Trigger wurde entfernt')
    },
    onError: (error: any) => {
      showError(error.response?.data?.detail || error.message)
    },
  })

  const [newTriggerPipeline, setNewTriggerPipeline] = useState('')
  const [newTriggerOnSuccess, setNewTriggerOnSuccess] = useState(true)
  const [newTriggerOnFailure, setNewTriggerOnFailure] = useState(false)
  const [newTriggerRunConfigId, setNewTriggerRunConfigId] = useState<string>('')

  const handleAddDownstreamTrigger = () => {
    if (!newTriggerPipeline.trim()) return
    createDownstreamTriggerMutation.mutate({
      downstream_pipeline: newTriggerPipeline.trim(),
      on_success: newTriggerOnSuccess,
      on_failure: newTriggerOnFailure,
      run_config_id: newTriggerRunConfigId || null,
    })
    setNewTriggerPipeline('')
    setNewTriggerOnSuccess(true)
    setNewTriggerOnFailure(false)
    setNewTriggerRunConfigId('')
  }

  const selectedDownstreamPipeline = allPipelines?.find((p) => p.name === newTriggerPipeline)
  const availableSchedules = selectedDownstreamPipeline?.metadata?.schedules?.filter((s) => s.id) ?? []

  const handleCopyWebhookUrl = (webhookKey: string) => {
    const baseUrl = window.location.origin
    const webhookUrl = `${baseUrl}/api/webhooks/${name}/${webhookKey}`
    navigator.clipboard.writeText(webhookUrl)
    showSuccess('Webhook-URL wurde in die Zwischenablage kopiert')
  }

  if (pipelineLoading || statsLoading) {
    return <div>{t('common.loading')}</div>
  }

  if (!pipeline) {
    return <div>Pipeline nicht gefunden</div>
  }

  return (
    <div className="pipeline-detail">
      <div className="pipeline-detail-header">
        <h2>{pipeline.name}</h2>
        <button onClick={() => navigate('/pipelines')} className="back-button">
          ← Zurück
        </button>
      </div>

      <div className="pipeline-info-card">
        <h3>Informationen</h3>
        <div className="info-grid">
        <div className="info-item">
          <span className="info-label">Status:</span>
          <span className={`status-badge ${pipeline.enabled ? 'enabled' : 'disabled'}`}>
            {pipeline.enabled ? 'Aktiv' : 'Inaktiv'}
          </span>
          <InfoIcon content="Status wird in pipeline.json konfiguriert. 'Aktiv' bedeutet, dass die Pipeline ausgeführt werden kann." />
          <span className="info-hint" style={{ fontSize: '0.75rem', color: '#888', marginLeft: '0.5rem' }}>
            (Konfiguriert in pipeline.json)
          </span>
        </div>
          <div className="info-item">
            <span className="info-label">Requirements:</span>
            <span className="info-value">
              {pipeline.has_requirements ? 'Ja' : 'Nein'}
            </span>
            <InfoIcon content="Zeigt an, ob eine requirements.txt Datei vorhanden ist" />
          </div>
          <div className="info-item">
            <span className="info-label">Python-Version:</span>
            <span className="info-value">
              {pipeline.metadata.python_version || '3.11 (Standard)'}
            </span>
            <InfoIcon content="Wird in pipeline.json über python_version gesetzt – beliebig pro Pipeline (z.B. 3.10, 3.11, 3.12). Fehlt es, gilt die Standardversion (z.B. 3.11)." />
          </div>
          {pipeline.last_cache_warmup && (
            <div className="info-item">
              <span className="info-label">Letzter Cache-Warmup:</span>
              <span className="info-value">
                {new Date(pipeline.last_cache_warmup).toLocaleString(getFormatLocale())}
              </span>
              <InfoIcon content="Zeitpunkt des letzten Pre-Heating. Pipelines mit Cache starten schneller." />
            </div>
          )}
          {pipeline.metadata.description && (
            <div className="info-item full-width">
              <span className="info-label">Beschreibung:</span>
              <span className="info-value">{pipeline.metadata.description}</span>
            </div>
          )}
          {pipeline.metadata.tags && pipeline.metadata.tags.length > 0 && (
            <div className="info-item full-width">
              <span className="info-label">Tags:</span>
              <div className="tags">
                {pipeline.metadata.tags.map((tag) => (
                  <span key={tag} className="tag-badge">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {pipeline.metadata.cpu_hard_limit && (
        <div className="resource-limits-card">
          <h3>Resource-Limits</h3>
          <div className="limits-grid">
            <div className="limit-section">
              <h4>
                Hard Limits
                <InfoIcon content="Harte Limits - Pipeline wird beendet, wenn diese überschritten werden" />
              </h4>
              <div className="limit-items">
                <Tooltip content="Anzahl der CPU-Kerne">
                  <div className="limit-item">
                    <span className="limit-label">CPU:</span>
                    <span className="limit-value">{pipeline.metadata.cpu_hard_limit}</span>
                  </div>
                </Tooltip>
                {pipeline.metadata.mem_hard_limit && (
                  <Tooltip content="Speicher-Limit (z.B. '512M', '2G')">
                    <div className="limit-item">
                      <span className="limit-label">RAM:</span>
                      <span className="limit-value">{pipeline.metadata.mem_hard_limit}</span>
                    </div>
                  </Tooltip>
                )}
              </div>
            </div>
            {(pipeline.metadata.cpu_soft_limit || pipeline.metadata.mem_soft_limit) && (
              <div className="limit-section">
                <h4>
                  Soft Limits (Monitoring)
                  <InfoIcon content="Weiche Limits - Nur für Monitoring, Pipeline läuft weiter bei Überschreitung" />
                </h4>
                <div className="limit-items">
                  {pipeline.metadata.cpu_soft_limit && (
                    <Tooltip content="Anzahl der CPU-Kerne">
                      <div className="limit-item">
                        <span className="limit-label">CPU:</span>
                        <span className="limit-value">{pipeline.metadata.cpu_soft_limit}</span>
                      </div>
                    </Tooltip>
                  )}
                  {pipeline.metadata.mem_soft_limit && (
                    <Tooltip content="Speicher-Limit (z.B. '512M', '2G')">
                      <div className="limit-item">
                        <span className="limit-label">RAM:</span>
                        <span className="limit-value">{pipeline.metadata.mem_soft_limit}</span>
                      </div>
                    </Tooltip>
                  )}
                </div>
              </div>
            )}
            <div className="limit-section">
              <h4>{t('pipelineDetail.moreSettings')}</h4>
              <div className="limit-items">
                {pipeline.metadata.timeout && (
                  <div className="limit-item">
                    <span className="limit-label">
                      {t('pipelineDetail.timeout')}
                      <InfoIcon content={t('pipelineDetail.timeoutInfo')} />
                    </span>
                    <span className="limit-value">{pipeline.metadata.timeout}s</span>
                  </div>
                )}
                {pipeline.metadata.retry_attempts !== undefined && (
                  <div className="limit-item">
                    <span className="limit-label">
                      {t('pipelineDetail.retryAttempts')}
                      <InfoIcon content={t('pipelineDetail.retryAttemptsInfo')} />
                    </span>
                    <span className="limit-value">{pipeline.metadata.retry_attempts}</span>
                  </div>
                )}
                {pipeline.metadata.max_instances !== undefined && pipeline.metadata.max_instances > 0 && (
                  <div className="limit-item">
                    <span className="limit-label">
                      {t('pipelineDetail.maxInstances')}
                      <InfoIcon content={t('pipelineDetail.maxInstancesInfo')} />
                    </span>
                    <span className="limit-value">{pipeline.metadata.max_instances}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {stats && (
        <div className="stats-card">
          <div className="stats-header">
            <h3>{t('pipelineDetail.statistics')}</h3>
            {!isReadonly && (
              <Tooltip content={t('pipelineDetail.resetStatsTooltip')}>
                <button
                  onClick={handleResetStats}
                  disabled={resetStatsMutation.isPending}
                  className="reset-button"
                >
                  {resetStatsMutation.isPending ? t('pipelineDetail.resetting') : t('pipelineDetail.resetStats')}
                </button>
              </Tooltip>
            )}
          </div>
          <div className="stats-grid">
            <div className="stat-box">
              <span className="stat-label">{t('pipelineDetail.totalRuns')}</span>
              <span className="stat-value">{stats.total_runs}</span>
            </div>
            <div className="stat-box success">
              <span className="stat-label">{t('pipelineDetail.successful')}</span>
              <span className="stat-value">{stats.successful_runs}</span>
            </div>
            <div className="stat-box error">
              <span className="stat-label">{t('pipelineDetail.failed')}</span>
              <span className="stat-value">{stats.failed_runs}</span>
            </div>
            <div className="stat-box">
              <span className="stat-label">{t('pipelineDetail.successRate')}</span>
              <span className="stat-value">{stats.success_rate.toFixed(1)}%</span>
            </div>
            {stats.webhook_runs > 0 && (
              <div className="stat-box">
                <span className="stat-label">{t('pipelineDetail.webhookRuns')}</span>
                <span className="stat-value">{stats.webhook_runs}</span>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="webhook-card">
        <h3>{t('pipelineDetail.webhooks')}</h3>
        {(() => {
          const hasPipelineKey = !!pipeline?.metadata?.webhook_key
          const scheduleWebhooks = (pipeline?.metadata?.schedules ?? []).filter(
            (s): s is { id?: string; webhook_key: string } => !!(s.id && s.webhook_key)
          )
          const hasAnyWebhook = hasPipelineKey || scheduleWebhooks.length > 0
          if (!hasAnyWebhook) {
            return (
              <div className="webhook-disabled">
                <p>{t('pipelineDetail.webhooksDisabled')}</p>
                <p style={{ fontSize: '0.85rem', color: '#888', marginTop: '0.5rem' }}>
                  {t('pipelineDetail.webhooksEnableHint')}
                </p>
              </div>
            )
          }
          const byConfig = stats?.webhook_runs_by_config
          const runCountFor = (configKey: string) => (byConfig && byConfig[configKey]) ?? 0
          return (
            <div className="webhook-enabled">
              <div className="webhook-status" style={{ marginBottom: '0.75rem' }}>
                <span className="status-badge enabled">{t('pipelineDetail.webhooksEnabled')}</span>
                <span className="info-hint" style={{ fontSize: '0.75rem', color: '#888', marginLeft: '0.5rem' }}>
                  {t('pipelineDetail.webhooksConfiguredIn')}
                </span>
              </div>
              {hasPipelineKey && (
                <div className="webhook-url-section" style={{ marginBottom: '1rem' }}>
                  <label className="webhook-url-label">
                    {t('pipelineDetail.pipelineStandard')}
                    <InfoIcon content={t('pipelineDetail.webhookStandardInfo')} />
                  </label>
                  <div className="webhook-url-container">
                    <code className="webhook-url">
                      {typeof window !== 'undefined' && `${window.location.origin}/api/webhooks/${name}/${pipeline!.metadata.webhook_key}`}
                    </code>
                    <Tooltip content={t('pipelineDetail.copyWebhookUrl')}>
                      <button
                        onClick={() => handleCopyWebhookUrl(pipeline!.metadata.webhook_key!)}
                        className="copy-button"
                        title={t('pipelineDetail.copyUrl')}
                      >
                        📋
                      </button>
                    </Tooltip>
                  </div>
                  {runCountFor('') > 0 && (
                    <div className="webhook-stats">
                      <span className="webhook-stat-label">{t('pipelineDetail.trigger')}</span>
                      <span className="webhook-stat-value">{runCountFor('')}</span>
                    </div>
                  )}
                </div>
              )}
              {scheduleWebhooks.map((s) => (
                <div key={s.id!} className="webhook-url-section" style={{ marginBottom: '1rem' }}>
                  <label className="webhook-url-label">
                    {t('pipelineDetail.scheduleLabel', { id: s.id })}
                    <InfoIcon content={t('pipelineDetail.webhookRunConfigInfo', { id: s.id })} />
                  </label>
                  <div className="webhook-url-container">
                    <code className="webhook-url">
                      {typeof window !== 'undefined' && `${window.location.origin}/api/webhooks/${name}/${s.webhook_key}`}
                    </code>
                    <Tooltip content={t('pipelineDetail.copyWebhookUrl')}>
                      <button
                        onClick={() => handleCopyWebhookUrl(s.webhook_key)}
                        className="copy-button"
                        title={t('pipelineDetail.copyUrl')}
                      >
                        📋
                      </button>
                    </Tooltip>
                  </div>
                  {runCountFor(s.id!) > 0 && (
                    <div className="webhook-stats">
                      <span className="webhook-stat-label">{t('pipelineDetail.trigger')}</span>
                      <span className="webhook-stat-value">{runCountFor(s.id!)}</span>
                    </div>
                  )}
                </div>
              ))}
              {stats && stats.webhook_runs > 0 && (
                <div className="webhook-stats" style={{ marginTop: '0.5rem' }}>
                  <span className="webhook-stat-label">{t('pipelineDetail.webhookTriggerTotal')}</span>
                  <span className="webhook-stat-value">{stats.webhook_runs}</span>
                </div>
              )}
            </div>
          )
        })()}
      </div>

      <div className="downstream-triggers-card">
        <h3>
          {t('pipelineDetail.downstreamChaining')}
          <InfoIcon content={t('pipelineDetail.downstreamTooltip')} />
        </h3>
        {downstreamTriggers && downstreamTriggers.length > 0 ? (
          <div className="downstream-triggers-list">
            <table className="downstream-triggers-table">
              <thead>
                <tr>
                  <th>{t('pipelineDetail.downstreamPipeline')}</th>
                  <th>{t('pipelineDetail.schedule')}</th>
                  <th>{t('pipelineDetail.onSuccess')}</th>
                  <th>{t('pipelineDetail.onFailure')}</th>
                  <th>{t('pipelineDetail.source')}</th>
                  {!isReadonly && <th></th>}
                </tr>
              </thead>
              <tbody>
                {downstreamTriggers.map((tr) => (
                  <tr key={tr.id || `json-${tr.downstream_pipeline}-${tr.run_config_id ?? ''}`}>
                    <td>{tr.downstream_pipeline}</td>
                    <td>{tr.run_config_id ?? '–'}</td>
                    <td>{tr.on_success ? '✓' : '–'}</td>
                    <td>{tr.on_failure ? '✓' : '–'}</td>
                    <td>
                      <span className={`source-badge source-${tr.source}`}>
                        {tr.source === 'pipeline_json' ? t('pipelineDetail.sourcePipelineJson') : t('pipelineDetail.sourceUi')}
                      </span>
                    </td>
                    {!isReadonly && (
                      <td>
                        {tr.source === 'api' && tr.id ? (
                          <button
                            type="button"
                            className="delete-trigger-button"
                            onClick={() => deleteDownstreamTriggerMutation.mutate(tr.id!)}
                            disabled={deleteDownstreamTriggerMutation.isPending}
                          >
                            {t('pipelineDetail.remove')}
                          </button>
                        ) : (
                          <span className="info-hint" style={{ fontSize: '0.75rem', color: '#888' }}>
                            {t('pipelineDetail.editInPipelineJson')}
                          </span>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p style={{ fontSize: '0.9rem', color: '#888' }}>
            {t('pipelineDetail.noDownstreamTriggered')}
          </p>
        )}
        {!isReadonly && allPipelines && (
          <div className="add-downstream-trigger">
            <h4>{t('pipelineDetail.addTrigger')}</h4>
            <div className="add-trigger-form">
              <select
                value={newTriggerPipeline}
                onChange={(e) => {
                  setNewTriggerPipeline(e.target.value)
                  setNewTriggerRunConfigId('')
                }}
                className="trigger-select"
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
                  className="trigger-select"
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
              <label className="trigger-checkbox">
                <input
                  type="checkbox"
                  checked={newTriggerOnSuccess}
                  onChange={(e) => setNewTriggerOnSuccess(e.target.checked)}
                />
                {t('pipelineDetail.startOnSuccess')}
              </label>
              <label className="trigger-checkbox">
                <input
                  type="checkbox"
                  checked={newTriggerOnFailure}
                  onChange={(e) => setNewTriggerOnFailure(e.target.checked)}
                />
                {t('pipelineDetail.startOnFailure')}
              </label>
              <button
                type="button"
                className="add-trigger-button"
                onClick={handleAddDownstreamTrigger}
                disabled={!newTriggerPipeline.trim() || createDownstreamTriggerMutation.isPending}
              >
                {createDownstreamTriggerMutation.isPending ? t('pipelineDetail.adding') : t('pipelineDetail.add')}
              </button>
            </div>
            <p style={{ fontSize: '0.75rem', color: '#888', marginTop: '0.5rem' }}>
              {t('pipelineDetail.downstreamAltHint')}
            </p>
          </div>
        )}
      </div>

      {dailyStats && dailyStats.daily_stats && dailyStats.daily_stats.length > 0 && (
        <>
          <div className="charts-section">
            <SuccessRateTrendChart dailyStats={dailyStats.daily_stats} days={30} />
            {runs && runs.length > 0 && (
              <AverageRuntimeChart runs={runs} days={30} />
            )}
          </div>
          <CalendarHeatmap dailyStats={dailyStats.daily_stats} days={365} />
        </>
      )}

      {runs && runs.length > 0 && (
        <div className="runs-card">
          <h3>{t('pipelineDetail.lastRuns')}</h3>
          <table className="runs-table">
            <thead>
              <tr>
                <th>{t('pipelineDetail.id')}</th>
                <th>{t('pipelineDetail.status')}</th>
                <th>{t('pipelineDetail.started')}</th>
                <th>{t('pipelineDetail.finished')}</th>
                <th>{t('pipelineDetail.exitCode')}</th>
                <th>{t('pipelineDetail.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run: any) => (
                <tr key={run.id}>
                  <td>{run.id.substring(0, 8)}...</td>
                  <td>
                    <span className={`status status-${run.status.toLowerCase()}`}>
                      {run.status}
                    </span>
                  </td>
                  <td>{new Date(run.started_at).toLocaleString(getFormatLocale(), { timeZone: 'UTC' })} UTC</td>
                  <td>
                    {run.finished_at
                      ? `${new Date(run.finished_at).toLocaleString(getFormatLocale(), { timeZone: 'UTC' })} UTC`
                      : '-'}
                  </td>
                  <td>
                    {run.exit_code !== null ? (
                      <span className={run.exit_code === 0 ? 'exit-success' : 'exit-error'}>
                        {run.exit_code}
                      </span>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td>
                    <button
                      onClick={() => navigate(`/runs/${run.id}`)}
                      className="view-button"
                    >
                      {t('pipelineDetail.details')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="source-files-card">
        <h3>{t('pipelineDetail.sourceFiles')}</h3>
        <div className="tabs">
          <button
            className={`tab ${activeTab === 'python' ? 'active' : ''}`}
            onClick={() => setActiveTab('python')}
          >
            {t('pipelineDetail.tabPython')}
          </button>
          <button
            className={`tab ${activeTab === 'requirements' ? 'active' : ''}`}
            onClick={() => setActiveTab('requirements')}
          >
            {t('pipelineDetail.tabRequirements')}
          </button>
          <button
            className={`tab ${activeTab === 'json' ? 'active' : ''}`}
            onClick={() => setActiveTab('json')}
          >
            {t('pipelineDetail.tabJson')}
          </button>
        </div>
        <div className="tab-content">
          {sourceFilesLoading ? (
            <div className="code-loading">{t('pipelineDetail.codeLoading')}</div>
          ) : (
            <>
              {activeTab === 'python' && (
                <div className="code-container">
                  {sourceFiles?.main_py ? (
                    <pre className="code-block"><code>{sourceFiles.main_py}</code></pre>
                  ) : (
                    <div className="code-empty">{t('pipelineDetail.mainPyNotFound')}</div>
                  )}
                </div>
              )}
              {activeTab === 'requirements' && (
                <div className="code-container">
                  {sourceFiles?.requirements_txt ? (
                    <pre className="code-block"><code>{sourceFiles.requirements_txt}</code></pre>
                  ) : (
                    <div className="code-empty">{t('pipelineDetail.requirementsNotFound')}</div>
                  )}
                </div>
              )}
              {activeTab === 'json' && (
                <div className="code-container">
                  {sourceFiles?.pipeline_json ? (
                    <pre className="code-block"><code>{(() => {
                      try {
                        return JSON.stringify(JSON.parse(sourceFiles.pipeline_json), null, 2)
                      } catch {
                        return sourceFiles.pipeline_json
                      }
                    })()}</code></pre>
                  ) : (
                    <div className="code-empty">{t('pipelineDetail.pipelineJsonNotFound')}</div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
