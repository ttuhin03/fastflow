import { createContext, useContext, useState, useCallback, useEffect, useMemo } from 'react'
import { showError as showErrorToast, showWarning as showWarningToast } from '../utils/toast'

export interface Notification {
  id: string
  type: 'error' | 'warning' | 'info' | 'success'
  title: string
  message: string
  timestamp: Date
  read: boolean
  actionUrl?: string
  actionLabel?: string
}

/** Persistierte Form: JSON kennt kein Date, timestamp liegt als ISO-String vor. */
type StoredNotification = Omit<Notification, 'timestamp'> & { timestamp: string }

interface NotificationContextType {
  notifications: Notification[]
  unreadCount: number
  addNotification: (notification: Omit<Notification, 'id' | 'timestamp' | 'read'>) => void
  markAsRead: (id: string) => void
  markAllAsRead: () => void
  clearNotification: (id: string) => void
  clearAll: () => void
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined)

const STORAGE_KEY = 'fastflow-notifications'
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

/**
 * Gespeicherte Notifications lesen und dabei alles älter als 7 Tage verwerfen.
 *
 * Läuft als Initializer von useState, nicht in einem Effect. Vorher taten das
 * zwei Mount-Effects (laden, dann aufräumen) — mit zwei zusätzlichen Rendern
 * und einer Lücke dazwischen: der Speicher-Effect lief im ersten Commit noch
 * mit der leeren Startliste und hat den localStorage-Eintrag gelöscht, bevor
 * der geladene State ankam und ihn wieder zurückschrieb.
 */
function loadStoredNotifications(): Notification[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (!stored) return []
    const parsed: StoredNotification[] = JSON.parse(stored)
    const cutoff = Date.now() - MAX_AGE_MS
    return parsed
      .map((n) => ({ ...n, timestamp: new Date(n.timestamp) }))
      .filter((n) => n.timestamp.getTime() > cutoff)
  } catch (e) {
    console.error('Fehler beim Laden von Notifications:', e)
    return []
  }
}

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>(loadStoredNotifications)

  // Speichere Notifications in localStorage. Der Zugriff ist abgesichert wie
  // beim Lesen: bei gesperrtem Speicher (privater Modus, Richtlinie) wirft
  // setItem, und das hier ungefangen mitten im Effect würde die App in die
  // ErrorBoundary schicken.
  useEffect(() => {
    try {
      if (notifications.length > 0) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications))
      } else {
        localStorage.removeItem(STORAGE_KEY)
      }
    } catch (e) {
      console.error('Fehler beim Speichern von Notifications:', e)
    }
  }, [notifications])

  const addNotification = useCallback(
    (notification: Omit<Notification, 'id' | 'timestamp' | 'read'>) => {
      const newNotification: Notification = {
        ...notification,
        id: `${Date.now()}-${Math.random()}`,
        timestamp: new Date(),
        read: false,
      }

      setNotifications((prev) => [newNotification, ...prev].slice(0, 100)) // Max 100 Notifications

      // Zeige Toast für wichtige Notifications
      if (notification.type === 'error') {
        showErrorToast(`${notification.title}: ${notification.message}`)
      } else if (notification.type === 'warning') {
        showWarningToast(`${notification.title}: ${notification.message}`)
      }
    },
    []
  )

  const markAsRead = useCallback((id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n))
    )
  }, [])

  const markAllAsRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })))
  }, [])

  const clearNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id))
  }, [])

  const clearAll = useCallback(() => {
    setNotifications([])
  }, [])

  const unreadCount = useMemo(() => notifications.filter((n) => !n.read).length, [notifications])

  return (
    <NotificationContext.Provider
      value={{
        notifications,
        unreadCount,
        addNotification,
        markAsRead,
        markAllAsRead,
        clearNotification,
        clearAll,
      }}
    >
      {children}
    </NotificationContext.Provider>
  )
}

export function useNotifications() {
  const context = useContext(NotificationContext)
  if (context === undefined) {
    throw new Error('useNotifications must be used within NotificationProvider')
  }
  return context
}
