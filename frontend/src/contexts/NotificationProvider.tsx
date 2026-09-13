import { useState, useCallback, useEffect, useMemo } from 'react'
import { showError as showErrorToast, showWarning as showWarningToast } from '../utils/toast'
import {
  NotificationContext,
  STORAGE_KEY,
  loadStoredNotifications,
  type Notification,
} from './NotificationContext'

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

