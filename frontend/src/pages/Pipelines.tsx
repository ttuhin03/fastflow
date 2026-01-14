import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
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

  const successRate = (pipeline: Pipeline) => {
    if (pipeline.total_runs === 0) return 0
    return ((pipeline.successful_runs / pipeline.total_runs) * 100).toFixed(1)
  }

  if (isLoading) {
    return <div>Laden...</div>
  }

  return (
    <div className="pipelines">
      <h2>Pipelines</h2>
      {pipelines && pipelines.length > 0 ? (
        <div className="pipelines-grid">
          {pipelines.map((pipeline) => (
            <div key={pipeline.name} className="pipeline-card">
              <div className="pipeline-header">
                <h3>{pipeline.name}</h3>
                <span className={`status-badge ${pipeline.enabled ? 'enabled' : 'disabled'}`}>
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
                {pipeline.total_runs > 0 && (
                  <div className="stat-item">
                    <span className="stat-label">Erfolgsrate:</span>
                    <span className="stat-value">{successRate(pipeline)}%</span>
                  </div>
                )}
              </div>

              {pipeline.metadata.cpu_hard_limit && (
                <div className="resource-limits">
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
              )}

              <div className="pipeline-badges">
                {pipeline.has_requirements && (
                  <span className="badge">requirements.txt</span>
                )}
                {pipeline.last_cache_warmup && (
                  <span className="badge cache">Cached</span>
                )}
                {pipeline.metadata.tags && pipeline.metadata.tags.length > 0 && (
                  <>
                    {pipeline.metadata.tags.map((tag) => (
                      <span key={tag} className="badge tag">
                        {tag}
                      </span>
                    ))}
                  </>
                )}
              </div>

              <div className="pipeline-actions">
                <button
                  onClick={() => navigate(`/pipelines/${pipeline.name}`)}
                  className="details-button"
                >
                  Details
                </button>
                <button
                  onClick={() => handleResetStats(pipeline.name)}
                  className="reset-button"
                  disabled={resetStatsMutation.isPending}
                >
                  Stats zurücksetzen
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p>Keine Pipelines gefunden</p>
      )}
    </div>
  )
}
