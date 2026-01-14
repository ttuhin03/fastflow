import { useQuery } from '@tanstack/react-query'
import apiClient from '../api/client'
import './Pipelines.css'

export default function Pipelines() {
  const { data: pipelines, isLoading } = useQuery({
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
    <div className="pipelines">
      <h2>Pipelines</h2>
      {pipelines && pipelines.length > 0 ? (
        <div className="pipelines-grid">
          {pipelines.map((pipeline: any) => (
            <div key={pipeline.pipeline_name} className="pipeline-card">
              <h3>{pipeline.pipeline_name}</h3>
              <p>Runs: {pipeline.total_runs}</p>
              <p>Erfolgreich: {pipeline.successful_runs}</p>
              <p>Fehlgeschlagen: {pipeline.failed_runs}</p>
            </div>
          ))}
        </div>
      ) : (
        <p>Keine Pipelines gefunden</p>
      )}
    </div>
  )
}
