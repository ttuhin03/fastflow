import { useSearchParams } from 'react-router-dom'
import { getApiOrigin } from '../config'

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

  const api = getApiOrigin()
  const stateParam = `state=${encodeURIComponent(token)}`

  return (
    <div style={{ padding: '2rem', textAlign: 'center', maxWidth: 480, margin: '0 auto' }}>
      <h2>Du wurdest zu Fast-Flow eingeladen!</h2>
      <p style={{ margin: '1rem 0' }}>
        Melde dich mit GitHub oder Google an, um die Einladung anzunehmen. Die E-Mail muss der Einladung entsprechen.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', alignItems: 'center' }}>
        <button
          type="button"
          onClick={() => { window.location.href = `${api}/api/auth/github/authorize?${stateParam}` }}
          className="btn btn-primary"
        >
          Mit GitHub registrieren
        </button>
        <button
          type="button"
          onClick={() => { window.location.href = `${api}/api/auth/google/authorize?${stateParam}` }}
          className="btn btn-primary"
        >
          Mit Google registrieren
        </button>
      </div>
    </div>
  )
}
