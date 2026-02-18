import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { MdRefresh, MdSecurity, MdSearch, MdExpandMore, MdExpandLess } from 'react-icons/md'
import Skeleton from '../components/Skeleton'
import './Dependencies.css'

interface DependencyAuditLast {
  last_scan_at: string | null
  results: PipelineDeps[]
}

interface PackageRow {
  name: string
  specifier: string
  version: string
}

interface VulnRow {
  id?: string
  name?: string
  description?: string
  fix_versions?: string[]
  [key: string]: unknown
}

interface PipelineDeps {
  pipeline: string
  packages: PackageRow[]
  vulnerabilities?: VulnRow[]
  audit_error?: string
}

export default function Dependencies() {
  const { t } = useTranslation()
  const { isReadonly } = useAuth()
  const [auditRequested, setAuditRequested] = useState(false)
  const [filterPipeline, setFilterPipeline] = useState<string>('')
  const [filterVulnsOnly, setFilterVulnsOnly] = useState(false)
  const [searchPackage, setSearchPackage] = useState('')
  const [expandedPipelines, setExpandedPipelines] = useState<Set<string>>(new Set())

  const { data: deps, isLoading, isFetching, refetch } = useQuery<PipelineDeps[]>({
    queryKey: ['pipelines-dependencies', auditRequested],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines/dependencies', {
        params: { audit: auditRequested },
      })
      return response.data
    },
  })

  const {
    data: auditLast,
    isLoading: auditLastLoading,
    isError: auditLastError,
    refetch: refetchAuditLast,
  } = useQuery<DependencyAuditLast>({
    queryKey: ['settings', 'dependency-audit-last'],
    queryFn: async () => {
      const r = await apiClient.get('/settings/dependency-audit-last')
      return r.data
    },
    staleTime: 60 * 1000,
  })

  const displayData = useMemo((): PipelineDeps[] | undefined => {
    if (auditRequested && deps && deps.length > 0) return deps
    if (auditLast?.last_scan_at && auditLast.results?.length) return auditLast.results
    return deps ?? undefined
  }, [auditRequested, deps, auditLast?.last_scan_at, auditLast?.results])

  const showAuditColumn = Boolean(
    (auditRequested && deps) || (auditLast?.last_scan_at && auditLast?.results?.length)
  )

  const pipelineNames = useMemo(() => (displayData ?? []).map((d) => d.pipeline), [displayData])

  const filtered = useMemo(() => {
    if (!displayData) return []
    let list = displayData
    if (filterPipeline) {
      list = list.filter((d) => d.pipeline === filterPipeline)
    }
    if (filterVulnsOnly) {
      list = list.filter((d) => (d.vulnerabilities?.length ?? 0) > 0)
    }
    if (searchPackage.trim()) {
      const q = searchPackage.trim().toLowerCase()
      list = list.map((d) => ({
        ...d,
        packages: d.packages.filter((p) => p.name.toLowerCase().includes(q)),
      })).filter((d) => d.packages.length > 0)
    }
    return list
  }, [displayData, filterPipeline, filterVulnsOnly, searchPackage])

  const toggleExpanded = (name: string) => {
    setExpandedPipelines((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  if (isLoading) {
    return (
      <div className="dependencies-page">
        <div className="dependencies-header">
          <h1>{t('dependencies.title')}</h1>
        </div>
        <div className="dependencies-filters card">
          <Skeleton width="100%" height="40px" />
          <Skeleton width="100%" height="40px" />
        </div>
        <div className="dependencies-table-wrap card">
          <Skeleton width="100%" height="200px" />
        </div>
      </div>
    )
  }

  const subtitleText = auditRequested
    ? t('dependencies.scanDone')
    : auditLast?.last_scan_at && auditLast?.results?.length
      ? t('dependencies.lastScan', { date: new Date(auditLast.last_scan_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) })
      : t('dependencies.scanPromptOrResults')

  return (
    <div className="dependencies-page">
      <div className="dependencies-header">
        <h1>{t('dependencies.title')}</h1>
        <p className="dependencies-subtitle">
          {t('dependencies.intro')}{' '}
          {auditLastError && (
            <span className="dependencies-subtitle-error">{t('dependencies.lastScanError')}</span>
          )}
          {!auditLastError && subtitleText}
        </p>
      </div>

      <div className="dependencies-actions card">
        <div className="dependencies-filters">
          <label className="filter-group">
            <span>{t('dependencies.pipeline')}</span>
            <select
              value={filterPipeline}
              onChange={(e) => setFilterPipeline(e.target.value)}
              className="filter-select"
            >
              <option value="">{t('dependencies.all')}</option>
              {pipelineNames.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="filter-group filter-checkbox">
            <input
              type="checkbox"
              checked={filterVulnsOnly}
              onChange={(e) => setFilterVulnsOnly(e.target.checked)}
            />
            <span>{t('dependencies.vulnsOnly')}</span>
          </label>
          <label className="filter-group search-box">
            <MdSearch size={18} />
            <input
              type="text"
              placeholder={t('dependencies.searchPackage')}
              value={searchPackage}
              onChange={(e) => setSearchPackage(e.target.value)}
              className="filter-input"
            />
          </label>
        </div>
        <div className="dependencies-buttons">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => { refetch(); refetchAuditLast() }}
            disabled={isFetching || auditLastLoading}
          >
            <MdRefresh size={18} />
            {isFetching || auditLastLoading ? t('common.loading') : t('dependencies.update')}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setAuditRequested(true)}
            disabled={isReadonly || isFetching}
          >
            <MdSecurity size={18} />
            {t('dependencies.runSecurityScan')}
          </button>
        </div>
      </div>

      <div className="dependencies-table-wrap card">
        {filtered.length === 0 ? (
          <div className="dependencies-empty">
            {!displayData?.length
              ? (auditLast?.results?.length ? t('dependencies.noEntries') : t('dependencies.noPipelinesWithRequirements'))
              : t('dependencies.noEntries')}
          </div>
        ) : (
          <div className="dependencies-list">
            {filtered.map((d) => {
              const expanded = expandedPipelines.has(d.pipeline)
              const vulns = d.vulnerabilities ?? []
              const packages = d.packages ?? []
              return (
                <div key={d.pipeline} className="pipeline-deps-block">
                  <button
                    type="button"
                    className="pipeline-deps-head"
                    onClick={() => toggleExpanded(d.pipeline)}
                  >
                    {expanded ? <MdExpandLess size={20} /> : <MdExpandMore size={20} />}
                    <span className="pipeline-deps-name">{d.pipeline}</span>
                    <span className="pipeline-deps-meta">
                      {packages.length === 1 ? t('dependencies.packagesCount', { count: 1 }) : t('dependencies.packagesCountPlural', { count: packages.length })}
                      {showAuditColumn && (
                        <>
                          {' · '}
                          {vulns.length > 0 ? (
                            <span className="vuln-badge vuln-yes">{vulns.length} {t('dependencies.vulnerabilities').toLowerCase()}</span>
                          ) : (
                            <span className="vuln-badge vuln-no">{t('dependencies.vulnNone')}</span>
                          )}
                        </>
                      )}
                    </span>
                  </button>
                  {expanded && (
                    <div className="pipeline-deps-body">
                      {d.audit_error && (
                        <div className="audit-error">{d.audit_error}</div>
                      )}
                      <table className="deps-table">
                        <thead>
                          <tr>
                            <th>{t('dependencies.packageLabel')}</th>
                            <th>{t('dependencies.versionLabel')}</th>
                            {showAuditColumn && <th>{t('dependencies.vulnerabilities')}</th>}
                          </tr>
                        </thead>
                        <tbody>
                          {packages.map((p) => {
                            const pkgVulns = vulns.filter(
                              (v) => (v.name && v.name.toLowerCase() === (p as PackageRow).name.toLowerCase()) || (v as { package?: string }).package === (p as PackageRow).name
                            )
                            return (
                              <tr key={(p as PackageRow).name}>
                                <td><code>{(p as PackageRow).name}</code></td>
                                <td>{(p as PackageRow).version ?? (p as PackageRow).specifier ?? '—'}</td>
                                {showAuditColumn && (
                                  <td>
                                    {pkgVulns.length > 0 ? (
                                      <ul className="vuln-list">
                                        {pkgVulns.map((v, i) => (
                                          <li key={i}>
                                            {v.id ? (
                                              <a href={`https://nvd.nist.gov/vuln/detail/${v.id}`} target="_blank" rel="noopener noreferrer">{v.id}</a>
                                            ) : (
                                              v.description || '—'
                                            )}
                                          </li>
                                        ))}
                                      </ul>
                                    ) : vulns.length > 0 ? (
                                      '—'
                                    ) : (
                                      '—'
                                    )}
                                  </td>
                                )}
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                      {showAuditColumn && vulns.length > 0 && (
                        <div className="vuln-summary">
                          <strong>{t('dependencies.foundVulns')}</strong>
                          <ul>
                            {vulns.map((v, i) => (
                              <li key={i}>
                                {v.id && (
                                  <a href={`https://nvd.nist.gov/vuln/detail/${v.id}`} target="_blank" rel="noopener noreferrer">{v.id}</a>
                                )}
                                {v.name && ` (${v.name})`}
                                {v.description && ` — ${String(v.description).slice(0, 120)}${String(v.description).length > 120 ? '…' : ''}`}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
