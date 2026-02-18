import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNotifications } from '../contexts/NotificationContext'
import { MdNotifications, MdNotificationsNone, MdClose, MdError, MdWarning, MdInfo, MdCheckCircle } from 'react-icons/md'
import { useNavigate } from 'react-router-dom'
import { getFormatLocale } from '../utils/locale'
import './NotificationCenter.css'

export default function NotificationCenter() {
  const { t } = useTranslation()
  const { notifications, unreadCount, markAsRead, markAllAsRead, clearNotification, clearAll } = useNotifications()
  const [isOpen, setIsOpen] = useState(false)
  const navigate = useNavigate()

  const getIcon = (type: string) => {
    switch (type) {
      case 'error':
        return <MdError className="notification-icon error" />
      case 'warning':
        return <MdWarning className="notification-icon warning" />
      case 'success':
        return <MdCheckCircle className="notification-icon success" />
      default:
        return <MdInfo className="notification-icon info" />
    }
  }

  const handleActionClick = (notification: any) => {
    markAsRead(notification.id)
    if (notification.actionUrl) {
      navigate(notification.actionUrl)
      setIsOpen(false)
    }
  }

  const unreadNotifications = notifications.filter((n) => !n.read)

  return (
    <div className="notification-center">
      <button
        className="notification-center-toggle"
        onClick={() => setIsOpen(!isOpen)}
        aria-label="Notifications"
      >
        {unreadCount > 0 ? (
          <>
            <MdNotifications />
            {unreadCount > 0 && <span className="notification-badge">{unreadCount > 9 ? '9+' : unreadCount}</span>}
          </>
        ) : (
          <MdNotificationsNone />
        )}
      </button>

      {isOpen && (
        <>
          <div className="notification-overlay" onClick={() => setIsOpen(false)}></div>
          <div className="notification-panel">
            <div className="notification-panel-header">
              <h3>{t('notifications.title')}</h3>
              <div className="notification-panel-actions">
                {unreadNotifications.length > 0 && (
                  <button
                    className="notification-action-btn"
                    onClick={markAllAsRead}
                    title={t('notifications.markAllRead')}
                  >
                    {t('notifications.markAllReadShort')}
                  </button>
                )}
                {notifications.length > 0 && (
                  <button
                    className="notification-action-btn"
                    onClick={clearAll}
                    title={t('notifications.clearAll')}
                  >
                    {t('notifications.clearAll')}
                  </button>
                )}
                <button
                  className="notification-close-btn"
                  onClick={() => setIsOpen(false)}
                  aria-label={t('notifications.close')}
                >
                  <MdClose />
                </button>
              </div>
            </div>

            <div className="notification-list">
              {notifications.length === 0 ? (
                <div className="notification-empty">
                  <MdNotificationsNone />
                  <p>{t('notifications.empty')}</p>
                </div>
              ) : (
                notifications.map((notification) => (
                  <div
                    key={notification.id}
                    className={`notification-item ${notification.read ? 'read' : 'unread'} ${notification.type}`}
                    onClick={() => !notification.read && markAsRead(notification.id)}
                  >
                    <div className="notification-item-icon">{getIcon(notification.type)}</div>
                    <div className="notification-item-content">
                      <div className="notification-item-header">
                        <h4 className="notification-item-title">{notification.title}</h4>
                        <button
                          className="notification-item-close"
                          onClick={(e) => {
                            e.stopPropagation()
                            clearNotification(notification.id)
                          }}
                          aria-label={t('notifications.delete')}
                        >
                          <MdClose />
                        </button>
                      </div>
                      <p className="notification-item-message">{notification.message}</p>
                      <div className="notification-item-footer">
                        <span className="notification-item-time">
                          {notification.timestamp.toLocaleString(getFormatLocale())}
                        </span>
                        {notification.actionUrl && (
                          <button
                            className="notification-item-action"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleActionClick(notification)
                            }}
                          >
                            {notification.actionLabel || t('notifications.show')}
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
