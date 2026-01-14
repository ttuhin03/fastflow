import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'
import './Dashboard.css'

interface Pipeline {
  pipeline_name: string
  has_requirements: boolean
  total_runs: number
  successful_runs: number
  failed_runs: number
}

export default function Dashboard() {
  const { data: pipelines, isLoading } = useQuery<Pipeline[]>({
    queryKey: ['pipelines'],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines')
      return response.data
    },
  })

  if (isLoading) {
    return <div>Laden...</div>
  }

  return (
    <div className="dashboard">
      <h2>Dashboard</h2>
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
              <div key={pipeline.pipeline_name} className="pipeline-card">
                <h4>{pipeline.pipeline_name}</h4>
                <div className="pipeline-stats">
                  <span>Runs: {pipeline.total_runs}</span>
                  <span className="success">✓ {pipeline.successful_runs}</span>
                  <span className="error">✗ {pipeline.failed_runs}</span>
                </div>
                {pipeline.has_requirements && (
                  <span className="badge">requirements.txt</span>
                )}
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
