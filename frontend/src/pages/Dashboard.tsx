import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
import { 
  MdPlayArrow, 
  MdInfo, 
  MdCheckCircle, 
  MdCancel, 
  MdSync,
  MdSchedule,
  MdMemory,
  MdViewList
} from 'react-icons/md'
import RunStatusCircles from '../components/RunStatusCircles'
import StorageStats from '../components/StorageStats'
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
    refetchInterval: 5000,
  })

  const { data: syncStatus } = useQuery<SyncStatus>({
    queryKey: ['sync-status'],
    queryFn: async () => {
      const response = await apiClient.get('/sync/status')
      return response.data
    },
    refetchInterval: 10000,
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
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Laden...</p>
      </div>
    )
  }

  const successRate = (pipeline: Pipeline) => {
    if (pipeline.total_runs === 0) return 0
    return ((pipeline.successful_runs / pipeline.total_runs) * 100).toFixed(1)
  }

  const totalRuns = pipelines?.reduce((sum, p) => sum + p.total_runs, 0) || 0
  const totalSuccessful = pipelines?.reduce((sum, p) => sum + p.successful_runs, 0) || 0
  const totalFailed = pipelines?.reduce((sum, p) => sum + p.failed_runs, 0) || 0

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <button
          onClick={handleSync}
          disabled={syncMutation.isPending}
          className="btn btn-primary sync-button"
        >
          <MdSync />
          {syncMutation.isPending ? 'Sync läuft...' : 'Git Sync'}
        </button>
      </div>

      {syncStatus && (
        <div className="sync-status card">
          <div className="sync-status-item">
            <strong>Branch:</strong> {syncStatus.branch}
          </div>
          {syncStatus.last_sync && (
            <div className="sync-status-item">
              <strong>Letzter Sync:</strong> {new Date(syncStatus.last_sync).toLocaleString('de-DE')}
            </div>
          )}
        </div>
      )}

      <div className="stats-grid">
        <div className="stat-card card">
          <div className="stat-icon pipelines">
            <MdViewList />
          </div>
          <div className="stat-content">
            <h3 className="stat-label">Pipelines</h3>
            <p className="stat-value">{pipelines?.length || 0}</p>
          </div>
        </div>
        
        <div className="stat-card card">
          <div className="stat-icon runs">
            <MdSchedule />
          </div>
          <div className="stat-content">
            <h3 className="stat-label">Gesamt Runs</h3>
            <p className="stat-value">{totalRuns}</p>
          </div>
        </div>
        
        <div className="stat-card card">
          <div className="stat-icon success">
            <MdCheckCircle />
          </div>
          <div className="stat-content">
            <h3 className="stat-label">Erfolgreich</h3>
            <p className="stat-value success">{totalSuccessful}</p>
          </div>
        </div>
        
        <div className="stat-card card">
          <div className="stat-icon error">
            <MdCancel />
          </div>
          <div className="stat-content">
            <h3 className="stat-label">Fehlgeschlagen</h3>
            <p className="stat-value error">{totalFailed}</p>
          </div>
        </div>
      </div>

      <div className="storage-section">
        <h3 className="section-title">Speicherplatz</h3>
        <StorageStats />
      </div>

      <div className="pipelines-section">
        <h3 className="section-title">Pipelines</h3>
        {pipelines && pipelines.length > 0 ? (
          <div className="pipeline-grid">
            {pipelines.map((pipeline) => (
              <div key={pipeline.name} className="pipeline-card card">
                <div className="pipeline-header">
                  <h4 className="pipeline-name">{pipeline.name}</h4>
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
                    <span className={`badge ${pipeline.enabled ? 'badge-success' : 'badge-secondary'}`}>
                      {pipeline.enabled ? 'Aktiv' : 'Inaktiv'}
                    </span>
                  </div>
                </div>
                
                {pipeline.metadata.description && (
                  <p className="pipeline-description">{pipeline.metadata.description}</p>
                )}
                
                <div className="pipeline-stats">
                  <div className="stat-row">
                    <span className="stat-label-small">Runs:</span>
                    <span className="stat-value-small">{pipeline.total_runs}</span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label-small success">Erfolgreich:</span>
                    <span className="stat-value-small success">{pipeline.successful_runs}</span>
                  </div>
                  <div className="stat-row">
                    <span className="stat-label-small error">Fehlgeschlagen:</span>
                    <span className="stat-value-small error">{pipeline.failed_runs}</span>
                  </div>
                  {pipeline.total_runs > 0 && (
                    <div className="stat-row">
                      <span className="stat-label-small">Erfolgsrate:</span>
                      <span className="stat-value-small">{successRate(pipeline)}%</span>
                    </div>
                  )}
                </div>
                
                {pipeline.metadata.cpu_hard_limit && (
                  <div className="resource-limits">
                    <div className="resource-item">
                      <MdMemory />
                      <span>CPU: {pipeline.metadata.cpu_hard_limit}</span>
                    </div>
                    {pipeline.metadata.mem_hard_limit && (
                      <div className="resource-item">
                        <MdMemory />
                        <span>RAM: {pipeline.metadata.mem_hard_limit}</span>
                      </div>
                    )}
                  </div>
                )}
                
                <div className="pipeline-badges">
                  {pipeline.has_requirements && (
                    <span className="badge badge-info">requirements.txt</span>
                  )}
                  {pipeline.last_cache_warmup && (
                    <span className="badge badge-success">Cached</span>
                  )}
                </div>

                <div className="pipeline-recent-runs">
                  <span className="recent-runs-label">Letzte Runs:</span>
                  <RunStatusCircles pipelineName={pipeline.name} />
                </div>
                
                <div className="pipeline-actions">
                  <button
                    onClick={() => handleStartPipeline(pipeline.name)}
                    disabled={!pipeline.enabled || startingPipeline === pipeline.name}
                    className="btn btn-success start-button"
                  >
                    <MdPlayArrow />
                    {startingPipeline === pipeline.name ? 'Startet...' : 'Starten'}
                  </button>
                  <button
                    onClick={() => navigate(`/pipelines/${pipeline.name}`)}
                    className="btn btn-outlined details-button"
                  >
                    <MdInfo />
                    Details
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty-state card">
            <p>Keine Pipelines gefunden</p>
          </div>
        )}
      </div>
    </div>
  )
}
