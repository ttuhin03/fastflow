import { useEffect, useState, useRef, useLayoutEffect } from 'react'
import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import {
  MdDashboard,
  MdAccountTree,
  MdSettings,
  MdLogout,
  MdCircle,
  MdMenu,
  MdClose,
  MdCode,
  MdMenuBook,
} from 'react-icons/md'
import NotificationCenter from './NotificationCenter'
import Tooltip from './Tooltip'
import VersionInfo from './VersionInfo'
import HeaderTime from './HeaderTime'
import SetupWizard from './SetupWizard'
import './Layout.css'

interface NavItem {
  path: string
  label: string
  icon: React.ReactNode
}

const navItems: NavItem[] = [
  { path: '/', label: 'Dashboard', icon: <MdDashboard /> },
  { path: '/pipelines', label: 'Pipelines', icon: <MdAccountTree /> },
  { path: '/settings', label: 'Einstellungen', icon: <MdSettings /> },
]

const BASE_TITLE = 'Fast-Flow'

export default function Layout() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [backendStatus, setBackendStatus] = useState<'online' | 'offline' | 'checking'>('checking')
  const [healthPulse, setHealthPulse] = useState(false)
  const [clickedIcons, setClickedIcons] = useState<Set<string>>(new Set())
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const previousStatusRef = useRef<'online' | 'offline' | 'checking'>('checking')
  const navRef = useRef<HTMLElement>(null)
  const [navIndicator, setNavIndicator] = useState({ top: 0, height: 0 })

  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const activePath = navItems.find((item) => isActive(item.path))?.path
    if (!activePath) return
    const el = nav.querySelector<HTMLElement>(`[data-nav-path="${activePath}"]`)
    if (!el) return
    const nr = nav.getBoundingClientRect()
    const er = el.getBoundingClientRect()
    setNavIndicator({ top: er.top - nr.top, height: er.height })
  }, [location.pathname])

  const healthInterval = useRefetchInterval(5000)
  const { data: health, isError, error, isFetching } = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const response = await apiClient.get('/health')
      return response.data
    },
    refetchInterval: healthInterval,
    retry: false, // Keine Retries, damit Fehler sofort erkannt werden
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
    const previousStatus = previousStatusRef.current

    // Wenn gerade gefetched wird, Status auf 'checking' setzen (nur beim ersten Mal)
    if (isFetching && previousStatus === 'checking') {
      return // Beim ersten Check nichts ändern
    }

    // Wenn ein Fehler auftritt, ist der Server offline
    if (isError || error) {
      if (previousStatus !== 'offline') {
        setBackendStatus('offline')
        previousStatusRef.current = 'offline'
      }
    }
    // Wenn health Daten vorhanden sind, ist der Server online
    else if (health && health.status === 'healthy') {
      if (previousStatus !== 'online') {
        setHealthPulse(true)
        setTimeout(() => setHealthPulse(false), 600)
      }
      setBackendStatus('online')
      previousStatusRef.current = 'online'
    }
    // Wenn health undefined/null ist und kein Fehler, könnte es noch laden
    else if (!health && !isError && !isFetching) {
      // Wenn kein Fetch läuft und keine Daten, dann offline
      if (previousStatus !== 'offline') {
        setBackendStatus('offline')
        previousStatusRef.current = 'offline'
      }
    }
  }, [health, isError, error, isFetching])

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/'
    if (path === '/pipelines') return location.pathname.startsWith('/pipelines') || location.pathname.startsWith('/runs')
    return location.pathname.startsWith(path)
  }

  useEffect(() => {
    const activeItem = navItems.find((item) => isActive(item.path))
    document.title = activeItem ? `${activeItem.label} · ${BASE_TITLE}` : BASE_TITLE
  }, [location.pathname])

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const handleNavClick = (path: string) => {
    // Icon-Animation auslösen
    setClickedIcons(prev => {
      const newSet = new Set(prev)
      newSet.add(path)
      return newSet
    })
    // Nach Animation wieder entfernen (länger für Runs wegen Pause-Icon)
    const animationDuration = 600
    setTimeout(() => {
      setClickedIcons(prev => {
        const newSet = new Set(prev)
        newSet.delete(path)
        return newSet
      })
    }, animationDuration)
  }

  const toggleSidebar = () => {
    setSidebarOpen(!sidebarOpen)
  }

  const closeSidebar = () => {
    setSidebarOpen(false)
  }

  return (
    <div className="layout">
      <SetupWizard />
      {/* Mobile Sidebar Overlay - always in DOM for fade transition */}
      <div
        className={`sidebar-overlay ${sidebarOpen ? 'visible' : ''}`}
        onClick={closeSidebar}
        aria-hidden
      />

      {/* Mobile Menu Button */}
      <button className="mobile-menu-button" onClick={toggleSidebar} aria-label="Menu">
        {sidebarOpen ? <MdClose /> : <MdMenu />}
      </button>

      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-header">
          <div className="sidebar-logo-container">
            <div className="sidebar-logo-icon">
              <MdCode />
            </div>
            <h1 className="sidebar-logo">Fast-Flow</h1>
          </div>
        </div>

        <nav ref={navRef} className="sidebar-nav">
          <div
            className="sidebar-nav-indicator"
            style={{ top: navIndicator.top, height: navIndicator.height }}
            aria-hidden
          />
          {navItems.map((item) => {
            const iconClass = clickedIcons.has(item.path) ? 'icon-clicked' : ''
            const iconType = item.path === '/settings' ? 'settings-icon' :
              item.path === '/pipelines' ? 'pipelines-icon' :
                item.path === '/' ? 'dashboard-icon' : 'default-icon'

            return (
              <Link
                key={item.path}
                to={item.path}
                data-nav-path={item.path}
                className={`nav-item ${isActive(item.path) ? 'active' : ''}`}
                onClick={() => {
                  handleNavClick(item.path)
                  closeSidebar() // Close sidebar on mobile after navigation
                }}
              >
                <span className={`nav-icon ${iconClass} ${iconType}`}>
                  {item.icon}
                </span>
                <span className="nav-label">{item.label}</span>
                {item.path === '/settings' && pendingCount > 0 && (
                  <span className="nav-badge" title="Offene Beitrittsanfragen">
                    {pendingCount > 99 ? '99+' : pendingCount}
                  </span>
                )}
              </Link>
            )
          })}
        </nav>


        <div className="sidebar-footer">
          <div className={`backend-status ${backendStatus} ${healthPulse ? 'pulse' : ''}`} title={backendStatus === 'online' ? 'Backend online' : 'Backend offline'}>
            <MdCircle className="status-dot-icon" />
            <span className="status-text">
              {backendStatus === 'online' ? 'Online' : backendStatus === 'offline' ? 'Offline' : 'Prüfe...'}
              {health?.pipeline_executor && (
                <span className="executor-label" style={{ marginLeft: '6px', opacity: 0.85 }}>
                  · {health.pipeline_executor === 'kubernetes' ? 'K8s' : 'Docker'}
                </span>
              )}
            </span>
          </div>

          <a
            href={import.meta.env.VITE_DOCS_URL || 'http://localhost:3001'}
            target="_blank"
            rel="noopener noreferrer"
            className="sidebar-docs-link"
          >
            <MdMenuBook style={{ flexShrink: 0, width: 16, height: 16 }} />
            <span>Doku</span>
          </a>

          <a
            href="https://github.com/ttuhin03/fastflow"
            target="_blank"
            rel="noopener noreferrer"
            className="sidebar-github-link"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style={{ flexShrink: 0 }}>
              <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
            </svg>
            <span>View on GitHub</span>
          </a>

          <p className="sidebar-footer-text">
            Made with <Tooltip content="Made with heart... and fueled by the healthy desire to never see a broken DAG again. Life is too short for over-engineering."><span className="heart">❤️</span></Tooltip> by <strong>ttuhin03</strong>
            <span style={{ marginLeft: '8px', opacity: 0.5, fontSize: '10px' }}>
              <VersionInfo variant="footer" />
            </span>
          </p>
          <button onClick={handleLogout} className="logout-btn">
            <MdLogout />
            <span>Abmelden</span>
          </button>
        </div>
      </aside>

      <div className="layout-main">
        <header className="main-header">
          <div className="header-content">
            <h2 className="page-title">
              {navItems.find(item => isActive(item.path))?.label || 'Dashboard'}
            </h2>
            <div className="header-center">
              <VersionInfo variant="banner" />
            </div>
            <div className="header-actions">
              <HeaderTime />
              <NotificationCenter />
            </div>
          </div>
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
