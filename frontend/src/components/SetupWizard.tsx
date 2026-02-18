import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError, showSuccess } from '../utils/toast'
import './SetupWizard.css'

export default function SetupWizard() {
  const { t } = useTranslation()
  const { isAdmin, is_setup_completed, refetchUserInfo } = useAuth()
  const [enable_telemetry, setEnableTelemetry] = useState(false)
  const [enable_error_reporting, setEnableErrorReporting] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  if (!isAdmin || is_setup_completed) {
    return null
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      await apiClient.put('/settings/system', {
        is_setup_completed: true,
        enable_telemetry,
        enable_error_reporting,
      })
      showSuccess(t('setupWizard.success'))
      await refetchUserInfo()
    } catch (err: any) {
      showError(err?.response?.data?.detail || err?.message || t('setupWizard.saveFailed'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="setup-wizard-overlay">
      <div className="setup-wizard-modal">
        <h2 className="setup-wizard-title">{t('setupWizard.title')}</h2>
        <p className="setup-wizard-text">
          {t('setupWizard.text')}
        </p>
        <p className="setup-wizard-link">
          <a href="https://posthog.com" target="_blank" rel="noopener noreferrer">{t('setupWizard.linkPostHog')}</a>
        </p>
        <form onSubmit={handleSubmit} className="setup-wizard-form">
          <label className="setup-wizard-toggle">
            <input
              type="checkbox"
              checked={enable_error_reporting}
              onChange={(e) => setEnableErrorReporting(e.target.checked)}
              className="setup-wizard-checkbox"
            />
            <span>{t('setupWizard.errorReporting')}</span>
          </label>
          <label className="setup-wizard-toggle">
            <input
              type="checkbox"
              checked={enable_telemetry}
              onChange={(e) => setEnableTelemetry(e.target.checked)}
              className="setup-wizard-checkbox"
            />
            <span>{t('setupWizard.telemetry')}</span>
          </label>
          <p className="setup-wizard-note">
            {t('setupWizard.note')}
          </p>
          <div className="setup-wizard-actions">
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? t('setupWizard.saving') : t('setupWizard.done')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
