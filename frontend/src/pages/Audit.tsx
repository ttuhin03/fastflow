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

export default function Audit() {
  const { t } = useTranslation()
  const { isAdmin } = useAuth()
  const [actionFilter, setActionFilter] = useState('')
  const [resourceTypeFilter, setResourceTypeFilter] = useState('')
  const [sinceFilter, setSinceFilter] = useState('')
  const [page, setPage] = useState(1)

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

  return (
    <div className="audit-page">
      <h2 className="audit-title">{t('audit.title')}</h2>
      <p className="audit-description">{t('audit.description')}</p>

      <div className="audit-filters card">
        <div className="audit-filter-row">
          <label htmlFor="audit-action">{t('audit.action')}</label>
          <input
            id="audit-action"
            type="text"
            value={actionFilter}
            onChange={(e) => { setActionFilter(e.target.value); setPage(1) }}
            placeholder="z.B. run_start, run_cancel"
            className="audit-input"
          />
        </div>
        <div className="audit-filter-row">
          <label htmlFor="audit-resource">{t('audit.resourceType')}</label>
          <input
            id="audit-resource"
            type="text"
            value={resourceTypeFilter}
            onChange={(e) => { setResourceTypeFilter(e.target.value); setPage(1) }}
            placeholder="z.B. pipeline, run, user, settings"
            className="audit-input"
          />
        </div>
        <div className="audit-filter-row">
          <label htmlFor="audit-since">{t('audit.since')}</label>
          <input
            id="audit-since"
            type="datetime-local"
            value={sinceFilter}
            onChange={(e) => { setSinceFilter(e.target.value); setPage(1) }}
            className="audit-input"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="audit-loading">{t('common.loading')}</div>
      ) : data && data.entries.length > 0 ? (
        <>
          <div className="audit-table-container card">
            <table className="audit-table">
              <thead>
                <tr>
                  <th>{t('audit.time')}</th>
                  <th>{t('audit.user')}</th>
                  <th>{t('audit.action')}</th>
                  <th>{t('audit.resourceType')}</th>
                  <th>{t('audit.resourceId')}</th>
                  <th>{t('audit.details')}</th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((entry) => (
                  <tr key={entry.id}>
                    <td className="audit-time">
                      {new Date(entry.created_at).toLocaleString(getFormatLocale(), { timeZone: 'UTC' })} UTC
                    </td>
                    <td>{entry.username || '-'}</td>
                    <td><code className="audit-action-badge">{entry.action}</code></td>
                    <td>{entry.resource_type}</td>
                    <td className="audit-resource-id">{entry.resource_id || '-'}</td>
                    <td className="audit-details">
                      {entry.details && Object.keys(entry.details).length > 0 ? (
                        <pre>{JSON.stringify(entry.details)}</pre>
                      ) : (
                        '-'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
