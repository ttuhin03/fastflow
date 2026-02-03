import { useQuery } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { MdStorage, MdDescription, MdDataUsage, MdArchive } from 'react-icons/md'
import './StorageStats.css'

interface StorageStats {
  log_files_count: number
  log_files_size_mb: number
  total_disk_space_gb: number
  used_disk_space_gb: number
  free_disk_space_gb: number
  log_files_percentage: number
  database_size_bytes?: number
  database_size_mb?: number
  database_size_gb?: number
  database_percentage?: number
}

export default function StorageStats() {
  const storageInterval = useRefetchInterval(30000)
  const { data: stats, isLoading } = useQuery<StorageStats>({
    queryKey: ['storage-stats'],
    queryFn: async () => {
      const response = await apiClient.get('/settings/storage')
      return response.data
    },
    refetchInterval: storageInterval,
  })

  if (isLoading) {
    return (
      <div className="storage-stats loading">
        <div className="spinner"></div>
        <p>Laden...</p>
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="storage-stats error">
        <p>Speicherplatz-Statistiken konnten nicht geladen werden</p>
      </div>
    )
  }

  const getPercentageColor = (percentage: number) => {
    if (percentage < 10) return 'low'
    if (percentage < 30) return 'medium'
    return 'high'
  }

  return (
    <div className="storage-stats">
      <div className="storage-stats-grid">
        <div className="storage-stat-card card">
          <div className="stat-icon">
            <MdDescription />
          </div>
          <div className="stat-content">
            <h4 className="stat-label">Log-Dateien</h4>
            <p className="stat-value">{stats.log_files_count.toLocaleString()}</p>
            <p className="stat-detail">{stats.log_files_size_mb.toFixed(2)} MB</p>
          </div>
        </div>

        <div className="storage-stat-card card">
          <div className="stat-icon">
            <MdStorage />
          </div>
          <div className="stat-content">
            <h4 className="stat-label">Log-Anteil</h4>
            <p className={`stat-value percentage ${getPercentageColor(stats.log_files_percentage)}`}>
              {stats.log_files_percentage.toFixed(2)}%
            </p>
            <p className="stat-detail">vom Gesamtspeicher</p>
          </div>
        </div>

        <div className="storage-stat-card card">
          <div className="stat-icon">
            <MdDataUsage />
          </div>
          <div className="stat-content">
            <h4 className="stat-label">Gesamtspeicher</h4>
            <p className="stat-value">{stats.total_disk_space_gb.toFixed(2)} GB</p>
            <div className="disk-usage-bar">
              <div
                className="disk-usage-fill"
                style={{
                  width: `${((stats.used_disk_space_gb / stats.total_disk_space_gb) * 100).toFixed(1)}%`,
                }}
              />
            </div>
            <p className="stat-detail">
              {stats.used_disk_space_gb.toFixed(2)} GB verwendet,{' '}
              {stats.free_disk_space_gb.toFixed(2)} GB frei
            </p>
          </div>
        </div>

        {stats.database_size_bytes !== undefined && stats.database_size_bytes > 0 && (
          <div className="storage-stat-card card">
            <div className="stat-icon database-icon">
              <MdArchive />
            </div>
            <div className="stat-content">
              <h4 className="stat-label">Datenbank</h4>
              <p className="stat-value">{stats.database_size_mb?.toFixed(2) || '0.00'} MB</p>
              {stats.database_size_gb !== undefined && stats.database_size_gb >= 1 && (
                <p className="stat-detail-small">
                  ({stats.database_size_gb.toFixed(2)} GB)
                </p>
              )}
              {stats.database_percentage !== undefined && stats.database_percentage > 0 && (
                <>
                  <div className="disk-usage-bar">
                    <div
                      className="disk-usage-fill database"
                      style={{
                        width: `${stats.database_percentage.toFixed(1)}%`,
                      }}
                    />
                  </div>
                  <p className={`stat-detail percentage ${getPercentageColor(stats.database_percentage)}`}>
                    {stats.database_percentage.toFixed(2)}% vom Gesamtspeicher
                  </p>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
