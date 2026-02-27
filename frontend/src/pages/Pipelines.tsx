import { useRef, useState, useLayoutEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError } from '../utils/toast'
import { MdInfo, MdPlayArrow, MdSchedule, MdLock, MdExtension, MdAccountTree } from 'react-icons/md'
import RunStatusCircles from '../components/RunStatusCircles'
import Skeleton from '../components/Skeleton'
import Runs from './Runs'
import Scheduler from './Scheduler'
import Secrets from './Secrets'
import Dependencies from './Dependencies'
import './Pipelines.css'

export type PipelinesSection = 'pipelines' | 'runs' | 'scheduler' | 'secrets' | 'dependencies'

interface Pipeline {
  name: string
  has_requirements: boolean
  last_cache_warmup: string | null
  total_runs: number
  successful_runs: number
  failed_runs: number
  enabled: boolean
  metadata: {
    cpu_hard_limit?: number
    mem_hard_limit?: string
    cpu_soft_limit?: number
    mem_soft_limit?: string
    description?: string
    tags?: string[]
  }
}

export default function Pipelines() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const section = (searchParams.get('section') as PipelinesSection) || 'pipelines'
  const setSection = (s: PipelinesSection) => {
    const np = new URLSearchParams(searchParams)
    np.set('section', s)
    setSearchParams(np, { replace: true })
  }
  const [tagsFilter, setTagsFilter] = useState('')

  const sectionItems: { id: PipelinesSection; labelKey: string; icon: React.ReactNode }[] = [
    { id: 'pipelines', labelKey: 'nav.pipelines', icon: <MdAccountTree /> },
    { id: 'runs', labelKey: 'pipelines.sectionRuns', icon: <MdPlayArrow /> },
    { id: 'scheduler', labelKey: 'pipelines.sectionScheduler', icon: <MdSchedule /> },
    { id: 'secrets', labelKey: 'pipelines.sectionSecrets', icon: <MdLock /> },
    { id: 'dependencies', labelKey: 'pipelines.sectionDependencies', icon: <MdExtension /> },
  ]

  const trayRef = useRef<HTMLDivElement>(null)
  const [indicator, setIndicator] = useState({ left: 0, width: 0 })

  useLayoutEffect(() => {
    const tray = trayRef.current
    if (!tray) return
    const pill = tray.querySelector<HTMLElement>(`[data-section="${section}"]`)
    if (!pill) return
    const tr = tray.getBoundingClientRect()
    const pr = pill.getBoundingClientRect()
    setIndicator({ left: pr.left - tr.left, width: pr.width })
  }, [section])

  const pipelinesInterval = useRefetchInterval(5000)
  const tagsParam = tagsFilter.trim() || undefined
  const { data: pipelines, isLoading } = useQuery<Pipeline[]>({
    queryKey: ['pipelines', tagsParam],
    queryFn: async () => {
      const response = await apiClient.get('/pipelines', {
        params: tagsParam ? { tags: tagsParam } : {},
      })
      return response.data
    },
    refetchInterval: pipelinesInterval,
  })

  const [startingPipeline, setStartingPipeline] = useState<string | null>(null)

  const startPipelineMutation = useMutation({
    mutationFn: async (name: string) => {
      const response = await apiClient.post(`/pipelines/${name}/run`, {
        env_vars: {},
        parameters: {},
      })
      return response.data
    },
    onSuccess: async (data: { id: string }) => {
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      setStartingPipeline(null)
      navigate(`/runs/${data.id}`)
    },
    onError: (error: any) => {
      setStartingPipeline(null)
      showError(t('pipelines.startError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const handleStartPipeline = (name: string) => {
    if (startingPipeline) return
    setStartingPipeline(name)
    startPipelineMutation.mutate(name)
  }

  const renderNav = () => (
    <nav className="pipelines-nav" role="tablist" aria-label={t('pipelines.sectionLabel')}>
      <div ref={trayRef} className="pipelines-nav-tray">
        <div
          className="pipelines-nav-indicator"
          style={{
            left: indicator.left,
            width: indicator.width,
          }}
          aria-hidden
        />
        {sectionItems.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            data-section={item.id}
            aria-selected={section === item.id}
            className={`pipelines-nav-pill ${section === item.id ? 'active' : ''}`}
            onClick={() => setSection(item.id)}
          >
            {item.icon}
            <span>{t(item.labelKey)}</span>
          </button>
        ))}
      </div>
    </nav>
  )

  if (section === 'runs') {
    return (
      <div className="pipelines-page">
        {renderNav()}
        <div className="pipelines-content pipelines-embedded">
          <Runs />
        </div>
      </div>
    )
  }
  if (section === 'scheduler') {
    return (
      <div className="pipelines-page">
        {renderNav()}
        <div className="pipelines-content pipelines-embedded">
          <Scheduler />
        </div>
      </div>
    )
  }
  if (section === 'secrets') {
    return (
      <div className="pipelines-page">
        {renderNav()}
        <div className="pipelines-content pipelines-embedded">
          <Secrets />
        </div>
      </div>
    )
  }
  if (section === 'dependencies') {
    return (
      <div className="pipelines-page">
        {renderNav()}
        <div className="pipelines-content pipelines-embedded">
          <Dependencies />
        </div>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="pipelines-page">
        {renderNav()}
        <div className="pipelines-content">
          <div className="pipelines">
            <div className="pipelines-grid">
              {[1, 2, 3].map((i) => (
                <div key={i} className="pipeline-card card pipeline-card-compact">
                  <div className="pipeline-header">
                    <Skeleton width="60%" height="24px" />
                    <Skeleton width="60px" height="24px" variant="rectangular" />
                  </div>
                  <Skeleton width="100%" height="28px" />
                  <div className="pipeline-actions">
                    <Skeleton width="50%" height="36px" />
                    <Skeleton width="50%" height="36px" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="pipelines-page">
      {renderNav()}
      <div className="pipelines-content">
    <div className="pipelines">
      <div className="pipelines-filter-row">
        <label htmlFor="pipelines-tags-filter" className="pipelines-filter-label">
          {t('pipelines.filterByTags')}:
        </label>
        <input
          id="pipelines-tags-filter"
          type="text"
          value={tagsFilter}
          onChange={(e) => setTagsFilter(e.target.value)}
          placeholder={t('pipelines.filterByTagsPlaceholder')}
          className="pipelines-tags-input"
        />
      </div>
      {pipelines && pipelines.length > 0 ? (
        <div className="pipelines-grid">
          {pipelines.map((pipeline, index) => (
            <div key={pipeline.name} className="pipeline-card card pipeline-card-compact" style={{ animationDelay: `${index * 0.04}s` }}>
              <div className="pipeline-header">
                <h3 className="pipeline-name">{pipeline.name}</h3>
                <span className={`badge ${pipeline.enabled ? 'badge-success' : 'badge-secondary'}`}>
                  {pipeline.enabled ? 'Aktiv' : 'Inaktiv'}
                </span>
              </div>
              <div className="pipeline-recent-runs">
                <span className="recent-runs-label">Letzte Runs:</span>
                <RunStatusCircles pipelineName={pipeline.name} />
              </div>
              <div className="pipeline-actions">
                {!isReadonly && (
                  <button
                    onClick={() => handleStartPipeline(pipeline.name)}
                    className="btn btn-success start-button"
                    disabled={!pipeline.enabled || startingPipeline === pipeline.name}
                  >
                    <MdPlayArrow />
                    {startingPipeline === pipeline.name ? 'Startet...' : 'Starten'}
                  </button>
                )}
                <button
                  onClick={() => navigate(`/pipelines/${pipeline.name}`)}
                  className="btn btn-outlined details-button"
                >
                  <MdInfo />
                  {t('pipelines.details')}
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state card">
          <p>{t('pipelines.noPipelines')}</p>
        </div>
      )}
    </div>
      </div>
    </div>
  )
}
