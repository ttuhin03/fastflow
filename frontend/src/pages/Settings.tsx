import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { MdSave, MdRefresh, MdInfo, MdWarning, MdEmail, MdGroup } from 'react-icons/md'
import StorageStats from '../components/StorageStats'
import SystemMetrics from '../components/SystemMetrics'
import './Settings.css'

interface Settings {
  log_retention_runs: number | null
  log_retention_days: number | null
  log_max_size_mb: number | null
  max_concurrent_runs: number
  container_timeout: number | null
  retry_attempts: number
  auto_sync_enabled: boolean
  auto_sync_interval: number | null
  email_enabled: boolean
  smtp_host: string | null
  smtp_port: number
  smtp_user: string | null
  smtp_from: string | null
  email_recipients: string[]
  teams_enabled: boolean
  teams_webhook_url: string | null
}

export default function Settings() {
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const [localSettings, setLocalSettings] = useState<Settings | null>(null)
  const [showCleanupInfo, setShowCleanupInfo] = useState(false)

  const { data: settings, isLoading } = useQuery<Settings>({
    queryKey: ['settings'],
    queryFn: async () => {
      const response = await apiClient.get('/settings')
      return response.data
    },
  })

  const updateSettingsMutation = useMutation({
    mutationFn: async (updatedSettings: Partial<Settings>) => {
      const response = await apiClient.put('/settings', updatedSettings)
      return response.data
    },
    onSuccess: (data) => {
      alert(data.message || 'Einstellungen aktualisiert (Neustart erforderlich)')
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (error: any) => {
      alert(`Fehler beim Aktualisieren: ${error.response?.data?.detail || error.message}`)
    },
  })

  const forceCleanupMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/settings/cleanup/force')
      return response.data
    },
    onSuccess: (data) => {
      // Erstelle detaillierte Nachricht
      let message = '✅ Cleanup erfolgreich abgeschlossen!\n\n'
      
      // Zusammenfassung
      if (data.summary && data.summary.length > 0) {
        message += '📊 Zusammenfassung:\n'
        data.summary.forEach((item: string) => {
          message += `  • ${item}\n`
        })
        message += '\n'
      }
      
      // Was wurde geflusht - Log-Cleanup
      if (data.cleanup_info?.log_cleanup) {
        message += `📁 Log-Cleanup:\n`
        message += `  ${data.cleanup_info.log_cleanup.description}\n`
        if (data.cleanup_info.log_cleanup.actions && data.cleanup_info.log_cleanup.actions.length > 0) {
          data.cleanup_info.log_cleanup.actions.forEach((action: string) => {
            message += `  • ${action}\n`
          })
        }
        message += '\n'
      }
      
      // Was wurde geflusht - Docker-Cleanup
      if (data.cleanup_info?.docker_cleanup) {
        message += `🐳 Docker-Cleanup:\n`
        message += `  ${data.cleanup_info.docker_cleanup.description}\n`
        if (data.cleanup_info.docker_cleanup.actions && data.cleanup_info.docker_cleanup.actions.length > 0) {
          data.cleanup_info.docker_cleanup.actions.forEach((action: string) => {
            message += `  • ${action}\n`
          })
        }
        message += '\n'
      }
      
      // Detaillierte Statistiken
      message += '📈 Detaillierte Statistiken:\n'
      if (data.log_cleanup) {
        message += `  Logs: ${data.log_cleanup.deleted_runs || 0} Runs, ${data.log_cleanup.deleted_logs || 0} Dateien gelöscht, ${data.log_cleanup.deleted_metrics || 0} Metrics gelöscht`
        if (data.log_cleanup.truncated_logs > 0) {
          message += `, ${data.log_cleanup.truncated_logs} Dateien gekürzt`
        }
        message += '\n'
      }
      if (data.docker_cleanup) {
        message += `  Docker: ${data.docker_cleanup.deleted_containers || 0} Container, ${data.docker_cleanup.deleted_volumes || 0} Volumes gelöscht\n`
      }
      
      alert(message)
    },
    onError: (error: any) => {
      alert(`Fehler beim Cleanup: ${error.response?.data?.detail || error.message}`)
    },
  })

  const testEmailMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/settings/test-email')
      return response.data
    },
    onSuccess: (data) => {
      alert(data.message || 'Test-E-Mail erfolgreich gesendet')
    },
    onError: (error: any) => {
      alert(`Fehler beim Senden der Test-E-Mail: ${error.response?.data?.detail || error.message}`)
    },
  })

  const testTeamsMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/settings/test-teams')
      return response.data
    },
    onSuccess: (data) => {
      alert(data.message || 'Test-Teams-Nachricht erfolgreich gesendet')
    },
    onError: (error: any) => {
      alert(`Fehler beim Senden der Test-Teams-Nachricht: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleInputChange = (field: keyof Settings, value: string | number | boolean | null) => {
    if (!settings) return
    
    let processedValue: number | boolean | null | string | string[]
    
    if (field === 'auto_sync_enabled' || field === 'email_enabled' || field === 'teams_enabled') {
      processedValue = typeof value === 'boolean' ? value : value === 'true'
    } else if (field === 'email_recipients') {
      // Komma-separierte Liste verarbeiten
      if (typeof value === 'string') {
        processedValue = value.split(',').map(email => email.trim()).filter(email => email.length > 0)
      } else {
        processedValue = value
      }
    } else if (field === 'smtp_port') {
      processedValue = typeof value === 'string' && value !== '' ? parseInt(value, 10) : 587
      if (isNaN(processedValue as number)) {
        processedValue = 587
      }
    } else if (typeof value === 'string' && (field === 'smtp_host' || field === 'smtp_user' || field === 'smtp_from' || field === 'teams_webhook_url')) {
      // String-Felder direkt übernehmen
      processedValue = value === '' ? null : value
    } else if (typeof value === 'string') {
      processedValue = value === '' ? null : parseInt(value, 10)
      if (isNaN(processedValue as number)) {
        processedValue = null
      }
    } else {
      processedValue = value
    }
    
    setLocalSettings({
      ...settings,
      [field]: processedValue,
    })
  }

  const handleSave = () => {
    if (!localSettings) return
    // Konvertiere email_recipients Array zu komma-separiertem String für API
    const { email_recipients, ...restSettings } = localSettings
    const settingsToSave: Partial<Omit<Settings, 'email_recipients'>> & { email_recipients?: string } = {
      ...restSettings,
      email_recipients: Array.isArray(email_recipients)
        ? email_recipients.join(', ')
        : typeof email_recipients === 'string'
        ? email_recipients
        : ''
    }
    updateSettingsMutation.mutate(settingsToSave as Partial<Settings>)
  }

  const handleForceCleanup = () => {
    // Zeige Informationen an, was geflusht wird
    setShowCleanupInfo(true)
  }

  const confirmForceCleanup = () => {
    setShowCleanupInfo(false)
    forceCleanupMutation.mutate()
  }

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Laden...</p>
      </div>
    )
  }

  const currentSettings = localSettings || settings

  return (
    <div className="settings">
      <div className="settings-header card">
        <h2>System-Einstellungen</h2>
        <p className="settings-info">
          <MdInfo />
          Einstellungen werden aktuell nur aus Environment-Variablen geladen.
          Änderungen erfordern einen Neustart der Anwendung.
        </p>
      </div>

      <div className="storage-section-settings">
        <h3 className="section-title">Speicherplatz-Statistiken</h3>
        <StorageStats />
      </div>

      <div className="system-metrics-section">
        <SystemMetrics />
      </div>

      {currentSettings && (
        <div className="settings-sections">
          {/* Log Retention Settings */}
          <div className="settings-section card">
            <h3 className="section-title">Log Retention</h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label htmlFor="log_retention_runs" className="setting-label">
                  Maximale Runs pro Pipeline
                  <span className="setting-hint">(None = unbegrenzt)</span>
                </label>
                <input
                  id="log_retention_runs"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.log_retention_runs || ''}
                  onChange={(e) => handleInputChange('log_retention_runs', e.target.value)}
                  placeholder="Unbegrenzt"
                  disabled={isReadonly}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="log_retention_days" className="setting-label">
                  Maximale Alter in Tagen
                  <span className="setting-hint">(None = unbegrenzt)</span>
                </label>
                <input
                  id="log_retention_days"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.log_retention_days || ''}
                  onChange={(e) => handleInputChange('log_retention_days', e.target.value)}
                  placeholder="Unbegrenzt"
                  disabled={isReadonly}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="log_max_size_mb" className="setting-label">
                  Maximale Log-Größe (MB)
                  <span className="setting-hint">(None = unbegrenzt)</span>
                </label>
                <input
                  id="log_max_size_mb"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.log_max_size_mb || ''}
                  onChange={(e) => handleInputChange('log_max_size_mb', e.target.value)}
                  placeholder="Unbegrenzt"
                  disabled={isReadonly}
                />
              </div>
            </div>
          </div>

          {/* Runtime Settings */}
          <div className="settings-section card">
            <h3 className="section-title">Runtime-Einstellungen</h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label htmlFor="max_concurrent_runs" className="setting-label">
                  Maximale gleichzeitige Runs
                </label>
                <input
                  id="max_concurrent_runs"
                  type="number"
                  min="1"
                  className="form-input"
                  value={currentSettings.max_concurrent_runs}
                  onChange={(e) => handleInputChange('max_concurrent_runs', e.target.value)}
                  disabled={isReadonly}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="container_timeout" className="setting-label">
                  Container Timeout (Sekunden)
                  <span className="setting-hint">(None = unbegrenzt)</span>
                </label>
                <input
                  id="container_timeout"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.container_timeout || ''}
                  onChange={(e) => handleInputChange('container_timeout', e.target.value)}
                  placeholder="Unbegrenzt"
                  disabled={isReadonly}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="retry_attempts" className="setting-label">
                  Retry-Versuche
                </label>
                <input
                  id="retry_attempts"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.retry_attempts}
                  onChange={(e) => handleInputChange('retry_attempts', e.target.value)}
                  disabled={isReadonly}
                />
              </div>
            </div>
          </div>

          {/* Auto Sync Settings */}
          <div className="settings-section card">
            <h3 className="section-title">Auto-Sync Einstellungen</h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label className="setting-label checkbox-label">
                  <input
                    type="checkbox"
                    checked={currentSettings.auto_sync_enabled}
                    onChange={(e) => handleInputChange('auto_sync_enabled', e.target.checked)}
                    className="checkbox-input"
                    disabled={isReadonly}
                  />
                  <span>Auto-Sync aktiviert</span>
                </label>
              </div>

              <div className="setting-item">
                <label htmlFor="auto_sync_interval" className="setting-label">
                  Auto-Sync Intervall (Sekunden)
                  <span className="setting-hint">(None = deaktiviert)</span>
                </label>
                <input
                  id="auto_sync_interval"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.auto_sync_interval || ''}
                  onChange={(e) => handleInputChange('auto_sync_interval', e.target.value)}
                  placeholder="Deaktiviert"
                  disabled={isReadonly || !currentSettings.auto_sync_enabled}
                />
              </div>
            </div>
          </div>

          {/* Email Notifications */}
          <div className="settings-section card">
            <h3 className="section-title">
              <MdEmail />
              E-Mail-Benachrichtigungen
            </h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label className="setting-label checkbox-label">
                  <input
                    type="checkbox"
                    checked={currentSettings.email_enabled}
                    onChange={(e) => handleInputChange('email_enabled', e.target.checked)}
                    className="checkbox-input"
                    disabled={isReadonly}
                  />
                  <span>E-Mail-Benachrichtigungen aktivieren</span>
                </label>
              </div>

              <div className="setting-item">
                <label htmlFor="smtp_host" className="setting-label">
                  SMTP Host
                </label>
                <input
                  id="smtp_host"
                  type="text"
                  className="form-input"
                  value={currentSettings.smtp_host || ''}
                  onChange={(e) => handleInputChange('smtp_host', e.target.value)}
                  placeholder="smtp.example.com"
                  disabled={isReadonly || !currentSettings.email_enabled}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="smtp_port" className="setting-label">
                  SMTP Port
                </label>
                <input
                  id="smtp_port"
                  type="number"
                  min="1"
                  max="65535"
                  className="form-input"
                  value={currentSettings.smtp_port}
                  onChange={(e) => handleInputChange('smtp_port', e.target.value)}
                  placeholder="587"
                  disabled={isReadonly || !currentSettings.email_enabled}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="smtp_user" className="setting-label">
                  SMTP Benutzername
                </label>
                <input
                  id="smtp_user"
                  type="text"
                  className="form-input"
                  value={currentSettings.smtp_user || ''}
                  onChange={(e) => handleInputChange('smtp_user', e.target.value)}
                  placeholder="user@example.com"
                  disabled={isReadonly || !currentSettings.email_enabled}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="smtp_password" className="setting-label">
                  SMTP Passwort
                  <span className="setting-hint">(über Environment-Variable SMTP_PASSWORD setzen)</span>
                </label>
                <input
                  id="smtp_password"
                  type="password"
                  className="form-input"
                  placeholder="Wird nicht angezeigt - über .env setzen"
                  disabled={true}
                  title="SMTP-Passwort muss über Environment-Variable SMTP_PASSWORD gesetzt werden"
                />
              </div>

              <div className="setting-item">
                <label htmlFor="smtp_from" className="setting-label">
                  Absender-E-Mail
                </label>
                <input
                  id="smtp_from"
                  type="email"
                  className="form-input"
                  value={currentSettings.smtp_from || ''}
                  onChange={(e) => handleInputChange('smtp_from', e.target.value)}
                  placeholder="noreply@example.com"
                  disabled={isReadonly || !currentSettings.email_enabled}
                />
              </div>

              <div className="setting-item full-width">
                <label htmlFor="email_recipients" className="setting-label">
                  Empfänger (komma-separiert)
                </label>
                <textarea
                  id="email_recipients"
                  className="form-input"
                  rows={3}
                  value={currentSettings.email_recipients.join(', ')}
                  onChange={(e) => handleInputChange('email_recipients', e.target.value)}
                  placeholder="admin@example.com, team@example.com"
                  disabled={isReadonly || !currentSettings.email_enabled}
                />
              </div>

              <div className="setting-item">
                {!isReadonly && (
                  <button
                    onClick={() => testEmailMutation.mutate()}
                    disabled={!currentSettings.email_enabled || testEmailMutation.isPending}
                    className="btn btn-primary"
                  >
                  <MdEmail />
                  {testEmailMutation.isPending ? 'Sende...' : 'Test-E-Mail senden'}
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Teams Notifications */}
          <div className="settings-section card">
            <h3 className="section-title">
              <MdGroup />
              Microsoft Teams-Benachrichtigungen
            </h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label className="setting-label checkbox-label">
                  <input
                    type="checkbox"
                    checked={currentSettings.teams_enabled}
                    onChange={(e) => handleInputChange('teams_enabled', e.target.checked)}
                    className="checkbox-input"
                    disabled={isReadonly}
                  />
                  <span>Teams-Benachrichtigungen aktivieren</span>
                </label>
              </div>

              <div className="setting-item full-width">
                <label htmlFor="teams_webhook_url" className="setting-label">
                  Teams Webhook-URL
                  <span className="setting-hint">(aus Teams-Kanal Connectors)</span>
                </label>
                <input
                  id="teams_webhook_url"
                  type="url"
                  className="form-input"
                  value={currentSettings.teams_webhook_url || ''}
                  onChange={(e) => handleInputChange('teams_webhook_url', e.target.value)}
                  placeholder="https://outlook.office.com/webhook/..."
                  disabled={isReadonly || !currentSettings.teams_enabled}
                />
              </div>

              <div className="setting-item">
                {!isReadonly && (
                  <button
                    onClick={() => testTeamsMutation.mutate()}
                    disabled={!currentSettings.teams_enabled || testTeamsMutation.isPending}
                    className="btn btn-primary"
                  >
                    <MdGroup />
                    {testTeamsMutation.isPending ? 'Sende...' : 'Test-Teams-Nachricht senden'}
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Actions */}
          {!isReadonly && (
            <div className="settings-actions card">
              <h3 className="section-title">Aktionen</h3>
              <div className="actions-grid">
                <button
                  onClick={handleSave}
                  disabled={updateSettingsMutation.isPending || !localSettings}
                  className="btn btn-primary"
                >
                  <MdSave />
                  Einstellungen speichern
                </button>
                <button
                  onClick={handleForceCleanup}
                  disabled={forceCleanupMutation.isPending}
                  className="btn btn-warning"
                >
                  <MdRefresh />
                  {forceCleanupMutation.isPending ? 'Cleanup läuft...' : 'Force Flush (Cleanup)'}
                </button>
              </div>
              <div className="warning-box">
                <MdWarning />
                <p>
                  <strong>Hinweis:</strong> Einstellungen werden aktuell nur aus Environment-Variablen geladen.
                  Um Einstellungen dauerhaft zu ändern, bearbeiten Sie die .env-Datei oder setzen Sie
                  Environment-Variablen. Ein Neustart der Anwendung ist erforderlich.
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Cleanup Info Modal */}
      {showCleanupInfo && currentSettings && (
        <div className="modal-overlay" onClick={() => setShowCleanupInfo(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Force Flush (Cleanup) - Was wird geflusht?</h3>
              <button
                className="modal-close"
                onClick={() => setShowCleanupInfo(false)}
                aria-label="Schließen"
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              <div className="cleanup-info-section">
                <h4>📁 Log-Cleanup</h4>
                <p className="cleanup-description">
                  Bereinigt Log-Dateien, Metrics-Dateien und Datenbank-Einträge
                </p>
                <ul className="cleanup-actions">
                  {currentSettings.log_retention_runs ? (
                    <li>
                      Löscht älteste Runs pro Pipeline (max. {currentSettings.log_retention_runs} Runs pro Pipeline behalten)
                    </li>
                  ) : null}
                  {currentSettings.log_retention_days ? (
                    <li>
                      Löscht Runs älter als {currentSettings.log_retention_days} Tage
                    </li>
                  ) : null}
                  {currentSettings.log_max_size_mb ? (
                    <li>
                      Kürzt oder löscht Log-Dateien größer als {currentSettings.log_max_size_mb} MB
                    </li>
                  ) : null}
                  {!currentSettings.log_retention_runs && !currentSettings.log_retention_days && !currentSettings.log_max_size_mb && (
                    <li className="cleanup-disabled">Keine Log-Cleanup-Regeln konfiguriert</li>
                  )}
                </ul>
              </div>

              <div className="cleanup-info-section">
                <h4>🐳 Docker-Cleanup</h4>
                <p className="cleanup-description">
                  Bereinigt verwaiste Docker-Container und Volumes
                </p>
                <ul className="cleanup-actions">
                  <li>Löscht verwaiste Container mit Label 'fastflow-run-id' (ohne zugehörigen DB-Eintrag)</li>
                  <li>Löscht beendete Container mit Label 'fastflow-run-id'</li>
                  <li>Löscht verwaiste Volumes mit Label 'fastflow-run-id'</li>
                </ul>
              </div>

              <div className="cleanup-warning">
                <MdWarning />
                <p>
                  <strong>Warnung:</strong> Diese Aktion kann nicht rückgängig gemacht werden.
                  Alle gelöschten Daten gehen unwiderruflich verloren.
                </p>
              </div>
            </div>
            <div className="modal-footer">
              <button
                className="btn btn-secondary"
                onClick={() => setShowCleanupInfo(false)}
              >
                Abbrechen
              </button>
              <button
                className="btn btn-warning"
                onClick={confirmForceCleanup}
                disabled={forceCleanupMutation.isPending}
              >
                <MdRefresh />
                {forceCleanupMutation.isPending ? 'Cleanup läuft...' : 'Cleanup durchführen'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
