import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../api/client'
import './Sync.css'

interface SyncStatus {
  branch: string
  remote_url?: string
  last_commit?: string
  last_sync?: string
  status?: string
  pipelines_cached?: string[]
}

interface SyncSettings {
  auto_sync_enabled: boolean
  auto_sync_interval: number | null
}

export default function Sync() {
  const queryClient = useQueryClient()
  const [syncBranch, setSyncBranch] = useState('')
  const [activeTab, setActiveTab] = useState<'status' | 'settings' | 'logs'>('status')
  const [settingsForm, setSettingsForm] = useState<SyncSettings>({
    auto_sync_enabled: false,
    auto_sync_interval: null,
  })

  const { data: syncStatus, isLoading } = useQuery<SyncStatus>({
    queryKey: ['sync-status'],
    queryFn: async () => {
      const response = await apiClient.get('/sync/status')
      return response.data
    },
    refetchInterval: 10000, // Auto-refresh alle 10 Sekunden
  })

  const { data: settings, isLoading: settingsLoading } = useQuery<SyncSettings>({
    queryKey: ['sync-settings'],
    queryFn: async () => {
      const response = await apiClient.get('/sync/settings')
      return response.data
    },
  })

  useEffect(() => {
    if (settings) {
      setSettingsForm(settings)
    }
  }, [settings])

  const { data: syncLogs } = useQuery({
    queryKey: ['sync-logs'],
    queryFn: async () => {
      const response = await apiClient.get('/sync/logs?limit=50')
      return response.data
    },
    enabled: activeTab === 'logs',
    refetchInterval: activeTab === 'logs' ? 5000 : false,
  })

  const syncMutation = useMutation({
    mutationFn: async (branch?: string) => {
      const response = await apiClient.post('/sync', branch ? { branch } : {})
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      alert('Git-Sync erfolgreich abgeschlossen')
    },
    onError: (error: any) => {
      alert(`Fehler beim Git-Sync: ${error.response?.data?.detail || error.message}`)
    },
  })

  const updateSettingsMutation = useMutation({
    mutationFn: async (newSettings: SyncSettings) => {
      const response = await apiClient.put('/sync/settings', newSettings)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-settings'] })
      alert('Sync-Einstellungen aktualisiert')
    },
    onError: (error: any) => {
      alert(`Fehler beim Aktualisieren: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleSync = () => {
    if (syncMutation.isPending) return
    if (confirm('Git-Sync ausführen? Dies kann einige Zeit dauern.')) {
      syncMutation.mutate(syncBranch || undefined)
    }
  }

  const handleSaveSettings = () => {
    if (settingsForm.auto_sync_interval !== null && settingsForm.auto_sync_interval < 60) {
      alert('Auto-Sync-Intervall muss mindestens 60 Sekunden betragen')
      return
    }
    updateSettingsMutation.mutate(settingsForm)
  }

  if (isLoading) {
    return <div>Laden...</div>
  }

  return (
    <div className="sync">
      <h2>Git Sync</h2>

      <div className="sync-tabs">
        <button
          className={activeTab === 'status' ? 'active' : ''}
          onClick={() => setActiveTab('status')}
        >
          Status
        </button>
        <button
          className={activeTab === 'settings' ? 'active' : ''}
          onClick={() => setActiveTab('settings')}
        >
          Einstellungen
        </button>
        <button
          className={activeTab === 'logs' ? 'active' : ''}
          onClick={() => setActiveTab('logs')}
        >
          Logs
        </button>
      </div>

      {activeTab === 'status' && (
        <>
      <div className="sync-status-card">
        <h3>Status</h3>
        <div className="status-info">
          <div className="status-row">
            <span className="status-label">Branch:</span>
            <span className="status-value">{syncStatus?.branch || '-'}</span>
          </div>
          {syncStatus?.remote_url && (
            <div className="status-row">
              <span className="status-label">Remote URL:</span>
              <span className="status-value">{syncStatus.remote_url}</span>
            </div>
          )}
          {syncStatus?.last_commit && (
            <div className="status-row">
              <span className="status-label">Letzter Commit:</span>
              <span className="status-value">{syncStatus.last_commit}</span>
            </div>
          )}
          {syncStatus?.last_sync && (
            <div className="status-row">
              <span className="status-label">Letzter Sync:</span>
              <span className="status-value">
                {new Date(syncStatus.last_sync).toLocaleString('de-DE')}
              </span>
            </div>
          )}
          {syncStatus?.status && (
            <div className="status-row">
              <span className="status-label">Status:</span>
              <span className={`status-badge ${syncStatus.status.toLowerCase()}`}>
                {syncStatus.status}
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="sync-actions-card">
        <h3>Sync ausführen</h3>
        <div className="sync-form">
          <div className="form-group">
            <label htmlFor="sync-branch">Branch (optional, leer = Standard):</label>
            <input
              id="sync-branch"
              type="text"
              value={syncBranch}
              onChange={(e) => setSyncBranch(e.target.value)}
              placeholder={syncStatus?.branch || 'main'}
            />
          </div>
          <button
            onClick={handleSync}
            disabled={syncMutation.isPending}
            className="sync-button"
          >
            {syncMutation.isPending ? 'Sync läuft...' : 'Git Sync ausführen'}
          </button>
        </div>
      </div>

      {syncStatus?.pipelines_cached && syncStatus.pipelines_cached.length > 0 && (
        <div className="cache-status-card">
          <h3>Gecachte Pipelines (Pre-Heated)</h3>
          <div className="cached-pipelines">
            {syncStatus.pipelines_cached.map((pipeline) => (
              <span key={pipeline} className="cached-badge">
                {pipeline}
              </span>
            ))}
          </div>
        </div>
      )}
        </>
      )}

      {activeTab === 'settings' && (
        <div className="sync-settings-card">
          <h3>Sync-Einstellungen</h3>
          {settingsLoading ? (
            <div>Lade Einstellungen...</div>
          ) : (
            <div className="settings-form">
              <div className="form-group">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={settingsForm.auto_sync_enabled}
                    onChange={(e) =>
                      setSettingsForm({ ...settingsForm, auto_sync_enabled: e.target.checked })
                    }
                  />
                  Automatisches Sync aktivieren
                </label>
              </div>
              <div className="form-group">
                <label htmlFor="sync-interval">Auto-Sync-Intervall (Sekunden, min. 60):</label>
                <input
                  id="sync-interval"
                  type="number"
                  min="60"
                  value={settingsForm.auto_sync_interval || ''}
                  onChange={(e) =>
                    setSettingsForm({
                      ...settingsForm,
                      auto_sync_interval: e.target.value ? parseInt(e.target.value) : null,
                    })
                  }
                  disabled={!settingsForm.auto_sync_enabled}
                />
              </div>
              <div className="form-actions">
                <button
                  onClick={handleSaveSettings}
                  disabled={updateSettingsMutation.isPending}
                  className="save-button"
                >
                  {updateSettingsMutation.isPending ? 'Speichert...' : 'Einstellungen speichern'}
                </button>
              </div>
              <p className="settings-note">
                Hinweis: Einstellungen werden nur für die laufende Instanz gespeichert.
                Für persistente Änderungen die .env-Datei bearbeiten.
              </p>
            </div>
          )}
        </div>
      )}

      {activeTab === 'logs' && (
        <div className="sync-logs-card">
          <h3>Sync-Logs</h3>
          {syncLogs && syncLogs.length > 0 ? (
            <div className="sync-logs-list">
              {syncLogs.map((log: any, index: number) => (
                <div key={index} className="sync-log-entry">
                  <div className="log-header">
                    <span className="log-timestamp">
                      {log.timestamp
                        ? new Date(log.timestamp).toLocaleString('de-DE')
                        : '-'}
                    </span>
                    <span className={`log-status log-${log.status || 'unknown'}`}>
                      {log.status || log.event || 'Unknown'}
                    </span>
                  </div>
                  {log.message && (
                    <div className="log-message">{log.message}</div>
                  )}
                  {log.error && (
                    <div className="log-error">Fehler: {log.error}</div>
                  )}
                  {log.branch && (
                    <div className="log-details">Branch: {log.branch}</div>
                  )}
                  {log.pipelines_cached && log.pipelines_cached.length > 0 && (
                    <div className="log-details">
                      Gecachte Pipelines: {log.pipelines_cached.join(', ')}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="no-logs">Keine Sync-Logs gefunden</p>
          )}
        </div>
      )}
    </div>
  )
}
