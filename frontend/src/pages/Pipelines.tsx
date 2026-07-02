import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError, showSuccess } from '../utils/toast'
import { LuPlay, LuSearch } from 'react-icons/lu'
import { getFormatLocale } from '../utils/locale'
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

interface SchedulerJob {
  id: string
  pipeline_name: string
  trigger_type: string
  trigger_value: string
  enabled: boolean
  next_run_time?: string | null
}

export default function Pipelines() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const [searchParams] = useSearchParams()
  const section = (searchParams.get('section') as PipelinesSection) || 'pipelines'
  const [tagsFilter, setTagsFilter] = useState('')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())

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
    placeholderData: (previousData) => previousData,
    refetchInterval: pipelinesInterval,
  })

  // Zeitpläne (Cron + nächste Ausführung) pro Pipeline aus dem Scheduler
  const { data: schedulerJobs } = useQuery<SchedulerJob[]>({
    queryKey: ['scheduler-jobs'],
    queryFn: async () => {
      const response = await apiClient.get('/scheduler/jobs')
      return response.data
    },
    staleTime: 30_000,
  })

  const scheduleByPipeline = useMemo(() => {
    const map = new Map<string, { crons: string[]; nextRun: string | null }>()
    for (const job of schedulerJobs ?? []) {
      const entry = map.get(job.pipeline_name) ?? { crons: [], nextRun: null }
      if (job.trigger_value) entry.crons.push(job.trigger_value)
      if (job.enabled && job.next_run_time) {
        if (!entry.nextRun || job.next_run_time < entry.nextRun) entry.nextRun = job.next_run_time
      }
      map.set(job.pipeline_name, entry)
    }
    return map
  }, [schedulerJobs])

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

  // Client-side search + status filtering over the fetched list.
  const filteredPipelines = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (pipelines ?? []).filter((p) => {
      if (statusFilter === 'active' && !p.enabled) return false
      if (statusFilter === 'inactive' && p.enabled) return false
      if (q && !p.name.toLowerCase().includes(q)) return false
      return true
    })
  }, [pipelines, search, statusFilter])

  const successRate = (p: Pipeline) =>
    p.total_runs > 0 ? Math.round((p.successful_runs / p.total_runs) * 100) : 0

  const successRateClass = (rate: number, total: number) => {
    if (total === 0) return 'neutral'
    if (rate >= 90) return 'success'
    if (rate >= 60) return 'warning'
    return 'error'
  }

  const toggleSelect = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const visibleNames = filteredPipelines.map((p) => p.name)
  const allSelected = visibleNames.length > 0 && visibleNames.every((n) => selected.has(n))
  const toggleSelectAll = () => {
    setSelected((prev) => {
      if (visibleNames.every((n) => prev.has(n))) {
        const next = new Set(prev)
        visibleNames.forEach((n) => next.delete(n))
        return next
      }
      return new Set([...prev, ...visibleNames])
    })
  }
  const clearSelection = () => setSelected(new Set())
  const selectedCount = selected.size

  const [bulkTriggering, setBulkTriggering] = useState(false)

  const handleBulkTrigger = async () => {
    if (isReadonly || bulkTriggering) return
    const targets = filteredPipelines.filter((p) => selected.has(p.name) && p.enabled)
    if (targets.length === 0) return
    setBulkTriggering(true)
    let started = 0
    try {
      for (const p of targets) {
        try {
          await apiClient.post(`/pipelines/${p.name}/run`, { env_vars: {}, parameters: {} })
          started += 1
        } catch (error: any) {
          showError(t('pipelines.startError', { detail: error.response?.data?.detail || error.message }))
        }
      }
    } finally {
      setBulkTriggering(false)
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      queryClient.invalidateQueries({ queryKey: ['runs'] })
    }
    if (started > 0) {
      showSuccess(t('pipelines.bulkTriggerSuccess', { count: started }))
      clearSelection()
    }
  }

  // Die Unterseiten-Navigation übernimmt die Sidebar (Runs/Scheduler/Secrets/Dependencies
  // sind dort eigene Einträge, die auf ?section=… verlinken).
  if (section === 'runs') {
    return (
      <div className="pipelines-page">
        <div className="pipelines-content pipelines-embedded">
          <Runs />
        </div>
      </div>
    )
  }
  if (section === 'scheduler') {
    return (
      <div className="pipelines-page">
        <div className="pipelines-content pipelines-embedded">
          <Scheduler />
        </div>
      </div>
    )
  }
  if (section === 'secrets') {
    return (
      <div className="pipelines-page">
        <div className="pipelines-content pipelines-embedded">
          <Secrets />
        </div>
      </div>
    )
  }
  if (section === 'dependencies') {
    return (
      <div className="pipelines-page">
        <div className="pipelines-content pipelines-embedded">
          <Dependencies />
        </div>
      </div>
    )
  }

  if (isLoading && !pipelines) {
    return (
      <div className="pipelines-page">
        <div className="pipelines-content">
          <div className="pipelines">
            <div className="table pipelines-table">
              <div className="table__head" />
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="table__row">
                  <Skeleton width="16px" height="16px" variant="rectangular" />
                  <Skeleton width="60%" height="16px" />
                  <Skeleton width="70px" height="22px" variant="rectangular" />
                  <Skeleton width="50%" height="14px" />
                  <Skeleton width="80%" height="14px" />
                  <Skeleton width="60%" height="14px" />
                  <Skeleton width="60px" height="22px" variant="rectangular" />
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
      <div className="pipelines-content">
    <div className="pipelines">
      {/* Toolbar: search + status filter + tags filter + count */}
      <div className="pipelines-toolbar">
        <div className="pipelines-search">
          <LuSearch aria-hidden />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('pipelines.searchPlaceholder', 'Filter pipelines…')}
            aria-label={t('pipelines.searchPlaceholder', 'Filter pipelines…')}
          />
        </div>
        <div className="segmented pipelines-status-filter" role="group" aria-label={t('pipelines.statusFilter', 'Status')}>
          {(['all', 'active', 'inactive'] as const).map((s) => (
            <button
              key={s}
              type="button"
              className={statusFilter === s ? 'active' : ''}
              onClick={() => setStatusFilter(s)}
            >
              {s === 'all'
                ? t('pipelines.statusAll', 'All')
                : s === 'active'
                  ? t('common.active')
                  : t('common.inactive')}
            </button>
          ))}
        </div>
        <input
          id="pipelines-tags-filter"
          type="text"
          value={tagsFilter}
          onChange={(e) => setTagsFilter(e.target.value)}
          placeholder={t('pipelines.filterByTagsPlaceholder')}
          aria-label={t('pipelines.filterByTags')}
          className="pipelines-tags-input"
        />
        <div className="pipelines-toolbar-spacer" />
        <span className="pipelines-count mono">
          {filteredPipelines.length} / {pipelines?.length ?? 0}
        </span>
      </div>

      {/* Bulk-action bar */}
      {selectedCount > 0 && (
        <div className="pipelines-bulkbar hasSel">
          <span className="pipelines-bulkbar-count">
            {t('pipelines.selectedCount', '{{count}} selected', { count: selectedCount })}
          </span>
          <span className="pipelines-bulkbar-divider" aria-hidden />
          {!isReadonly && (
            <button type="button" className="btn btn-sm btn-outlined" onClick={handleBulkTrigger} disabled={bulkTriggering}>
              <LuPlay />
              {t('pipelines.trigger', 'Trigger')}
            </button>
          )}
          <div className="pipelines-toolbar-spacer" />
          <button type="button" className="btn btn-sm btn-ghost" onClick={clearSelection}>
            {t('pipelines.clear', 'Clear')}
          </button>
        </div>
      )}

      {filteredPipelines.length > 0 ? (
        <div className="table pipelines-table">
          <div className="table__head">
            <span className="pipelines-cell-check">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleSelectAll}
                aria-label={t('pipelines.selectAll', 'Select all')}
              />
            </span>
            <span>{t('runs.thPipeline', 'Pipeline')}</span>
            <span>{t('runs.thStatus', 'Status')}</span>
            <span>{t('pipelines.thSchedule', 'Schedule')}</span>
            <span>{t('dashboard.successRate', 'Success rate')}</span>
            <span>{t('pipelines.thNextRun', 'Next run')}</span>
            <span className="pipelines-cell-actions">{t('runs.thActions', 'Actions')}</span>
          </div>
          {filteredPipelines.map((pipeline) => {
            const rate = successRate(pipeline)
            const rateClass = successRateClass(rate, pipeline.total_runs)
            const isSelected = selected.has(pipeline.name)
            const tags = pipeline.metadata?.tags ?? []
            const schedule = scheduleByPipeline.get(pipeline.name)
            return (
              <div
                key={pipeline.name}
                className={`table__row clickable pipelines-row ${isSelected ? 'selected' : ''}`}
                onClick={() => navigate(`/pipelines/${pipeline.name}`)}
              >
                <span
                  className="pipelines-cell-check"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleSelect(pipeline.name)}
                    aria-label={t('pipelines.selectRow', 'Select {{name}}', { name: pipeline.name })}
                  />
                </span>
                <span className="pipelines-cell-name">
                  <span className={`status-dot ${pipeline.enabled ? 'online' : 'disabled'}`} aria-hidden />
                  <span className="mono pipelines-name-text" title={pipeline.name}>
                    {pipeline.name}
                  </span>
                  {tags.map((tag) => (
                    <span key={tag} className="pipelines-tag">{tag}</span>
                  ))}
                </span>
                <span>
                  <span className={`badge ${pipeline.enabled ? 'badge-success' : 'badge-secondary'}`}>
                    {pipeline.enabled ? t('common.active') : t('common.inactive')}
                  </span>
                </span>
                <span className="pipelines-cell-cron mono" title={schedule?.crons.join(', ')}>
                  {schedule && schedule.crons.length > 0 ? schedule.crons.join(', ') : '—'}
                </span>
                <span className="pipelines-cell-rate">
                  <span className="pipelines-bar">
                    <span
                      className={`pipelines-bar-fill ${rateClass}`}
                      style={{ width: `${rate}%` }}
                    />
                  </span>
                  <span className="mono pipelines-rate-pct">
                    {pipeline.total_runs > 0 ? `${rate}%` : '—'}
                  </span>
                </span>
                <span className="mono pipelines-cell-nextrun">
                  {schedule?.nextRun ? new Date(schedule.nextRun).toLocaleString(getFormatLocale(), { dateStyle: 'short', timeStyle: 'short' }) : '—'}
                </span>
                <span className="pipelines-cell-actions" onClick={(e) => e.stopPropagation()}>
                  {!isReadonly && (
                    <button
                      type="button"
                      className="btn-icon pipelines-trigger-btn"
                      title={t('pipelines.start')}
                      onClick={() => handleStartPipeline(pipeline.name)}
                      disabled={!pipeline.enabled || startingPipeline === pipeline.name}
                    >
                      <LuPlay />
                    </button>
                  )}
                </span>
              </div>
            )
          })}
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
