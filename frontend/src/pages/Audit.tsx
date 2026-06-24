import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import { Navigate } from 'react-router-dom'
import apiClient from '../api/client'
import { getFormatLocale } from '../utils/locale'
import './Audit.css'

interface AuditEntry {
  id: string
  created_at: string
  user_id: string | null
  username: string
  action: string
  resource_type: string
  resource_id: string | null
  details: Record<string, unknown> | null
}

interface AuditResponse {
  entries: AuditEntry[]
  total: number
  page: number
  page_size: number
}

const PAGE_SIZE = 50

/** Derive a 2-letter "kind" pill from the action string (no backend field exists). */
function actionKind(action: string): { kind: string; cls: string } {
  const a = (action || '').toLowerCase()
  if (a.startsWith('run_')) return { kind: 'RUN', cls: 'kind-run' }
  if (a.startsWith('pipeline_')) return { kind: 'CFG', cls: 'kind-cfg' }
  if (a.startsWith('user_')) return { kind: 'USR', cls: 'kind-usr' }
  if (a.startsWith('secret_')) return { kind: 'SEC', cls: 'kind-sec' }
  if (a.startsWith('schedule_')) return { kind: 'SCH', cls: 'kind-sch' }
  if (a.startsWith('settings_') || a.startsWith('sync_')) return { kind: 'SYS', cls: 'kind-sys' }
  if (a.startsWith('auth_') || a.startsWith('login') || a.startsWith('logout')) return { kind: 'AUT', cls: 'kind-aut' }
  return { kind: 'EVT', cls: 'kind-evt' }
}

/** Quote a CSV field, escaping embedded quotes. */
function csvCell(value: unknown): string {
  const s = value == null ? '' : String(value)
  return `"${s.replace(/"/g, '""')}"`
}

export default function Audit() {
  const { t } = useTranslation()
  const { isAdmin } = useAuth()
  const [actionFilter, setActionFilter] = useState('')
  const [resourceTypeFilter, setResourceTypeFilter] = useState('')
  const [sinceFilter, setSinceFilter] = useState('')
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data, isLoading, isError, error } = useQuery<AuditResponse>({
    queryKey: ['audit', actionFilter, resourceTypeFilter, sinceFilter, page],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (actionFilter.trim()) params.set('action', actionFilter.trim())
      if (resourceTypeFilter.trim()) params.set('resource_type', resourceTypeFilter.trim())
      if (sinceFilter.trim()) params.set('since', sinceFilter.trim())
      params.set('limit', String(PAGE_SIZE))
      params.set('offset', String((page - 1) * PAGE_SIZE))
      const response = await apiClient.get(`/audit?${params.toString()}`)
      return response.data
    },
    enabled: isAdmin,
  })

  if (!isAdmin) {
    return <Navigate to="/" replace />
  }

  if (isError) {
    return (
      <div className="audit-page">
        <div className="audit-error card">
          <p>{t('audit.loadError')}: {(error as any)?.response?.data?.detail || (error as Error)?.message}</p>
        </div>
      </div>
    )
  }

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0

  const handleExportCsv = () => {
    if (!data || data.entries.length === 0) return
    const header = ['Timestamp', 'User', 'Action', 'ResourceType', 'Target', 'IP', 'Details']
    const rows = data.entries.map((e) => [
      new Date(e.created_at).toISOString(),
      e.username || '',
      e.action,
      e.resource_type,
      e.resource_id || '',
      '', // TODO(redesign): needs backend — no IP address in the audit API
      e.details && Object.keys(e.details).length > 0 ? JSON.stringify(e.details) : '',
    ])
    const csv = [header, ...rows].map((r) => r.map(csvCell).join(',')).join('\r\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit-log-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="audit-page">
      <div className="audit-header">
        <div>
          <h2 className="audit-title">{t('audit.title')}</h2>
          <p className="audit-description">
            {t('audit.subtitle', 'Immutable record of every workspace action')}
          </p>
        </div>
        <button
          type="button"
          className="btn btn-outlined audit-export-btn"
          onClick={handleExportCsv}
          disabled={!data || data.entries.length === 0}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3v12M7 10l5 5 5-5M5 21h14" />
          </svg>
          {t('audit.exportCsv', 'Export CSV')}
        </button>
      </div>

      {/* Filter bar: inline search + resource/date filters */}
      <div className="audit-filters">
        <div className="audit-search">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="M21 21l-4-4" />
          </svg>
          <input
            id="audit-action"
            type="text"
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); setPage(1) }}
            placeholder={t('audit.filterActionsPlaceholder', 'Filter actions…')}
          />
        </div>
        <input
          id="audit-resource"
          type="text"
          className="audit-filter-input"
          value={resourceTypeFilter}
          onChange={(e) => { setResourceTypeFilter(e.target.value); setPage(1) }}
          placeholder={t('audit.resourceType')}
        />
        <input
          id="audit-since"
          type="datetime-local"
          className="audit-filter-input"
          value={sinceFilter}
          onChange={(e) => { setSinceFilter(e.target.value); setPage(1) }}
          aria-label={t('audit.since')}
        />
      </div>

      {isLoading ? (
        <div className="audit-loading">{t('common.loading')}</div>
      ) : data && data.entries.length > 0 ? (
        <>
          <div className="table audit-table">
            <div className="table__head audit-table__head">
              <span>{t('audit.time')}</span>
              <span>{t('audit.user')}</span>
              <span>{t('audit.action')}</span>
              <span>{t('audit.target', 'Target')}</span>
              <span className="audit-col-ip">{t('audit.ip', 'IP')}</span>
            </div>
            {data.entries.map((entry) => {
              const { kind, cls } = actionKind(entry.action)
              const hasDetails = entry.details && Object.keys(entry.details).length > 0
              const isOpen = expanded === entry.id
              return (
                <div key={entry.id}>
                  <div
                    className={`table__row audit-table__row${hasDetails ? ' clickable' : ''}`}
                    onClick={hasDetails ? () => setExpanded(isOpen ? null : entry.id) : undefined}
                    title={hasDetails ? JSON.stringify(entry.details) : undefined}
                  >
                    <span className="audit-cell-time mono">
                      {new Date(entry.created_at).toLocaleString(getFormatLocale(), { timeZone: 'UTC' })}
                    </span>
                    <span className="audit-cell-user">{entry.username || '-'}</span>
                    <span className="audit-cell-action">
                      <span className={`audit-kind ${cls}`}>{kind}</span>
                      <span className="mono audit-action-name">{entry.action}</span>
                    </span>
                    <span className="mono audit-cell-target" title={entry.resource_id || undefined}>
                      {entry.resource_id || `${entry.resource_type}`}
                    </span>
                    {/* TODO(redesign): needs backend — IP address is not present in the audit API */}
                    <span className="mono audit-cell-ip">—</span>
                  </div>
                  {isOpen && hasDetails && (
                    <div className="audit-details-row">
                      <pre>{JSON.stringify(entry.details, null, 2)}</pre>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          <div className="audit-pagination">
            <span className="audit-pagination-info">
              {t('audit.pagination', {
                from: (page - 1) * PAGE_SIZE + 1,
                to: Math.min(page * PAGE_SIZE, data.total),
                total: data.total,
              })}
            </span>
            <div className="audit-pagination-buttons">
              <button
                type="button"
                className="btn btn-outlined btn-sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                {t('audit.prev')}
              </button>
              <span className="audit-page-num">
                {t('audit.page', { page, total: totalPages || 1 })}
              </span>
              <button
                type="button"
                className="btn btn-outlined btn-sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                {t('audit.next')}
              </button>
            </div>
          </div>
        </>
      ) : (
        <div className="audit-empty card">
          <p>{t('audit.noEntries')}</p>
        </div>
      )}
    </div>
  )
}
