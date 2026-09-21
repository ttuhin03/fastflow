import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import apiClient from '../api/client'
import { getFormatLocale } from '../utils/locale'
import {
  LuDatabase,
  LuFileText,
  LuChartPie,
  LuArchive,
  LuFolder,
  LuBox,
  LuCode,
  LuHardDrive,
} from 'react-icons/lu'
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
  uv_cache_dir?: string
  uv_cache_size_mb?: number
  uv_cache_percentage?: number
  uv_python_install_dir?: string
  uv_python_install_size_mb?: number
  uv_python_percentage?: number
  uv_pre_heat?: boolean
  default_python_version?: string
  /** Shared PVC des Kubernetes-Backends: eigenes Volume, nicht der Gesamtspeicher oben */
  shared_volume_dir?: string
  shared_volume_total_gb?: number
  shared_volume_used_gb?: number
  shared_volume_free_gb?: number
  shared_volume_used_percent?: number
  /** false: UV-Cache-/Python-Größen nicht ermittelt (keine Karten) */
  uv_storage_stats_enabled?: boolean
}

// Ab hier scheitern Runs beim Kopieren ins shared Volume. Eine Stelle für Icon
// und Balken, damit die beiden nicht auseinanderlaufen.
const SHARED_VOLUME_WARN_PERCENT = 90
const SHARED_WARN = (pct?: number) => (pct ?? 0) > SHARED_VOLUME_WARN_PERCENT

interface BreakdownEntry {
  path: string
  size_mb: number
  size_gb: number
  file_count: number
  percent_of_volume: number
  children?: BreakdownEntry[]
  children_omitted?: number
  children_omitted_bytes?: number
}

interface SharedBreakdown {
  dir: string
  available: boolean
  entries: BreakdownEntry[]
  total_gb?: number
  file_count?: number
  duration_seconds?: number
}

/** Die Rechnung läuft im Hintergrund; der Client fragt ihren Zustand ab. */
interface SharedBreakdownState {
  status: 'never' | 'running' | 'done' | 'failed'
  started_at?: string
  finished_at?: string
  elapsed_seconds?: number
  files_seen?: number
  bytes_seen?: number
  error?: string | null
  result?: SharedBreakdown | null
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

  // Zwei Anfragen mit sehr unterschiedlichen Kosten: Das GET liest nur einen
  // Zustand und läuft deshalb immer mit — nur so hängt sich die Anzeige nach
  // einem Reload von selbst wieder an eine laufende Rechnung. Der teure
  // Durchlauf über das ganze Volume wird ausschliesslich per POST angestossen.
  const sharedVolumeKnown = stats?.shared_volume_total_gb !== undefined
  const { data: breakdown, isError: breakdownError } = useQuery<SharedBreakdownState>({
    queryKey: ['storage-shared-breakdown'],
    queryFn: async () => {
      const response = await apiClient.get('/settings/storage/shared-breakdown')
      return response.data
    },
    enabled: sharedVolumeKnown,
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 2000 : false),
    staleTime: 0,
  })
  const queryClient = useQueryClient()
  const startBreakdown = useMutation({
    mutationFn: async () => {
      await apiClient.post('/settings/storage/shared-breakdown')
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['storage-shared-breakdown'] }),
  })
  const breakdownBusy = startBreakdown.isPending || breakdown?.status === 'running'
  const breakdownResult = breakdown?.status === 'done' ? breakdown.result : undefined

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

  // Circular progress ring (52x52 SVG, rotated -90deg). r=21 → circumference ≈ 131.95.
  const RING_R = 21
  const RING_C = 2 * Math.PI * RING_R
  const ringColor = (pct: number) =>
    pct >= 90 ? 'var(--color-error)' : pct >= 70 ? 'var(--color-warning)' : 'var(--color-success)'

  const diskPct =
    stats.total_disk_space_gb > 0
      ? (stats.used_disk_space_gb / stats.total_disk_space_gb) * 100
      : 0

  const rings: { key: string; label: string; pct: number; used: string }[] = [
    {
      key: 'disk',
      label: t('storage.totalStorage'),
      pct: diskPct,
      used: t('storage.diskUsedFree', {
        used: stats.used_disk_space_gb.toFixed(1),
        free: stats.free_disk_space_gb.toFixed(1),
      }),
    },
  ]
  if (stats.database_size_bytes !== undefined && stats.database_size_bytes > 0) {
    rings.push({
      key: 'db',
      label: t('storage.database'),
      pct: stats.database_percentage ?? 0,
      used: t('storage.sizeMb', { size: stats.database_size_mb?.toFixed(1) || '0.0' }),
    })
  }

  return (
    <div className="storage-stats">
      <div className="storage-rings">
        {rings.map((r) => {
          const pct = Math.min(Math.max(r.pct, 0), 100)
          const dash = `${(pct / 100) * RING_C} ${RING_C}`
          return (
            <div key={r.key} className="storage-ring">
              <svg width="52" height="52" viewBox="0 0 52 52" className="storage-ring__svg">
                <circle cx="26" cy="26" r={RING_R} fill="none" stroke="var(--color-surface-3)" strokeWidth="6" />
                <circle
                  cx="26"
                  cy="26"
                  r={RING_R}
                  fill="none"
                  stroke={ringColor(pct)}
                  strokeWidth="6"
                  strokeLinecap="round"
                  strokeDasharray={dash}
                  strokeDashoffset="0"
                />
              </svg>
              <div className="storage-ring__info">
                <div className="storage-ring__label">{r.label}</div>
                <div className="storage-ring__pct mono">{pct.toFixed(0)}%</div>
                <div className="storage-ring__used mono">{r.used}</div>
              </div>
            </div>
          )
        })}
      </div>

      <div className="storage-stats-grid">
        <div className="storage-stat-card card">
          <div className="stat-icon">
            <LuFileText />
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
            <LuDatabase />
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
            <LuChartPie />
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

        {/* Eigenes Volume: der Gesamtspeicher oben stammt von LOGS_DIR und bleibt
            unverdächtig, während hier kein Byte mehr frei ist und jeder Run
            beim Kopieren scheitert. */}
        {stats.shared_volume_total_gb !== undefined && (
          <div className="storage-stat-card card">
            <div className={`stat-icon shared-icon ${SHARED_WARN(stats.shared_volume_used_percent) ? 'shared-warn' : ''}`}>
              <LuHardDrive />
            </div>
            <div className="stat-content">
              <h4 className="stat-label">{t('storage.sharedVolumeTitle')}</h4>
              <p className="stat-value">{stats.shared_volume_total_gb.toFixed(2)} GB</p>
              <div className="disk-usage-bar">
                <div
                  className={`disk-usage-fill shared ${SHARED_WARN(stats.shared_volume_used_percent) ? 'shared-warn' : ''}`}
                  style={{
                    width: `${(stats.shared_volume_used_percent ?? 0).toFixed(1)}%`,
                  }}
                />
              </div>
              <p className="stat-detail">
                {t('storage.diskUsedFree', {
                  used: (stats.shared_volume_used_gb ?? 0).toFixed(2),
                  free: (stats.shared_volume_free_gb ?? 0).toFixed(2),
                })}
              </p>
              <p className="stat-detail-small">{t('storage.sharedVolumeDir')}</p>
            </div>
          </div>
        )}

        {stats.inode_total !== undefined && stats.inode_free !== undefined && (
          <div className="storage-stat-card card">
            <div className={`stat-icon inode-icon ${(stats.inode_used_percent ?? 0) > 90 ? 'inode-warn' : ''}`}>
              <LuFolder />
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
              <LuArchive />
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

        {stats.uv_storage_stats_enabled !== false &&
          stats.uv_cache_dir !== undefined &&
          stats.uv_cache_size_mb !== undefined && (
          <div className="storage-stat-card card">
            <div className="stat-icon">
              <LuBox />
            </div>
            <div className="stat-content">
              <h4 className="stat-label">{t('storage.uvCacheTitle')}</h4>
              <p className="stat-value">
                {t('storage.sizeMb', { size: stats.uv_cache_size_mb.toFixed(2) })}
              </p>
              {stats.uv_cache_percentage !== undefined && (
                <>
                  <div className="disk-usage-bar">
                    <div
                      className="disk-usage-fill uv-cache"
                      style={{
                        width: `${Math.min(stats.uv_cache_percentage, 100).toFixed(1)}%`,
                      }}
                    />
                  </div>
                  <p className={`stat-detail percentage ${getPercentageColor(stats.uv_cache_percentage)}`}>
                    {t('storage.uvPercentOfTotal', {
                      pct: stats.uv_cache_percentage.toFixed(2),
                    })}
                  </p>
                </>
              )}
              <p className="stat-detail storage-path-detail" title={stats.uv_cache_dir}>
                {t('storage.pathLabel')}: {stats.uv_cache_dir}
              </p>
              {stats.uv_pre_heat !== undefined && (
                <p className="stat-detail-small">
                  {stats.uv_pre_heat ? t('storage.preHeatOn') : t('storage.preHeatOff')}
                </p>
              )}
              {stats.default_python_version !== undefined && (
                <p className="stat-detail-small">
                  {t('storage.defaultPython', { version: stats.default_python_version })}
                </p>
              )}
            </div>
          </div>
        )}

        {stats.uv_storage_stats_enabled !== false &&
          stats.uv_python_install_dir !== undefined &&
          stats.uv_python_install_size_mb !== undefined && (
          <div className="storage-stat-card card">
            <div className="stat-icon">
              <LuCode />
            </div>
            <div className="stat-content">
              <h4 className="stat-label">{t('storage.uvPythonTitle')}</h4>
              <p className="stat-value">
                {t('storage.sizeMb', { size: stats.uv_python_install_size_mb.toFixed(2) })}
              </p>
              {stats.uv_python_percentage !== undefined && (
                <>
                  <div className="disk-usage-bar">
                    <div
                      className="disk-usage-fill uv-python"
                      style={{
                        width: `${Math.min(stats.uv_python_percentage, 100).toFixed(1)}%`,
                      }}
                    />
                  </div>
                  <p className={`stat-detail percentage ${getPercentageColor(stats.uv_python_percentage)}`}>
                    {t('storage.uvPercentOfTotal', {
                      pct: stats.uv_python_percentage.toFixed(2),
                    })}
                  </p>
                </>
              )}
              <p className="stat-detail storage-path-detail" title={stats.uv_python_install_dir}>
                {t('storage.pathLabel')}: {stats.uv_python_install_dir}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Was das Volume belegt, beantwortet GET /storage nicht — und ein
          `du -xsh /shared/*` im Pod braucht Cluster-Zugriff, der ausgerechnet
          dann fehlt, wenn das Volume vollläuft. Deshalb hier, auf Klick. */}
      {stats.shared_volume_total_gb !== undefined && (
        <div className="shared-breakdown card">
          <div className="shared-breakdown__head">
            <h4 className="stat-label">{t('storage.sharedBreakdownTitle')}</h4>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => startBreakdown.mutate()}
              disabled={breakdownBusy}
            >
              {breakdownBusy
                ? t('storage.sharedBreakdownRunning')
                : t('storage.sharedBreakdownButton')}
            </button>
          </div>

          {breakdown?.status === 'never' && !startBreakdown.isPending && (
            <p className="stat-detail-small">{t('storage.sharedBreakdownHint')}</p>
          )}
          {breakdown?.status === 'running' && (
            <>
              <p className="stat-detail-small">
                {t('storage.sharedBreakdownRunningFor', {
                  seconds: (breakdown.elapsed_seconds ?? 0).toFixed(0),
                })}
              </p>
              {breakdown.files_seen !== undefined && (
                <p className="stat-detail-small">
                  {t('storage.sharedBreakdownProgress', {
                    files: breakdown.files_seen.toLocaleString(numberLocale),
                    size: ((breakdown.bytes_seen ?? 0) / 1024 ** 3).toFixed(2),
                  })}
                </p>
              )}
            </>
          )}
          {(breakdownError || startBreakdown.isError || breakdown?.status === 'failed') && (
            <p className="stat-detail percentage high">
              {breakdown?.error || t('storage.sharedBreakdownFailed')}
            </p>
          )}
          {breakdown?.status === 'done' && breakdownResult && !breakdownResult.available && (
            <p className="stat-detail-small">{t('storage.sharedBreakdownUnavailable')}</p>
          )}

          {breakdownResult?.available && (
            <>
              <p className="stat-detail-small">
                {t('storage.sharedBreakdownSummary', {
                  files: (breakdownResult.file_count ?? 0).toLocaleString(numberLocale),
                  size: (breakdownResult.total_gb ?? 0).toFixed(2),
                  seconds: (breakdownResult.duration_seconds ?? 0).toFixed(1),
                })}
              </p>
              <ul className="shared-breakdown__list">
                {breakdownResult.entries.map((entry) => (
                  <li key={entry.path} className="shared-breakdown__entry">
                    <div className="shared-breakdown__row">
                      <span className="shared-breakdown__path">{entry.path}</span>
                      <span className="shared-breakdown__size">
                        {entry.size_gb >= 1
                          ? `${entry.size_gb.toFixed(2)} GB`
                          : t('storage.sizeMb', { size: entry.size_mb.toFixed(1) })}
                      </span>
                      <span className="shared-breakdown__meta">
                        {entry.percent_of_volume.toFixed(1)}% ·{' '}
                        {t('storage.sharedBreakdownFiles', {
                          count: entry.file_count.toLocaleString(numberLocale),
                        })}
                      </span>
                    </div>
                    {entry.children && entry.children.length > 0 && (
                      <ul className="shared-breakdown__children">
                        {entry.children.map((child) => (
                          <li key={child.path} className="shared-breakdown__row">
                            <span className="shared-breakdown__path">{child.path}</span>
                            <span className="shared-breakdown__size">
                              {child.size_gb >= 1
                                ? `${child.size_gb.toFixed(2)} GB`
                                : t('storage.sizeMb', { size: child.size_mb.toFixed(1) })}
                            </span>
                            <span className="shared-breakdown__meta">
                              {t('storage.sharedBreakdownFiles', {
                                count: child.file_count.toLocaleString(numberLocale),
                              })}
                            </span>
                          </li>
                        ))}
                        {entry.children_omitted !== undefined && (
                          <li className="shared-breakdown__row shared-breakdown__omitted">
                            {t('storage.sharedBreakdownOmitted', {
                              count: entry.children_omitted,
                              size: (
                                (entry.children_omitted_bytes ?? 0) / (1024 * 1024)
                              ).toFixed(1),
                            })}
                          </li>
                        )}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}
