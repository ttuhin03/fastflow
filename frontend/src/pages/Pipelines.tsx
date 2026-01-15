import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
import { MdInfo, MdRefresh, MdMemory } from 'react-icons/md'
import RunStatusCircles from '../components/RunStatusCircles'
import ProgressBar from '../components/ProgressBar'
import Skeleton from '../components/Skeleton'
import './Pipelines.css'

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
  }
}

export default function Pipelines() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: pipelines, isLoading } = useQuery<Pipeline[]>({
    queryKey: ['pipelines'],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines')
      return response.data
    },
    refetchInterval: 5000,
  })

  const resetStatsMutation = useMutation({
    mutationFn: async (name: string) => {
      const response = await apiClient.post(`/pipelines/${name}/stats/reset`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      alert('Statistiken wurden zurückgesetzt')
    },
    onError: (error: any) => {
      alert(`Fehler beim Zurücksetzen: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleResetStats = (name: string) => {
    if (confirm(`Möchten Sie die Statistiken für '${name}' wirklich zurücksetzen?`)) {
      resetStatsMutation.mutate(name)
    }
  }

  const successRate = (pipeline: Pipeline): number => {
    if (pipeline.total_runs === 0) return 0
    return parseFloat(((pipeline.successful_runs / pipeline.total_runs) * 100).toFixed(1))
  }

  if (isLoading) {
    return (
      <div className="pipelines">
        <div className="pipelines-grid">
          {[1, 2, 3].map((i) => (
            <div key={i} className="pipeline-card card">
              <div className="pipeline-header">
                <Skeleton width="60%" height="24px" />
                <Skeleton width="60px" height="24px" variant="rectangular" />
              </div>
              <Skeleton width="100%" height="16px" />
              <div className="pipeline-stats">
                <Skeleton width="100%" height="40px" />
              </div>
              <Skeleton width="100%" height="8px" />
              <Skeleton width="100%" height="28px" />
              <div className="pipeline-actions">
                <Skeleton width="50%" height="36px" />
                <Skeleton width="50%" height="36px" />
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="pipelines">
      {pipelines && pipelines.length > 0 ? (
        <div className="pipelines-grid">
          {pipelines.map((pipeline) => (
            <div key={pipeline.name} className="pipeline-card card">
              <div className="pipeline-header">
                <h3 className="pipeline-name">{pipeline.name}</h3>
                <span className={`badge ${pipeline.enabled ? 'badge-success' : 'badge-secondary'}`}>
                  {pipeline.enabled ? 'Aktiv' : 'Inaktiv'}
                </span>
              </div>

              {pipeline.metadata.description && (
                <p className="pipeline-description">{pipeline.metadata.description}</p>
              )}

              <div className="pipeline-stats">
                <div className="stat-item">
                  <span className="stat-label">Runs:</span>
                  <span className="stat-value">{pipeline.total_runs}</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label success">Erfolgreich:</span>
                  <span className="stat-value success">{pipeline.successful_runs}</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label error">Fehlgeschlagen:</span>
                  <span className="stat-value error">{pipeline.failed_runs}</span>
                </div>
              </div>

              {pipeline.total_runs > 0 && (
                <div className="pipeline-success-rate">
                  <ProgressBar value={successRate(pipeline)} />
                </div>
              )}

              <div className="pipeline-recent-runs">
                <span className="recent-runs-label">Letzte Runs:</span>
                <RunStatusCircles pipelineName={pipeline.name} />
              </div>

              {pipeline.metadata.cpu_hard_limit && (
                <div className="resource-limits">
                  <div className="limit-item">
                    <MdMemory />
                    <div>
                      <span className="limit-label">CPU:</span>
                      <span className="limit-value">{pipeline.metadata.cpu_hard_limit}</span>
                    </div>
                  </div>
                  {pipeline.metadata.mem_hard_limit && (
                    <div className="limit-item">
                      <MdMemory />
                      <div>
                        <span className="limit-label">RAM:</span>
                        <span className="limit-value">{pipeline.metadata.mem_hard_limit}</span>
                      </div>
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
                {pipeline.metadata.tags && pipeline.metadata.tags.length > 0 && (
                  <>
                    {pipeline.metadata.tags.map((tag) => (
                      <span key={tag} className="badge badge-secondary">
                        {tag}
                      </span>
                    ))}
                  </>
                )}
              </div>

              <div className="pipeline-actions">
                <button
                  onClick={() => navigate(`/pipelines/${pipeline.name}`)}
                  className="btn btn-primary details-button"
                >
                  <MdInfo />
                  Details
                </button>
                <button
                  onClick={() => handleResetStats(pipeline.name)}
                  className="btn btn-warning reset-button"
                  disabled={resetStatsMutation.isPending}
                >
                  <MdRefresh />
                  Stats zurücksetzen
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
  )
}
