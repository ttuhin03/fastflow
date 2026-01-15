import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { MdLock, MdPerson, MdWarning } from 'react-icons/md'
import './Login.css'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      await login(username, password)
      navigate('/')
    } catch (err: any) {
      setError(err.message || 'Login fehlgeschlagen')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-container">
      <div className="login-card card">
        <div className="login-header">
          <div className="login-icon">
            <MdLock />
          </div>
          <h1>Fast-Flow Orchestrator</h1>
          <p className="login-subtitle">Anmeldung erforderlich</p>
        </div>
        
        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label htmlFor="username" className="form-label">
              <MdPerson />
              Benutzername
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="form-input"
              required
              autoFocus
              placeholder="Benutzername eingeben"
            />
          </div>
          
          <div className="form-group">
            <label htmlFor="password" className="form-label">
              <MdLock />
              Passwort
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="form-input"
              required
              placeholder="Passwort eingeben"
            />
          </div>
          
          {error && (
            <div className="error-message">
              <MdWarning />
              <span>{error}</span>
            </div>
          )}
          
          <button 
            type="submit" 
            disabled={loading} 
            className="btn btn-primary login-btn"
          >
            {loading ? 'Anmelden...' : 'Anmelden'}
          </button>
        </form>
        
        <div className="login-hint">
          <MdWarning />
          <div>
            <strong>Standard-Credentials:</strong> admin/admin
            <br />
            <small>Bitte in Produktion ändern!</small>
          </div>
        </div>
      </div>
    </div>
  )
}
