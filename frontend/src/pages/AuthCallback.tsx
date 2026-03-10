import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

export default function AuthCallback() {
  const navigate = useNavigate()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    if (!code) {
      navigate('/login', { replace: true })
      return
    }
    fetch(`/api/auth/exchange?code=${encodeURIComponent(code)}`)
      .then((res) => {
        if (!res.ok) throw new Error('Code ungültig oder abgelaufen')
        return res.json()
      })
      .then((data) => {
        if (data.access_token) {
          sessionStorage.setItem('auth_token', data.access_token)
          window.location.replace('/')
        } else {
          navigate('/login', { replace: true })
        }
      })
      .catch(() => {
        navigate('/login', { replace: true })
      })
  }, [navigate])

  return <div className="login-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>Anmeldung wird abgeschlossen…</div>
}
