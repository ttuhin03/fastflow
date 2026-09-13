/**
 * Context und Hook — ohne Komponente, damit der Provider in einer eigenen Datei
 * stehen kann. Ein Modul, das Komponenten und Nicht-Komponenten mischt, lässt
 * Fast Refresh bei jeder Änderung die ganze App neu laden.
 */
import { createContext, useContext } from 'react'

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

export const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
