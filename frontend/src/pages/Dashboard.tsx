import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import { MdCheckCircle, MdCancel, MdSync, MdSchedule, MdViewList } from 'react-icons/md'
import Tooltip from '../components/Tooltip'
import InfoIcon from '../components/InfoIcon'
import RunStatusCircles from '../components/RunStatusCircles'
import StorageStats from '../components/StorageStats'
import CalendarHeatmap from '../components/CalendarHeatmap'
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
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  // Reduzierte Polling-Frequenz: weniger API-Last bei vielen Nutzern (Enterprise-tauglich)
  const pipelinesInterval = useRefetchInterval(30_000, 120_000)   // sichtbar: 30s, Hintergrund: 2min
  const syncInterval = useRefetchInterval(15_000, 120_000)        // sichtbar: 15s, Hintergrund: 2min
  const dailyStatsInterval = useRefetchInterval(60_000, 120_000)  // sichtbar: 1min, Hintergrund: 2min

  const { data: pipelines, isLoading } = useQuery<Pipeline[]>({
    queryKey: ['pipelines'],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines')
      return response.data
    },
    refetchInterval: pipelinesInterval,
    staleTime: 30_000,  // 30s – vermeidet unnötige Refetches bei Tab-Wechsel
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
    refetchInterval: dailyStatsInterval,
    staleTime: 120_000,  // 2min – Daily-Stats ändern sich selten
  })

  const syncMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/sync', {})
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      showSuccess('Git-Sync erfolgreich abgeschlossen')
    },
    onError: (error: any) => {
      showError(`Fehler beim Git-Sync: ${error.response?.data?.detail || error.message}`)
    },
  })


  const handleSync = async () => {
    if (syncMutation.isPending) return
    const confirmed = await showConfirm('Git-Sync ausführen? Dies kann einige Zeit dauern.')
    if (confirmed) {
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

  const totalRuns = pipelines?.reduce((sum, p) => sum + p.total_runs, 0) || 0
  const totalSuccessful = pipelines?.reduce((sum, p) => sum + p.successful_runs, 0) || 0
  const totalFailed = pipelines?.reduce((sum, p) => sum + p.failed_runs, 0) || 0

  return (
    <div className="dashboard">
      {!isReadonly && (
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

      {allPipelinesDailyStats && allPipelinesDailyStats.daily_stats && allPipelinesDailyStats.daily_stats.length > 0 && (
        <div className="dashboard-calendar-section">
          <h3 className="section-title">Laufhistorie</h3>
          <div className="dashboard-calendar-wrapper">
            <CalendarHeatmap dailyStats={allPipelinesDailyStats.daily_stats} days={365} showTitle={false} />
          </div>
        </div>
      )}

      <div className="storage-section">
        <h3 className="section-title">Speicherplatz</h3>
        <StorageStats />
      </div>

      <div className="pipelines-section">
        <h3 className="section-title">Pipelines</h3>
        {pipelines && pipelines.length > 0 ? (
          <div className="pipeline-grid">
            {pipelines.map((pipeline, index) => (
              <div key={pipeline.name} className="pipeline-card card" style={{ animationDelay: `${index * 0.05}s` }}>
                <div className="pipeline-header">
                  <h4 className="pipeline-name">{pipeline.name}</h4>
                  <Tooltip content="Aktiv: Pipeline kann ausgeführt werden | Inaktiv: Pipeline ist deaktiviert">
                    <span className={`badge ${pipeline.enabled ? 'badge-success' : 'badge-secondary'}`}>
                      {pipeline.enabled ? 'Aktiv' : 'Inaktiv'}
                    </span>
                  </Tooltip>
                </div>
                <div className="pipeline-recent-runs">
                  <span className="recent-runs-label">
                    Letzte Runs:
                    <InfoIcon content="Zeigt die Status der letzten Runs (grün=erfolgreich, rot=fehlgeschlagen, gelb=läuft)" />
                  </span>
                  <RunStatusCircles pipelineName={pipeline.name} />
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
