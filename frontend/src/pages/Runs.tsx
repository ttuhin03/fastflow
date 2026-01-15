import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import apiClient from '../api/client'
import { MdInfo, MdCheckCircle, MdCancel, MdHourglassEmpty, MdPlayArrow, MdWarning, MdStop } from 'react-icons/md'
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
    refetchInterval: 5000,
  })

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Laden...</p>
      </div>
    )
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

  const getStatusIcon = (status: string) => {
    switch (status.toUpperCase()) {
      case 'SUCCESS':
        return <MdCheckCircle className="status-icon success" />
      case 'FAILED':
        return <MdCancel className="status-icon error" />
      case 'RUNNING':
        return <MdPlayArrow className="status-icon running" />
      case 'PENDING':
        return <MdHourglassEmpty className="status-icon pending" />
      case 'WARNING':
        return <MdWarning className="status-icon warning" />
      case 'INTERRUPTED':
        return <MdStop className="status-icon interrupted" />
      default:
        return null
    }
  }

  return (
    <div className="runs">
      <div className="runs-filters card">
        <div className="filter-group">
          <label htmlFor="pipeline-filter" className="form-label">Pipeline:</label>
          <select
            id="pipeline-filter"
            value={pipelineFilter}
            onChange={(e) => setPipelineFilter(e.target.value)}
            className="form-input"
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
          <label htmlFor="status-filter" className="form-label">Status:</label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="form-input"
          >
            <option value="">Alle</option>
            <option value="PENDING">Pending</option>
            <option value="RUNNING">Running</option>
            <option value="SUCCESS">Success</option>
            <option value="FAILED">Failed</option>
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="sort-order" className="form-label">Sortierung:</label>
          <select
            id="sort-order"
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value as 'asc' | 'desc')}
            className="form-input"
          >
            <option value="desc">Neueste zuerst</option>
            <option value="asc">Älteste zuerst</option>
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="start-date" className="form-label">Von:</label>
          <input
            id="start-date"
            type="datetime-local"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="form-input"
          />
        </div>

        <div className="filter-group">
          <label htmlFor="end-date" className="form-label">Bis:</label>
          <input
            id="end-date"
            type="datetime-local"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="form-input"
          />
        </div>
      </div>

      {filteredAndSortedRuns.length > 0 ? (
        <div className="runs-table-container card">
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
                  <td className="run-id">{run.id.substring(0, 8)}...</td>
                  <td>{run.pipeline_name}</td>
                  <td>
                    <div className="status-cell">
                      {getStatusIcon(run.status)}
                      <span className={`status-badge status-${run.status.toLowerCase()}`}>
                        {run.status}
                      </span>
                    </div>
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
                    <Link to={`/runs/${run.id}`} className="btn btn-outlined btn-sm details-link">
                      <MdInfo />
                      Details
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-state card">
          <p>Keine Runs gefunden</p>
        </div>
      )}
    </div>
  )
}
