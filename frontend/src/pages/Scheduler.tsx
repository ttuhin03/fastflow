import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { LuClock, LuPlus, LuChevronDown, LuChevronUp, LuExternalLink } from 'react-icons/lu'
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

  // TODO(redesign): needs backend — there is no create-schedule endpoint yet.
  // Schedules are defined in pipeline.json on the repo, so "New schedule"
  // points users at editing that file rather than calling an API.
  const handleNewSchedule = () => {
    const firstWithUrl = jobs?.find((j) => j.pipeline_json_edit_url)
    if (firstWithUrl?.pipeline_json_edit_url) {
      window.open(firstWithUrl.pipeline_json_edit_url, '_blank', 'noopener,noreferrer')
    } else {
      showError(t('scheduler.editError'))
    }
  }

  if (jobsLoading) {
    return <div>{t('common.loading')}</div>
  }

  const jobList = jobs ?? []
  // Schedules live in pipeline.json on the repo, so "New schedule" links out to
  // GitHub. We can only do that if at least one job exposes an edit URL.
  const newScheduleUrl = jobList.find((j) => j.pipeline_json_edit_url)?.pipeline_json_edit_url ?? null
  const activeCount = jobList.filter((j) => j.enabled).length
  const pausedCount = jobList.length - activeCount

  // Group schedules by pipeline so multiple triggers for the same pipeline
  // render with a "↳" indent under the first one (per mockup).
  const seenPipeline = new Set<string>()

  const formatNext = (job: Job): string => {
    if (!job.next_run_time) return '—'
    return new Date(job.next_run_time).toLocaleString(formatLocale)
  }

  return (
    <div className="scheduler">
      <div className="scheduler-header">
        <div>
          <h1 className="scheduler-title">{t('scheduler.title')}</h1>
          <p className="scheduler-subtitle">
            {t('scheduler.subtitlePrefix', 'Cron-based triggers')}
            {' · '}
            <span className="scheduler-subtitle-strong">
              {t('scheduler.activeCount', '{{count}} active', { count: activeCount })}
            </span>
            {' · '}
            {t('scheduler.pausedCount', '{{count}} paused', { count: pausedCount })}
          </p>
        </div>
        {!isReadonly && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleNewSchedule}
            disabled={!newScheduleUrl}
            title={
              newScheduleUrl
                ? t('scheduler.newScheduleHint', 'Schedules are defined in pipeline.json — opens GitHub to add one')
                : t('scheduler.editDisabledHint', 'GitHub repository not configured — edit pipeline.json in your repo')
            }
          >
            <LuPlus aria-hidden />
            {t('scheduler.newScheduleInGithub', 'New schedule in GitHub')}
            <LuExternalLink className="icon-external" aria-hidden />
          </button>
        )}
      </div>

      {jobList.length > 0 ? (
        <div className="table scheduler-table">
          <div className="table__head">
            <span>{t('scheduler.pipeline')}</span>
            <span>{t('scheduler.scheduleName', 'Schedule')}</span>
            <span>{t('scheduler.cron', 'Cron')}</span>
            <span>{t('scheduler.environment', 'Environment')}</span>
            <span>{t('scheduler.nextRun')}</span>
            <span className="scheduler-cell-active">{t('common.active')}</span>
          </div>
          {jobList.map((job) => {
            const isGrouped = seenPipeline.has(job.pipeline_name)
            seenPipeline.add(job.pipeline_name)
            const expanded = expandedJob === job.id
            return (
              <React.Fragment key={job.id}>
                <div className="table__row scheduler-row">
                  <span className="scheduler-cell-pipeline">
                    <LuClock className="scheduler-pipe-icon" aria-hidden />
                    <span className="mono scheduler-pipe-name" title={job.pipeline_name}>
                      {isGrouped && <span className="scheduler-indent" aria-hidden>↳ </span>}
                      {job.pipeline_name}
                    </span>
                  </span>
                  <span className="mono scheduler-cell-name" title={job.run_config_id || job.trigger_type}>
                    {job.run_config_id || job.trigger_type.toLowerCase()}
                  </span>
                  <span className="mono scheduler-cell-cron">
                    <Tooltip content={job.trigger_type === 'CRON'
                      ? "Format: min hour day month weekday (z.B. '0 0 * * *' = täglich um Mitternacht)"
                      : job.trigger_type === 'DATE'
                      ? 'Einmalige Ausführung zu diesem Zeitpunkt'
                      : `Intervall: alle ${job.trigger_value} Sekunden`}>
                      <span>
                        {job.trigger_type === 'DATE' && job.trigger_value
                          ? new Date(job.trigger_value).toLocaleString(formatLocale)
                          : job.trigger_value}
                      </span>
                    </Tooltip>
                  </span>
                  <span className="scheduler-cell-env">
                    {/* TODO(redesign): needs backend — no per-schedule env-override
                        data is returned, so we always show the base environment. */}
                    {job.run_config_id ? (
                      <span className="badge badge-primary">{job.run_config_id}</span>
                    ) : (
                      <span className="badge badge-secondary">{t('scheduler.baseEnv', 'base env')}</span>
                    )}
                  </span>
                  <span className="mono scheduler-cell-next">{formatNext(job)}</span>
                  <span className="scheduler-cell-active scheduler-cell-active--row">
                    {!isReadonly ? (
                      <Tooltip content="Klicken, um Job zu aktivieren/deaktivieren">
                        <label className="toggle">
                          <input
                            type="checkbox"
                            checked={job.enabled}
                            onChange={() => handleToggleEnabled(job)}
                            disabled={toggleEnabledMutation.isPending}
                            aria-label={job.enabled ? t('scheduler.enabled') : t('scheduler.disabled')}
                          />
                          <span className="track" />
                          <span className="knob" />
                        </label>
                      </Tooltip>
                    ) : (
                      <span className={`status-dot ${job.enabled ? 'online' : 'disabled'}`} aria-hidden />
                    )}
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm scheduler-details-btn"
                      onClick={() => setExpandedJob(expanded ? null : job.id)}
                      aria-expanded={expanded}
                      title={t('schedulerExtra.lastRuns')}
                    >
                      {expanded ? <LuChevronUp aria-hidden /> : <LuChevronDown aria-hidden />}
                    </button>
                  </span>
                </div>
                {expanded && (
                  <div className="scheduler-details-row">
                    <div className="scheduler-details-actions">
                      {!isReadonly && (
                        <Tooltip content={job.pipeline_json_edit_url
                          ? t('scheduler.editInGithubHint', 'Edit pipeline.json on GitHub (add/remove schedules there)')
                          : t('scheduler.editDisabledHint', 'GitHub repository not configured — edit pipeline.json in your repo')}>
                          <button
                            type="button"
                            onClick={() => handleEdit(job)}
                            className="btn btn-outlined btn-sm"
                            disabled={!job.pipeline_json_edit_url}
                            title={job.pipeline_json_edit_url
                              ? undefined
                              : t('scheduler.editDisabledHint', 'GitHub repository not configured — edit pipeline.json in your repo')}
                          >
                            {t('scheduler.editInGithub', 'Edit in GitHub')}
                            {job.pipeline_json_edit_url && <LuExternalLink className="icon-external" aria-hidden />}
                          </button>
                        </Tooltip>
                      )}
                      <span className="scheduler-runcount mono">
                        {t('common.runs')}: {job.run_count || 0}
                      </span>
                    </div>
                    <JobDetails jobId={job.id} triggerType={job.trigger_type} />
                  </div>
                )}
              </React.Fragment>
            )
          })}
        </div>
      ) : (
        <p className="no-jobs">{t('schedulerExtra.noJobsFound')}</p>
      )}
    </div>
  )
}

function JobDetails({ jobId, triggerType }: { jobId: string; triggerType: Job['trigger_type'] }) {
  const { t } = useTranslation()
  const formatLocale = getFormatLocale()

  const { data: runs, isLoading: runsLoading } = useQuery({
    queryKey: ['job-runs', jobId],
    queryFn: async () => {
      const response = await apiClient.get(`/scheduler/jobs/${jobId}/runs?limit=10`)
      return response.data
    },
  })

  const { data: nextRunsData, isLoading: nextRunsLoading } = useQuery<{ next_runs: string[] }>({
    queryKey: ['job-next-runs', jobId],
    queryFn: async () => {
      const response = await apiClient.get(`/scheduler/jobs/${jobId}/next-runs?count=5`)
      return response.data
    },
    enabled: triggerType !== 'DATE',
  })

  if (runsLoading) {
    return <div className="no-data">{t('schedulerExtra.loadHistory')}</div>
  }

  return (
    <div className="job-details">
      {triggerType !== 'DATE' && (
        <div className="next-runs-section">
          <h4>{t('schedulerExtra.nextRuns')}</h4>
          {nextRunsLoading ? (
            <p className="no-data">{t('schedulerExtra.loadNextRuns')}</p>
          ) : nextRunsData && nextRunsData.next_runs.length > 0 ? (
            <ol className="next-runs-list">
              {nextRunsData.next_runs.map((ts) => (
                <li key={ts}>
                  <span className="next-run-index-dot" />
                  <span className="mono">{new Date(ts).toLocaleString(formatLocale)}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="no-data">{t('schedulerExtra.noNextRuns')}</p>
          )}
        </div>
      )}

      <h4>{t('schedulerExtra.lastRuns')}</h4>
      {runs && runs.length > 0 ? (
        <div className="table job-runs-table">
          <div className="table__head">
            <span>{t('schedulerExtra.id')}</span>
            <span>{t('scheduler.status')}</span>
            <span>{t('schedulerExtra.started')}</span>
            <span>{t('schedulerExtra.finished')}</span>
            <span>{t('schedulerExtra.exitCode')}</span>
            <span>{t('scheduler.actions')}</span>
          </div>
          {runs.map((run: any) => (
            <div key={run.id} className="table__row job-runs-row">
              <span className="mono">{run.id.substring(0, 8)}…</span>
              <span>
                <span className={`badge badge-${statusBadge(run.status)}`}>{run.status}</span>
              </span>
              <span className="mono">{new Date(run.started_at).toLocaleString(formatLocale)}</span>
              <span className="mono">
                {run.finished_at ? new Date(run.finished_at).toLocaleString(formatLocale) : '—'}
              </span>
              <span className="mono">
                {run.exit_code !== null ? (
                  <span className={run.exit_code === 0 ? 'exit-success' : 'exit-error'}>
                    {run.exit_code}
                  </span>
                ) : (
                  '—'
                )}
              </span>
              <span>
                <Link to={`/runs/${run.id}`} className="view-link">
                  {t('schedulerExtra.details')}
                </Link>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="no-data">{t('schedulerExtra.noRuns')}</p>
      )}
    </div>
  )
}

function statusBadge(status: string): string {
  switch (status?.toLowerCase()) {
    case 'success':
      return 'success'
    case 'failed':
    case 'error':
      return 'error'
    case 'running':
      return 'running'
    default:
      return 'warning'
  }
}
