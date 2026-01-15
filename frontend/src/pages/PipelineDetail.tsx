import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
import CalendarHeatmap from '../components/CalendarHeatmap'
import './PipelineDetail.css'

interface PipelineStats {
  pipeline_name: string
  total_runs: number
  successful_runs: number
  failed_runs: number
  success_rate: number
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
  }
}

export default function PipelineDetail() {
  const { name } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

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
    refetchInterval: 10000, // Refresh every 10 seconds to show new runs faster
    staleTime: 0, // Always consider data stale to ensure fresh data
    gcTime: 0, // Don't cache to always get fresh data (was cacheTime in v4)
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
      alert('Statistiken wurden zurückgesetzt')
    },
    onError: (error: any) => {
      alert(`Fehler beim Zurücksetzen: ${error.response?.data?.detail || error.message}`)
    },
  })

  const toggleEnabledMutation = useMutation({
    mutationFn: async (enabled: boolean) => {
      const response = await apiClient.put(`/pipelines/${name}/enabled`, { enabled })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipeline', name] })
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
    },
    onError: (error: any) => {
      alert(`Fehler beim Umschalten: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleToggleEnabled = () => {
    if (pipeline) {
      toggleEnabledMutation.mutate(!pipeline.enabled)
    }
  }

  const handleResetStats = () => {
    if (confirm('Möchten Sie die Statistiken wirklich zurücksetzen?')) {
      resetStatsMutation.mutate()
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
          <div className="pipeline-status-controls">
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={pipeline.enabled}
                onChange={handleToggleEnabled}
                disabled={toggleEnabledMutation.isPending}
              />
              <span className="toggle-slider"></span>
            </label>
            <span className={`status-badge ${pipeline.enabled ? 'enabled' : 'disabled'}`}>
              {pipeline.enabled ? 'Aktiv' : 'Inaktiv'}
            </span>
          </div>
        </div>
          <div className="info-item">
            <span className="info-label">Requirements:</span>
            <span className="info-value">
              {pipeline.has_requirements ? 'Ja' : 'Nein'}
            </span>
          </div>
          {pipeline.last_cache_warmup && (
            <div className="info-item">
              <span className="info-label">Letzter Cache-Warmup:</span>
              <span className="info-value">
                {new Date(pipeline.last_cache_warmup).toLocaleString('de-DE')}
              </span>
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
              <h4>Hard Limits</h4>
              <div className="limit-items">
                <div className="limit-item">
                  <span className="limit-label">CPU:</span>
                  <span className="limit-value">{pipeline.metadata.cpu_hard_limit}</span>
                </div>
                {pipeline.metadata.mem_hard_limit && (
                  <div className="limit-item">
                    <span className="limit-label">RAM:</span>
                    <span className="limit-value">{pipeline.metadata.mem_hard_limit}</span>
                  </div>
                )}
              </div>
            </div>
            {(pipeline.metadata.cpu_soft_limit || pipeline.metadata.mem_soft_limit) && (
              <div className="limit-section">
                <h4>Soft Limits (Monitoring)</h4>
                <div className="limit-items">
                  {pipeline.metadata.cpu_soft_limit && (
                    <div className="limit-item">
                      <span className="limit-label">CPU:</span>
                      <span className="limit-value">{pipeline.metadata.cpu_soft_limit}</span>
                    </div>
                  )}
                  {pipeline.metadata.mem_soft_limit && (
                    <div className="limit-item">
                      <span className="limit-label">RAM:</span>
                      <span className="limit-value">{pipeline.metadata.mem_soft_limit}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
            <div className="limit-section">
              <h4>Weitere Einstellungen</h4>
              <div className="limit-items">
                {pipeline.metadata.timeout && (
                  <div className="limit-item">
                    <span className="limit-label">Timeout:</span>
                    <span className="limit-value">{pipeline.metadata.timeout}s</span>
                  </div>
                )}
                {pipeline.metadata.retry_attempts !== undefined && (
                  <div className="limit-item">
                    <span className="limit-label">Retry-Versuche:</span>
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
            <button
              onClick={handleResetStats}
              disabled={resetStatsMutation.isPending}
              className="reset-button"
            >
              {resetStatsMutation.isPending ? 'Zurücksetzen...' : 'Statistiken zurücksetzen'}
            </button>
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
          </div>
        </div>
      )}

      {dailyStats && dailyStats.daily_stats && dailyStats.daily_stats.length > 0 && (
        <>
          <CalendarHeatmap dailyStats={dailyStats.daily_stats} days={365} />
          {/* Debug: Zeige die letzten 5 Tage */}
          <div style={{ marginTop: '10px', fontSize: '12px', color: '#666' }}>
            Letzte 5 Tage: {dailyStats.daily_stats.slice(-5).map((s: { date: string; total_runs: number; successful_runs: number; failed_runs: number; success_rate: number }) => `${s.date}: ${s.total_runs} runs`).join(', ')}
          </div>
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
                  <td>{new Date(run.started_at).toLocaleString('de-DE')}</td>
                  <td>
                    {run.finished_at
                      ? new Date(run.finished_at).toLocaleString('de-DE')
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
    </div>
  )
}
