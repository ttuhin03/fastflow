import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { getFormatLocale } from '../utils/locale'
import { MdInfo, MdCheckCircle, MdCancel, MdHourglassEmpty, MdPlayArrow, MdWarning, MdStop } from 'react-icons/md'
import Tooltip from '../components/Tooltip'
import InfoIcon from '../components/InfoIcon'
import './Runs.css'

interface Run {
  id: string
  pipeline_name: string
  status: string
  started_at: string
  finished_at: string | null
  exit_code: number | null
  error_type?: string | null  // "pipeline_error" oder "infrastructure_error"
  error_message?: string | null
  git_sha?: string | null
  git_branch?: string | null
}

interface RunsResponse {
  runs: Run[]
  total: number
  page: number
  page_size: number
}

export default function Runs() {
  const { t } = useTranslation()
  const [pipelineFilter, setPipelineFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [startDate, setStartDate] = useState<string>('')
  const [endDate, setEndDate] = useState<string>('')
  const [page, setPage] = useState<number>(1)
  const [pageSize, setPageSize] = useState<number>(50)

  const { data: pipelines } = useQuery({
    queryKey: ['pipelines'],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines')
      return response.data
    },
  })

  const queryClient = useQueryClient()
  const runsInterval = useRefetchInterval(5000)
  const { data: runsData, isLoading } = useQuery<RunsResponse>({
    queryKey: ['runs', pipelineFilter, statusFilter, startDate, endDate, page, pageSize],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (pipelineFilter) params.append('pipeline_name', pipelineFilter)
      if (statusFilter) params.append('status_filter', statusFilter)
      if (startDate) params.append('start_date', startDate)
      if (endDate) params.append('end_date', endDate)
      const offset = (page - 1) * pageSize
      params.append('offset', offset.toString())
      params.append('limit', pageSize.toString())
      const response = await apiClient.get(`/runs?${params.toString()}`)
      return response.data
    },
    refetchInterval: runsInterval,
  })

  const runs = runsData?.runs || []

  // Reset to page 1 when filters change
  useEffect(() => {
    setPage(1)
  }, [pipelineFilter, statusFilter, startDate, endDate])

  // Invalidate daily-stats when runs complete
  const prevRunsRef = useRef<Run[]>([])
  useEffect(() => {
    if (runs && runs.length > 0) {
      const prevRuns = prevRunsRef.current
      
      // Check if any run changed from RUNNING/PENDING to SUCCESS/FAILED
      const completedRuns = runs.filter(run => {
        const prevRun = prevRuns.find(pr => pr.id === run.id)
        if (!prevRun) return false
        return (prevRun.status === 'RUNNING' || prevRun.status === 'PENDING') &&
               (run.status === 'SUCCESS' || run.status === 'FAILED')
      })
      
      if (completedRuns.length > 0) {
        const pipelineNames = new Set(completedRuns.map(r => r.pipeline_name))
        queryClient.invalidateQueries({ queryKey: ['all-pipelines-daily-stats'] })
        queryClient.invalidateQueries({ queryKey: ['pipeline-daily-stats'] })
        pipelineNames.forEach(name => {
          queryClient.invalidateQueries({ queryKey: ['pipeline-daily-stats', name] })
          queryClient.invalidateQueries({ queryKey: ['pipeline-stats', name] })
        })
        queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      }
      
      prevRunsRef.current = runs
    }
  }, [runs, queryClient])

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>{t('common.loading')}</p>
      </div>
    )
  }

  // Backend already sorts by started_at desc, so we only need to reverse if sortOrder is 'asc'
  const filteredAndSortedRuns = runs
    ? sortOrder === 'asc'
      ? [...runs].reverse()
      : runs
    : []

  const totalPages = runsData ? Math.ceil(runsData.total / pageSize) : 0
  const totalRuns = runsData?.total || 0

  const getDuration = (run: Run) => {
    if (!run.finished_at) return t('runs.runningDuration')
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

  const statusTooltipText = (status: string) => {
    switch (status) {
      case 'SUCCESS':
        return t('runs.statusTooltipSuccess')
      case 'FAILED':
        return t('runs.statusTooltipFailed')
      case 'RUNNING':
        return t('runs.statusTooltipRunning')
      case 'PENDING':
        return t('runs.statusTooltipPending')
      case 'WARNING':
        return t('runs.statusTooltipWarning')
      case 'INTERRUPTED':
        return t('runs.statusTooltipInterrupted')
      default:
        return status
    }
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
          <label htmlFor="pipeline-filter" className="form-label">{t('runs.filterPipeline')}</label>
          <select
            id="pipeline-filter"
            value={pipelineFilter}
            onChange={(e) => setPipelineFilter(e.target.value)}
            className="form-input"
          >
            <option value="">{t('runs.listAll')}</option>
            {pipelines?.map((p: any) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="status-filter" className="form-label">
            {t('runs.filterStatus')}
            <InfoIcon content={t('runs.statusFilterHint')} />
          </label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="form-input"
          >
            <option value="">{t('runs.listAll')}</option>
            <option value="PENDING">Pending</option>
            <option value="RUNNING">Running</option>
            <option value="SUCCESS">Success</option>
            <option value="FAILED">Failed</option>
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="sort-order" className="form-label">{t('runs.sortLabel')}</label>
          <select
            id="sort-order"
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value as 'asc' | 'desc')}
            className="form-input"
          >
            <option value="desc">{t('runs.sortNewest')}</option>
            <option value="asc">{t('runs.sortOldest')}</option>
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="page-size" className="form-label">{t('runs.pageSizeLabel')}</label>
          <select
            id="page-size"
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value))
              setPage(1)
            }}
            className="form-input"
          >
            <option value="25">25</option>
            <option value="50">50</option>
            <option value="100">100</option>
            <option value="200">200</option>
          </select>
        </div>

        <div className="filter-group">
          <label htmlFor="start-date" className="form-label">{t('runs.dateFrom')}</label>
          <input
            id="start-date"
            type="datetime-local"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="form-input"
          />
        </div>

        <div className="filter-group">
          <label htmlFor="end-date" className="form-label">{t('runs.dateTo')}</label>
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
        <>
          {/* Desktop Table View */}
          <div className="runs-table-container card desktop-only">
            <table className="runs-table">
              <thead>
                <tr>
                  <th>{t('runs.thId')}</th>
                  <th>{t('runs.thPipeline')}</th>
                  <th>{t('runs.thCommit')}</th>
                  <th>{t('runs.thStatus')}</th>
                  <th>{t('runs.thStarted')}</th>
                  <th>{t('runs.thDuration')}</th>
                  <th>{t('runs.thExitCode')}</th>
                  <th>{t('runs.thActions')}</th>
                </tr>
              </thead>
              <tbody>
                {filteredAndSortedRuns.map((run, index) => (
                  <tr key={run.id} style={{ animationDelay: `${index * 0.03}s` }}>
                    <td className="run-id">{run.id.substring(0, 8)}...</td>
                    <td>{run.pipeline_name}</td>
                    <td className="run-commit">
                      {run.git_sha ? (
                        <Tooltip content={`${run.git_sha}${run.git_branch ? ` (${run.git_branch})` : ''}`}>
                          <span className="commit-sha">{run.git_sha.slice(0, 7)}</span>
                        </Tooltip>
                      ) : (
                        '-'
                      )}
                    </td>
                    <td>
                      <Tooltip content={statusTooltipText(run.status)}>
                        <div className="status-cell">
                          {getStatusIcon(run.status)}
                          <span className={`status-badge status-${run.status.toLowerCase()}`}>
                            {run.status}
                          </span>
                          {run.error_type && (
                            <span className={`error-type-badge error-type-${run.error_type}`}>
                              {run.error_type === 'pipeline_error' ? t('runs.errorTypePipeline') : t('runs.errorTypeInfrastructure')}
                            </span>
                          )}
                        </div>
                      </Tooltip>
                    </td>
                    <td>{new Date(run.started_at).toLocaleString(getFormatLocale())}</td>
                    <td>
                      <Tooltip content={t('runs.durationTooltip')}>
                        {getDuration(run)}
                      </Tooltip>
                    </td>
                    <td>
                      {run.exit_code !== null ? (
                        <Tooltip content={t('runs.exitCodeTooltip')}>
                          <span className={run.exit_code === 0 ? 'exit-success' : 'exit-error'}>
                            {run.exit_code}
                          </span>
                        </Tooltip>
                      ) : (
                        '-'
                      )}
                    </td>
                    <td>
                      <Link to={`/runs/${run.id}`} className="btn btn-outlined btn-sm details-link">
                        <MdInfo />
                        {t('runs.details')}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile Card View */}
          <div className="runs-cards-container mobile-only">
            {filteredAndSortedRuns.map((run, index) => (
              <div key={run.id} className="run-card card" style={{ animationDelay: `${index * 0.04}s` }}>
                <div className="run-card-header">
                  <div className="run-card-id">
                    {getStatusIcon(run.status)}
                    <span className="run-card-id-text">{run.id.substring(0, 8)}...</span>
                  </div>
                  <span className={`status-badge status-${run.status.toLowerCase()}`}>
                    {run.status}
                  </span>
                  {run.error_type && (
                    <span className={`error-type-badge error-type-${run.error_type}`}>
                      {run.error_type === 'pipeline_error' ? t('runs.errorTypePipeline') : t('runs.errorTypeInfrastructure')}
                    </span>
                  )}
                </div>
                <div className="run-card-body">
                  <div className="run-card-row">
                    <span className="run-card-label">{t('runs.cardPipeline')}</span>
                    <span className="run-card-value">{run.pipeline_name}</span>
                  </div>
                  {run.git_sha && (
                    <div className="run-card-row">
                      <span className="run-card-label">{t('runs.cardCommit')}</span>
                      <Tooltip content={`${run.git_sha}${run.git_branch ? ` (${run.git_branch})` : ''}`}>
                        <span className="run-card-value commit-sha">{run.git_sha.slice(0, 7)}</span>
                      </Tooltip>
                    </div>
                  )}
                  <div className="run-card-row">
                    <span className="run-card-label">{t('runs.cardStarted')}</span>
                    <span className="run-card-value">{new Date(run.started_at).toLocaleString(getFormatLocale())}</span>
                  </div>
                  <div className="run-card-row">
                    <span className="run-card-label">{t('runs.cardDuration')}</span>
                    <Tooltip content={t('runs.durationTooltip')}>
                      <span className="run-card-value">{getDuration(run)}</span>
                    </Tooltip>
                  </div>
                  {run.exit_code !== null && (
                    <div className="run-card-row">
                      <span className="run-card-label">{t('runs.cardExitCode')}</span>
                      <Tooltip content={t('runs.exitCodeTooltip')}>
                        <span className={`run-card-value ${run.exit_code === 0 ? 'exit-success' : 'exit-error'}`}>
                          {run.exit_code}
                        </span>
                      </Tooltip>
                    </div>
                  )}
                </div>
                <div className="run-card-footer">
                  <Link to={`/runs/${run.id}`} className="btn btn-outlined btn-sm details-link">
                    <MdInfo />
                    {t('runs.details')}
                  </Link>
                </div>
              </div>
            ))}
          </div>
          
          {totalPages > 1 && (
            <div className="pagination-container card">
              <div className="pagination-info">
                {t('runs.paginationShowing', {
                  from: (page - 1) * pageSize + 1,
                  to: Math.min(page * pageSize, totalRuns),
                  total: totalRuns,
                })}
              </div>
              <div className="pagination-controls">
                <button
                  className="pagination-btn"
                  onClick={() => setPage(1)}
                  disabled={page === 1}
                >
                  {t('runs.paginationFirst')}
                </button>
                <button
                  className="pagination-btn"
                  onClick={() => setPage(page - 1)}
                  disabled={page === 1}
                >
                  {t('runs.paginationBack')}
                </button>
                <span className="pagination-page-info">
                  {t('runs.paginationPage', { page, total: totalPages })}
                </span>
                <button
                  className="pagination-btn"
                  onClick={() => setPage(page + 1)}
                  disabled={page >= totalPages}
                >
                  {t('runs.paginationNext')}
                </button>
                <button
                  className="pagination-btn"
                  onClick={() => setPage(totalPages)}
                  disabled={page >= totalPages}
                >
                  {t('runs.paginationLast')}
                </button>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="empty-state card">
          <p>{t('runs.emptyList')}</p>
        </div>
      )}
    </div>
  )
}
