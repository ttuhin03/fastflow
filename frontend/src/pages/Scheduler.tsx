import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError } from '../utils/toast'
import { getFormatLocale } from '../utils/locale'
import Tooltip from '../components/Tooltip'
import './Scheduler.css'

interface Job {
  id: string
  pipeline_name: string
  trigger_type: 'CRON' | 'INTERVAL' | 'DATE'
  trigger_value: string
  enabled: boolean
  created_at: string
  next_run_time?: string | null
  last_run_time?: string | null
  run_count?: number
  run_config_id?: string | null
  pipeline_json_edit_url?: string | null
}

export default function Scheduler() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const [expandedJob, setExpandedJob] = useState<string | null>(null)
  const formatLocale = getFormatLocale()

  const { data: jobs, isLoading: jobsLoading } = useQuery<Job[]>({
    queryKey: ['scheduler-jobs'],
    queryFn: async () => {
      const response = await apiClient.get('/scheduler/jobs')
      return response.data
    },
  })

  const toggleEnabledMutation = useMutation({
    mutationFn: async ({ jobId, enabled }: { jobId: string; enabled: boolean }) => {
      const response = await apiClient.put(`/scheduler/jobs/${jobId}`, { enabled })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduler-jobs'] })
    },
    onError: (error: any) => {
      showError(t('scheduler.toggleError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const handleEdit = (job: Job) => {
    const url = job.pipeline_json_edit_url
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer')
    } else {
      showError(t('scheduler.editError'))
    }
  }

  const handleToggleEnabled = (job: Job) => {
    toggleEnabledMutation.mutate({ jobId: job.id, enabled: !job.enabled })
  }

  if (jobsLoading) {
    return <div>{t('common.loading')}</div>
  }

  return (
    <div className="scheduler">
      <div className="scheduler-header">
        <h2>{t('scheduler.title')}</h2>
      </div>

      {jobs && jobs.length > 0 ? (
        <table className="jobs-table">
          <thead>
            <tr>
              <th>{t('scheduler.pipeline')}</th>
              <th>{t('scheduler.triggerType')}</th>
              <th>{t('scheduler.triggerValue')}</th>
              <th>{t('scheduler.status')}</th>
              <th>{t('scheduler.nextRun')}</th>
              <th>{t('scheduler.lastRun')}</th>
              <th>{t('common.runs')}</th>
              <th>{t('scheduler.created')}</th>
              <th>{t('scheduler.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <>
                <tr key={job.id}>
                  <td>
                    {job.pipeline_name}
                    {job.run_config_id && (
                      <span className="run-config-badge" title={t('scheduler.runConfigTooltip')}>
                        {job.run_config_id}
                      </span>
                    )}
                  </td>
                  <td>{job.trigger_type}</td>
                  <td>
                    <Tooltip content={job.trigger_type === 'CRON'
                      ? "Format: min hour day month weekday (z.B. '0 0 * * *' = täglich um Mitternacht)"
                      : job.trigger_type === 'DATE'
                      ? 'Einmalige Ausführung zu diesem Zeitpunkt'
                      : `Intervall: alle ${job.trigger_value} Sekunden`}>
                      <code className="trigger-value">
                        {job.trigger_type === 'DATE' && job.trigger_value
                          ? new Date(job.trigger_value).toLocaleString(formatLocale)
                          : job.trigger_value}
                      </code>
                    </Tooltip>
                  </td>
                  <td>
                    {!isReadonly && (
                      <Tooltip content="Klicken, um Job zu aktivieren/deaktivieren">
                        <button
                          onClick={() => handleToggleEnabled(job)}
                          className={`status-toggle ${job.enabled ? 'enabled' : 'disabled'}`}
                          disabled={toggleEnabledMutation.isPending}
                        >
                          {job.enabled ? t('scheduler.enabled') : t('scheduler.disabled')}
                        </button>
                      </Tooltip>
                    )}
                    {isReadonly && (
                      <span className={`status-badge ${job.enabled ? 'enabled' : 'disabled'}`}>
                        {job.enabled ? t('scheduler.enabled') : t('scheduler.disabled')}
                      </span>
                    )}
                  </td>
                  <td>
                    <Tooltip content="Wird basierend auf der CRON/INTERVAL Expression berechnet">
                      {job.next_run_time ? (
                        new Date(job.next_run_time).toLocaleString(formatLocale)
                      ) : (
                        <span className="no-data">-</span>
                      )}
                    </Tooltip>
                  </td>
                  <td>
                    <Tooltip content="Zeitpunkt des letzten erfolgreichen oder fehlgeschlagenen Runs">
                      {job.last_run_time ? (
                        new Date(job.last_run_time).toLocaleString(formatLocale)
                      ) : (
                        <span className="no-data">-</span>
                      )}
                    </Tooltip>
                  </td>
                  <td>
                    <Tooltip content="Anzahl der bisher ausgeführten Jobs">
                      <span className="run-count">{job.run_count || 0}</span>
                    </Tooltip>
                  </td>
                  <td>{new Date(job.created_at).toLocaleString(formatLocale)}</td>
                  <td>
                    <div className="action-buttons">
                      <Tooltip content="Zeige letzte 10 Runs dieses Jobs">
                        <button
                          onClick={() => setExpandedJob(expandedJob === job.id ? null : job.id)}
                          className="details-button"
                        >
                          {expandedJob === job.id ? 'Details ▲' : 'Details ▼'}
                        </button>
                      </Tooltip>
                      {!isReadonly && (
                        <>
                          <Tooltip content={job.pipeline_json_edit_url
                            ? "pipeline.json auf GitHub bearbeiten (Schedules dort anlegen/entfernen)"
                            : "GitHub-Repository nicht konfiguriert"}>
                            <button
                              onClick={() => handleEdit(job)}
                              className="edit-button"
                              disabled={!job.pipeline_json_edit_url}
                            >
                              {t('scheduler.edit')}
                            </button>
                          </Tooltip>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
                {expandedJob === job.id && (
                  <tr className="job-details-row">
                    <td colSpan={9}>
                      <JobDetails jobId={job.id} />
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="no-jobs">{t('schedulerExtra.noJobsFound')}</p>
      )}
    </div>
  )
}

function JobDetails({ jobId }: { jobId: string }) {
  const { t } = useTranslation()
  const { data: runs, isLoading } = useQuery({
    queryKey: ['job-runs', jobId],
    queryFn: async () => {
      const response = await apiClient.get(`/scheduler/jobs/${jobId}/runs?limit=10`)
      return response.data
    },
  })

  if (isLoading) {
    return <div>{t('schedulerExtra.loadHistory')}</div>
  }

  return (
    <div className="job-details">
      <h4>{t('schedulerExtra.lastRuns')}</h4>
      {runs && runs.length > 0 ? (
        <table className="job-runs-table">
          <thead>
            <tr>
              <th>{t('schedulerExtra.id')}</th>
              <th>{t('scheduler.status')}</th>
              <th>{t('schedulerExtra.started')}</th>
              <th>{t('schedulerExtra.finished')}</th>
              <th>{t('schedulerExtra.exitCode')}</th>
              <th>{t('scheduler.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run: any) => (
              <tr key={run.id}>
                <td>{run.id.substring(0, 8)}...</td>
                <td>
                  <span className={`status status-${run.status.toLowerCase()}`}>
                    {run.status}
                  </span>
                </td>
                <td>{new Date(run.started_at).toLocaleString(getFormatLocale())}</td>
                <td>
                  {run.finished_at
                    ? new Date(run.finished_at).toLocaleString(getFormatLocale())
                    : '-'}
                </td>
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
                  <Link to={`/runs/${run.id}`} className="view-link">
                    {t('schedulerExtra.details')}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>Keine Runs für diesen Job</p>
      )}
    </div>
  )
}
