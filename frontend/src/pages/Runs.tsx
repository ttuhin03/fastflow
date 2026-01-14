import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import apiClient from '../api/client'
import './Runs.css'

export default function Runs() {
  const { data: runs, isLoading } = useQuery({
    queryKey: ['runs'],
    queryFn: async () => {
      const response = await apiClient.get('/runs')
      return response.data
    },
  })

  if (isLoading) {
    return <div>Laden...</div>
  }

  return (
    <div className="runs">
      <h2>Runs</h2>
      {runs && runs.length > 0 ? (
        <table className="runs-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Pipeline</th>
              <th>Status</th>
              <th>Gestartet</th>
              <th>Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run: any) => (
              <tr key={run.id}>
                <td>{run.id.substring(0, 8)}...</td>
                <td>{run.pipeline_name}</td>
                <td>
                  <span className={`status status-${run.status.toLowerCase()}`}>
                    {run.status}
                  </span>
                </td>
                <td>{new Date(run.started_at).toLocaleString('de-DE')}</td>
                <td>
                  <Link to={`/runs/${run.id}`}>Details</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>Keine Runs gefunden</p>
      )}
    </div>
  )
}
