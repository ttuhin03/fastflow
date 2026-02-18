/**
 * Toast-Notification Utilities
 *
 * Zentralisierte Funktionen für Toast-Benachrichtigungen.
 * Ersetzt alert() und confirm() durch moderne, nicht-blockierende Toasts.
 */

import React from 'react'
import toast from 'react-hot-toast'
import i18n from '../i18n'

/**
 * Zeigt eine Erfolgs-Toast-Nachricht an.
 */
export const showSuccess = (message: string) => {
  toast.success(message)
}

/**
 * Zeigt eine Fehler-Toast-Nachricht an.
 */
export const showError = (message: string) => {
  toast.error(message)
}

/**
 * Zeigt eine Info-Toast-Nachricht an.
 */
export const showInfo = (message: string) => {
  toast(message, {
    icon: 'ℹ️',
  })
}

/**
 * Zeigt eine Warnung-Toast-Nachricht an.
 */
export const showWarning = (message: string) => {
  toast(message, {
    icon: '⚠️',
  })
}

/**
 * Zeigt eine Bestätigungs-Dialog als Toast.
 * 
 * @param message - Die Nachricht
 * @param onConfirm - Callback wenn bestätigt
 * @param onCancel - Optionaler Callback wenn abgebrochen
 * @returns Promise<boolean> - true wenn bestätigt, false wenn abgebrochen
 */
export const showConfirm = (
  message: string,
  onConfirm?: () => void,
  onCancel?: () => void
): Promise<boolean> => {
  return new Promise((resolve) => {
    toast(
      (t) => React.createElement('div', { style: { display: 'flex', flexDirection: 'column', gap: '0.5rem' } },
        React.createElement('span', null, message),
        React.createElement('div', { style: { display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' } },
          React.createElement('button', {
            onClick: () => {
              toast.dismiss(t.id)
              resolve(true)
              onConfirm?.()
            },
            style: {
              padding: '0.5rem 1rem',
              background: '#4caf50',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: '500',
            }
          }, i18n.t('toast.ok')),
          React.createElement('button', {
            onClick: () => {
              toast.dismiss(t.id)
              resolve(false)
              onCancel?.()
            },
            style: {
              padding: '0.5rem 1rem',
              background: '#666',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: '500',
            }
          }, i18n.t('toast.cancel'))
        )
      ),
      {
        duration: Infinity, // Bleibt bis Benutzer interagiert
        style: {
          minWidth: '300px',
        },
      }
    )
  })
}
