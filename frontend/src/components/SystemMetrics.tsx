import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { MdMemory, MdSpeed, MdStorage, MdDataUsage } from 'react-icons/md'
import './SystemMetrics.css'

interface SystemMetrics {
  active_containers: number
  containers_ram_mb: number
  containers_cpu_percent: number
  api_ram_mb: number
  api_cpu_percent: number
  system_ram_total_mb: number
  system_ram_used_mb: number
  system_ram_percent: number
  system_cpu_percent: number
  container_details: Array<{
    run_id: string
    pipeline_name: string
    container_id: string
    ram_mb: number
    ram_percent: number
    cpu_percent: number
    status: string
  }>
}

export default function SystemMetrics() {
  const { t } = useTranslation()
  const metricsInterval = useRefetchInterval(5000)
  const { data: metrics, isLoading } = useQuery<SystemMetrics>({
    queryKey: ['system-metrics'],
    queryFn: async () => {
      const response = await apiClient.get('/settings/system-metrics')
      return response.data
    },
    refetchInterval: metricsInterval,
  })

  if (isLoading) {
    return (
      <div className="system-metrics loading">
        <div className="spinner"></div>
        <p>{t('common.loading')}</p>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="system-metrics error">
        <p>{t('systemMetrics.loadError')}</p>
      </div>
    )
  }

  const getPercentageColor = (percentage: number) => {
    if (percentage < 50) return 'low'
    if (percentage < 80) return 'medium'
    return 'high'
  }

  const formatMB = (mb: number) => {
    if (mb >= 1024) {
      return `${(mb / 1024).toFixed(2)} GB`
    }
    return `${mb.toFixed(2)} MB`
  }

  return (
    <div className="system-metrics">
      <h3 className="section-title">{t('systemMetrics.title')}</h3>
      
      <div className="system-metrics-grid">
        {/* Aktive Container */}
        <div className="metric-card card">
          <div className="metric-icon">
            <MdStorage />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">{t('systemMetrics.activeContainers')}</h4>
            <p className="metric-value">{metrics.active_containers}</p>
            <p className="metric-detail">{t('systemMetrics.pipelineContainers')}</p>
          </div>
        </div>

        {/* Container RAM */}
        <div className="metric-card card">
          <div className="metric-icon">
            <MdMemory />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">{t('systemMetrics.containerRam')}</h4>
            <p className="metric-value">{formatMB(metrics.containers_ram_mb)}</p>
            <p className="metric-detail">{t('systemMetrics.totalUsage')}</p>
          </div>
        </div>

        {/* Container CPU */}
        <div className="metric-card card">
          <div className="metric-icon">
            <MdSpeed />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">{t('systemMetrics.containerCpu')}</h4>
            <p className={`metric-value percentage ${getPercentageColor(metrics.containers_cpu_percent)}`}>
              {metrics.containers_cpu_percent.toFixed(1)}%
            </p>
            <p className="metric-detail">{t('systemMetrics.totalUsage')}</p>
          </div>
        </div>

        {/* API RAM */}
        <div className="metric-card card">
          <div className="metric-icon api">
            <MdDataUsage />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">{t('systemMetrics.apiRam')}</h4>
            <p className="metric-value">{formatMB(metrics.api_ram_mb)}</p>
            <p className="metric-detail">{t('systemMetrics.fastflowApi')}</p>
          </div>
        </div>

        {/* API CPU */}
        <div className="metric-card card">
          <div className="metric-icon api">
            <MdSpeed />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">{t('systemMetrics.apiCpu')}</h4>
            <p className={`metric-value percentage ${getPercentageColor(metrics.api_cpu_percent)}`}>
              {metrics.api_cpu_percent.toFixed(1)}%
            </p>
            <p className="metric-detail">{t('systemMetrics.fastflowApi')}</p>
          </div>
        </div>

        {/* System RAM */}
        <div className="metric-card card">
          <div className="metric-icon system">
            <MdMemory />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">{t('systemMetrics.systemRam')}</h4>
            <p className="metric-value">{formatMB(metrics.system_ram_used_mb)} / {formatMB(metrics.system_ram_total_mb)}</p>
            <div className="usage-bar">
              <div
                className="usage-bar-fill"
                style={{
                  width: `${metrics.system_ram_percent}%`,
                }}
              />
            </div>
            <p className={`metric-detail percentage ${getPercentageColor(metrics.system_ram_percent)}`}>
              {t('systemMetrics.percentUsed', { pct: metrics.system_ram_percent.toFixed(1) })}
            </p>
          </div>
        </div>

        {/* System CPU */}
        <div className="metric-card card">
          <div className="metric-icon system">
            <MdSpeed />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">{t('systemMetrics.systemCpu')}</h4>
            <p className={`metric-value percentage ${getPercentageColor(metrics.system_cpu_percent)}`}>
              {metrics.system_cpu_percent.toFixed(1)}%
            </p>
            <p className="metric-detail">{t('systemMetrics.overallLoad')}</p>
          </div>
        </div>
      </div>

      {/* Container Details */}
      {metrics.container_details.length > 0 && (
        <div className="container-details">
          <h4 className="details-title">{t('systemMetrics.containerDetails')}</h4>
          <div className="container-details-table">
            <table>
              <thead>
                <tr>
                  <th>{t('systemMetrics.pipeline')}</th>
                  <th>{t('systemMetrics.runId')}</th>
                  <th>{t('systemMetrics.containerId')}</th>
                  <th>{t('systemMetrics.ram')}</th>
                  <th>{t('systemMetrics.cpu')}</th>
                  <th>{t('systemMetrics.status')}</th>
                </tr>
              </thead>
              <tbody>
                {metrics.container_details.map((container) => (
                  <tr key={container.run_id}>
                    <td>{container.pipeline_name}</td>
                    <td className="monospace">{container.run_id.substring(0, 8)}...</td>
                    <td className="monospace">{container.container_id}</td>
                    <td>
                      {formatMB(container.ram_mb)}
                      {container.ram_percent > 0 && (
                        <span className="percentage-badge"> ({container.ram_percent.toFixed(1)}%)</span>
                      )}
                    </td>
                    <td>
                      <span className={`cpu-value ${getPercentageColor(container.cpu_percent)}`}>
                        {container.cpu_percent.toFixed(1)}%
                      </span>
                    </td>
                    <td>
                      <span className={`status-badge status-${container.status.toLowerCase()}`}>
                        {container.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
