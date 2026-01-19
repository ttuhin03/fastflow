import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
import { showError, showSuccess } from '../utils/toast'
import { LineChart } from '../components/LineChart'
import { RunEnvSection } from '../components/RunEnvSection'
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
}

interface Pipeline {
  name: string
  metadata?: {
    cpu_hard_limit?: number
    mem_hard_limit?: string
    cpu_soft_limit?: number
    mem_soft_limit?: string
  }
}

interface Metric {
  timestamp: string
  cpu_percent: number
  ram_mb: number
  ram_limit_mb?: number
  soft_limit_exceeded?: boolean
}

export default function RunDetail() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'info' | 'logs' | 'metrics' | 'env'>('info')
  const [autoScroll, setAutoScroll] = useState(true)
  const [logSearch, setLogSearch] = useState('')
  const logsEndRef = useRef<HTMLDivElement>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [metrics, setMetrics] = useState<Metric[]>([])
  const logStreamAbortRef = useRef<AbortController | null>(null)
  const metricsStreamAbortRef = useRef<AbortController | null>(null)
  const [logReconnectAttempts, setLogReconnectAttempts] = useState(0)
  const [metricsReconnectAttempts, setMetricsReconnectAttempts] = useState(0)
  const [logConnectionStatus, setLogConnectionStatus] = useState<'connected' | 'disconnected' | 'reconnecting'>('connected')
  const [metricsConnectionStatus, setMetricsConnectionStatus] = useState<'connected' | 'disconnected' | 'reconnecting'>('connected')

  const { data: run, isLoading } = useQuery<Run>({
    queryKey: ['run', runId],
    queryFn: async () => {
      const response = await apiClient.get(`/runs/${runId}`)
      return response.data
    },
    refetchInterval: (query) => {
      // Auto-refresh nur wenn Run noch läuft
      const run = query.state.data
      return run?.status === 'RUNNING' || run?.status === 'PENDING' ? 2000 : false
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
      return run?.status === 'RUNNING' || run?.status === 'PENDING' ? 5000 : false
    },
  })

  const { data: pipeline } = useQuery<Pipeline>({
    queryKey: ['pipeline', run?.pipeline_name],
    queryFn: async () => {
      if (!run?.pipeline_name) return null
      const response = await apiClient.get('/pipelines')
      const pipelines = response.data
      return pipelines.find((p: any) => p.name === run.pipeline_name) || null
    },
    enabled: !!run?.pipeline_name,
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
      showSuccess('Run wurde erfolgreich abgebrochen')
    },
    onError: (error: any) => {
      showError(`Fehler beim Abbrechen: ${error.response?.data?.detail || error.message}`)
    },
  })

  const retryMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post(`/pipelines/${run?.pipeline_name}/run`, {
        env_vars: run?.env_vars || {},
        parameters: run?.parameters || {},
      })
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      queryClient.invalidateQueries({ queryKey: ['all-pipelines-daily-stats'] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-daily-stats'] })
      navigate(`/runs/${data.id}`)
    },
    onError: (error: any) => {
      showError(`Fehler beim Neustart: ${error.response?.data?.detail || error.message}`)
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

    const loadHistoricalLogs = async () => {
      try {
        const response = await apiClient.get(`/runs/${runId}/logs?tail=1000`, { responseType: 'text' })
        const lines = response.data.split('\n').filter((line: string) => line.trim())
        setLogs(lines)
      } catch (error) {
        console.warn('Konnte historische Logs nicht laden:', error)
        setLogs([])
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
          setLogConnectionStatus('connected')
          setLogReconnectAttempts(0)
          const reader = res.body!.getReader()
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
              connectLogStream()
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
              connectLogStream()
            }, RECONNECT_DELAY)
          }
        }
      })()
    }

    if (isRunning) {
      setLogs([])
      connectLogStream()
      return () => {
        if (reconnectTimeout) clearTimeout(reconnectTimeout)
        logStreamAbortRef.current?.abort()
        logStreamAbortRef.current = null
      }
    } else {
      loadHistoricalLogs()
    }
  }, [runId, run, activeTab, logReconnectAttempts])

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
          setMetricsConnectionStatus('connected')
          setMetricsReconnectAttempts(0)
          const reader = res.body!.getReader()
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
              connectMetricsStream()
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
              connectMetricsStream()
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
      apiClient.get(`/runs/${runId}/metrics`).then((r) => setMetrics(r.data)).catch((e) => console.error('Fehler beim Laden der Metrics:', e))
    }
  }, [runId, run, activeTab, metricsReconnectAttempts])

  // Auto-Scroll für Logs
  useEffect(() => {
    if (autoScroll && logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  const handleDownloadLogs = () => {
    if (!run) return
    apiClient
      .get(`/runs/${runId}/logs`, { responseType: 'blob' })
      .then((response) => {
        const url = window.URL.createObjectURL(new Blob([response.data]))
        const link = document.createElement('a')
        link.href = url
        link.setAttribute('download', `run-${runId}-logs.txt`)
        document.body.appendChild(link)
        link.click()
        link.remove()
      })
  }

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
  }

  const filteredLogs = logs.filter((log) =>
    log.toLowerCase().includes(logSearch.toLowerCase())
  )

  const getDuration = () => {
    if (!run) return '-'
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

  if (isLoading) {
    return <div>Laden...</div>
  }

  if (!run) {
    return <div>Run nicht gefunden</div>
  }

  const isRunning = run.status === 'RUNNING' || run.status === 'PENDING'
  const isFailed = run.status === 'FAILED'

  return (
    <div className="run-detail">
      <div className="run-detail-header">
        <h2>Run Details</h2>
        <div className="run-actions">
          {isRunning && (
            <button
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              className="cancel-button"
            >
              {cancelMutation.isPending ? 'Bricht ab...' : 'Abbrechen'}
            </button>
          )}
          {isFailed && (
            <button
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              className="retry-button"
            >
              {retryMutation.isPending ? 'Startet...' : 'Erneut starten'}
            </button>
          )}
        </div>
      </div>

      <div className="run-info-card">
        <div className="info-row">
          <span className="info-label">ID:</span>
          <span className="info-value">{run.id}</span>
        </div>
        <div className="info-row">
          <span className="info-label">Pipeline:</span>
          <span className="info-value">{run.pipeline_name}</span>
        </div>
        <div className="info-row">
          <span className="info-label">Status:</span>
          <span className={`status status-${run.status.toLowerCase()}`}>
            {run.status}
          </span>
        </div>
        {run.error_type && (
          <div className="info-row">
            <span className="info-label">Fehler-Typ:</span>
            <span className={`error-type-badge error-type-${run.error_type}`}>
              {run.error_type === 'pipeline_error' ? 'Pipeline Error' : 'Infrastructure Error'}
            </span>
          </div>
        )}
        {run.error_message && (
          <div className="info-row">
            <span className="info-label">Fehler-Details:</span>
            <span className={`error-message error-message-${run.error_type || 'unknown'}`}>
              {run.error_message}
            </span>
          </div>
        )}
        <div className="info-row">
          <span className="info-label">Gestartet:</span>
          <span className="info-value">
            {new Date(run.started_at).toLocaleString('de-DE', { timeZone: 'UTC' })} UTC
          </span>
        </div>
        {run.finished_at && (
          <div className="info-row">
            <span className="info-label">Beendet:</span>
            <span className="info-value">
              {new Date(run.finished_at).toLocaleString('de-DE', { timeZone: 'UTC' })} UTC
            </span>
          </div>
        )}
        <div className="info-row">
          <span className="info-label">Dauer:</span>
          <span className="info-value">{getDuration()}</span>
        </div>
        {run.exit_code !== null && (
          <div className="info-row">
            <span className="info-label">Exit Code:</span>
            <span className={`info-value ${run.exit_code === 0 ? 'exit-success' : 'exit-error'}`}>
              {run.exit_code}
            </span>
          </div>
        )}
        {run.uv_version && (
          <div className="info-row">
            <span className="info-label">UV Version:</span>
            <span className="info-value">{run.uv_version}</span>
          </div>
        )}
        {run.setup_duration !== null && (
          <div className="info-row">
            <span className="info-label">Setup Dauer:</span>
            <span className="info-value">{run.setup_duration.toFixed(2)}s</span>
          </div>
        )}
        {health && (
          <div className="info-row">
            <span className="info-label">Container Status:</span>
            <span className={`health-status ${health.healthy ? 'healthy' : 'unhealthy'}`}>
              {health.container_status || health.status || (health.healthy ? 'Running' : 'Unknown')}
            </span>
            {health.health && (
              <span className={`health-badge ${health.health === 'healthy' ? 'healthy' : 'unhealthy'}`}>
                {health.health}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="tabs">
        <button
          className={activeTab === 'info' ? 'active' : ''}
          onClick={() => setActiveTab('info')}
        >
          Info
        </button>
        <button
          className={activeTab === 'env' ? 'active' : ''}
          onClick={() => setActiveTab('env')}
        >
          Environment-Variablen
        </button>
        <button
          className={activeTab === 'logs' ? 'active' : ''}
          onClick={() => setActiveTab('logs')}
        >
          Logs {logs.length > 0 && `(${logs.length})`}
        </button>
        <button
          className={activeTab === 'metrics' ? 'active' : ''}
          onClick={() => setActiveTab('metrics')}
        >
          Metrics {metrics.length > 0 && `(${metrics.length})`}
        </button>
      </div>

      {activeTab === 'logs' && (
        <div className="logs-container">
          <div className="logs-controls">
            <input
              type="text"
              placeholder="Logs durchsuchen..."
              value={logSearch}
              onChange={(e) => setLogSearch(e.target.value)}
              className="log-search"
            />
            <label className="auto-scroll-toggle">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />
              Auto-Scroll
            </label>
            {isRunning && (
              <span className={`connection-status ${logConnectionStatus}`}>
                {logConnectionStatus === 'connected' ? '✓ Verbunden' : 
                 logConnectionStatus === 'reconnecting' ? '↻ Verbinde...' : 
                 '✗ Getrennt'}
              </span>
            )}
            <button onClick={handleDownloadLogs} className="download-button">
              Download Logs
            </button>
          </div>
          <div className="logs-viewer">
            {filteredLogs.length > 0 ? (
              filteredLogs.map((log, index) => (
                <div key={index} className="log-line">
                  {log}
                </div>
              ))
            ) : (
              <div className="no-logs">Keine Logs gefunden</div>
            )}
            <div ref={logsEndRef} />
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
            <button onClick={handleDownloadMetrics} className="download-button">
              Download Metrics
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
                  color="#4caf50"
                  warningColor="#ff9800"
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
                  color="#2196f3"
                  warningColor="#ff9800"
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
