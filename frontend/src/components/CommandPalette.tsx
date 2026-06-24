import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LuSearch,
  LuLayoutGrid,
  LuWorkflow,
  LuActivity,
  LuClock,
  LuKeyRound,
  LuPackage,
  LuRefreshCw,
  LuHistory,
  LuSlidersHorizontal,
} from 'react-icons/lu'
import apiClient from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import './CommandPalette.css'

/**
 * Globales ⌘K-Command-Palette-Overlay.
 * Öffnet via ⌘/Ctrl+K oder das `open-command-palette`-CustomEvent (Header-Suche).
 * Schließt via Escape / Klick auf Scrim.
 */

interface CmdItem {
  id: string
  label: string
  hint?: string
  icon: React.ReactNode
  iconColor?: string
  mono?: boolean
  run: () => void
}

interface CmdGroup {
  label: string
  items: CmdItem[]
}

const ICON_ACCENT = 'var(--color-primary-light)'
const ICON_BLUE = 'var(--color-running-text)'

export default function CommandPalette() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { isAuthenticated, isAdmin } = useAuth()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const close = useCallback(() => {
    setOpen(false)
    setQuery('')
    setActive(0)
  }, [])

  // Global open/close shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    const onOpen = () => setOpen(true)
    window.addEventListener('keydown', onKey)
    window.addEventListener('open-command-palette', onOpen)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('open-command-palette', onOpen)
    }
  }, [])

  // Focus input when opening
  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      const id = window.setTimeout(() => inputRef.current?.focus(), 20)
      return () => window.clearTimeout(id)
    }
  }, [open])

  // Pipelines for the "Pipelines" group (only load while open)
  const { data: pipelines } = useQuery<{ name: string }[]>({
    queryKey: ['cmdk', 'pipelines'],
    queryFn: async () => {
      const r = await apiClient.get('/pipelines')
      return Array.isArray(r.data) ? r.data : []
    },
    enabled: open && isAuthenticated,
    staleTime: 60_000,
  })

  const go = useCallback(
    (to: string) => {
      navigate(to)
      close()
    },
    [navigate, close],
  )

  const groups: CmdGroup[] = useMemo(() => {
    const jump: CmdItem[] = [
      { id: 'dashboard', label: t('nav.dashboard'), hint: 'G D', icon: <LuLayoutGrid size={15} />, iconColor: ICON_ACCENT, run: () => go('/') },
      { id: 'pipelines', label: t('nav.pipelines'), hint: 'G P', icon: <LuWorkflow size={15} />, iconColor: ICON_ACCENT, run: () => go('/pipelines') },
      { id: 'runs', label: t('nav.runs'), hint: 'G R', icon: <LuActivity size={15} />, iconColor: ICON_BLUE, run: () => go('/pipelines?section=runs') },
      { id: 'scheduler', label: t('nav.scheduler'), icon: <LuClock size={15} />, iconColor: ICON_BLUE, run: () => go('/pipelines?section=scheduler') },
      { id: 'secrets', label: t('nav.secrets'), icon: <LuKeyRound size={15} />, iconColor: ICON_BLUE, run: () => go('/pipelines?section=secrets') },
      { id: 'dependencies', label: t('nav.dependencies'), icon: <LuPackage size={15} />, iconColor: ICON_BLUE, run: () => go('/pipelines?section=dependencies') },
      { id: 'sync', label: t('nav.sync'), icon: <LuRefreshCw size={15} />, iconColor: ICON_BLUE, run: () => go('/settings?section=git-sync') },
      ...(isAdmin ? [{ id: 'audit', label: t('nav.audit'), icon: <LuHistory size={15} />, iconColor: ICON_BLUE, run: () => go('/audit') } as CmdItem] : []),
      { id: 'settings', label: t('nav.settings'), icon: <LuSlidersHorizontal size={15} />, iconColor: ICON_BLUE, run: () => go('/settings') },
    ]

    const pipeItems: CmdItem[] = (pipelines || []).map((p) => ({
      id: `pipe-${p.name}`,
      label: p.name,
      mono: true,
      icon: <LuWorkflow size={15} />,
      iconColor: ICON_ACCENT,
      hint: t('common.open', 'Open'),
      run: () => go(`/pipelines/${encodeURIComponent(p.name)}`),
    }))

    const q = query.trim().toLowerCase()
    const filterItems = (items: CmdItem[]) =>
      q ? items.filter((it) => it.label.toLowerCase().includes(q)) : items

    const result: CmdGroup[] = []
    const jumpFiltered = filterItems(jump)
    if (jumpFiltered.length) result.push({ label: t('cmdk.jumpTo', 'Jump to'), items: jumpFiltered })
    const pipeFiltered = filterItems(pipeItems)
    if (pipeFiltered.length) result.push({ label: t('nav.pipelines'), items: pipeFiltered.slice(0, 8) })
    return result
  }, [t, go, pipelines, query, isAdmin])

  // Flat list for keyboard navigation
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups])

  useEffect(() => {
    if (active >= flat.length) setActive(0)
  }, [flat.length, active])

  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, flat.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      flat[active]?.run()
    }
  }

  if (!open) return null

  let runningIndex = -1

  return (
    <div className="cmdk-overlay" onClick={close} role="presentation">
      <div className="cmdk-panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={t('cmdk.title', 'Command palette')}>
        <div className="cmdk-header">
          <LuSearch size={17} className="cmdk-header__icon" />
          <input
            ref={inputRef}
            className="cmdk-input"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            onKeyDown={onListKey}
            placeholder={t('cmdk.placeholder', 'Search pipelines, runs, actions…')}
            aria-label={t('cmdk.placeholder', 'Search pipelines, runs, actions…')}
          />
          <kbd className="cmdk-kbd">ESC</kbd>
        </div>

        <div className="cmdk-list">
          {flat.length === 0 && (
            <div className="cmdk-empty">{t('cmdk.noResults', 'No results')}</div>
          )}
          {groups.map((g) => (
            <div key={g.label} className="cmdk-group">
              <div className="cmdk-group__label">{g.label}</div>
              {g.items.map((it) => {
                runningIndex += 1
                const idx = runningIndex
                return (
                  <div
                    key={it.id}
                    className={`cmdk-item ${idx === active ? 'active' : ''}`}
                    onClick={it.run}
                    onMouseEnter={() => setActive(idx)}
                    role="button"
                    tabIndex={-1}
                  >
                    <span className="cmdk-item__icon" style={{ color: it.iconColor }}>
                      {it.icon}
                    </span>
                    <span className={`cmdk-item__label ${it.mono ? 'mono' : ''}`}>{it.label}</span>
                    {it.hint && <span className="cmdk-item__hint">{it.hint}</span>}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
