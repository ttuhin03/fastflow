import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import apiClient from '../api/client'
import './Runs.css'

interface Run {
  id: string
  pipeline_name: string
  status: string
  started_at: string
  finished_at: string | null
  exit_code: number | null
}

export default function Runs() {
  const [pipelineFilter, setPipelineFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [startDate, setStartDate] = useState<string>('')
  const [endDate, setEndDate] = useState<string>('')

  const { data: pipelines } = useQuery({
    queryKey: ['pipelines'],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines')
      return response.data
    },
  })

  const { data: runs, isLoading } = useQuery<Run[]>({
    queryKey: ['runs', pipelineFilter, statusFilter, startDate, endDate],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (pipelineFilter) params.append('pipeline_name', pipelineFilter)
      if (statusFilter) params.append('status_filter', statusFilter)
      if (startDate) params.append('start_date', startDate)
      if (endDate) params.append('end_date', endDate)
      const response = await apiClient.get(`/runs?${params.toString()}`)
      return response.data
    },
    refetchInterval: 5000, // Auto-refresh alle 5 Sekunden
  })

  if (isLoading) {
    return <div>Laden...</div>
  }

  const filteredAndSortedRuns = runs
    ? [...runs].sort((a, b) => {
        const dateA = new Date(a.started_at).getTime()
        const dateB = new Date(b.started_at).getTime()
        return sortOrder === 'asc' ? dateA - dateB : dateB - dateA
      })
    : []

  const getDuration = (run: Run) => {
    if (!run.finished_at) return 'Läuft...'
    const start = new Date(run.started_at).getTime()
    const end = new Date(run.finished_at).getTime()
    const seconds = Math.floor((end - start) / 1000)
    if (seconds < 60) return `${seconds}s`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    if (minutes < 60) return `${minutes}m ${remainingSeconds}s`
    const hours = Math.floor(minutes / 60)
    const remainingMinutes = minutes % 60
    return `${hours}h ${remainingMinutes}m`
  }

  return (
    <div className="runs">
      <h2>Runs</h2>
      
      <div className="runs-filters">
        <div className="filter-group">
          <label htmlFor="pipeline-filter">Pipeline:</label>
          <select
            id="pipeline-filter"
            value={pipelineFilter}
            onChange={(e) => setPipelineFilter(e.target.value)}
          >
            <option value="">Alle</option>
            {pipelines?.map((p: any) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="status-filter">Status:</label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">Alle</option>
            <option value="PENDING">Pending</option>
            <option value="RUNNING">Running</option>
            <option value="SUCCESS">Success</option>
            <option value="FAILED">Failed</option>
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="sort-order">Sortierung:</label>
          <select
            id="sort-order"
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value as 'asc' | 'desc')}
          >
            <option value="desc">Neueste zuerst</option>
            <option value="asc">Älteste zuerst</option>
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="start-date">Von:</label>
          <input
            id="start-date"
            type="datetime-local"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </div>

        <div className="filter-group">
          <label htmlFor="end-date">Bis:</label>
          <input
            id="end-date"
            type="datetime-local"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </div>
      </div>

      {filteredAndSortedRuns.length > 0 ? (
        <table className="runs-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Pipeline</th>
              <th>Status</th>
              <th>Gestartet</th>
              <th>Dauer</th>
              <th>Exit Code</th>
              <th>Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {filteredAndSortedRuns.map((run) => (
              <tr key={run.id}>
                <td>{run.id.substring(0, 8)}...</td>
                <td>{run.pipeline_name}</td>
                <td>
                  <span className={`status status-${run.status.toLowerCase()}`}>
                    {run.status}
                  </span>
                </td>
                <td>{new Date(run.started_at).toLocaleString('de-DE')}</td>
                <td>{getDuration(run)}</td>
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
