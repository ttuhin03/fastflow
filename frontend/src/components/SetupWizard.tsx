import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError, showSuccess } from '../utils/toast'
import './SetupWizard.css'

export default function SetupWizard() {
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
      showSuccess('Einstellungen gespeichert.')
      await refetchUserInfo()
    } catch (err: any) {
      showError(err?.response?.data?.detail || err?.message || 'Speichern fehlgeschlagen.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="setup-wizard-overlay">
      <div className="setup-wizard-modal">
        <h2 className="setup-wizard-title">Erste Einstellungen</h2>
        <p className="setup-wizard-text">
          Fehlerberichte und Nutzungsstatistiken helfen uns, Fast-Flow zu verbessern.
          Alles läuft anonym und sicher in der EU. Session Recording wird nicht verwendet.
        </p>
        <p className="setup-wizard-link">
          <a href="https://posthog.com" target="_blank" rel="noopener noreferrer">Mehr zu PostHog</a>
        </p>
        <form onSubmit={handleSubmit} className="setup-wizard-form">
          <label className="setup-wizard-toggle">
            <input
              type="checkbox"
              checked={enable_error_reporting}
              onChange={(e) => setEnableErrorReporting(e.target.checked)}
              className="setup-wizard-checkbox"
            />
            <span>Fehlerberichte erlauben</span>
          </label>
          <label className="setup-wizard-toggle">
            <input
              type="checkbox"
              checked={enable_telemetry}
              onChange={(e) => setEnableTelemetry(e.target.checked)}
              className="setup-wizard-checkbox"
            />
            <span>Nutzungsstatistiken erlauben</span>
          </label>
          <p className="setup-wizard-note">
            Das hilft unseren Entwicklern sehr – vielen Dank. Alles anonym und sicher. Session Recording (Bildschirmaufzeichnung) wird ausdrücklich nicht genutzt.
          </p>
          <div className="setup-wizard-actions">
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Speichern…' : 'Fertig'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
