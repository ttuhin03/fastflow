import { useState, FormEvent } from 'react'
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
        <div className="login-background-gradient"></div>
        <div className="login-background-pattern"></div>
        <div className="graph-flow-animation">
          <svg className="graph-svg" viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid slice">
            <defs>
              <linearGradient id="nodeGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="rgba(33, 150, 243, 0.8)" />
                <stop offset="100%" stopColor="rgba(156, 39, 176, 0.8)" />
              </linearGradient>
              <linearGradient id="edgeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="rgba(33, 150, 243, 0.3)" />
                <stop offset="50%" stopColor="rgba(156, 39, 176, 0.4)" />
                <stop offset="100%" stopColor="rgba(33, 150, 243, 0.3)" />
              </linearGradient>
              <filter id="glow">
                <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
                <feMerge>
                  <feMergeNode in="coloredBlur"/>
                  <feMergeNode in="SourceGraphic"/>
                </feMerge>
              </filter>
            </defs>
            
            {/* Layer 1: Source nodes (top) */}
            <circle className="graph-node node-layer-1" cx="200" cy="150" r="6" />
            <circle className="graph-node node-layer-1" cx="400" cy="150" r="6" />
            <circle className="graph-node node-layer-1" cx="600" cy="150" r="6" />
            <circle className="graph-node node-layer-1" cx="800" cy="150" r="6" />
            <circle className="graph-node node-layer-1" cx="1000" cy="150" r="6" />
            
            {/* Layer 2: Processing nodes */}
            <circle className="graph-node node-layer-2" cx="300" cy="300" r="7" />
            <circle className="graph-node node-layer-2" cx="500" cy="300" r="7" />
            <circle className="graph-node node-layer-2" cx="700" cy="300" r="7" />
            <circle className="graph-node node-layer-2" cx="900" cy="300" r="7" />
            
            {/* Layer 3: Aggregation nodes */}
            <circle className="graph-node node-layer-3" cx="400" cy="450" r="8" />
            <circle className="graph-node node-layer-3" cx="600" cy="450" r="8" />
            <circle className="graph-node node-layer-3" cx="800" cy="450" r="8" />
            
            {/* Layer 4: Output nodes (bottom) */}
            <circle className="graph-node node-layer-4" cx="500" cy="600" r="9" />
            <circle className="graph-node node-layer-4" cx="700" cy="600" r="9" />
            
            {/* Edges: Layer 1 -> Layer 2 */}
            <line className="graph-edge edge-1-2" x1="200" y1="150" x2="300" y2="300" />
            <line className="graph-edge edge-1-2" x1="400" y1="150" x2="300" y2="300" />
            <line className="graph-edge edge-1-2" x1="400" y1="150" x2="500" y2="300" />
            <line className="graph-edge edge-1-2" x1="600" y1="150" x2="500" y2="300" />
            <line className="graph-edge edge-1-2" x1="600" y1="150" x2="700" y2="300" />
            <line className="graph-edge edge-1-2" x1="800" y1="150" x2="700" y2="300" />
            <line className="graph-edge edge-1-2" x1="800" y1="150" x2="900" y2="300" />
            <line className="graph-edge edge-1-2" x1="1000" y1="150" x2="900" y2="300" />
            
            {/* Edges: Layer 2 -> Layer 3 */}
            <line className="graph-edge edge-2-3" x1="300" y1="300" x2="400" y2="450" />
            <line className="graph-edge edge-2-3" x1="500" y1="300" x2="400" y2="450" />
            <line className="graph-edge edge-2-3" x1="500" y1="300" x2="600" y2="450" />
            <line className="graph-edge edge-2-3" x1="700" y1="300" x2="600" y2="450" />
            <line className="graph-edge edge-2-3" x1="700" y1="300" x2="800" y2="450" />
            <line className="graph-edge edge-2-3" x1="900" y1="300" x2="800" y2="450" />
            
            {/* Edges: Layer 3 -> Layer 4 */}
            <line className="graph-edge edge-3-4" x1="400" y1="450" x2="500" y2="600" />
            <line className="graph-edge edge-3-4" x1="600" y1="450" x2="500" y2="600" />
            <line className="graph-edge edge-3-4" x1="600" y1="450" x2="700" y2="600" />
            <line className="graph-edge edge-3-4" x1="800" y1="450" x2="700" y2="600" />
            
            {/* Flow particles - following logical paths */}
            <circle className="flow-particle particle-1" cx="200" cy="150" r="4" />
            <circle className="flow-particle particle-2" cx="400" cy="150" r="4" />
            <circle className="flow-particle particle-3" cx="600" cy="150" r="4" />
            <circle className="flow-particle particle-4" cx="800" cy="150" r="4" />
            <circle className="flow-particle particle-5" cx="1000" cy="150" r="4" />
            <circle className="flow-particle particle-6" cx="200" cy="150" r="4" />
            <circle className="flow-particle particle-7" cx="600" cy="150" r="4" />
          </svg>
        </div>
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
