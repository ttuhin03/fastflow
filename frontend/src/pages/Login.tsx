import { useState, FormEvent, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { MdLock, MdPerson, MdWarning, MdCode } from 'react-icons/md'
import './Login.css'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.playbackRate = 0.5
    }
  }, [])

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
      <div className="login-background">
        <video 
          ref={videoRef}
          className="login-background-video"
          autoPlay
          loop
          muted
          playsInline
        >
          <source src="/background.mp4" type="video/mp4" />
          {/* Fallback if video doesn't load */}
        </video>
        <div className="login-background-overlay"></div>
      </div>
      
      <div className="login-content">
        <div className="login-card card">
          <div className="login-header">
            <div className="login-icon">
              <MdCode />
            </div>
            <h1>Fast-Flow</h1>
            <p className="login-subtitle">Pipeline Orchestrator</p>
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
        
        <div className="login-footer">
          <a 
            href="https://github.com/ttuhin03/fastflow" 
            target="_blank" 
            rel="noopener noreferrer"
            className="github-link"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" style={{ flexShrink: 0 }}>
              <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
            </svg>
            <span>View on GitHub</span>
          </a>
          <p className="login-footer-text">
            Made with <span className="heart">❤️</span> by <strong>ttuhin03</strong>
          </p>
        </div>
      </div>
    </div>
  )
}
