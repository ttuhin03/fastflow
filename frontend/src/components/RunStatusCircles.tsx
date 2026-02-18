import { useQuery } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { getFormatLocale } from '../utils/locale'
import {
  MdCheckCircle,
  MdCancel,
  MdWarning,
  MdStop,
  MdPlayArrow,
  MdHourglassEmpty,
} from 'react-icons/md'
import './RunStatusCircles.css'

interface Run {
  id: string
  status: string
  started_at: string
  finished_at: string | null
}

interface RunStatusCirclesProps {
  pipelineName: string
}

export default function RunStatusCircles({ pipelineName }: RunStatusCirclesProps) {
  const runsInterval = useRefetchInterval(5000)
  const { data: runs, isLoading } = useQuery<Run[]>({
    queryKey: ['pipeline-runs', pipelineName],
    queryFn: async () => {
      const response = await apiClient.get(`/pipelines/${pipelineName}/runs?limit=5`)
      return response.data
    },
    refetchInterval: runsInterval,
  })

  const getStatusIcon = (status: string) => {
    switch (status.toUpperCase()) {
      case 'SUCCESS':
        return <MdCheckCircle className="run-status-icon" />
      case 'FAILED':
        return <MdCancel className="run-status-icon" />
      case 'WARNING':
        return <MdWarning className="run-status-icon" />
      case 'INTERRUPTED':
        return <MdStop className="run-status-icon" />
      case 'RUNNING':
        return <MdPlayArrow className="run-status-icon" />
      case 'PENDING':
        return <MdHourglassEmpty className="run-status-icon" />
      default:
        return null
    }
  }

  const getStatusClass = (status: string) => {
    switch (status.toUpperCase()) {
      case 'SUCCESS':
        return 'status-success'
      case 'FAILED':
        return 'status-failed'
      case 'WARNING':
        return 'status-warning'
      case 'INTERRUPTED':
        return 'status-interrupted'
      case 'RUNNING':
        return 'status-running'
      case 'PENDING':
        return 'status-pending'
      default:
        return 'status-unknown'
    }
  }

  const getTooltipText = (run: Run | null) => {
    if (!run) return 'Kein Run'
    const date = new Date(run.started_at).toLocaleString(getFormatLocale())
    const duration = run.finished_at
      ? `${Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000)}s`
      : 'Läuft...'
    return `${run.status} - ${date} (${duration})`
  }

  // Erstelle Array mit 5 Einträgen (füllt mit null wenn weniger Runs vorhanden)
  const displayRuns = Array.from({ length: 5 }, (_, i) => runs?.[i] || null)

  return (
    <div className="run-status-circles">
      {displayRuns.map((run, index) => (
        <div
          key={run?.id || `empty-${index}`}
          className={`run-status-circle ${run ? getStatusClass(run.status) : 'status-empty'}`}
          title={getTooltipText(run)}
        >
          {isLoading ? (
            <div className="run-status-skeleton" />
          ) : run ? (
            getStatusIcon(run.status)
          ) : null}
        </div>
      ))}
    </div>
  )
}
