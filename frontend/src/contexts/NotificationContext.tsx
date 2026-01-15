import { createContext, useContext, useState, useCallback, useEffect } from 'react'
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

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([])

  // Lade gespeicherte Notifications aus localStorage
  useEffect(() => {
    const stored = localStorage.getItem('fastflow-notifications')
    if (stored) {
      try {
        const parsed = JSON.parse(stored)
        setNotifications(
          parsed.map((n: any) => ({
            ...n,
            timestamp: new Date(n.timestamp),
          }))
        )
      } catch (e) {
        console.error('Fehler beim Laden von Notifications:', e)
      }
    }
  }, [])

  // Speichere Notifications in localStorage
  useEffect(() => {
    if (notifications.length > 0) {
      localStorage.setItem('fastflow-notifications', JSON.stringify(notifications))
    } else {
      localStorage.removeItem('fastflow-notifications')
    }
  }, [notifications])

  // Entferne alte Notifications (> 7 Tage)
  useEffect(() => {
    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000
    setNotifications((prev) =>
      prev.filter((n) => n.timestamp.getTime() > sevenDaysAgo)
    )
  }, [])

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

  const unreadCount = notifications.filter((n) => !n.read).length

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
