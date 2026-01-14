import { Outlet, Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import './Layout.css'

export default function Layout() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="layout">
      <header className="header">
        <h1>Fast-Flow Orchestrator</h1>
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
