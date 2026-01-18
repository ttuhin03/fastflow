import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

export default function AuthCallback() {
  const navigate = useNavigate()

  useEffect(() => {
    const hash = window.location.hash
    const params = new URLSearchParams(hash.replace(/^#/, ''))
    const token = params.get('token')
    if (token) {
      sessionStorage.setItem('auth_token', token)
      window.location.replace('/')
    } else {
      navigate('/login', { replace: true })
    }
  }, [navigate])

  return <div className="login-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>Anmeldung wird abgeschlossen…</div>
}
