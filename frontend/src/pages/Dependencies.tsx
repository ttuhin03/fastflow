import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showConfirm } from '../utils/toast'
import { LuRefreshCw, LuShieldCheck, LuSearch, LuChevronDown, LuChevronUp } from 'react-icons/lu'
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
  latest?: string
}

interface VulnRow {
  id?: string
  name?: string
  description?: string
  fix_versions?: string[]
  severity?: string
  [key: string]: unknown
}

interface PipelineDeps {
  pipeline: string
  packages: PackageRow[]
  vulnerabilities?: VulnRow[]
  audit_error?: string
}

type Severity = 'critical' | 'high' | 'medium' | 'low'
const SEVERITY_ORDER: Severity[] = ['critical', 'high', 'medium', 'low']

// TODO(redesign): needs backend — pip-audit results do not always include a
// CVSS severity. Derive a best-effort severity from any `severity`/`cvss` field
// and fall back to "high" so vulnerable packages are never silently counted as 0.
function vulnSeverity(v: VulnRow): Severity {
  const raw = String(
    v.severity ?? (v as { cvss_severity?: string }).cvss_severity ?? ''
  ).toLowerCase()
  if (raw.includes('crit')) return 'critical'
  if (raw.includes('high')) return 'high'
  if (raw.includes('med') || raw.includes('moderate')) return 'medium'
  if (raw.includes('low')) return 'low'
  return 'high'
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

  // Aggregate CVE counts across all pipelines by severity for the KPI row.
  const cveCounts = useMemo(() => {
    const counts: Record<Severity, number> = { critical: 0, high: 0, medium: 0, low: 0 }
    for (const d of displayData ?? []) {
      for (const v of d.vulnerabilities ?? []) {
        counts[vulnSeverity(v)] += 1
      }
    }
    return counts
  }, [displayData])

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

  // The live pip-audit scan is rate-limited and expensive, so confirm first.
  const handleRunSecurityScan = async () => {
    const confirmed = await showConfirm(
      t('dependencies.runSecurityScanConfirm', 'Running a security scan can take a while. Continue?')
    )
    if (confirmed) setAuditRequested(true)
  }

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
          <h1 className="dependencies-title">{t('dependencies.title')}</h1>
        </div>
        <div className="deps-kpi-row">
          {SEVERITY_ORDER.map((s) => (
            <Skeleton key={s} width="100%" height="74px" />
          ))}
        </div>
        <div className="dependencies-actions card">
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
        <div>
          <h1 className="dependencies-title">{t('dependencies.title')}</h1>
          <p className="dependencies-subtitle">
            {t('dependencies.intro')}{' '}
            {auditLastError && (
              <span className="dependencies-subtitle-error">{t('dependencies.lastScanError')}</span>
            )}
            {!auditLastError && subtitleText}
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => { refetch(); refetchAuditLast() }}
          disabled={isFetching || auditLastLoading}
        >
          <LuRefreshCw aria-hidden />
          {isFetching || auditLastLoading ? t('common.loading') : t('dependencies.refresh', 'Refresh')}
        </button>
      </div>

      {/* CVE-summary KPI row */}
      <div className="deps-kpi-row">
        {SEVERITY_ORDER.map((sev) => (
          <div key={sev} className="card deps-kpi">
            <div className="deps-kpi-label">
              <span className={`deps-sev-dot deps-sev-dot--${sev}`} aria-hidden />
              {t(`dependencies.severity.${sev}`, capitalize(sev))}
            </div>
            <div className={`deps-kpi-count mono deps-kpi-count--${sev}`}>
              {showAuditColumn ? cveCounts[sev] : 0}
            </div>
          </div>
        ))}
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
            <LuSearch size={18} />
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
            className="btn btn-primary"
            onClick={handleRunSecurityScan}
            disabled={isReadonly || isFetching}
            title={t('dependencies.runSecurityScanHint', 'Runs a live pip-audit scan — rate-limited and may take a while')}
          >
            <LuShieldCheck size={18} />
            {t('dependencies.runSecurityScan', 'Run security scan')}
          </button>
        </div>
      </div>

      <div className="dependencies-table-wrap">
        {filtered.length === 0 ? (
          <div className="dependencies-empty card">
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
                    aria-expanded={expanded}
                  >
                    {expanded ? <LuChevronUp size={20} /> : <LuChevronDown size={20} />}
                    <span className="pipeline-deps-name mono">{d.pipeline}</span>
                    <span className="pipeline-deps-meta">
                      {packages.length === 1 ? t('dependencies.packagesCount', { count: 1 }) : t('dependencies.packagesCountPlural', { count: packages.length })}
                      {showAuditColumn && (
                        <>
                          {' · '}
                          {vulns.length > 0 ? (
                            <span className="badge badge-error">{vulns.length} {t('dependencies.vulnerabilities').toLowerCase()}</span>
                          ) : (
                            <span className="badge badge-success">{t('dependencies.vulnNone')}</span>
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
                      <div className="table deps-table">
                        <div className="table__head">
                          <span>{t('dependencies.packageLabel')}</span>
                          <span>{t('dependencies.installed', 'Installed')}</span>
                          <span>{t('dependencies.latest', 'Latest')}</span>
                          <span>{t('dependencies.status', 'Status')}</span>
                          <span>{t('dependencies.cve', 'CVE')}</span>
                        </div>
                        {packages.map((p) => {
                          const pkgVulns = vulns.filter(
                            (v) => (v.name && v.name.toLowerCase() === p.name.toLowerCase()) || (v as { package?: string }).package === p.name
                          )
                          const latest = p.latest ?? pkgVulns.find((v) => v.fix_versions?.length)?.fix_versions?.[0]
                          const status = pkgVulns.length > 0
                            ? 'vulnerable'
                            : latest && latest !== p.version
                              ? 'outdated'
                              : 'uptodate'
                          return (
                            <div key={p.name} className="table__row deps-row">
                              <span className="mono deps-pkg">{p.name}</span>
                              <span className="mono deps-version">{p.version ?? p.specifier ?? '—'}</span>
                              {/* TODO(redesign): needs backend — latest version is
                                  not provided; inferred from fix_versions when present. */}
                              <span className="mono deps-latest">{latest ?? '—'}</span>
                              <span>
                                {showAuditColumn ? (
                                  <span className={`badge dot ${statusBadge(status)}`}>
                                    {t(`dependencies.statusLabel.${status}`, statusFallback(status))}
                                  </span>
                                ) : (
                                  '—'
                                )}
                              </span>
                              <span className="mono deps-cve">
                                {pkgVulns.length > 0 ? (
                                  pkgVulns.map((v, i) => (
                                    <span key={i}>
                                      {i > 0 && ', '}
                                      {v.id ? (
                                        <a href={`https://nvd.nist.gov/vuln/detail/${v.id}`} target="_blank" rel="noopener noreferrer" className="deps-cve-link">{v.id}</a>
                                      ) : (
                                        '—'
                                      )}
                                    </span>
                                  ))
                                ) : (
                                  '—'
                                )}
                              </span>
                            </div>
                          )
                        })}
                      </div>
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

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function statusBadge(status: string): string {
  switch (status) {
    case 'vulnerable':
      return 'badge-error'
    case 'outdated':
      return 'badge-warning'
    default:
      return 'badge-success'
  }
}

function statusFallback(status: string): string {
  switch (status) {
    case 'vulnerable':
      return 'vulnerable'
    case 'outdated':
      return 'outdated'
    default:
      return 'up-to-date'
  }
}
