import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { getFormatLocale } from '../utils/locale'
import {
  LuCircleCheck,
  LuCircleX,
  LuTriangleAlert,
  LuOctagonX,
  LuPlay,
  LuTimer,
} from 'react-icons/lu'
import './RunStatusCircles.css'

interface Run {
  id: string
  status: string
  started_at: string
  finished_at: string | null
}

interface RunStatusCirclesProps {
  pipelineName: string
  /** 'circles' = legacy round icons; 'strip' = dense colored last-N bar (dashboard cards) */
  variant?: 'circles' | 'strip'
  /** How many cells to render (strip uses up to 10 — backend limit) */
  count?: number
}

function useRecentRunsPerPipeline(pipelineName: string) {
  const runsInterval = useRefetchInterval(5000)
  return useQuery<Run[]>({
    queryKey: ['recent-runs-per-pipeline'],
    queryFn: async () => {
      // Backend erlaubt maximal 10 Runs pro Pipeline (le=10)
      const response = await apiClient.get('/runs/recent-per-pipeline?limit_per_pipeline=10')
      return response.data
    },
    refetchInterval: runsInterval,
    select: (data: any) => (data?.pipelines?.[pipelineName] ?? []) as Run[],
  })
}

function getStatusClass(status: string) {
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

export default function RunStatusCircles({ pipelineName, variant = 'circles', count }: RunStatusCirclesProps) {
  const { t } = useTranslation()
  const { data: runs, isLoading } = useRecentRunsPerPipeline(pipelineName)

  const getStatusIcon = (status: string) => {
    switch (status.toUpperCase()) {
      case 'SUCCESS':
        return <LuCircleCheck className="run-status-icon" />
      case 'FAILED':
        return <LuCircleX className="run-status-icon" />
      case 'WARNING':
        return <LuTriangleAlert className="run-status-icon" />
      case 'INTERRUPTED':
        return <LuOctagonX className="run-status-icon" />
      case 'RUNNING':
        return <LuPlay className="run-status-icon" />
      case 'PENDING':
        return <LuTimer className="run-status-icon" />
      default:
        return null
    }
  }

  const getTooltipText = (run: Run | null) => {
    if (!run) return t('runStatusCircles.noRun', 'No run')
    const date = new Date(run.started_at).toLocaleString(getFormatLocale())
    const duration = run.finished_at
      ? `${Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000)}s`
      : t('runStatusCircles.running', 'Running…')
    return `${run.status} - ${date} (${duration})`
  }

  // Strip variant: dense last-N colored cells (oldest → newest, left → right)
  if (variant === 'strip') {
    const total = count ?? 10
    const recent = (runs ?? []).slice(0, total).reverse()
    const cells = Array.from({ length: total }, (_, i) => {
      const offset = total - recent.length
      return i >= offset ? recent[i - offset] : null
    })
    return (
      <div className="run-strip">
        {cells.map((run, index) => (
          <span
            key={run?.id || `empty-${index}`}
            className={`run-strip__cell ${run ? getStatusClass(run.status) : 'status-empty'}`}
            title={getTooltipText(run)}
          />
        ))}
      </div>
    )
  }

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
