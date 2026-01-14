import { useEffect, useState } from 'react'
import { Outlet, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import './Layout.css'

export default function Layout() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const [backendStatus, setBackendStatus] = useState<'online' | 'offline' | 'checking'>('checking')

  const { data: health, isError } = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const response = await apiClient.get('/health')
      return response.data
    },
    refetchInterval: 5000, // Alle 5 Sekunden prüfen
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

  return (
    <div className="layout">
      <header className="header">
        <div className="header-left">
          <h1>Fast-Flow Orchestrator</h1>
          <div className={`backend-status ${backendStatus}`} title={backendStatus === 'online' ? 'Backend online' : 'Backend offline'}>
            <span className="status-dot"></span>
            <span className="status-text">
              {backendStatus === 'online' ? 'Online' : backendStatus === 'offline' ? 'Offline' : 'Prüfe...'}
            </span>
          </div>
        </div>
        <nav className="nav">
          <Link to="/">Dashboard</Link>
          <Link to="/pipelines">Pipelines</Link>
          <Link to="/runs">Runs</Link>
          <Link to="/scheduler">Scheduler</Link>
          <Link to="/secrets">Secrets</Link>
          <Link to="/sync">Git Sync</Link>
          <button onClick={handleLogout} className="logout-btn">
            Abmelden
          </button>
        </nav>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
