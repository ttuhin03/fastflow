import { useEffect, useState, useRef } from 'react'
import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { 
  MdDashboard, 
  MdAccountTree, 
  MdPlayArrow, 
  MdSchedule, 
  MdLock, 
  MdSync,
  MdSettings,
  MdPeople,
  MdLogout,
  MdCircle,
  MdPause,
  MdMenu,
  MdClose
} from 'react-icons/md'
import NotificationCenter from './NotificationCenter'
import './Layout.css'

interface NavItem {
  path: string
  label: string
  icon: React.ReactNode
}

const navItems: NavItem[] = [
  { path: '/', label: 'Dashboard', icon: <MdDashboard /> },
  { path: '/pipelines', label: 'Pipelines', icon: <MdAccountTree /> },
  { path: '/runs', label: 'Runs', icon: <MdPlayArrow /> },
  { path: '/scheduler', label: 'Scheduler', icon: <MdSchedule /> },
  { path: '/secrets', label: 'Secrets', icon: <MdLock /> },
  { path: '/sync', label: 'Git Sync', icon: <MdSync /> },
  { path: '/users', label: 'Nutzer', icon: <MdPeople /> },
  { path: '/settings', label: 'Einstellungen', icon: <MdSettings /> },
]

export default function Layout() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [backendStatus, setBackendStatus] = useState<'online' | 'offline' | 'checking'>('checking')
  const [healthPulse, setHealthPulse] = useState(false)
  const [clickedIcons, setClickedIcons] = useState<Set<string>>(new Set())
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const previousStatusRef = useRef<'online' | 'offline' | 'checking'>('checking')

  const { data: health, isError, error, isFetching } = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const response = await apiClient.get('/health')
      return response.data
    },
    refetchInterval: 5000,
    retry: false, // Keine Retries, damit Fehler sofort erkannt werden
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchOnMount: true,
  })
  
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

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  const isActive = (path: string) => {
    if (path === '/') {
      return location.pathname === '/'
    }
    return location.pathname.startsWith(path)
  }

  const handleNavClick = (path: string) => {
    // Icon-Animation auslösen
    setClickedIcons(prev => {
      const newSet = new Set(prev)
      newSet.add(path)
      return newSet
    })
    // Nach Animation wieder entfernen (länger für Runs wegen Pause-Icon)
    const animationDuration = path === '/runs' ? 800 : 600
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
      {/* Mobile Sidebar Overlay */}
      {sidebarOpen && (
        <div className="sidebar-overlay" onClick={closeSidebar}></div>
      )}
      
      {/* Mobile Menu Button */}
      <button className="mobile-menu-button" onClick={toggleSidebar} aria-label="Menu">
        {sidebarOpen ? <MdClose /> : <MdMenu />}
      </button>

      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="sidebar-header">
          <h1 className="sidebar-logo">Fast-Flow</h1>
        </div>
        
        <nav className="sidebar-nav">
          {navItems.map((item) => {
            const iconClass = clickedIcons.has(item.path) ? 'icon-clicked' : ''
            const iconType = item.path === '/settings' ? 'settings-icon' :
                           item.path === '/sync' ? 'sync-icon' :
                           item.path === '/scheduler' ? 'scheduler-icon' :
                           item.path === '/runs' ? 'runs-icon' :
                           item.path === '/pipelines' ? 'pipelines-icon' :
                           item.path === '/' ? 'dashboard-icon' :
                           item.path === '/secrets' ? 'secrets-icon' :
                           item.path === '/users' ? 'users-icon' : 'default-icon'
            
            // Für Runs: Pause-Icon während Animation zeigen
            const showPauseIcon = item.path === '/runs' && clickedIcons.has(item.path)
            
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`nav-item ${isActive(item.path) ? 'active' : ''}`}
                onClick={() => {
                  handleNavClick(item.path)
                  closeSidebar() // Close sidebar on mobile after navigation
                }}
              >
                <span className={`nav-icon ${iconClass} ${iconType}`}>
                  {showPauseIcon ? <MdPause /> : item.icon}
                </span>
                <span className="nav-label">{item.label}</span>
              </Link>
            )
          })}
        </nav>

        <div className="sidebar-footer">
          <div className={`backend-status ${backendStatus} ${healthPulse ? 'pulse' : ''}`} title={backendStatus === 'online' ? 'Backend online' : 'Backend offline'}>
            <MdCircle className="status-dot-icon" />
            <span className="status-text">
              {backendStatus === 'online' ? 'Online' : backendStatus === 'offline' ? 'Offline' : 'Prüfe...'}
            </span>
          </div>
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
            <NotificationCenter />
          </div>
        </header>
        
        <main className="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
