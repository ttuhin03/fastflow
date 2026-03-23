import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import apiClient from '../api/client'
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
    apiClient.get(`/auth/exchange?code=${encodeURIComponent(code)}`)
      .then((res) => {
        const data = res.data
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
