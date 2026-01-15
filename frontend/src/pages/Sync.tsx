import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import Tooltip from '../components/Tooltip'
import InfoIcon from '../components/InfoIcon'
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

interface GitHubConfig {
  app_id: string | null
  installation_id: string | null
  configured: boolean
  has_private_key: boolean
}

export default function Sync() {
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const [syncBranch, setSyncBranch] = useState('')
  const [activeTab, setActiveTab] = useState<'status' | 'settings' | 'logs' | 'github'>('status')
  const [settingsForm, setSettingsForm] = useState<SyncSettings>({
    auto_sync_enabled: false,
    auto_sync_interval: null,
  })

  // GitHub Config State
  const [githubForm, setGithubForm] = useState({
    app_id: '',
    installation_id: '',
    private_key: '',
    private_key_file: null as File | null,
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

  // GitHub Config Query - immer laden, nicht nur wenn Tab aktiv
  const { data: githubConfig, isLoading: githubConfigLoading } = useQuery<GitHubConfig>({
    queryKey: ['github-config'],
    queryFn: async () => {
      const response = await apiClient.get('/sync/github-config')
      return response.data
    },
  })

  useEffect(() => {
    if (githubConfig && activeTab === 'github') {
      setGithubForm({
        app_id: githubConfig.app_id || '',
        installation_id: githubConfig.installation_id || '',
        private_key: '',
        private_key_file: null,
      })
    }
  }, [githubConfig, activeTab])

  // Handle Callbacks (URL-Parameter)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const setupSuccess = params.get('setup_success')
    const installationSuccess = params.get('installation_success')
    const manifestCode = params.get('manifest_code')
    const state = params.get('state')
    const exchangeError = params.get('exchange_error')
    const tab = params.get('tab')

    if (setupSuccess === 'true' && tab === 'github') {
      // Erfolgreiche App-Erstellung UND Installation in einem Schritt!
      queryClient.invalidateQueries({ queryKey: ['github-config'] })
      showSuccess('✓ GitHub App erfolgreich erstellt und installiert! Die App ist jetzt bereit für Git-Sync.')
      // Entferne URL-Parameter
      window.history.replaceState({}, '', window.location.pathname + '?tab=github')
    } else if (installationSuccess === 'true' && tab === 'github') {
      // Erfolgreiche Installation (Fallback für manuellen Flow)
      queryClient.invalidateQueries({ queryKey: ['github-config'] })
      showSuccess('✓ GitHub App erfolgreich installiert und konfiguriert! Die App ist jetzt bereit für Git-Sync.')
      // Entferne URL-Parameter
      window.history.replaceState({}, '', window.location.pathname + '?tab=github')
    } else if (manifestCode && state && tab === 'github' && exchangeError === 'true') {
      // Automatischer Exchange fehlgeschlagen - versuche manuellen Exchange
      manifestExchangeMutation.mutate({ code: manifestCode, state })
    }
  }, [])

  const syncMutation = useMutation({
    mutationFn: async (branch?: string) => {
      const response = await apiClient.post('/sync', branch ? { branch } : {})
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      showSuccess('Git-Sync erfolgreich abgeschlossen')
    },
    onError: (error: any) => {
      showError(`Fehler beim Git-Sync: ${error.response?.data?.detail || error.message}`)
    },
  })

  const updateSettingsMutation = useMutation({
    mutationFn: async (newSettings: SyncSettings) => {
      const response = await apiClient.put('/sync/settings', newSettings)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-settings'] })
      showSuccess('Sync-Einstellungen aktualisiert')
    },
    onError: (error: any) => {
      showError(`Fehler beim Aktualisieren: ${error.response?.data?.detail || error.message}`)
    },
  })

  // GitHub Config Mutations
  const saveGithubConfigMutation = useMutation({
    mutationFn: async (data: { app_id: string; installation_id: string; private_key: string }) => {
      const response = await apiClient.post('/sync/github-config', data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['github-config'] })
      showSuccess('GitHub Apps Konfiguration erfolgreich gespeichert')
      setGithubForm({ ...githubForm, private_key: '', private_key_file: null })
    },
    onError: (error: any) => {
      showError(`Fehler beim Speichern: ${error.response?.data?.detail || error.message}`)
    },
  })

  const testGithubConfigMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/sync/github-config/test')
      return response.data
    },
    onSuccess: (data) => {
      if (data.success) {
        showSuccess('✓ Konfiguration erfolgreich getestet!')
      } else {
        showError(`✗ Test fehlgeschlagen: ${data.message}`)
      }
    },
    onError: (error: any) => {
      showError(`Fehler beim Testen: ${error.response?.data?.detail || error.message}`)
    },
  })

  const deleteGithubConfigMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.delete('/sync/github-config')
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['github-config'] })
      showSuccess('GitHub Apps Konfiguration gelöscht')
      setGithubForm({
        app_id: '',
        installation_id: '',
        private_key: '',
        private_key_file: null,
      })
    },
    onError: (error: any) => {
      showError(`Fehler beim Löschen: ${error.response?.data?.detail || error.message}`)
    },
  })

  // Manifest Flow Mutations
  const manifestAuthorizeMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.get('/sync/github-manifest/authorize')
      return response.data
    },
    onSuccess: (data) => {
      // Redirect zu GitHub
      window.location.href = data.authorization_url
    },
    onError: (error: any) => {
      showError(`Fehler: ${error.response?.data?.detail || error.message}`)
    },
  })

  const manifestExchangeMutation = useMutation({
    mutationFn: async (data: { code: string; state: string }) => {
      const response = await apiClient.post('/sync/github-manifest/exchange', data)
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['github-config'] })
      showSuccess(`✓ ${data.message}${data.next_step ? ' ' + data.next_step : ''}`)
      // Entferne URL-Parameter
      window.history.replaceState({}, '', window.location.pathname + '?tab=github')
    },
    onError: (error: any) => {
      showError(`Fehler beim Code-Exchange: ${error.response?.data?.detail || error.message}`)
      // Entferne URL-Parameter auch bei Fehler
      window.history.replaceState({}, '', window.location.pathname + '?tab=github')
    },
  })

  const handleSync = async () => {
    if (syncMutation.isPending) return
    const confirmed = await showConfirm('Git-Sync ausführen? Dies kann einige Zeit dauern.')
    if (confirmed) {
      syncMutation.mutate(syncBranch || undefined)
    }
  }

  const handleSaveSettings = () => {
    if (settingsForm.auto_sync_interval !== null && settingsForm.auto_sync_interval < 60) {
      showError('Auto-Sync-Intervall muss mindestens 60 Sekunden betragen')
      return
    }
    updateSettingsMutation.mutate(settingsForm)
  }

  // GitHub Config Handlers
  const handleFileUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      if (!file.name.endsWith('.pem')) {
        showError('Bitte wählen Sie eine .pem Datei aus')
        return
      }
      const reader = new FileReader()
      reader.onload = (e) => {
        const content = e.target?.result as string
        setGithubForm({
          ...githubForm,
          private_key: content,
          private_key_file: file,
        })
      }
      reader.readAsText(file)
    }
  }

  const handleSaveGithubConfig = () => {
    if (!githubForm.app_id || !githubForm.installation_id || !githubForm.private_key) {
      showError('Bitte füllen Sie alle Felder aus')
      return
    }

    // Validiere numerische IDs
    if (!/^\d+$/.test(githubForm.app_id.trim())) {
      showError('GitHub App ID muss eine Zahl sein')
      return
    }

    if (!/^\d+$/.test(githubForm.installation_id.trim())) {
      showError('Installation ID muss eine Zahl sein')
      return
    }

    // Validiere Private Key Format
    if (!githubForm.private_key.includes('-----BEGIN') || !githubForm.private_key.includes('-----END')) {
      showError('Private Key muss PEM-Format haben (-----BEGIN ... -----END ...)')
      return
    }

    saveGithubConfigMutation.mutate({
      app_id: githubForm.app_id.trim(),
      installation_id: githubForm.installation_id.trim(),
      private_key: githubForm.private_key,
    })
  }

  const handleTestGithubConfig = () => {
    testGithubConfigMutation.mutate()
  }

  const handleDeleteGithubConfig = async () => {
    const confirmed = await showConfirm('GitHub Apps Konfiguration wirklich löschen?')
    if (confirmed) {
      deleteGithubConfigMutation.mutate()
    }
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
        <button
          className={activeTab === 'github' ? 'active' : ''}
          onClick={() => setActiveTab('github')}
        >
          GitHub Apps
        </button>
      </div>

      {activeTab === 'status' && (
        <>
      <div className="sync-status-card">
        <h3>Status</h3>
        <div className="status-info">
          <div className="status-row">
            <span className="status-label">
              Branch:
              <InfoIcon content="Der Git-Branch, der für den Sync verwendet wird" />
            </span>
            <span className="status-value">{syncStatus?.branch || '-'}</span>
          </div>
          {syncStatus?.remote_url && (
            <div className="status-row">
              <span className="status-label">
                Remote URL:
                <InfoIcon content="URL des Git-Repositories" />
              </span>
              <span className="status-value">{syncStatus.remote_url}</span>
            </div>
          )}
          {syncStatus?.last_commit && (
            <div className="status-row">
              <span className="status-label">
                Letzter Commit:
                <InfoIcon content="Commit-Hash des letzten synchronisierten Commits" />
              </span>
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
          {!isReadonly && (
            <button
              onClick={handleSync}
              disabled={syncMutation.isPending}
              className="sync-button"
            >
              {syncMutation.isPending ? 'Sync läuft...' : 'Git Sync ausführen'}
            </button>
          )}
        </div>
      </div>

      {syncStatus?.pipelines_cached && syncStatus.pipelines_cached.length > 0 && (
        <div className="cache-status-card">
          <h3>
            Gecachte Pipelines (Pre-Heated)
            <InfoIcon content="Diese Pipelines wurden beim Sync bereits vorgewärmt (pre-heated) für schnellere Ausführung" />
          </h3>
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
                  <InfoIcon content="Wenn aktiviert, wird automatisch in regelmäßigen Abständen synchronisiert" />
                </label>
              </div>
              <div className="form-group">
                <label htmlFor="sync-interval">
                  Auto-Sync-Intervall (Sekunden, min. 60):
                  <InfoIcon content="Intervall in Sekunden (Minimum: 60). Beispiel: 300 = alle 5 Minuten" />
                </label>
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
              {!isReadonly && (
                <div className="form-actions">
                  <button
                    onClick={handleSaveSettings}
                    disabled={updateSettingsMutation.isPending}
                    className="save-button"
                  >
                    {updateSettingsMutation.isPending ? 'Speichert...' : 'Einstellungen speichern'}
                  </button>
                </div>
              )}
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

      {activeTab === 'github' && (
        <div className="sync-github-card">
          <h3>GitHub Apps Konfiguration</h3>
          {githubConfigLoading ? (
            <div>Lade Konfiguration...</div>
          ) : (
            <>
              {/* Zeige Connect Button immer wenn nicht konfiguriert */}
              {(!githubConfig || !githubConfig.configured) && (
                <div className="github-connect-section">
                  <h4>
                    Ein-Klick GitHub Integration
                    <InfoIcon content="Ein-Klick-Setup: 1. App wird automatisch erstellt 2. Sie wählen Ihre Repositories aus 3. Alles wird automatisch konfiguriert" />
                  </h4>
                  <p>
                    Klicken Sie auf den Button und wählen Sie Ihre Repositories aus.
                    Alles andere passiert automatisch - App-Erstellung, Konfiguration und Installation.
                  </p>
                  <button
                    onClick={() => {
                      // Öffne in neuem Fenster/Tab für nahtlosen Flow
                      window.location.href = '/api/sync/github-manifest/authorize'
                    }}
                    disabled={manifestAuthorizeMutation.isPending}
                    className="connect-github-button"
                  >
                    {manifestAuthorizeMutation.isPending
                      ? 'Wird weitergeleitet...'
                      : '🔗 Mit GitHub verbinden'}
                  </button>
                  <div className="github-flow-info">
                    <small>
                      ✓ App wird automatisch erstellt<br />
                      ✓ Sie wählen nur Ihre Repositories aus<br />
                      ✓ Alles wird automatisch konfiguriert
                    </small>
                  </div>
                  <div className="or-divider">
                    <span>oder</span>
                  </div>
                </div>
              )}
              
              {githubConfig?.configured && (
                <div className="github-success-message">
                  ✓ GitHub App ist bereits konfiguriert!
                </div>
              )}

              <div className="github-status">
                <div className="status-row">
                  <span className="status-label">Status:</span>
                  <span
                    className={`status-badge ${githubConfig?.configured ? 'configured' : 'not-configured'}`}
                  >
                    {githubConfig?.configured ? 'Konfiguriert' : 'Nicht konfiguriert'}
                  </span>
                </div>
                {githubConfig?.app_id && (
                  <div className="status-row">
                    <span className="status-label">App ID:</span>
                    <span className="status-value">{githubConfig.app_id}</span>
                  </div>
                )}
                {githubConfig?.installation_id && (
                  <div className="status-row">
                    <span className="status-label">Installation ID:</span>
                    <span className="status-value">{githubConfig.installation_id}</span>
                  </div>
                )}
                {githubConfig?.configured && !githubConfig?.has_private_key && (
                  <div className="status-warning">
                    ⚠️ Warnung: Private Key Datei fehlt
                  </div>
                )}
              </div>

              {!githubConfig?.configured && (
                <div className="github-manual-section">
                  <h4>Manuelle Konfiguration</h4>
                  <p>Falls Sie bereits eine GitHub App haben, können Sie die Daten manuell eingeben.</p>
                </div>
              )}

              <div className="github-form">
                <div className="form-group">
                  <label htmlFor="github-app-id">
                    GitHub App ID:
                    <InfoIcon content="Numerische ID der GitHub App (wird automatisch konfiguriert)" />
                  </label>
                  <input
                    id="github-app-id"
                    type="text"
                    value={githubForm.app_id}
                    onChange={(e) => setGithubForm({ ...githubForm, app_id: e.target.value })}
                    placeholder="123456"
                    disabled={!!githubConfig?.app_id}
                  />
                  <small>
                    {githubConfig?.app_id
                      ? 'App ID wurde automatisch konfiguriert'
                      : 'Numerische App ID von GitHub'}
                  </small>
                </div>

                <div className="form-group">
                  <label htmlFor="github-installation-id">
                    Installation ID:
                    <InfoIcon content="Numerische ID der Installation in Ihrem Repository/Organisation" />
                  </label>
                  <input
                    id="github-installation-id"
                    type="text"
                    value={githubForm.installation_id}
                    onChange={(e) =>
                      setGithubForm({ ...githubForm, installation_id: e.target.value })
                    }
                    placeholder="12345678"
                  />
                  <small>Numerische Installation ID von GitHub</small>
                </div>

                <div className="form-group">
                  <label htmlFor="github-private-key">
                    Private Key (.pem Datei):
                    <InfoIcon content="PEM-formatierte Private Key Datei. Wird verschlüsselt gespeichert." />
                  </label>
                  <input
                    id="github-private-key"
                    type="file"
                    accept=".pem"
                    onChange={handleFileUpload}
                  />
                  {githubForm.private_key_file && (
                    <div className="file-info">
                      ✓ Datei ausgewählt: {githubForm.private_key_file.name}
                    </div>
                  )}
                  <small>Private Key im PEM-Format (-----BEGIN ... -----END ...)</small>
                </div>

                {!isReadonly && (
                  <div className="form-actions">
                    <button
                      onClick={handleSaveGithubConfig}
                      disabled={saveGithubConfigMutation.isPending}
                      className="save-button"
                    >
                      {saveGithubConfigMutation.isPending ? 'Speichert...' : 'Speichern'}
                    </button>
                    {githubConfig?.configured && (
                      <>
                        <Tooltip content="Testet die Verbindung zur GitHub API">
                          <button
                            onClick={handleTestGithubConfig}
                            disabled={testGithubConfigMutation.isPending}
                            className="test-button"
                          >
                            {testGithubConfigMutation.isPending ? 'Testet...' : 'Konfiguration testen'}
                          </button>
                        </Tooltip>
                        <button
                          onClick={handleDeleteGithubConfig}
                          disabled={deleteGithubConfigMutation.isPending}
                          className="delete-button"
                        >
                          {deleteGithubConfigMutation.isPending ? 'Löscht...' : 'Löschen'}
                        </button>
                      </>
                    )}
                  </div>
                )}

                <div className="github-info">
                  <h4>Hilfe:</h4>
                  <ul>
                    <li>
                      Erstellen Sie eine GitHub App unter{' '}
                      <a
                        href="https://github.com/settings/apps/new"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        GitHub Settings
                      </a>
                    </li>
                    <li>Laden Sie den Private Key herunter (.pem Datei)</li>
                    <li>Installieren Sie die App in Ihrer Organisation/Repository</li>
                    <li>Geben Sie App ID und Installation ID ein</li>
                    <li>Laden Sie den Private Key hoch</li>
                    <li>Testen Sie die Konfiguration mit dem Test-Button</li>
                  </ul>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
