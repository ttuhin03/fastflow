import { useEffect, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Outlet, Link, useNavigate, useLocation, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import { useAuth } from '../contexts/AuthContext'
import { useUiPreferences } from '../contexts/UiPreferencesContext'
import apiClient from '../api/client'
import {
  LuLayoutGrid,
  LuWorkflow,
  LuActivity,
  LuClock,
  LuKeyRound,
  LuPackage,
  LuRefreshCw,
  LuHistory,
  LuSlidersHorizontal,
  LuSearch,
  LuLogOut,
  LuMenu,
  LuX,
  LuBookOpen,
  LuGithub,
} from 'react-icons/lu'
import NotificationCenter from './NotificationCenter'
import VersionInfo from './VersionInfo'
import HeaderTime from './HeaderTime'
import HeaderLanguage from './HeaderLanguage'
import SetupWizard from './SetupWizard'
import CommandPalette from './CommandPalette'
import './Layout.css'

const openCommandPalette = () => window.dispatchEvent(new Event('open-command-palette'))

interface NavSection {
  labelKey: string
  items: NavItemDef[]
}

interface NavItemDef {
  path: string
  labelKey: string
  icon: React.ReactNode
  adminOnly?: boolean
  count?: number
}

export default function Layout() {
  const { t } = useTranslation()
  const { logout, isAdmin, userRole } = useAuth()
  const { showAttribution, showVersion } = useUiPreferences()
  const navigate = useNavigate()
  const location = useLocation()
  const params = useParams()

  const { data: authProviders } = useQuery({
    queryKey: ['auth/providers'],
    queryFn: async () => {
      const r = await apiClient.get('/auth/providers')
      return r.data as { login_branding_logo_url?: string }
    },
    staleTime: 60_000,
  })

  const { data: userInfo } = useQuery({
    queryKey: ['auth/me-layout'],
    queryFn: async () => {
      const r = await apiClient.get('/auth/me')
      return r.data as { email?: string; avatar_url?: string }
    },
    staleTime: 300_000,
  })

  const navSections: NavSection[] = [
    {
      labelKey: 'nav.sectionOverview',
      items: [
        { path: '/', labelKey: 'nav.dashboard', icon: <LuLayoutGrid size={16} /> },
      ],
    },
    {
      labelKey: 'nav.sectionOrchestration',
      items: [
        { path: '/pipelines', labelKey: 'nav.pipelines', icon: <LuWorkflow size={16} /> },
        { path: '/runs', labelKey: 'nav.runs', icon: <LuActivity size={16} /> },
        { path: '/scheduler', labelKey: 'nav.scheduler', icon: <LuClock size={16} /> },
      ],
    },
    {
      labelKey: 'nav.sectionSecurity',
      items: [
        { path: '/secrets', labelKey: 'nav.secrets', icon: <LuKeyRound size={16} /> },
        { path: '/dependencies', labelKey: 'nav.dependencies', icon: <LuPackage size={16} /> },
      ],
    },
    {
      labelKey: 'nav.sectionSystem',
      items: [
        { path: '/sync', labelKey: 'nav.sync', icon: <LuRefreshCw size={16} /> },
        { path: '/audit', labelKey: 'nav.audit', icon: <LuHistory size={16} />, adminOnly: true },
        { path: '/settings', labelKey: 'nav.settings', icon: <LuSlidersHorizontal size={16} /> },
      ],
    },
  ]

  const [backendStatus, setBackendStatus] = useState<'online' | 'offline' | 'checking'>('checking')
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // Sidebar-Active-State: /pipelines und /settings bündeln mehrere Sektionen
  // (?section=…); der aktive Nav-Eintrag richtet sich nach der Sektion.
  const isActive = useCallback((path: string) => {
    const p = location.pathname
    const section = new URLSearchParams(location.search).get('section')
    if (path === '/') return p === '/'
    if (p === '/pipelines') {
      const sectionToPath: Record<string, string> = {
        pipelines: '/pipelines',
        runs: '/runs',
        scheduler: '/scheduler',
        secrets: '/secrets',
        dependencies: '/dependencies',
      }
      return (sectionToPath[section || 'pipelines'] || '/pipelines') === path
    }
    if (p.startsWith('/pipelines/')) return path === '/pipelines' // Pipeline-Detail
    if (p.startsWith('/runs')) return path === '/runs' // Run-Detail
    if (p === '/settings') {
      if (section === 'git-sync') return path === '/sync'
      return path === '/settings'
    }
    return p.startsWith(path)
  }, [location.pathname, location.search])

  const healthInterval = useRefetchInterval(5000)
  const { data: health, isError, error, isFetching } = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const response = await apiClient.get('/health')
      return response.data
    },
    refetchInterval: healthInterval,
    retry: false,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchOnMount: true,
  })

  const { data: users } = useQuery<{ status?: string }[]>({
    queryKey: ['users'],
    queryFn: async () => {
      const response = await apiClient.get('/users')
      return response.data
    },
    retry: false,
    staleTime: 5 * 60 * 1000,
  })
  const pendingCount = Array.isArray(users)
    ? users.filter((u) => (u.status || 'active') === 'pending').length
    : 0

  useEffect(() => {
    if (isError || error) {
      setBackendStatus('offline')
    } else if (health && health.status === 'healthy') {
      setBackendStatus('online')
    } else if (!health && !isError && !isFetching) {
      setBackendStatus('offline')
    }
  }, [health, isError, error, isFetching])

  useEffect(() => {
    const allItems = navSections.flatMap(s => s.items)
    const activeItem = allItems.find(item => isActive(item.path))
    document.title = activeItem ? `${t(activeItem.labelKey)} · ${t('appTitle')}` : t('appTitle')
  }, [location.pathname, location.search, t]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const toggleSidebar = () => setSidebarOpen(v => !v)
  const closeSidebar = () => setSidebarOpen(false)

  // Breadcrumb: derive root + optional leaf from current route (incl. ?section=…)
  const breadcrumb = useBreadcrumb(location.pathname, location.search, params, t, navSections)

  // User display
  const userEmail = userInfo?.email || ''
  const userInitials = userEmail
    ? userEmail.split('@')[0].slice(0, 2).toUpperCase()
    : (userRole ? userRole.slice(0, 2).toUpperCase() : 'U')

  const allSystemsOk = backendStatus === 'online'

  return (
    <div className="layout">
      <SetupWizard />
      <CommandPalette />

      <div
        className={`sidebar-overlay ${sidebarOpen ? 'visible' : ''}`}
        onClick={closeSidebar}
        aria-hidden
      />

      <button className="mobile-menu-button" onClick={toggleSidebar} aria-label={t('nav.menu')}>
        {sidebarOpen ? <LuX size={20} /> : <LuMenu size={20} />}
      </button>

      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        {/* Brand */}
        <div className="sidebar__brand">
          {authProviders?.login_branding_logo_url ? (
            <div className="sidebar__logo sidebar__logo--image">
              <img src={authProviders.login_branding_logo_url} alt="" />
            </div>
          ) : (
            <div className="sidebar__logo">
              <LuWorkflow size={16} />
            </div>
          )}
          <div>
            <div className="sidebar__name">{t('appTitle')}</div>
            {showVersion && (
              <div className="sidebar__version">
                <VersionInfo variant="footer" />
              </div>
            )}
          </div>
        </div>

        {/* Nav */}
        <nav className="sidebar__nav">
          {navSections.map(section => (
            <div key={section.labelKey}>
              <div className="nav-group-label">{t(section.labelKey)}</div>
              {section.items
                .filter(item => !item.adminOnly || isAdmin)
                .map(item => (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={`nav-item ${isActive(item.path) ? 'active' : ''}`}
                    onClick={closeSidebar}
                  >
                    <span className="nav-icon">{item.icon}</span>
                    <span className="nav-label">{t(item.labelKey)}</span>
                    {item.path === '/settings' && pendingCount > 0 && (
                      <span className="nav-badge">{pendingCount > 99 ? '99+' : pendingCount}</span>
                    )}
                  </Link>
                ))}
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="sidebar__footer">
          {/* System status chip */}
          <div className="sidebar__status">
            <span className={`status-dot ${allSystemsOk ? 'online' : backendStatus === 'checking' ? 'checking' : 'offline'}`} />
            <span>
              {allSystemsOk
                ? t('nav.online')
                : backendStatus === 'checking'
                ? t('nav.checking')
                : t('nav.offline')}
              {health?.pipeline_executor && allSystemsOk && (
                <span style={{ marginLeft: 6, opacity: 0.7 }}>
                  · {health.pipeline_executor === 'kubernetes' ? 'K8s' : 'Docker'}
                </span>
              )}
            </span>
          </div>

          {/* User row */}
          <div className="sidebar__user">
            <div className="sidebar__avatar" aria-hidden>
              {userInitials}
            </div>
            <div className="sidebar__user-info">
              <div className="sidebar__user-name" title={userEmail}>{userEmail || t('nav.user')}</div>
              <div className="sidebar__user-role">{userRole || 'user'}</div>
            </div>
            <button
              className="sidebar__logout-btn"
              onClick={handleLogout}
              title={t('nav.logout')}
              aria-label={t('nav.logout')}
            >
              <LuLogOut size={15} />
            </button>
          </div>

          {/* Docs + GitHub */}
          <a
            href={import.meta.env.VITE_DOCS_URL || 'http://localhost:3001'}
            target="_blank"
            rel="noopener noreferrer"
            className="sidebar-docs-link"
          >
            <LuBookOpen size={15} style={{ flexShrink: 0 }} />
            <span>{t('nav.docs')}</span>
          </a>
          <a
            href="https://github.com/ttuhin03/fastflow"
            target="_blank"
            rel="noopener noreferrer"
            className="sidebar-github-link"
          >
            <LuGithub size={15} style={{ flexShrink: 0 }} />
            <span>{t('nav.viewOnGitHub')}</span>
          </a>

          {showAttribution && (
            <p className="sidebar-footer-text">
              Made with <span className="heart">❤️</span> by <strong>ttuhin03</strong>
            </p>
          )}
        </div>
      </aside>

      <div className="layout-main">
        <header className="main-header">
          {/* Breadcrumb */}
          <nav className="breadcrumb" aria-label="breadcrumb">
            {breadcrumb.root && (
              <>
                <span className="breadcrumb__root">{breadcrumb.root}</span>
                {breadcrumb.leaf && (
                  <>
                    <span className="breadcrumb__sep">/</span>
                    <span className="breadcrumb__leaf">{breadcrumb.leaf}</span>
                  </>
                )}
              </>
            )}
          </nav>

          <div className="header-spacer" />

          {/* ⌘K search trigger */}
          <button className="header-search" aria-label="Search" onClick={openCommandPalette}>
            <LuSearch size={14} />
            <span className="label">{t('common.search') || 'Search or jump to…'}</span>
            <kbd>⌘K</kbd>
          </button>

          {/* Header actions */}
          <HeaderLanguage />
          <HeaderTime />
          <NotificationCenter />
        </header>

        <main className="main-content">
          <div key={location.pathname} className="page-transition-wrap">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}

function useBreadcrumb(
  pathname: string,
  search: string,
  params: Record<string, string | undefined>,
  t: (key: string) => string,
  sections: NavSection[],
): { root: string; leaf?: string } {
  const allItems = sections.flatMap(s => s.items)
  const section = new URLSearchParams(search).get('section')

  // Sections innerhalb der gebündelten Seiten (/pipelines, /settings)
  if (pathname === '/pipelines' && section && section !== 'pipelines') {
    const sectionLabels: Record<string, string> = {
      runs: 'nav.runs',
      scheduler: 'nav.scheduler',
      secrets: 'nav.secrets',
      dependencies: 'nav.dependencies',
    }
    if (sectionLabels[section]) return { root: t(sectionLabels[section]) }
  }
  if (pathname === '/settings' && section === 'git-sync') {
    return { root: t('nav.sync') }
  }

  // Exact match first
  const exact = allItems.find(item => item.path === pathname)
  if (exact) return { root: t(exact.labelKey) }

  // Run detail: /runs/:runId
  if (pathname.startsWith('/runs/') && params.runId) {
    return { root: t('nav.runs'), leaf: params.runId }
  }

  // Pipeline detail: /pipelines/:name
  if (pathname.startsWith('/pipelines/') && params.name) {
    return { root: t('nav.pipelines'), leaf: params.name }
  }

  // Prefix match
  const prefix = allItems
    .filter(i => i.path !== '/')
    .find(i => pathname.startsWith(i.path))
  if (prefix) return { root: t(prefix.labelKey) }

  if (pathname === '/') return { root: t('nav.dashboard') }

  return { root: t('appTitle') }
}
