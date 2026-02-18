import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getApiOrigin } from '../config'

export default function Invite() {
  const { t } = useTranslation()
  const [search] = useSearchParams()
  const token = search.get('token')

  if (!token) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center' }}>
        <h2>{t('invite.invalidLink')}</h2>
        <p>{t('invite.invalidLinkDesc')}</p>
      </div>
    )
  }

  const api = getApiOrigin()
  const stateParam = `state=${encodeURIComponent(token)}`

  return (
    <div style={{ padding: '2rem', textAlign: 'center', maxWidth: 480, margin: '0 auto' }}>
      <h2>{t('invite.invitedTitle')}</h2>
      <p style={{ margin: '1rem 0' }}>
        {t('invite.invitedDesc')}
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', alignItems: 'center' }}>
        <button
          type="button"
          onClick={() => { window.location.href = `${api}/api/auth/github/authorize?${stateParam}` }}
          className="btn btn-primary"
        >
          {t('invite.registerGitHub')}
        </button>
        <button
          type="button"
          onClick={() => { window.location.href = `${api}/api/auth/google/authorize?${stateParam}` }}
          className="btn btn-primary"
        >
          {t('invite.registerGoogle')}
        </button>
      </div>
    </div>
  )
}
