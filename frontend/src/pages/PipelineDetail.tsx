import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
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
    webhook_key?: string
    python_version?: string
  }
}

interface PipelineSourceFiles {
  main_py: string | null
  requirements_txt: string | null
  pipeline_json: string | null
}

export default function PipelineDetail() {
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


  const handleCopyWebhookUrl = () => {
    if (pipeline?.metadata.webhook_key) {
      const baseUrl = window.location.origin
      const webhookUrl = `${baseUrl}/api/webhooks/${name}/${pipeline.metadata.webhook_key}`
      navigator.clipboard.writeText(webhookUrl)
      showSuccess('Webhook-URL wurde in die Zwischenablage kopiert')
    }
  }

  if (pipelineLoading || statsLoading) {
    return <div>Laden...</div>
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
                {new Date(pipeline.last_cache_warmup).toLocaleString('de-DE')}
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
              <h4>Weitere Einstellungen</h4>
              <div className="limit-items">
                {pipeline.metadata.timeout && (
                  <div className="limit-item">
                    <span className="limit-label">
                      Timeout:
                      <InfoIcon content="Maximale Laufzeit in Sekunden. Pipeline wird beendet bei Überschreitung." />
                    </span>
                    <span className="limit-value">{pipeline.metadata.timeout}s</span>
                  </div>
                )}
                {pipeline.metadata.retry_attempts !== undefined && (
                  <div className="limit-item">
                    <span className="limit-label">
                      Retry-Versuche:
                      <InfoIcon content="Anzahl der Wiederholungsversuche bei Fehlschlag" />
                    </span>
                    <span className="limit-value">{pipeline.metadata.retry_attempts}</span>
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
            <h3>Statistiken</h3>
            {!isReadonly && (
              <Tooltip content="Setzt alle Statistiken dieser Pipeline zurück. Läufe und Daten bleiben erhalten.">
                <button
                  onClick={handleResetStats}
                  disabled={resetStatsMutation.isPending}
                  className="reset-button"
                >
                  {resetStatsMutation.isPending ? 'Zurücksetzen...' : 'Statistiken zurücksetzen'}
                </button>
              </Tooltip>
            )}
          </div>
          <div className="stats-grid">
            <div className="stat-box">
              <span className="stat-label">Gesamt Runs</span>
              <span className="stat-value">{stats.total_runs}</span>
            </div>
            <div className="stat-box success">
              <span className="stat-label">Erfolgreich</span>
              <span className="stat-value">{stats.successful_runs}</span>
            </div>
            <div className="stat-box error">
              <span className="stat-label">Fehlgeschlagen</span>
              <span className="stat-value">{stats.failed_runs}</span>
            </div>
            <div className="stat-box">
              <span className="stat-label">Erfolgsrate</span>
              <span className="stat-value">{stats.success_rate.toFixed(1)}%</span>
            </div>
            {stats.webhook_runs > 0 && (
              <div className="stat-box">
                <span className="stat-label">Webhook Runs</span>
                <span className="stat-value">{stats.webhook_runs}</span>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="webhook-card">
        <h3>Webhooks</h3>
        {pipeline?.metadata.webhook_key ? (
          <div className="webhook-enabled">
            <div className="webhook-info">
              <div className="webhook-status">
                <span className="status-badge enabled">Aktiviert</span>
                <span className="info-hint" style={{ fontSize: '0.75rem', color: '#888', marginLeft: '0.5rem' }}>
                  (Konfiguriert in pipeline.json)
                </span>
              </div>
              <div className="webhook-url-section">
                <label className="webhook-url-label">
                  Webhook-URL:
                  <InfoIcon content="Diese URL kann verwendet werden, um die Pipeline von außen zu triggern" />
                </label>
                <div className="webhook-url-container">
                  <code className="webhook-url">
                    {typeof window !== 'undefined' && `${window.location.origin}/api/webhooks/${name}/${pipeline.metadata.webhook_key}`}
                  </code>
                  <Tooltip content="Webhook-URL in Zwischenablage kopieren">
                    <button
                      onClick={handleCopyWebhookUrl}
                      className="copy-button"
                      title="URL kopieren"
                    >
                      📋
                    </button>
                  </Tooltip>
                </div>
              </div>
              {stats && stats.webhook_runs > 0 && (
                <div className="webhook-stats">
                  <span className="webhook-stat-label">Webhook-Trigger:</span>
                  <span className="webhook-stat-value">{stats.webhook_runs}</span>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="webhook-disabled">
            <p>Webhooks sind für diese Pipeline deaktiviert.</p>
            <p style={{ fontSize: '0.85rem', color: '#888', marginTop: '0.5rem' }}>
              Um Webhooks zu aktivieren, fügen Sie <code>webhook_key</code> in die <code>pipeline.json</code> im Repository hinzu.
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
          <h3>Letzte Runs</h3>
          <table className="runs-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Status</th>
                <th>Gestartet</th>
                <th>Beendet</th>
                <th>Exit Code</th>
                <th>Aktionen</th>
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
                  <td>{new Date(run.started_at).toLocaleString('de-DE', { timeZone: 'UTC' })} UTC</td>
                  <td>
                    {run.finished_at
                      ? `${new Date(run.finished_at).toLocaleString('de-DE', { timeZone: 'UTC' })} UTC`
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
                      Details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="source-files-card">
        <h3>Quelldateien</h3>
        <div className="tabs">
          <button
            className={`tab ${activeTab === 'python' ? 'active' : ''}`}
            onClick={() => setActiveTab('python')}
          >
            Python (main.py)
          </button>
          <button
            className={`tab ${activeTab === 'requirements' ? 'active' : ''}`}
            onClick={() => setActiveTab('requirements')}
          >
            Requirements
          </button>
          <button
            className={`tab ${activeTab === 'json' ? 'active' : ''}`}
            onClick={() => setActiveTab('json')}
          >
            JSON (pipeline.json)
          </button>
        </div>
        <div className="tab-content">
          {sourceFilesLoading ? (
            <div className="code-loading">Laden...</div>
          ) : (
            <>
              {activeTab === 'python' && (
                <div className="code-container">
                  {sourceFiles?.main_py ? (
                    <pre className="code-block"><code>{sourceFiles.main_py}</code></pre>
                  ) : (
                    <div className="code-empty">main.py nicht gefunden</div>
                  )}
                </div>
              )}
              {activeTab === 'requirements' && (
                <div className="code-container">
                  {sourceFiles?.requirements_txt ? (
                    <pre className="code-block"><code>{sourceFiles.requirements_txt}</code></pre>
                  ) : (
                    <div className="code-empty">requirements.txt nicht gefunden</div>
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
                    <div className="code-empty">pipeline.json nicht gefunden</div>
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
