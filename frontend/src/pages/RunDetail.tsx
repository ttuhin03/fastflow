import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import apiClient from '../api/client'
import './RunDetail.css'

export default function RunDetail() {
  const { runId } = useParams()
  const { data: run, isLoading } = useQuery({
    queryKey: ['run', runId],
    queryFn: async () => {
      const response = await apiClient.get(`/runs/${runId}`)
      return response.data
    },
  })

  if (isLoading) {
    return <div>Laden...</div>
  }

  if (!run) {
    return <div>Run nicht gefunden</div>
  }

  return (
    <div className="run-detail">
      <h2>Run Details</h2>
      <div className="run-info">
        <p><strong>ID:</strong> {run.id}</p>
        <p><strong>Pipeline:</strong> {run.pipeline_name}</p>
        <p><strong>Status:</strong> {run.status}</p>
        <p><strong>Gestartet:</strong> {new Date(run.started_at).toLocaleString('de-DE')}</p>
        {run.finished_at && (
          <p><strong>Beendet:</strong> {new Date(run.finished_at).toLocaleString('de-DE')}</p>
        )}
      </div>
    </div>
  )
}
