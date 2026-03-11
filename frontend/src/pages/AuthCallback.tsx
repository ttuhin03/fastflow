import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { showError } from '../utils/toast'

export default function AuthCallback() {
  const navigate = useNavigate()
  const { t } = useTranslation()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    if (!code) {
      showError(t('auth.callbackError'))
      navigate('/login', { replace: true })
      return
    }
    fetch(`/api/auth/exchange?code=${encodeURIComponent(code)}`)
      .then((res) => {
        if (!res.ok) throw new Error('exchange_failed')
        return res.json()
      })
      .then((data) => {
        if (data.access_token) {
          sessionStorage.setItem('auth_token', data.access_token)
          window.location.replace('/')
        } else {
          showError(t('auth.callbackError'))
          navigate('/login', { replace: true })
        }
      })
      .catch(() => {
        showError(t('auth.callbackError'))
        navigate('/login', { replace: true })
      })
  }, [navigate, t])

  return <div className="login-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>{t('common.loading')}</div>
}
