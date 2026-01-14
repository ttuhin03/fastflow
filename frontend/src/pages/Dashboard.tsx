import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
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

export default function Dashboard() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [startingPipeline, setStartingPipeline] = useState<string | null>(null)

  const { data: pipelines, isLoading } = useQuery<Pipeline[]>({
    queryKey: ['pipelines'],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines')
      return response.data
    },
    refetchInterval: 5000, // Auto-refresh alle 5 Sekunden
  })

  const { data: syncStatus } = useQuery<SyncStatus>({
    queryKey: ['sync-status'],
    queryFn: async () => {
      const response = await apiClient.get('/sync/status')
      return response.data
    },
    refetchInterval: 10000, // Auto-refresh alle 10 Sekunden
  })

  const startPipelineMutation = useMutation({
    mutationFn: async (name: string) => {
      const response = await apiClient.post(`/pipelines/${name}/run`, {
        env_vars: {},
        parameters: {},
      })
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      setStartingPipeline(null)
      navigate(`/runs/${data.id}`)
    },
    onError: (error: any) => {
      setStartingPipeline(null)
      alert(`Fehler beim Starten der Pipeline: ${error.response?.data?.detail || error.message}`)
    },
  })

  const syncMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/sync', {})
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      alert('Git-Sync erfolgreich abgeschlossen')
    },
    onError: (error: any) => {
      alert(`Fehler beim Git-Sync: ${error.response?.data?.detail || error.message}`)
    },
  })

  const togglePipelineEnabledMutation = useMutation({
    mutationFn: async ({ name, enabled }: { name: string; enabled: boolean }) => {
      const response = await apiClient.put(`/pipelines/${name}/enabled`, { enabled })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
    },
    onError: (error: any) => {
      alert(`Fehler beim Umschalten: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleTogglePipeline = (name: string, currentEnabled: boolean) => {
    togglePipelineEnabledMutation.mutate({ name, enabled: !currentEnabled })
  }

  const handleStartPipeline = (name: string) => {
    if (startingPipeline) return
    setStartingPipeline(name)
    startPipelineMutation.mutate(name)
  }

  const handleSync = () => {
    if (syncMutation.isPending) return
    if (confirm('Git-Sync ausführen? Dies kann einige Zeit dauern.')) {
      syncMutation.mutate()
    }
  }

  if (isLoading) {
    return <div>Laden...</div>
  }

  const successRate = (pipeline: Pipeline) => {
    if (pipeline.total_runs === 0) return 0
    return ((pipeline.successful_runs / pipeline.total_runs) * 100).toFixed(1)
  }

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h2>Dashboard</h2>
        <button
          onClick={handleSync}
          disabled={syncMutation.isPending}
          className="sync-button"
        >
          {syncMutation.isPending ? 'Sync läuft...' : 'Git Sync'}
        </button>
      </div>

      {syncStatus && (
        <div className="sync-status">
          <span>Branch: {syncStatus.branch}</span>
          {syncStatus.last_sync && (
            <span>Letzter Sync: {new Date(syncStatus.last_sync).toLocaleString('de-DE')}</span>
          )}
        </div>
      )}

      <div className="stats-grid">
        <div className="stat-card">
          <h3>Pipelines</h3>
          <p className="stat-value">{pipelines?.length || 0}</p>
        </div>
        <div className="stat-card">
          <h3>Gesamt Runs</h3>
          <p className="stat-value">
            {pipelines?.reduce((sum, p) => sum + p.total_runs, 0) || 0}
          </p>
        </div>
        <div className="stat-card">
          <h3>Erfolgreich</h3>
          <p className="stat-value success">
            {pipelines?.reduce((sum, p) => sum + p.successful_runs, 0) || 0}
          </p>
        </div>
        <div className="stat-card">
          <h3>Fehlgeschlagen</h3>
          <p className="stat-value error">
            {pipelines?.reduce((sum, p) => sum + p.failed_runs, 0) || 0}
          </p>
        </div>
      </div>

      <div className="pipelines-list">
        <h3>Pipelines</h3>
        {pipelines && pipelines.length > 0 ? (
          <div className="pipeline-grid">
            {pipelines.map((pipeline) => (
              <div key={pipeline.name} className="pipeline-card">
                <div className="pipeline-header">
                  <h4>{pipeline.name}</h4>
                  <div className="pipeline-status-controls">
                    <label className="toggle-switch">
                      <input
                        type="checkbox"
                        checked={pipeline.enabled}
                        onChange={() => handleTogglePipeline(pipeline.name, pipeline.enabled)}
                        disabled={togglePipelineEnabledMutation.isPending}
                      />
                      <span className="toggle-slider"></span>
                    </label>
                    <span className={`status-badge ${pipeline.enabled ? 'enabled' : 'disabled'}`}>
                      {pipeline.enabled ? 'Aktiv' : 'Inaktiv'}
                    </span>
                  </div>
                </div>
                <div className="pipeline-stats">
                  <span>Runs: {pipeline.total_runs}</span>
                  <span className="success">✓ {pipeline.successful_runs}</span>
                  <span className="error">✗ {pipeline.failed_runs}</span>
                  {pipeline.total_runs > 0 && (
                    <span className="success-rate">
                      {successRate(pipeline)}% Erfolg
                    </span>
                  )}
                </div>
                {pipeline.metadata.description && (
                  <p className="pipeline-description">{pipeline.metadata.description}</p>
                )}
                {pipeline.metadata.cpu_hard_limit && (
                  <div className="resource-limits">
                    <span>CPU: {pipeline.metadata.cpu_hard_limit}</span>
                    {pipeline.metadata.mem_hard_limit && (
                      <span>RAM: {pipeline.metadata.mem_hard_limit}</span>
                    )}
                  </div>
                )}
                <div className="pipeline-badges">
                  {pipeline.has_requirements && (
                    <span className="badge">requirements.txt</span>
                  )}
                  {pipeline.last_cache_warmup && (
                    <span className="badge cache">Cached</span>
                  )}
                </div>
                <div className="pipeline-actions">
                  <button
                    onClick={() => handleStartPipeline(pipeline.name)}
                    disabled={!pipeline.enabled || startingPipeline === pipeline.name}
                    className="start-button"
                  >
                    {startingPipeline === pipeline.name ? 'Startet...' : 'Starten'}
                  </button>
                  <button
                    onClick={() => navigate(`/pipelines/${pipeline.name}`)}
                    className="details-button"
                  >
                    Details
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p>Keine Pipelines gefunden</p>
        )}
      </div>
    </div>
  )
}
