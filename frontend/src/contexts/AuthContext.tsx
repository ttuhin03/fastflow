import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import apiClient from '../api/client'
import { showError } from '../utils/toast'

interface AuthContextType {
  isAuthenticated: boolean
  loading: boolean
  logout: () => Promise<void>
  token: string | null
  userRole: 'readonly' | 'write' | 'admin' | null
  isReadonly: boolean
  isWrite: boolean
  isAdmin: boolean
  is_setup_completed: boolean
  refetchUserInfo: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState<string | null>(null)
  const [userRole, setUserRole] = useState<'readonly' | 'write' | 'admin' | null>(null)
  const [is_setup_completed, setIsSetupCompleted] = useState(true)

  const fetchUserInfo = async () => {
    try {
      const response = await apiClient.get('/auth/me')
      const role = response.data.role?.toLowerCase() as 'readonly' | 'write' | 'admin'
      setUserRole(role || 'readonly')
      setIsSetupCompleted(response.data.is_setup_completed !== false)
    } catch (error: any) {
      setUserRole(null)
      setIsAuthenticated(false)
      setToken(null)
      setIsSetupCompleted(true)
      // Interceptor behandelt 401 (Redirect, Token-Entfernung). Bei anderen Fehlern Hinweis anzeigen.
      if (error?.response?.status !== 401) {
        showError('Sitzung konnte nicht geladen werden. Bitte erneut anmelden.')
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

  const logout = async () => {
    try {
      await apiClient.post('/auth/logout')
    } catch (error) {
      // Ignoriere Fehler beim Logout
    } finally {
      sessionStorage.removeItem('auth_token')
      setToken(null)
      setIsAuthenticated(false)
      setUserRole(null)
      setIsSetupCompleted(true)
    }
  }

  const isReadonly = userRole === 'readonly'
  const isWrite = userRole === 'write' || userRole === 'admin'
  const isAdmin = userRole === 'admin'

  return (
    <AuthContext.Provider value={{ 
      isAuthenticated, 
      loading, 
      logout, 
      token,
      userRole,
      isReadonly,
      isWrite,
      isAdmin,
      is_setup_completed,
      refetchUserInfo: fetchUserInfo,
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
