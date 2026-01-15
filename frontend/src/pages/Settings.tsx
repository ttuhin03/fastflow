import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/client'
import { MdSave, MdRefresh, MdInfo, MdWarning } from 'react-icons/md'
import StorageStats from '../components/StorageStats'
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
}

export default function Settings() {
  const queryClient = useQueryClient()
  const [localSettings, setLocalSettings] = useState<Settings | null>(null)

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
      alert(
        `Cleanup erfolgreich!\n` +
        `Logs: ${data.log_cleanup?.deleted_logs || 0} gelöscht, ${data.log_cleanup?.truncated_logs || 0} gekürzt\n` +
        `Docker: ${data.docker_cleanup?.deleted_containers || 0} Container, ${data.docker_cleanup?.deleted_volumes || 0} Volumes`
      )
    },
    onError: (error: any) => {
      alert(`Fehler beim Cleanup: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleInputChange = (field: keyof Settings, value: string | number | boolean | null) => {
    if (!settings) return
    
    let processedValue: number | boolean | null
    
    if (field === 'auto_sync_enabled') {
      processedValue = typeof value === 'boolean' ? value : value === 'true'
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
    updateSettingsMutation.mutate(localSettings)
  }

  const handleForceCleanup = () => {
    if (confirm('Möchten Sie wirklich einen Force-Flush (Cleanup) durchführen? Dies kann nicht rückgängig gemacht werden.')) {
      forceCleanupMutation.mutate()
    }
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
                  disabled={!currentSettings.auto_sync_enabled}
                />
              </div>
            </div>
          </div>

          {/* Actions */}
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
        </div>
      )}
    </div>
  )
}
