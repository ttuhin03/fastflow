import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import apiClient from '../api/client'

interface AuthContextType {
  isAuthenticated: boolean
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  token: string | null
  userRole: 'readonly' | 'write' | 'admin' | null
  isReadonly: boolean
  isWrite: boolean
  isAdmin: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState<string | null>(null)
  const [userRole, setUserRole] = useState<'readonly' | 'write' | 'admin' | null>(null)

  const fetchUserInfo = async () => {
    try {
      const response = await apiClient.get('/auth/me')
      const role = response.data.role?.toLowerCase() as 'readonly' | 'write' | 'admin'
      setUserRole(role || 'readonly')
    } catch (error: any) {
      // Wenn Session abgelaufen ist, wird der Interceptor in client.ts
      // automatisch den User ausloggen und zur Login-Seite weiterleiten
      setUserRole(null)
      // Wenn es ein 401-Fehler ist, wird der Token bereits vom Interceptor entfernt
      if (error?.response?.status === 401) {
        setIsAuthenticated(false)
        setToken(null)
      }
    }
  }

  useEffect(() => {
    // Prüfe ob Token vorhanden ist
    // Verwende sessionStorage statt localStorage für besseren XSS-Schutz
    // sessionStorage wird beim Schließen des Tabs/Browsers gelöscht
    const storedToken = sessionStorage.getItem('auth_token')
    if (storedToken) {
      setToken(storedToken)
      setIsAuthenticated(true)
      fetchUserInfo()
    }
    setLoading(false)
  }, [])

  const login = async (username: string, password: string) => {
    try {
      const response = await apiClient.post('/auth/login', {
        username,
        password,
      })
      const { access_token } = response.data
      // Verwende sessionStorage statt localStorage für besseren XSS-Schutz
      // sessionStorage wird beim Schließen des Tabs/Browsers gelöscht
      sessionStorage.setItem('auth_token', access_token)
      setToken(access_token)
      setIsAuthenticated(true)
      await fetchUserInfo()
    } catch (error: any) {
      throw new Error(error.response?.data?.detail || 'Login fehlgeschlagen')
    }
  }

  const logout = async () => {
    try {
      await apiClient.post('/auth/logout')
    } catch (error) {
      // Ignoriere Fehler beim Logout
    } finally {
      // Entferne Token aus sessionStorage
      sessionStorage.removeItem('auth_token')
      setToken(null)
      setIsAuthenticated(false)
      setUserRole(null)
    }
  }

  const isReadonly = userRole === 'readonly'
  const isWrite = userRole === 'write' || userRole === 'admin'
  const isAdmin = userRole === 'admin'

  return (
    <AuthContext.Provider value={{ 
      isAuthenticated, 
      loading, 
      login, 
      logout, 
      token,
      userRole,
      isReadonly,
      isWrite,
      isAdmin
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
