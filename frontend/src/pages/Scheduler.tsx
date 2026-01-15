import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import './Scheduler.css'

interface Job {
  id: string
  pipeline_name: string
  trigger_type: 'CRON' | 'INTERVAL'
  trigger_value: string
  enabled: boolean
  created_at: string
  next_run_time?: string | null
  last_run_time?: string | null
  run_count?: number
}

export default function Scheduler() {
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const [isAdding, setIsAdding] = useState(false)
  const [editingJob, setEditingJob] = useState<Job | null>(null)
  const [expandedJob, setExpandedJob] = useState<string | null>(null)
  const [formPipeline, setFormPipeline] = useState('')
  const [formTriggerType, setFormTriggerType] = useState<'CRON' | 'INTERVAL'>('CRON')
  const [formTriggerValue, setFormTriggerValue] = useState('')
  const [formEnabled, setFormEnabled] = useState(true)

  const { data: jobs, isLoading: jobsLoading } = useQuery<Job[]>({
    queryKey: ['scheduler-jobs'],
    queryFn: async () => {
      const response = await apiClient.get('/scheduler/jobs')
      return response.data
    },
  })

  const { data: pipelines } = useQuery({
    queryKey: ['pipelines'],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines')
      return response.data
    },
  })

  const createMutation = useMutation({
    mutationFn: async (data: {
      pipeline_name: string
      trigger_type: 'CRON' | 'INTERVAL'
      trigger_value: string
      enabled: boolean
    }) => {
      const response = await apiClient.post('/scheduler/jobs', data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduler-jobs'] })
      setIsAdding(false)
      resetForm()
      showSuccess('Job erfolgreich erstellt')
    },
    onError: (error: any) => {
      showError(`Fehler beim Erstellen: ${error.response?.data?.detail || error.message}`)
    },
  })

  const updateMutation = useMutation({
    mutationFn: async ({
      jobId,
      data,
    }: {
      jobId: string
      data: {
        pipeline_name?: string
        trigger_type?: 'CRON' | 'INTERVAL'
        trigger_value?: string
        enabled?: boolean
      }
    }) => {
      const response = await apiClient.put(`/scheduler/jobs/${jobId}`, data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduler-jobs'] })
      setEditingJob(null)
      resetForm()
      showSuccess('Job erfolgreich aktualisiert')
    },
    onError: (error: any) => {
      showError(`Fehler beim Aktualisieren: ${error.response?.data?.detail || error.message}`)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (jobId: string) => {
      await apiClient.delete(`/scheduler/jobs/${jobId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduler-jobs'] })
      showSuccess('Job erfolgreich gelöscht')
    },
    onError: (error: any) => {
      showError(`Fehler beim Löschen: ${error.response?.data?.detail || error.message}`)
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
      showError(`Fehler beim Umschalten: ${error.response?.data?.detail || error.message}`)
    },
  })

  const resetForm = () => {
    setFormPipeline('')
    setFormTriggerType('CRON')
    setFormTriggerValue('')
    setFormEnabled(true)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formPipeline || !formTriggerValue) {
      showError('Bitte füllen Sie alle Felder aus')
      return
    }

    if (editingJob) {
      updateMutation.mutate({
        jobId: editingJob.id,
        data: {
          pipeline_name: formPipeline,
          trigger_type: formTriggerType,
          trigger_value: formTriggerValue,
          enabled: formEnabled,
        },
      })
    } else {
      createMutation.mutate({
        pipeline_name: formPipeline,
        trigger_type: formTriggerType,
        trigger_value: formTriggerValue,
        enabled: formEnabled,
      })
    }
  }

  const handleEdit = (job: Job) => {
    setEditingJob(job)
    setFormPipeline(job.pipeline_name)
    setFormTriggerType(job.trigger_type)
    setFormTriggerValue(job.trigger_value)
    setFormEnabled(job.enabled)
    setIsAdding(true)
  }

  const handleDelete = async (jobId: string, pipelineName: string) => {
    const confirmed = await showConfirm(`Möchten Sie den Job für '${pipelineName}' wirklich löschen?`)
    if (confirmed) {
      deleteMutation.mutate(jobId)
    }
  }

  const handleToggleEnabled = (job: Job) => {
    toggleEnabledMutation.mutate({ jobId: job.id, enabled: !job.enabled })
  }

  if (jobsLoading) {
    return <div>Laden...</div>
  }

  return (
    <div className="scheduler">
      <div className="scheduler-header">
        <h2>Scheduler</h2>
        {!isReadonly && (
          <button
            onClick={() => {
              setIsAdding(true)
              setEditingJob(null)
              resetForm()
            }}
            className="add-button"
          >
            + Neuer Job
          </button>
        )}
      </div>

      {isAdding && (
        <div className="job-form">
          <h3>{editingJob ? 'Job bearbeiten' : 'Neuer Job'}</h3>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="job-pipeline">Pipeline:</label>
              <select
                id="job-pipeline"
                value={formPipeline}
                onChange={(e) => setFormPipeline(e.target.value)}
                required
              >
                <option value="">-- Pipeline auswählen --</option>
                {pipelines?.map((p: any) => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="job-trigger-type">Trigger-Typ:</label>
              <select
                id="job-trigger-type"
                value={formTriggerType}
                onChange={(e) => setFormTriggerType(e.target.value as 'CRON' | 'INTERVAL')}
                required
              >
                <option value="CRON">CRON</option>
                <option value="INTERVAL">INTERVAL</option>
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="job-trigger-value">
                {formTriggerType === 'CRON'
                  ? 'Cron-Expression (z.B. "0 0 * * *"):'
                  : 'Interval in Sekunden (z.B. "3600"):'}
              </label>
              <input
                id="job-trigger-value"
                type="text"
                value={formTriggerValue}
                onChange={(e) => setFormTriggerValue(e.target.value)}
                placeholder={formTriggerType === 'CRON' ? '0 0 * * *' : '3600'}
                required
              />
            </div>
            <div className="form-group">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={formEnabled}
                  onChange={(e) => setFormEnabled(e.target.checked)}
                />
                Aktiviert
              </label>
            </div>
            <div className="form-actions">
              <button type="submit" className="submit-button">
                {editingJob ? 'Aktualisieren' : 'Erstellen'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setIsAdding(false)
                  setEditingJob(null)
                  resetForm()
                }}
                className="cancel-button"
              >
                Abbrechen
              </button>
            </div>
          </form>
        </div>
      )}

      {jobs && jobs.length > 0 ? (
        <table className="jobs-table">
          <thead>
            <tr>
              <th>Pipeline</th>
              <th>Trigger-Typ</th>
              <th>Trigger-Wert</th>
              <th>Status</th>
              <th>Nächste Ausführung</th>
              <th>Letzte Ausführung</th>
              <th>Runs</th>
              <th>Erstellt</th>
              <th>Aktionen</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <>
                <tr key={job.id}>
                  <td>{job.pipeline_name}</td>
                  <td>{job.trigger_type}</td>
                  <td>
                    <code className="trigger-value">{job.trigger_value}</code>
                  </td>
                  <td>
                    {!isReadonly && (
                      <button
                        onClick={() => handleToggleEnabled(job)}
                        className={`status-toggle ${job.enabled ? 'enabled' : 'disabled'}`}
                        disabled={toggleEnabledMutation.isPending}
                      >
                        {job.enabled ? 'Aktiv' : 'Inaktiv'}
                      </button>
                    )}
                    {isReadonly && (
                      <span className={`status-badge ${job.enabled ? 'enabled' : 'disabled'}`}>
                        {job.enabled ? 'Aktiv' : 'Inaktiv'}
                      </span>
                    )}
                  </td>
                  <td>
                    {job.next_run_time ? (
                      new Date(job.next_run_time).toLocaleString('de-DE')
                    ) : (
                      <span className="no-data">-</span>
                    )}
                  </td>
                  <td>
                    {job.last_run_time ? (
                      new Date(job.last_run_time).toLocaleString('de-DE')
                    ) : (
                      <span className="no-data">-</span>
                    )}
                  </td>
                  <td>
                    <span className="run-count">{job.run_count || 0}</span>
                  </td>
                  <td>{new Date(job.created_at).toLocaleString('de-DE')}</td>
                  <td>
                    <div className="action-buttons">
                      <button
                        onClick={() => setExpandedJob(expandedJob === job.id ? null : job.id)}
                        className="details-button"
                      >
                        {expandedJob === job.id ? 'Details ▲' : 'Details ▼'}
                      </button>
                      {!isReadonly && (
                        <>
                          <button
                            onClick={() => handleEdit(job)}
                            className="edit-button"
                          >
                            Bearbeiten
                          </button>
                          <button
                            onClick={() => handleDelete(job.id, job.pipeline_name)}
                            className="delete-button"
                          >
                            Löschen
                          </button>
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
        <p className="no-jobs">Keine Jobs gefunden</p>
      )}
    </div>
  )
}

function JobDetails({ jobId }: { jobId: string }) {
  const { data: runs, isLoading } = useQuery({
    queryKey: ['job-runs', jobId],
    queryFn: async () => {
      const response = await apiClient.get(`/scheduler/jobs/${jobId}/runs?limit=10`)
      return response.data
    },
  })

  if (isLoading) {
    return <div>Lade Historie...</div>
  }

  return (
    <div className="job-details">
      <h4>Letzte Runs</h4>
      {runs && runs.length > 0 ? (
        <table className="job-runs-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Status</th>
              <th>Gestartet</th>
              <th>Beendet</th>
              <th>Exit Code</th>
              <th>Aktionen</th>
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
                <td>{new Date(run.started_at).toLocaleString('de-DE')}</td>
                <td>
                  {run.finished_at
                    ? new Date(run.finished_at).toLocaleString('de-DE')
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
                    Details
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
