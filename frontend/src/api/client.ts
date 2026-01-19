import axios, { AxiosInstance, InternalAxiosRequestConfig } from 'axios'
import { showError } from '../utils/toast'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'
const LOGIN_PATH = import.meta.env.VITE_LOGIN_PATH || '/login'

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request Interceptor: Füge Auth-Token hinzu
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Verwende sessionStorage statt localStorage für besseren XSS-Schutz
    // sessionStorage wird beim Schließen des Tabs/Browsers gelöscht
    const token = sessionStorage.getItem('auth_token')
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response Interceptor: Handle 401 Unauthorized und Token-Refresh
let isRefreshing = false
let failedQueue: Array<{
  resolve: (value?: any) => void
  reject: (reason?: any) => void
}> = []

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token)
    }
  })

  failedQueue = []
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    const isRefreshEndpoint = originalRequest?.url?.includes('/auth/refresh')

    // Wenn 401 und nicht bereits Refresh-Versuch
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // Wenn bereits Refresh läuft, warte auf Ergebnis
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        })
          .then(token => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            return apiClient(originalRequest)
          })
          .catch(err => {
            return Promise.reject(err)
          })
      }

      originalRequest._retry = true
      isRefreshing = true

      const token = sessionStorage.getItem('auth_token')

      if (token && !isRefreshEndpoint) {
        try {
          // Versuche Token-Refresh
          const response = await apiClient.post('/auth/refresh', {}, {
            headers: {
              Authorization: `Bearer ${token}`
            }
          })

          const { access_token } = response.data
          sessionStorage.setItem('auth_token', access_token)

          // Aktualisiere Authorization Header für ursprüngliche Request
          originalRequest.headers.Authorization = `Bearer ${access_token}`

          // Prozessiere Warteschlange
          processQueue(null, access_token)
          isRefreshing = false

          // Wiederhole ursprüngliche Request mit neuem Token
          return apiClient(originalRequest)
        } catch (refreshError: any) {
          // Refresh fehlgeschlagen - prüfe ob Session abgelaufen ist
          const errorDetail = refreshError?.response?.data?.detail || ''
          const isSessionExpired =
            errorDetail.includes('Session nicht gefunden') ||
            errorDetail.includes('abgelaufen') ||
            errorDetail.includes('nach 24 Stunden') ||
            errorDetail.includes('Bitte melden Sie sich erneut an')

          // Refresh fehlgeschlagen - logge User aus
          processQueue(refreshError, null)
          isRefreshing = false
          sessionStorage.removeItem('auth_token')

          // Zeige benutzerfreundliche Nachricht wenn Session abgelaufen ist
          if (isSessionExpired && window.location.pathname !== LOGIN_PATH) {
            showError('Ihre Sitzung ist abgelaufen. Bitte melden Sie sich erneut an.')
          }

          // Nur redirecten wenn nicht bereits auf Login-Seite
          if (window.location.pathname !== LOGIN_PATH) {
            window.location.href = LOGIN_PATH
          }
          return Promise.reject(refreshError)
        }
      } else {
        // Kein Token vorhanden oder Refresh-Endpoint - logge User aus
        processQueue(error, null)
        isRefreshing = false
        sessionStorage.removeItem('auth_token')
        // Nur redirecten wenn nicht bereits auf Login-Seite
        if (window.location.pathname !== LOGIN_PATH) {
          window.location.href = LOGIN_PATH
        }
        return Promise.reject(error)
      }
    }

    return Promise.reject(error)
  }
)

export default apiClient
