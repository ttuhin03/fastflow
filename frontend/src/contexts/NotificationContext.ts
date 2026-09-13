/**
 * Context, Typen und Hook — ohne Komponente, damit der Provider in einer eigenen
 * Datei stehen kann. Sonst exportiert ein Modul Komponenten und Nicht-Komponenten
 * gemischt und Fast Refresh lädt bei jeder Änderung die ganze App neu.
 */
import { createContext, useContext } from 'react'

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

export const NotificationContext = createContext<NotificationContextType | undefined>(undefined)

export const STORAGE_KEY = 'fastflow-notifications'
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
export function loadStoredNotifications(): Notification[] {
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

export function useNotifications() {
  const context = useContext(NotificationContext)
  if (context === undefined) {
    throw new Error('useNotifications must be used within NotificationProvider')
  }
  return context
}
