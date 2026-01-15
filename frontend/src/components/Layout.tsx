import { useEffect, useState } from 'react'
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
  MdLogout,
  MdCircle
} from 'react-icons/md'
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
  { path: '/settings', label: 'Einstellungen', icon: <MdSettings /> },
]

export default function Layout() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [backendStatus, setBackendStatus] = useState<'online' | 'offline' | 'checking'>('checking')

  const { data: health, isError } = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const response = await apiClient.get('/health')
      return response.data
    },
    refetchInterval: 5000,
    retry: 1,
  })

  useEffect(() => {
    if (health) {
      setBackendStatus('online')
    } else if (isError) {
      setBackendStatus('offline')
    }
  }, [health, isError])

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

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1 className="sidebar-logo">Fast-Flow</h1>
        </div>
        
        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`nav-item ${isActive(item.path) ? 'active' : ''}`}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
            </Link>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className={`backend-status ${backendStatus}`} title={backendStatus === 'online' ? 'Backend online' : 'Backend offline'}>
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
          </div>
        </header>
        
        <main className="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
