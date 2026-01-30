import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { MdRefresh, MdSecurity, MdSearch, MdExpandMore, MdExpandLess } from 'react-icons/md'
import Skeleton from '../components/Skeleton'
import './Dependencies.css'

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

  const pipelineNames = useMemo(() => (deps ?? []).map((d) => d.pipeline), [deps])

  const filtered = useMemo(() => {
    if (!deps) return []
    let list = deps
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
  }, [deps, filterPipeline, filterVulnsOnly, searchPackage])

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
          <h1>Abhängigkeiten</h1>
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

  return (
    <div className="dependencies-page">
      <div className="dependencies-header">
        <h1>Abhängigkeiten</h1>
        <p className="dependencies-subtitle">
          Libraries und Versionen aller Pipelines mit requirements.txt.
          {auditRequested ? ' Sicherheitsprüfung (pip-audit) wurde ausgeführt.' : ' Klicke auf „Sicherheitsprüfung“, um CVE-Scans zu laden.'}
        </p>
      </div>

      <div className="dependencies-actions card">
        <div className="dependencies-filters">
          <label className="filter-group">
            <span>Pipeline</span>
            <select
              value={filterPipeline}
              onChange={(e) => setFilterPipeline(e.target.value)}
              className="filter-select"
            >
              <option value="">Alle</option>
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
            <span>Nur mit Schwachstellen</span>
          </label>
          <label className="filter-group search-box">
            <MdSearch size={18} />
            <input
              type="text"
              placeholder="Paket suchen…"
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
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <MdRefresh size={18} />
            {isFetching ? 'Laden…' : 'Aktualisieren'}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setAuditRequested(true)}
            disabled={isReadonly || isFetching}
          >
            <MdSecurity size={18} />
            Sicherheitsprüfung ausführen
          </button>
        </div>
      </div>

      <div className="dependencies-table-wrap card">
        {filtered.length === 0 ? (
          <div className="dependencies-empty">
            {deps?.length === 0
              ? 'Keine Pipelines mit requirements.txt gefunden.'
              : 'Keine Einträge passen zu den Filtern.'}
          </div>
        ) : (
          <div className="dependencies-list">
            {filtered.map((d) => {
              const expanded = expandedPipelines.has(d.pipeline)
              const vulns = d.vulnerabilities ?? []
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
                      {d.packages.length} Paket{d.packages.length !== 1 ? 'e' : ''}
                      {auditRequested && (
                        <>
                          {' · '}
                          {vulns.length > 0 ? (
                            <span className="vuln-badge vuln-yes">{vulns.length} Schwachstelle{vulns.length !== 1 ? 'n' : ''}</span>
                          ) : (
                            <span className="vuln-badge vuln-no">Keine</span>
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
                            <th>Paket</th>
                            <th>Version</th>
                            {auditRequested && <th>Schwachstellen</th>}
                          </tr>
                        </thead>
                        <tbody>
                          {d.packages.map((p) => {
                            const pkgVulns = vulns.filter(
                              (v) => (v.name && v.name.toLowerCase() === p.name.toLowerCase()) || (v as { package?: string }).package === p.name
                            )
                            return (
                              <tr key={p.name}>
                                <td><code>{p.name}</code></td>
                                <td>{p.version}</td>
                                {auditRequested && (
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
                      {auditRequested && vulns.length > 0 && (
                        <div className="vuln-summary">
                          <strong>Gefundene Schwachstellen:</strong>
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
