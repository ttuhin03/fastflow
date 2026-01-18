import { useSearchParams } from 'react-router-dom'

const getApiOrigin = () => {
  const u = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'
  return u.replace(/\/api\/?$/, '') || 'http://localhost:8000'
}

export default function Invite() {
  const [search] = useSearchParams()
  const token = search.get('token')

  if (!token) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center' }}>
        <h2>Ungültiger Einladungslink</h2>
        <p>Der Einladungslink ist unvollständig oder ungültig.</p>
      </div>
    )
  }

  const handleRegister = () => {
    const api = getApiOrigin()
    window.location.href = `${api}/api/auth/github/authorize?state=${encodeURIComponent(token)}`
  }

  return (
    <div style={{ padding: '2rem', textAlign: 'center', maxWidth: 480, margin: '0 auto' }}>
      <h2>Du wurdest zu Fast-Flow eingeladen!</h2>
      <p style={{ margin: '1rem 0' }}>Melde dich mit deinem GitHub-Account an, um die Einladung anzunehmen.</p>
      <button type="button" onClick={handleRegister} className="btn btn-primary">
        Mit GitHub registrieren
      </button>
    </div>
  )
}
