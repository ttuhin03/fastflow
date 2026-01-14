import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import apiClient from '../api/client'

interface AuthContextType {
  isAuthenticated: boolean
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  token: string | null
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState<string | null>(null)

  useEffect(() => {
    // Prüfe ob Token vorhanden ist
    const storedToken = localStorage.getItem('auth_token')
    if (storedToken) {
      setToken(storedToken)
      setIsAuthenticated(true)
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
      localStorage.setItem('auth_token', access_token)
      setToken(access_token)
      setIsAuthenticated(true)
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
      localStorage.removeItem('auth_token')
      setToken(null)
      setIsAuthenticated(false)
    }
  }

  return (
    <AuthContext.Provider value={{ isAuthenticated, loading, login, logout, token }}>
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
