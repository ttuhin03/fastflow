import { useQuery } from '@tanstack/react-query'
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
  const { data: metrics, isLoading } = useQuery<SystemMetrics>({
    queryKey: ['system-metrics'],
    queryFn: async () => {
      const response = await apiClient.get('/settings/system-metrics')
      return response.data
    },
    refetchInterval: 5000, // Alle 5 Sekunden aktualisieren
  })

  if (isLoading) {
    return (
      <div className="system-metrics loading">
        <div className="spinner"></div>
        <p>Laden...</p>
      </div>
    )
  }

  if (!metrics) {
    return (
      <div className="system-metrics error">
        <p>System-Metriken konnten nicht geladen werden</p>
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
      <h3 className="section-title">System-Metriken</h3>
      
      <div className="system-metrics-grid">
        {/* Aktive Container */}
        <div className="metric-card card">
          <div className="metric-icon">
            <MdStorage />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">Aktive Container</h4>
            <p className="metric-value">{metrics.active_containers}</p>
            <p className="metric-detail">Pipeline-Container</p>
          </div>
        </div>

        {/* Container RAM */}
        <div className="metric-card card">
          <div className="metric-icon">
            <MdMemory />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">Container RAM</h4>
            <p className="metric-value">{formatMB(metrics.containers_ram_mb)}</p>
            <p className="metric-detail">Gesamtverbrauch</p>
          </div>
        </div>

        {/* Container CPU */}
        <div className="metric-card card">
          <div className="metric-icon">
            <MdSpeed />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">Container CPU</h4>
            <p className={`metric-value percentage ${getPercentageColor(metrics.containers_cpu_percent)}`}>
              {metrics.containers_cpu_percent.toFixed(1)}%
            </p>
            <p className="metric-detail">Gesamtverbrauch</p>
          </div>
        </div>

        {/* API RAM */}
        <div className="metric-card card">
          <div className="metric-icon api">
            <MdDataUsage />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">API RAM</h4>
            <p className="metric-value">{formatMB(metrics.api_ram_mb)}</p>
            <p className="metric-detail">FastFlow API</p>
          </div>
        </div>

        {/* API CPU */}
        <div className="metric-card card">
          <div className="metric-icon api">
            <MdSpeed />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">API CPU</h4>
            <p className={`metric-value percentage ${getPercentageColor(metrics.api_cpu_percent)}`}>
              {metrics.api_cpu_percent.toFixed(1)}%
            </p>
            <p className="metric-detail">FastFlow API</p>
          </div>
        </div>

        {/* System RAM */}
        <div className="metric-card card">
          <div className="metric-icon system">
            <MdMemory />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">System RAM</h4>
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
              {metrics.system_ram_percent.toFixed(1)}% verwendet
            </p>
          </div>
        </div>

        {/* System CPU */}
        <div className="metric-card card">
          <div className="metric-icon system">
            <MdSpeed />
          </div>
          <div className="metric-content">
            <h4 className="metric-label">System CPU</h4>
            <p className={`metric-value percentage ${getPercentageColor(metrics.system_cpu_percent)}`}>
              {metrics.system_cpu_percent.toFixed(1)}%
            </p>
            <p className="metric-detail">Gesamtauslastung</p>
          </div>
        </div>
      </div>

      {/* Container Details */}
      {metrics.container_details.length > 0 && (
        <div className="container-details">
          <h4 className="details-title">Container-Details</h4>
          <div className="container-details-table">
            <table>
              <thead>
                <tr>
                  <th>Pipeline</th>
                  <th>Run ID</th>
                  <th>Container ID</th>
                  <th>RAM</th>
                  <th>CPU</th>
                  <th>Status</th>
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
