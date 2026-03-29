import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { getFormatLocale } from '../utils/locale'
import { MdStorage, MdDescription, MdDataUsage, MdArchive, MdFolder } from 'react-icons/md'
import './StorageStats.css'

interface StorageStatsData {
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
  inode_total?: number
  inode_free?: number
  inode_used?: number
  inode_used_percent?: number
}

export default function StorageStats() {
  const { t } = useTranslation()
  const numberLocale = getFormatLocale()
  const storageInterval = useRefetchInterval(30000)
  const { data: stats, isLoading } = useQuery<StorageStatsData>({
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
        <p>{t('common.loading')}</p>
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="storage-stats error">
        <p>{t('storage.loadError')}</p>
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
            <h4 className="stat-label">{t('storage.logFiles')}</h4>
            <p className="stat-value">{stats.log_files_count.toLocaleString(numberLocale)}</p>
            <p className="stat-detail">
              {t('storage.sizeMb', { size: stats.log_files_size_mb.toFixed(2) })}
            </p>
          </div>
        </div>

        <div className="storage-stat-card card">
          <div className="stat-icon">
            <MdStorage />
          </div>
          <div className="stat-content">
            <h4 className="stat-label">{t('storage.logShare')}</h4>
            <p className={`stat-value percentage ${getPercentageColor(stats.log_files_percentage)}`}>
              {stats.log_files_percentage.toFixed(2)}%
            </p>
            <p className="stat-detail">{t('storage.ofTotalStorage')}</p>
          </div>
        </div>

        <div className="storage-stat-card card">
          <div className="stat-icon">
            <MdDataUsage />
          </div>
          <div className="stat-content">
            <h4 className="stat-label">{t('storage.totalStorage')}</h4>
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
              {t('storage.diskUsedFree', {
                used: stats.used_disk_space_gb.toFixed(2),
                free: stats.free_disk_space_gb.toFixed(2),
              })}
            </p>
          </div>
        </div>

        {stats.inode_total !== undefined && stats.inode_free !== undefined && (
          <div className="storage-stat-card card">
            <div className={`stat-icon inode-icon ${(stats.inode_used_percent ?? 0) > 90 ? 'inode-warn' : ''}`}>
              <MdFolder />
            </div>
            <div className="stat-content">
              <h4 className="stat-label">{t('storage.inodesDfTitle')}</h4>
              <p className={`stat-value percentage ${getPercentageColor(stats.inode_used_percent ?? 0)}`}>
                {stats.inode_used_percent !== undefined
                  ? t('storage.inodeUsedPercent', { pct: stats.inode_used_percent.toFixed(1) })
                  : t('storage.inodePercentUnavailable')}
              </p>
              <div className="disk-usage-bar">
                <div
                  className={`disk-usage-fill inode ${(stats.inode_used_percent ?? 0) > 90 ? 'inode-warn' : ''}`}
                  style={{
                    width: `${(stats.inode_used_percent ?? 0).toFixed(1)}%`,
                  }}
                />
              </div>
              <p className="stat-detail">
                {t('storage.inodeFreeOfTotal', {
                  free: stats.inode_free.toLocaleString(numberLocale),
                  total: stats.inode_total.toLocaleString(numberLocale),
                })}
              </p>
            </div>
          </div>
        )}

        {stats.database_size_bytes !== undefined && stats.database_size_bytes > 0 && (
          <div className="storage-stat-card card">
            <div className="stat-icon database-icon">
              <MdArchive />
            </div>
            <div className="stat-content">
              <h4 className="stat-label">{t('storage.database')}</h4>
              <p className="stat-value">
                {t('storage.sizeMb', { size: stats.database_size_mb?.toFixed(2) || '0.00' })}
              </p>
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
                    {t('storage.databasePercentOfTotal', {
                      pct: stats.database_percentage.toFixed(2),
                    })}
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
