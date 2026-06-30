import { useState, useEffect, useRef, useLayoutEffect, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { getFormatLocale } from '../utils/locale'
import { showError, showSuccess } from '../utils/toast'
import { LineChart } from '../components/LineChart'
import { RunEnvSection } from '../components/RunEnvSection'
import { LuSearch, LuWrapText, LuArrowDown, LuDownload, LuHash, LuCopy, LuCheck } from 'react-icons/lu'
import '../components/LogViewer.css'
import './RunDetail.css'

interface Run {
  id: string
  pipeline_name: string
  status: string
  started_at: string
  finished_at: string | null
  exit_code: number | null
  uv_version: string | null
  setup_duration: number | null
  env_vars: Record<string, string>
  parameters: Record<string, string>
  log_file: string
  metrics_file: string | null
  error_type?: string | null  // "pipeline_error" oder "infrastructure_error"
  error_message?: string | null
  cell_logs?: CellLog[]
  git_sha?: string | null
  git_branch?: string | null
  git_commit_message?: string | null
}

interface Pipeline {
  name: string
  metadata?: {
    cpu_hard_limit?: number
    mem_hard_limit?: string
    cpu_soft_limit?: number
    mem_soft_limit?: string
    python_version?: string
    description?: string
    tags?: string[]
  }
}

interface Metric {
  timestamp: string
  cpu_percent: number
  ram_mb: number
  ram_limit_mb?: number
  soft_limit_exceeded?: boolean
}

interface CellLog {
  cell_index: number
  status: string
  stdout: string
  stderr: string
  outputs?: { images?: Array<{ mime: string; data: string }> }
}

export default function RunDetail() {
  const { t } = useTranslation()
  const { runId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'info' | 'logs' | 'metrics' | 'env'>('logs')
  const [autoScroll, setAutoScroll] = useState(true)
  const [logSearch, setLogSearch] = useState('')
  const [searchVisible, setSearchVisible] = useState(false)
  const [wrapLogs, setWrapLogs] = useState(false)
  const [showLineNumbers, setShowLineNumbers] = useState(true)
  const [logStream, setLogStream] = useState<'all' | 'stdout' | 'stderr'>('all')
  const logBodyRef = useRef<HTMLDivElement>(null)
  const logsEndRef = useRef<HTMLDivElement>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [metrics, setMetrics] = useState<Metric[]>([])
  const logStreamAbortRef = useRef<AbortController | null>(null)
  const metricsStreamAbortRef = useRef<AbortController | null>(null)
  const [logReconnectAttempts, setLogReconnectAttempts] = useState(0)
  const [metricsReconnectAttempts, setMetricsReconnectAttempts] = useState(0)
  const [logConnectionStatus, setLogConnectionStatus] = useState<'connected' | 'disconnected' | 'reconnecting'>('connected')
  const [metricsConnectionStatus, setMetricsConnectionStatus] = useState<'connected' | 'disconnected' | 'reconnecting'>('connected')
  const [cellExpanded, setCellExpanded] = useState<Record<number, boolean>>({})
  const [idCopied, setIdCopied] = useState(false)
  const tabsRef = useRef<HTMLDivElement>(null)
  const [tabIndicator, setTabIndicator] = useState({ left: 0, width: 0 })
  const runPollInterval = useRefetchInterval(2000)
  const healthPollInterval = useRefetchInterval(5000)

  useLayoutEffect(() => {
    const container = tabsRef.current
    if (!container) return
    const btn = container.querySelector<HTMLElement>(`[data-tab="${activeTab}"]`)
    if (!btn) return
    const cr = container.getBoundingClientRect()
    const br = btn.getBoundingClientRect()
    setTabIndicator({ left: br.left - cr.left, width: br.width })
  }, [activeTab])

  const { data: run, isLoading } = useQuery<Run>({
    queryKey: ['run', runId],
    queryFn: async () => {
      const response = await apiClient.get(`/runs/${runId}`)
      return response.data
    },
    refetchInterval: (query) => {
      const r = query.state.data
      return r?.status === 'RUNNING' || r?.status === 'PENDING' ? runPollInterval : false
    },
  })

  const { data: health } = useQuery({
    queryKey: ['run-health', runId],
    queryFn: async () => {
      const response = await apiClient.get(`/runs/${runId}/health`)
      return response.data
    },
    enabled: !!runId && (run?.status === 'RUNNING' || run?.status === 'PENDING'),
    refetchInterval: () => {
      return run?.status === 'RUNNING' || run?.status === 'PENDING' ? healthPollInterval : false
    },
  })

  const { data: pipeline } = useQuery<Pipeline>({
    queryKey: ['pipeline', run?.pipeline_name],
    queryFn: async () => {
      if (!run?.pipeline_name) return null
      // Cached pipeline list reuse — avoids a /pipelines request when navigating from the list page
      const cached = queryClient.getQueryData<Pipeline[]>(['pipelines'])
      if (cached) {
        return cached.find((p) => p.name === run.pipeline_name) ?? null
      }
      const response = await apiClient.get('/pipelines')
      return response.data.find((p: Pipeline) => p.name === run.pipeline_name) ?? null
    },
    enabled: !!run?.pipeline_name,
  })

  const { data: logsDownloadUrl, isError: logsDownloadUrlError } = useQuery({
    queryKey: ['logs-download-url', runId],
    queryFn: async () => {
      const { data } = await apiClient.get<{ token: string }>(`/runs/${runId}/logs/download-url`)
      if (!data?.token) return ''
      const base = (apiClient.defaults.baseURL || '/api').replace(/\/api\/?$/, '') || window.location.origin
      return `${base}/api/runs/${runId}/logs?download_token=${encodeURIComponent(data.token)}`
    },
    enabled: !!runId && !!run && activeTab === 'logs',
    staleTime: 30_000,
  })

  // Invalidate daily-stats when run completes
  const prevStatusRef = useRef<string | null>(null)
  useEffect(() => {
    if (run && run.pipeline_name) {
      const currentStatus = run.status
      const prevStatus = prevStatusRef.current
      
      // Only invalidate when status changes from RUNNING/PENDING to SUCCESS/FAILED
      if (prevStatus && 
          (prevStatus === 'RUNNING' || prevStatus === 'PENDING') &&
          (currentStatus === 'SUCCESS' || currentStatus === 'FAILED')) {
        // Invalidate all daily-stats queries immediately
        queryClient.invalidateQueries({ queryKey: ['all-pipelines-daily-stats'] })
        queryClient.invalidateQueries({ queryKey: ['pipeline-daily-stats'] })
        queryClient.invalidateQueries({ queryKey: ['pipeline-stats', run.pipeline_name] })
        queryClient.invalidateQueries({ queryKey: ['pipeline-stats'] })
        queryClient.invalidateQueries({ queryKey: ['pipelines'] })
        queryClient.invalidateQueries({ queryKey: ['pipeline', run.pipeline_name] })
        // Force refetch immediately with fresh data
        queryClient.refetchQueries({ queryKey: ['all-pipelines-daily-stats'], exact: false })
        queryClient.refetchQueries({ queryKey: ['pipeline-daily-stats', run.pipeline_name], exact: false })
      }
      
      prevStatusRef.current = currentStatus
    }
  }, [run?.status, run?.pipeline_name, queryClient])

  // Hilfsfunktion zum Parsen von Memory-Strings (z.B. "512M" -> 512)
  const parseMemoryString = (memStr: string): number => {
    if (!memStr) return 0
    const memStrLower = memStr.toLowerCase().trim()
    if (memStrLower.endsWith('g')) {
      return parseFloat(memStrLower.slice(0, -1)) * 1024
    } else if (memStrLower.endsWith('m')) {
      return parseFloat(memStrLower.slice(0, -1))
    } else if (memStrLower.endsWith('k')) {
      return parseFloat(memStrLower.slice(0, -1)) / 1024
    } else {
      return parseFloat(memStrLower) / (1024 * 1024) // Bytes zu MB
    }
  }

  const cancelMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post(`/runs/${runId}/cancel`)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['run', runId] })
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      if (run?.pipeline_name) {
        queryClient.invalidateQueries({ queryKey: ['all-pipelines-daily-stats'] })
        queryClient.invalidateQueries({ queryKey: ['pipeline-daily-stats', run.pipeline_name] })
      }
      showSuccess(t('runDetail.cancelSuccess'))
    },
    onError: (error: any) => {
      showError(t('runs.cancelError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const retryMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post(`/runs/${runId}/retry`)
      return response.data
    },
    onSuccess: (data: { id: string }) => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      queryClient.invalidateQueries({ queryKey: ['all-pipelines-daily-stats'] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-daily-stats'] })
      navigate(`/runs/${data.id}`)
    },
    onError: (error: any) => {
      showError(t('runDetail.retryError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  // Log-Streaming mit SSE via fetch (Authorization-Header, kein Token in URL)
  useEffect(() => {
    if (!run || activeTab !== 'logs') {
      logStreamAbortRef.current?.abort()
      logStreamAbortRef.current = null
      return
    }

    const isRunning = run.status === 'RUNNING' || run.status === 'PENDING'
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null
    const MAX_RECONNECT_ATTEMPTS = 5
    const RECONNECT_DELAY = 3000

    const loadHistoricalLogs = async (signal: AbortSignal) => {
      try {
        const response = await apiClient.get(`/runs/${runId}/logs?tail=1000`, { responseType: 'text', signal })
        const lines = response.data.split('\n').filter((line: string) => line.trim())
        setLogs(lines)
      } catch {
        if (!signal.aborted) setLogs([])
      }
    }

    const connectLogStream = () => {
      logStreamAbortRef.current?.abort()
      const ctrl = new AbortController()
      logStreamAbortRef.current = ctrl

      setLogConnectionStatus('reconnecting')
      const token = sessionStorage.getItem('auth_token')
      if (!token) {
        console.error('Kein Auth-Token gefunden, kann Log-Stream nicht verbinden')
        setLogConnectionStatus('disconnected')
        return
      }

      const baseURL = apiClient.defaults.baseURL || 'http://localhost:8000/api'
      const url = `${baseURL}/runs/${runId}/logs/stream`

      ;(async () => {
        try {
          const res = await fetch(url, {
            headers: { Authorization: `Bearer ${token}` },
            signal: ctrl.signal,
          })
          if (!res.ok) throw new Error(res.statusText)
          if (!res.body) throw new Error('Log stream response body is null')
          setLogConnectionStatus('connected')
          setLogReconnectAttempts(0)
          const reader = res.body.getReader()
          const dec = new TextDecoder()
          let buf = ''
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            buf += dec.decode(value, { stream: true })
            for (;;) {
              const i = buf.indexOf('\n\n')
              if (i === -1) break
              const block = buf.slice(0, i).trimEnd()
              buf = buf.slice(i + 2)
              if (block.startsWith('data: ')) {
                const payload = block.slice(6)
                try {
                  const data = JSON.parse(payload)
                  if (data.line) {
                    setLogs((prev) => {
                      if (prev.length > 0 && prev[prev.length - 1] === data.line) return prev
                      return [...prev, data.line]
                    })
                  } else if (data.error) console.error('Log stream error from server:', data.error)
                } catch {
                  if (payload) setLogs((prev) => [...prev, payload])
                }
              }
            }
          }
          setLogConnectionStatus('disconnected')
          if (logReconnectAttempts < MAX_RECONNECT_ATTEMPTS && isRunning) {
            reconnectTimeout = setTimeout(() => {
              setLogReconnectAttempts((prev) => prev + 1)
            }, RECONNECT_DELAY)
          }
        } catch (e: unknown) {
          if ((e as { name?: string })?.name === 'AbortError') return
          console.error('Log stream error:', e)
          setLogConnectionStatus('disconnected')
          logStreamAbortRef.current = null
          if (logReconnectAttempts < MAX_RECONNECT_ATTEMPTS && isRunning) {
            reconnectTimeout = setTimeout(() => {
              setLogReconnectAttempts((prev) => prev + 1)
            }, RECONNECT_DELAY)
          }
        }
      })()
    }

    if (isRunning) {
      if (logReconnectAttempts === 0) setLogs([])
      connectLogStream()
      return () => {
        if (reconnectTimeout) clearTimeout(reconnectTimeout)
        logStreamAbortRef.current?.abort()
        logStreamAbortRef.current = null
      }
    } else {
      const abortCtrl = new AbortController()
      loadHistoricalLogs(abortCtrl.signal)
      return () => abortCtrl.abort()
    }
  // run?.status statt run (Objekt-Referenz), um Stream-Reconnect bei jedem Poll zu verhindern
  }, [runId, run?.status, activeTab, logReconnectAttempts])

  // Metrics-Streaming mit SSE via fetch (Authorization-Header, kein Token in URL)
  useEffect(() => {
    if (!run || activeTab !== 'metrics') {
      metricsStreamAbortRef.current?.abort()
      metricsStreamAbortRef.current = null
      return
    }

    const isRunning = run.status === 'RUNNING' || run.status === 'PENDING'
    let reconnectTimeout: ReturnType<typeof setTimeout> | null = null
    const MAX_RECONNECT_ATTEMPTS = 5
    const RECONNECT_DELAY = 3000

    const connectMetricsStream = () => {
      metricsStreamAbortRef.current?.abort()
      const ctrl = new AbortController()
      metricsStreamAbortRef.current = ctrl

      setMetricsConnectionStatus('reconnecting')
      const token = sessionStorage.getItem('auth_token')
      if (!token) {
        console.error('Kein Auth-Token gefunden, kann Metrics-Stream nicht verbinden')
        setMetricsConnectionStatus('disconnected')
        return
      }

      const baseURL = apiClient.defaults.baseURL || 'http://localhost:8000/api'
      const url = `${baseURL}/runs/${runId}/metrics/stream`

      ;(async () => {
        try {
          const res = await fetch(url, {
            headers: { Authorization: `Bearer ${token}` },
            signal: ctrl.signal,
          })
          if (!res.ok) throw new Error(res.statusText)
          if (!res.body) throw new Error('Metrics stream response body is null')
          setMetricsConnectionStatus('connected')
          setMetricsReconnectAttempts(0)
          const reader = res.body.getReader()
          const dec = new TextDecoder()
          let buf = ''
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            buf += dec.decode(value, { stream: true })
            for (;;) {
              const i = buf.indexOf('\n\n')
              if (i === -1) break
              const block = buf.slice(0, i).trimEnd()
              buf = buf.slice(i + 2)
              if (block.startsWith('data: ')) {
                try {
                  const metric = JSON.parse(block.slice(6))
                  if (metric.timestamp) setMetrics((prev) => [...prev, metric])
                  else if (metric.error) console.error('Metrics stream error from server:', metric.error)
                } catch (e) {
                  console.error('Fehler beim Parsen der Metrics:', e)
                }
              }
            }
          }
          setMetricsConnectionStatus('disconnected')
          if (metricsReconnectAttempts < MAX_RECONNECT_ATTEMPTS && isRunning) {
            reconnectTimeout = setTimeout(() => {
              setMetricsReconnectAttempts((prev) => prev + 1)
            }, RECONNECT_DELAY)
          }
        } catch (e: unknown) {
          if ((e as { name?: string })?.name === 'AbortError') return
          console.error('Metrics stream error:', e)
          setMetricsConnectionStatus('disconnected')
          metricsStreamAbortRef.current = null
          if (metricsReconnectAttempts < MAX_RECONNECT_ATTEMPTS && isRunning) {
            reconnectTimeout = setTimeout(() => {
              setMetricsReconnectAttempts((prev) => prev + 1)
            }, RECONNECT_DELAY)
          }
        }
      })()
    }

    if (isRunning) {
      setMetrics([])
      connectMetricsStream()
      return () => {
        if (reconnectTimeout) clearTimeout(reconnectTimeout)
        metricsStreamAbortRef.current?.abort()
        metricsStreamAbortRef.current = null
      }
    } else if (run.metrics_file) {
      const abortCtrl = new AbortController()
      apiClient.get(`/runs/${runId}/metrics`, { signal: abortCtrl.signal })
        .then((r) => setMetrics(r.data))
        .catch(() => { /* Ignored: component unmounted or network error */ })
      return () => abortCtrl.abort()
    }
  // run?.status + run?.metrics_file statt run (Objekt-Referenz), um Stream-Reconnect bei jedem Poll zu verhindern
  }, [runId, run?.status, run?.metrics_file, activeTab, metricsReconnectAttempts])

  // Auto-Scroll für Logs — scrollt den logviewer__body ans Ende
  useEffect(() => {
    if (autoScroll) {
      const body = logBodyRef.current
      if (body) body.scrollTop = body.scrollHeight
    }
  }, [logs, autoScroll])

  // Disable follow when user scrolls up
  const handleLogBodyScroll = useCallback(() => {
    const body = logBodyRef.current
    if (!body) return
    const atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40
    if (!atBottom && autoScroll) setAutoScroll(false)
    if (atBottom && !autoScroll) setAutoScroll(true)
  }, [autoScroll])

  const handleDownloadMetrics = () => {
    if (!metrics.length) return
    const dataStr = JSON.stringify(metrics, null, 2)
    const dataBlob = new Blob([dataStr], { type: 'application/json' })
    const url = window.URL.createObjectURL(dataBlob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `run-${runId}-metrics.json`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  const handleCopyRunId = useCallback(async () => {
    if (!run?.id) return
    try {
      await navigator.clipboard.writeText(run.id)
      showSuccess(t('runDetail.idCopied', 'Run ID copied'))
      setIdCopied(true)
      setTimeout(() => setIdCopied(false), 1500)
    } catch {
      showError(t('runDetail.idCopyError', 'Could not copy run ID'))
    }
  }, [run?.id, t])

  // Parse a log level out of the raw line text (best-effort, for data-level colouring)
  const parseLogLevel = (line: string): 'ERROR' | 'WARN' | 'INFO' | 'DEBUG' | 'SUCCESS' | '' => {
    const m = line.match(/\b(ERROR|ERR|CRITICAL|FATAL|WARN(?:ING)?|INFO|DEBUG|TRACE|SUCCESS)\b/i)
    if (!m) return ''
    const lvl = m[1].toUpperCase()
    if (lvl === 'ERR' || lvl === 'CRITICAL' || lvl === 'FATAL') return 'ERROR'
    if (lvl === 'WARNING') return 'WARN'
    if (lvl === 'TRACE') return 'DEBUG'
    return lvl as 'ERROR' | 'WARN' | 'INFO' | 'DEBUG' | 'SUCCESS'
  }

  // Structured, search- and stream-filtered log lines for rendering
  const visibleLogs = useMemo(() => {
    const search = logSearch.toLowerCase()
    return logs
      .map((text, i) => {
        const level = parseLogLevel(text)
        // stderr lines are conventionally the error/warn ones; stdout = the rest.
        // (Backend does not yet tag the stream per line — see TODO in the toolbar.)
        const stream: 'stdout' | 'stderr' = level === 'ERROR' || level === 'WARN' ? 'stderr' : 'stdout'
        return { n: i + 1, text, level, stream }
      })
      .filter((l) => (logStream === 'all' ? true : l.stream === logStream))
      .filter((l) => (search ? l.text.toLowerCase().includes(search) : true))
  }, [logs, logSearch, logStream])

  const getDuration = () => {
    if (!run) return '-'
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

  // Map run status to .badge variant + .status-dot kind for the redesigned pill
  const statusBadgeClass = (status: string) => {
    switch (status.toUpperCase()) {
      case 'SUCCESS': return 'badge-success'
      case 'FAILED': return 'badge-error'
      case 'RUNNING': return 'badge-running'
      case 'PENDING':
      case 'WARNING': return 'badge-warning'
      default: return 'badge-secondary'
    }
  }
  const statusDotKind = (status: string) => {
    switch (status.toUpperCase()) {
      case 'SUCCESS': return 'success'
      case 'FAILED': return 'failed'
      case 'RUNNING': return 'running'
      case 'PENDING': return 'checking'
      case 'WARNING': return 'degraded'
      default: return 'queued'
    }
  }

  if (isLoading) {
    return <div>{t('common.loading')}</div>
  }

  if (!run) {
    return <div>{t('runs.notFound')}</div>
  }

  const isRunning = run.status === 'RUNNING' || run.status === 'PENDING'
  const canRetry = ['SUCCESS', 'FAILED', 'INTERRUPTED', 'WARNING'].includes(run.status)

  return (
    <div className="run-detail">
      <div className="run-detail-header">
        <div className="run-detail-head-main">
          <div className="run-detail-title-row">
            <h1 className="run-detail-title mono">{run.id.substring(0, 8)}</h1>
            <button
              type="button"
              className="run-id-copy"
              onClick={handleCopyRunId}
              title={t('runDetail.copyRunId', 'Copy run ID')}
              aria-label={t('runDetail.copyRunId', 'Copy run ID')}
            >
              {idCopied ? <LuCheck size={13} /> : <LuCopy size={13} />}
            </button>
            <span className={`badge dot ${statusBadgeClass(run.status)} run-detail-status`}>
              <span className={`status-dot ${statusDotKind(run.status)}`} />
              {run.status}
            </span>
          </div>
          <div className="run-detail-meta">
            <span className="run-detail-meta-label">{t('runDetail.pipelineLabel')}</span>
            <span className="run-detail-meta-pipeline mono">{run.pipeline_name}</span>
            <span className="run-detail-meta-sep">·</span>
            <span>{t('runDetail.started')} <span className="run-detail-meta-strong">{new Date(run.started_at).toLocaleString(getFormatLocale(), { timeZone: 'UTC' })} UTC</span></span>
            <span className="run-detail-meta-sep">·</span>
            <span>{t('runDetail.durationLabel')} <span className="run-detail-meta-strong mono">{getDuration()}</span></span>
            {run.exit_code !== null && (
              <>
                <span className="run-detail-meta-sep">·</span>
                <span>{t('runDetail.exitCodeLabel')} <span className={`mono ${run.exit_code === 0 ? 'exit-success' : 'exit-error'}`}>{run.exit_code}</span></span>
              </>
            )}
          </div>
        </div>
        <div className="run-actions">
          {isRunning && (
            <button
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              className="btn btn-error"
            >
              {cancelMutation.isPending ? t('runs.cancelling') : t('runs.cancel')}
            </button>
          )}
          {canRetry && (
            <button
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              className="btn btn-primary"
            >
              {retryMutation.isPending ? t('common.saving') : t('runDetail.retry')}
            </button>
          )}
        </div>
      </div>

      {activeTab === 'info' && (
      <div className="run-info-card">
        <div className="info-row">
          <span className="info-label">{t('runDetail.idLabel')}</span>
          <span className="info-value">{run.id}</span>
        </div>
        <div className="info-row">
          <span className="info-label">{t('runDetail.pipelineLabel')}</span>
          <span className="info-value">{run.pipeline_name}</span>
        </div>
        <div className="info-row">
          <span className="info-label">{t('runDetail.pythonVersionLabel')}</span>
          <span className="info-value">{pipeline?.metadata?.python_version || t('runDetail.pythonVersionDefault')}</span>
        </div>
        {pipeline?.metadata?.description && (
          <div className="info-row">
            <span className="info-label">{t('pipelineDetail.descriptionLabel')}</span>
            <span className="info-value">{pipeline.metadata.description}</span>
          </div>
        )}
        {pipeline?.metadata?.tags && pipeline.metadata.tags.length > 0 && (
          <div className="info-row">
            <span className="info-label">{t('pipelineDetail.tagsLabel')}</span>
            <span className="info-value">
              {pipeline.metadata.tags.join(', ')}
            </span>
          </div>
        )}
        <div className="info-row">
          <span className="info-label">{t('runDetail.statusLabel')}</span>
          <span className={`status status-${run.status.toLowerCase()}`}>
            {run.status}
          </span>
        </div>
        {run.error_type && (
          <div className="info-row">
            <span className="info-label">{t('runDetail.errorTypeLabel')}</span>
            <span className={`error-type-badge error-type-${run.error_type}`}>
              {run.error_type === 'pipeline_error' ? t('runDetail.errorTypePipeline') : t('runDetail.errorTypeInfrastructure')}
            </span>
          </div>
        )}
        {run.error_message && (
          <div className="info-row">
            <span className="info-label">{t('runDetail.errorDetailsLabel')}</span>
            <span className={`error-message error-message-${run.error_type || 'unknown'}`}>
              {run.error_message}
            </span>
          </div>
        )}
        <div className="info-row">
          <span className="info-label">{t('runDetail.started')}:</span>
          <span className="info-value">
            {new Date(run.started_at).toLocaleString(getFormatLocale(), { timeZone: 'UTC' })} UTC
          </span>
        </div>
        {run.finished_at && (
          <div className="info-row">
            <span className="info-label">{t('runDetail.finished')}:</span>
            <span className="info-value">
              {new Date(run.finished_at).toLocaleString(getFormatLocale(), { timeZone: 'UTC' })} UTC
            </span>
          </div>
        )}
        <div className="info-row">
          <span className="info-label">{t('runDetail.durationLabel')}</span>
          <span className="info-value">{getDuration()}</span>
        </div>
        {run.exit_code !== null && (
          <div className="info-row">
            <span className="info-label">{t('runDetail.exitCodeLabel')}</span>
            <span className={`info-value ${run.exit_code === 0 ? 'exit-success' : 'exit-error'}`}>
              {run.exit_code}
            </span>
          </div>
        )}
        {run.uv_version && (
          <div className="info-row">
            <span className="info-label">{t('runDetail.uvVersionLabel')}</span>
            <span className="info-value">{run.uv_version}</span>
          </div>
        )}
        {run.setup_duration !== null && (
          <div className="info-row">
            <span className="info-label">{t('runDetail.setupDurationLabel')}</span>
            <span className="info-value">{run.setup_duration.toFixed(2)}s</span>
          </div>
        )}
        {(run.git_sha || run.git_branch) && (
          <>
            {run.git_sha && (
              <div className="info-row">
                <span className="info-label">{t('runDetail.gitSha')}:</span>
                <span className="info-value info-value-mono" title={run.git_sha}>
                  {run.git_sha.slice(0, 7)}
                </span>
              </div>
            )}
            {run.git_branch && (
              <div className="info-row">
                <span className="info-label">{t('runDetail.gitBranch')}:</span>
                <span className="info-value">{run.git_branch}</span>
              </div>
            )}
            {run.git_commit_message && (
              <div className="info-row">
                <span className="info-label">{t('runDetail.gitCommitMessage')}:</span>
                <span className="info-value" title={run.git_commit_message}>
                  {run.git_commit_message.length > 60 ? `${run.git_commit_message.slice(0, 60)}…` : run.git_commit_message}
                </span>
              </div>
            )}
          </>
        )}
        {health && (
          <div className="info-row">
            <span className="info-label">{t('runDetail.containerStatusLabel')}</span>
            <span className={`health-status ${health.healthy ? 'healthy' : 'unhealthy'}`}>
              {health.container_status || health.status || (health.healthy ? t('runDetail.healthRunning') : t('runDetail.healthUnknown'))}
            </span>
            {health.health && (
              <span className={`health-badge ${health.health === 'healthy' ? 'healthy' : 'unhealthy'}`}>
                {health.health}
              </span>
            )}
          </div>
        )}
      </div>
      )}

      <div ref={tabsRef} className="tab-strip tab-strip--indicator run-tabs">
        <div
          className="tab-strip__indicator"
          style={{ left: tabIndicator.left, width: tabIndicator.width }}
          aria-hidden
        />
        <button
          type="button"
          data-tab="logs"
          className={`tab-strip__tab${activeTab === 'logs' ? ' active' : ''}`}
          onClick={() => setActiveTab('logs')}
        >
          {t('runDetail.logs')} {logs.length > 0 && `(${logs.length})`}
        </button>
        <button
          type="button"
          data-tab="metrics"
          className={`tab-strip__tab${activeTab === 'metrics' ? ' active' : ''}`}
          onClick={() => setActiveTab('metrics')}
        >
          {t('runDetail.metrics')} {metrics.length > 0 && `(${metrics.length})`}
        </button>
        <button
          type="button"
          data-tab="env"
          className={`tab-strip__tab${activeTab === 'env' ? ' active' : ''}`}
          onClick={() => setActiveTab('env')}
        >
          {t('runDetail.env')}
        </button>
        <button
          type="button"
          data-tab="info"
          className={`tab-strip__tab${activeTab === 'info' ? ' active' : ''}`}
          onClick={() => setActiveTab('info')}
        >
          {t('runDetail.info')}
        </button>
      </div>

      {activeTab === 'logs' && (
        <div className={`logviewer${wrapLogs ? ' wrap' : ''}${!showLineNumbers ? ' no-linenumbers' : ''}`}>
          {/* Toolbar */}
          <div className="logviewer__toolbar">
            {/* Stream filter — All is functional; stdout/stderr split on parsed level.
                TODO(redesign): needs a per-line stream field from the backend SSE payload. */}
            <div className="segmented logviewer__streams" role="group" aria-label={t('runDetail.streamFilter', 'Stream')}>
              <button
                type="button"
                className={logStream === 'all' ? 'active' : ''}
                onClick={() => setLogStream('all')}
              >
                {t('runDetail.streamAll', 'All')}
              </button>
              <button
                type="button"
                data-stream="stdout"
                className={logStream === 'stdout' ? 'active' : ''}
                onClick={() => setLogStream('stdout')}
              >
                stdout
              </button>
              <button
                type="button"
                data-stream="stderr"
                className={logStream === 'stderr' ? 'active' : ''}
                onClick={() => setLogStream('stderr')}
              >
                stderr
              </button>
            </div>
            <button
              className={`log-toggle icon${searchVisible ? ' active' : ''}`}
              onClick={() => setSearchVisible(v => !v)}
              title={t('runDetail.searchLogs')}
              aria-label={t('runDetail.searchLogs')}
            >
              <LuSearch size={13} />
            </button>
            {searchVisible && (
              <div className="logviewer__search">
                <LuSearch size={13} className="logviewer__search-icon" />
                <input
                  type="text"
                  placeholder={t('runDetail.searchLogs')}
                  value={logSearch}
                  onChange={(e) => setLogSearch(e.target.value)}
                  autoFocus
                />
                {logSearch && (
                  <span className="count">{t('runDetail.searchHits', '{{n}} hits', { n: visibleLogs.length })}</span>
                )}
              </div>
            )}
            <span className="spacer" />
            <button
              className={`log-toggle icon${showLineNumbers ? ' active' : ''}`}
              onClick={() => setShowLineNumbers(v => !v)}
              title={t('runDetail.lineNumbers', 'Line numbers')}
              aria-label={t('runDetail.lineNumbers', 'Line numbers')}
            >
              <LuHash size={13} />
            </button>
            <button
              className={`log-toggle icon${wrapLogs ? ' active' : ''}`}
              onClick={() => setWrapLogs(v => !v)}
              title={t('runDetail.wrapLines', 'Wrap lines')}
              aria-label={t('runDetail.wrapLines', 'Wrap lines')}
            >
              <LuWrapText size={13} />
            </button>
            <button
              className={`log-toggle${autoScroll ? ' active follow' : ''}`}
              onClick={() => setAutoScroll(v => !v)}
              title={t('runDetail.follow', 'Follow')}
            >
              <LuArrowDown size={13} />
              {t('runDetail.follow', 'Follow')}
            </button>
            {logsDownloadUrl ? (
              <a
                href={logsDownloadUrl}
                download={`run-${runId}-logs.txt`}
                target="_blank"
                rel="noopener noreferrer"
                className="log-toggle"
                title={t('runDetail.downloadLogs')}
              >
                <LuDownload size={13} />
                {t('runDetail.downloadLogs')}
              </a>
            ) : (
              <button
                className="log-toggle"
                disabled={!logsDownloadUrlError}
                title={logsDownloadUrlError ? t('runDetail.retryDownload') : t('runDetail.loadingDownloadUrl')}
                onClick={() => logsDownloadUrlError && queryClient.invalidateQueries({ queryKey: ['logs-download-url', runId] })}
              >
                <LuDownload size={13} />
                {logsDownloadUrlError ? t('runDetail.retryDownload') : t('runDetail.downloadLogs')}
              </button>
            )}
          </div>

          {/* Log body */}
          <div
            className="logviewer__body"
            ref={logBodyRef}
            onScroll={handleLogBodyScroll}
          >
            {run.cell_logs && run.cell_logs.length > 0 ? (
              /* Notebook cell logs — keep original structure */
              <div className="cell-logs-grouped" style={{ padding: '12px 14px' }}>
                {run.cell_logs.map((cell) => {
                  const isExpanded = cellExpanded[cell.cell_index] !== false
                  const toggle = () =>
                    setCellExpanded((prev) => ({ ...prev, [cell.cell_index]: !isExpanded }))
                  const statusClass =
                    cell.status === 'SUCCESS'
                      ? 'cell-status-success'
                      : cell.status === 'FAILED'
                        ? 'cell-status-failed'
                        : cell.status === 'RETRYING'
                          ? 'cell-status-retrying'
                          : 'cell-status-running'
                  return (
                    <div key={cell.cell_index} className="cell-log-section">
                      <button
                        type="button"
                        className="cell-log-header"
                        onClick={toggle}
                        aria-expanded={isExpanded}
                      >
                        <span className="cell-log-header-title">
                          Zelle {cell.cell_index}
                        </span>
                        <span className={`cell-status-badge ${statusClass}`}>
                          {cell.status}
                        </span>
                        <span className="cell-log-header-toggle">
                          {isExpanded ? '▼' : '▶'}
                        </span>
                      </button>
                      {isExpanded && (
                        <div className="cell-log-content">
                          {cell.stdout && (
                            <div className="cell-log-stdout">
                              <div className="cell-log-stream-label">stdout</div>
                              <pre>{cell.stdout}</pre>
                            </div>
                          )}
                          {cell.stderr && (
                            <div className="cell-log-stderr">
                              <div className="cell-log-stream-label">stderr</div>
                              <pre>{cell.stderr}</pre>
                            </div>
                          )}
                          {(() => {
                            const images = cell.outputs?.images ?? []
                            return images.length > 0 ? (
                              <div className="cell-log-images">
                                {images.map((img, i) => (
                                  <img
                                    key={i}
                                    src={`data:${img.mime};base64,${img.data}`}
                                    alt={`Zelle ${cell.cell_index} Ausgabe ${i + 1}`}
                                    className="cell-log-image"
                                  />
                                ))}
                              </div>
                            ) : null
                          })()}
                          {!cell.stdout && !cell.stderr && !cell.outputs?.images?.length && (
                            <div className="cell-log-empty">Keine Ausgabe</div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : visibleLogs.length > 0 ? (
              visibleLogs.map((l) => (
                <div
                  key={l.n}
                  className={`log-line${logSearch ? ' match' : ''}`}
                  data-level={l.level || undefined}
                >
                  <span className="log-gutter">{l.n}</span>
                  <span className="log-level">{l.level}</span>
                  <span className="log-text">{l.text}</span>
                </div>
              ))
            ) : (
              <div className="logviewer__empty">{t('runDetail.noLogs', 'No logs found')}</div>
            )}
            {isRunning && <div className="log-cursor"><span className="block" /></div>}
            <div ref={logsEndRef} />
          </div>

          {/* Footer */}
          <div className="logviewer__footer">
            <span className={`logviewer__sse${isRunning && logConnectionStatus === 'connected' ? '' : ' closed'}`}>
              <span className="dot" />
              {isRunning
                ? logConnectionStatus === 'connected'
                  ? t('runDetail.streamingSse', 'streaming via SSE')
                  : logConnectionStatus === 'reconnecting'
                    ? t('runDetail.reconnecting', 'reconnecting…')
                    : t('runDetail.disconnected', 'disconnected')
                : t('runDetail.streamClosed', 'stream closed')}
            </span>
            <span className="logviewer__count">
              {t('runDetail.lineCount', '{{shown}} / {{total}} lines', { shown: visibleLogs.length, total: logs.length })}
            </span>
          </div>
        </div>
      )}

      {activeTab === 'env' && (
        <RunEnvSection
          envVars={run.env_vars || {}}
          parameters={run.parameters || {}}
        />
      )}

      {activeTab === 'metrics' && (
        <div className="metrics-container">
          <div className="metrics-controls">
            {isRunning && (
              <span className={`connection-status ${metricsConnectionStatus}`}>
                {metricsConnectionStatus === 'connected' ? '✓ Verbunden' : 
                 metricsConnectionStatus === 'reconnecting' ? '↻ Verbinde...' : 
                 '✗ Getrennt'}
              </span>
            )}
            <button type="button" onClick={handleDownloadMetrics} className="btn btn-secondary btn-sm">
              {t('runDetail.downloadMetrics')}
            </button>
          </div>
          {metrics.length > 0 ? (
            <div className="metrics-viewer">
              <div className="metrics-chart">
                <h4>CPU Usage (%)</h4>
                <LineChart
                  data={metrics}
                  valueKey="cpu_percent"
                  maxValue={Math.max(
                    100,
                    pipeline?.metadata?.cpu_hard_limit ?? 100,
                    pipeline?.metadata?.cpu_soft_limit ?? 0
                  )}
                  color="#22c55e"
                  warningColor="#f59e0b"
                  softLimit={pipeline?.metadata?.cpu_soft_limit}
                  hardLimit={pipeline?.metadata?.cpu_hard_limit}
                />
              </div>
              <div className="metrics-chart">
                <h4>RAM Usage (MB)</h4>
                <LineChart
                  data={metrics}
                  valueKey="ram_mb"
                  maxValue={Math.max(
                    metrics.reduce((max, m) => Math.max(max, m.ram_mb ?? 0, m.ram_limit_mb ?? 0), 0),
                    pipeline?.metadata?.mem_hard_limit ? parseMemoryString(pipeline.metadata.mem_hard_limit) : 0,
                    pipeline?.metadata?.mem_soft_limit ? parseMemoryString(pipeline.metadata.mem_soft_limit) : 0
                  )}
                  color="#6366f1"
                  warningColor="#f59e0b"
                  softLimit={pipeline?.metadata?.mem_soft_limit ? parseMemoryString(pipeline.metadata.mem_soft_limit) : undefined}
                  hardLimit={pipeline?.metadata?.mem_hard_limit ? parseMemoryString(pipeline.metadata.mem_hard_limit) : undefined}
                />
              </div>
              <div className="metrics-table">
                <table>
                  <thead>
                    <tr>
                      <th>Zeit</th>
                      <th>CPU %</th>
                      <th>RAM (MB)</th>
                      <th>RAM Limit</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.slice(-20).reverse().map((metric, index) => {
                      const cpuPercent = metric.cpu_percent ?? null
                      const ramMb = metric.ram_mb ?? null
                      return (
                        <tr key={index}>
                          <td>{new Date(metric.timestamp).toLocaleTimeString()}</td>
                          <td>{cpuPercent !== null ? `${cpuPercent.toFixed(1)}%` : '-'}</td>
                          <td>{ramMb !== null ? ramMb.toFixed(1) : '-'}</td>
                          <td>{metric.ram_limit_mb ? `${metric.ram_limit_mb} MB` : '-'}</td>
                          <td>
                            {metric.soft_limit_exceeded && (
                              <span className="warning-badge">Soft-Limit überschritten</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="no-metrics">Keine Metrics verfügbar</div>
          )}
        </div>
      )}
    </div>
  )
}
