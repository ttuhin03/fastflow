import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import Tooltip from '../components/Tooltip'
import InfoIcon from '../components/InfoIcon'
import './Sync.css'

interface SyncStatus {
  branch: string
  remote_url?: string
  last_commit?: { hash: string; message: string; date: string } | string
  last_sync?: string
  status?: string
  pipelines_cached?: string[]
  repo_configured?: boolean
}

/** Formatiert last_commit sicher (Backend liefert Objekt { hash, message, date }); nie ein Objekt als React-Child rendern. */
function formatLastCommit(lc: SyncStatus['last_commit']): string {
  if (lc == null) return ''
  if (typeof lc === 'string') return lc
  if (typeof lc === 'object' && lc !== null && 'hash' in lc) {
    const hash = typeof lc.hash === 'string' ? lc.hash.slice(0, 7) : ''
    const msg = typeof lc.message === 'string' ? lc.message : ''
    const date = typeof lc.date === 'string' ? lc.date : ''
    return [hash, msg].filter(Boolean).join(' – ') + (date ? ` (${date})` : '')
  }
  return ''
}

interface SyncSettings {
  auto_sync_enabled: boolean
  auto_sync_interval: number | null
}

interface RepoConfig {
  repo_url: string | null
  branch: string | null
  configured: boolean
  pipelines_subdir?: string | null
}

export default function Sync() {
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const [syncBranch, setSyncBranch] = useState('')
  const [activeTab, setActiveTab] = useState<'status' | 'settings' | 'logs' | 'repository'>('status')
  const [settingsForm, setSettingsForm] = useState<SyncSettings>({
    auto_sync_enabled: false,
    auto_sync_interval: null,
  })

  const [repoForm, setRepoForm] = useState({
    repo_url: '',
    token: '',
    branch: 'main',
    pipelines_subdir: '',
  })

  const syncInterval = useRefetchInterval(10000)
  const { data: syncStatus, isLoading } = useQuery<SyncStatus>({
    queryKey: ['sync-status'],
    queryFn: async () => {
      const response = await apiClient.get('/sync/status')
      return response.data
    },
    refetchInterval: syncInterval,
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

  const syncLogsInterval = useRefetchInterval(activeTab === 'logs' ? 5000 : false)
  const { data: syncLogs } = useQuery({
    queryKey: ['sync-logs'],
    queryFn: async () => {
      const response = await apiClient.get('/sync/logs?limit=50')
      return response.data
    },
    enabled: activeTab === 'logs',
    refetchInterval: syncLogsInterval,
  })

  const { data: repoConfig, isLoading: repoConfigLoading } = useQuery<RepoConfig>({
    queryKey: ['repo-config'],
    queryFn: async () => {
      const response = await apiClient.get('/sync/repo-config')
      return response.data
    },
  })

  useEffect(() => {
    if (repoConfig && activeTab === 'repository') {
      setRepoForm({
        repo_url: repoConfig.repo_url || '',
        token: '',
        branch: repoConfig.branch || 'main',
        pipelines_subdir: repoConfig.pipelines_subdir ?? '',
      })
    }
  }, [repoConfig, activeTab])

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

  const saveRepoConfigMutation = useMutation({
    mutationFn: async (data: { repo_url: string; token?: string; branch?: string; pipelines_subdir?: string }) => {
      const response = await apiClient.post('/sync/repo-config', data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['repo-config'] })
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      showSuccess('Repository-Konfiguration gespeichert')
      setRepoForm((f) => ({ ...f, token: '' }))
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
    },
    onError: (error: any) => {
      showError(`Fehler beim Speichern: ${error.response?.data?.detail || error.message}`)
    },
  })

  const testRepoConfigMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/sync/repo-config/test')
      return response.data
    },
    onSuccess: (data: { success: boolean; message: string }) => {
      if (data.success) {
        showSuccess('✓ ' + data.message)
      } else {
        showError('✗ ' + data.message)
      }
    },
    onError: (error: any) => {
      showError(`Fehler beim Testen: ${error.response?.data?.detail || error.message}`)
    },
  })

  const deleteRepoConfigMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.delete('/sync/repo-config')
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['repo-config'] })
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      showSuccess('Repository-Konfiguration gelöscht')
      setRepoForm({ repo_url: '', token: '', branch: 'main', pipelines_subdir: '' })
    },
    onError: (error: any) => {
      showError(`Fehler beim Löschen: ${error.response?.data?.detail || error.message}`)
    },
  })

  const clearPipelinesMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/sync/clear-pipelines')
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      showSuccess('Pipelines-Verzeichnis wurde geleert. Sie können nun ein neues Repo synchronisieren.')
    },
    onError: (error: any) => {
      showError(`Fehler: ${error.response?.data?.detail || error.message}`)
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

  const handleSaveRepoConfig = () => {
    const url = repoForm.repo_url.trim()
    if (!url) {
      showError('Bitte geben Sie die Repository-URL ein')
      return
    }
    if (!url.startsWith('https://') && !url.startsWith('http://')) {
      showError('URL muss mit https:// oder http:// beginnen')
      return
    }
    saveRepoConfigMutation.mutate({
      repo_url: url,
      token: repoForm.token.trim() || undefined,
      branch: repoForm.branch.trim() || undefined,
      pipelines_subdir: repoForm.pipelines_subdir.trim() || undefined,
    })
  }

  const handleTestRepoConfig = () => {
    testRepoConfigMutation.mutate()
  }

  const handleClearPipelines = async () => {
    const confirmed = await showConfirm(
      'Alle Pipelines im Verzeichnis löschen (inkl. .git)? Danach können Sie ein neues Repository per Sync klonen. Diese Aktion kann nicht rückgängig gemacht werden.'
    )
    if (confirmed) {
      clearPipelinesMutation.mutate()
    }
  }

  const handleDeleteRepoConfig = async () => {
    const confirmed = await showConfirm('Repository-Konfiguration wirklich löschen?')
    if (confirmed) {
      deleteRepoConfigMutation.mutate()
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
          className={activeTab === 'repository' ? 'active' : ''}
          onClick={() => setActiveTab('repository')}
        >
          Repository
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
          {formatLastCommit(syncStatus?.last_commit) && (
            <div className="status-row">
              <span className="status-label">
                Letzter Commit:
                <InfoIcon content="Commit-Hash des letzten synchronisierten Commits" />
              </span>
              <span className="status-value">{formatLastCommit(syncStatus?.last_commit)}</span>
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
              disabled={isReadonly}
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
                    disabled={isReadonly}
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
                  disabled={isReadonly || !settingsForm.auto_sync_enabled}
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

      {activeTab === 'repository' && (
        <div className="sync-repo-card">
          <h3>Repository verbinden</h3>
          <p className="repo-config-intro">
            Geben Sie die HTTPS-URL Ihres Pipeline-Repositories ein. Für private Repos einen Personal Access Token (PAT) mit Lese-Recht angeben.
            Alternativ können Sie GIT_REPO_URL und GIT_SYNC_TOKEN in der Umgebung setzen.
          </p>
          {repoConfigLoading ? (
            <div>Lade Konfiguration...</div>
          ) : (
            <>
              {repoConfig?.configured && (
                <div className="repo-configured-badge">
                  Repository ist konfiguriert: {repoConfig.repo_url}
                </div>
              )}
              <div className="github-form">
                <div className="form-group">
                  <label htmlFor="repo-url">
                    Repository-URL (HTTPS):
                    <InfoIcon content="z. B. https://github.com/org/repo.git" />
                  </label>
                  <input
                    id="repo-url"
                    type="url"
                    value={repoForm.repo_url}
                    onChange={(e) => setRepoForm({ ...repoForm, repo_url: e.target.value })}
                    placeholder="https://github.com/org/repo.git"
                    disabled={isReadonly}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="repo-token">
                    Token (optional, für private Repos):
                    <InfoIcon content="Personal Access Token mit repo-Berechtigung. Leer lassen bei öffentlichen Repos." />
                  </label>
                  <input
                    id="repo-token"
                    type="password"
                    value={repoForm.token}
                    onChange={(e) => setRepoForm({ ...repoForm, token: e.target.value })}
                    placeholder="ghp_..."
                    disabled={isReadonly}
                    autoComplete="off"
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="repo-branch">Branch:</label>
                  <input
                    id="repo-branch"
                    type="text"
                    value={repoForm.branch}
                    onChange={(e) => setRepoForm({ ...repoForm, branch: e.target.value })}
                    placeholder="main"
                    disabled={isReadonly}
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="repo-pipelines-subdir">
                    Pipelines-Unterordner (optional):
                    <InfoIcon content="Wenn Ihre Pipelines im Repo in einem Unterordner liegen (z. B. pipelines/), hier den Ordnernamen eintragen. Leer = Repo-Root." />
                  </label>
                  <input
                    id="repo-pipelines-subdir"
                    type="text"
                    value={repoForm.pipelines_subdir}
                    onChange={(e) => setRepoForm({ ...repoForm, pipelines_subdir: e.target.value })}
                    placeholder="z. B. pipelines"
                    disabled={isReadonly}
                  />
                </div>
                {!isReadonly && (
                  <div className="form-actions">
                    <button
                      onClick={handleSaveRepoConfig}
                      disabled={saveRepoConfigMutation.isPending}
                      className="save-button"
                    >
                      {saveRepoConfigMutation.isPending ? 'Speichert...' : 'Speichern'}
                    </button>
                    <Tooltip content="Testet die Verbindung (git ls-remote)">
                      <button
                        onClick={handleTestRepoConfig}
                        disabled={testRepoConfigMutation.isPending}
                        className="test-button"
                      >
                        {testRepoConfigMutation.isPending ? 'Testet...' : 'Konfiguration testen'}
                      </button>
                    </Tooltip>
                    {repoConfig?.configured && (
                      <button
                        onClick={handleDeleteRepoConfig}
                        disabled={deleteRepoConfigMutation.isPending}
                        className="delete-button"
                      >
                        {deleteRepoConfigMutation.isPending ? 'Löscht...' : 'Löschen'}
                      </button>
                    )}
                  </div>
                )}
                <div className="github-info">
                  <h4>Hilfe:</h4>
                  <ul>
                    <li>Öffentliche Repos: Nur URL und optional Branch eintragen.</li>
                    <li>Private Repos: Personal Access Token (GitHub: Settings → Developer settings → Personal access tokens) mit Scope <code>repo</code> erstellen.</li>
                    <li>Alternativ: GIT_REPO_URL und ggf. GIT_SYNC_TOKEN in .env bzw. ConfigMap/Secret setzen.</li>
                  </ul>
                </div>
                {!isReadonly && (
                  <div className="clear-pipelines-section">
                    <h4>Neues Repo verbinden</h4>
                    <p>
                      Wenn bereits Pipelines (z. B. Beispiele) im Verzeichnis liegen, muss es zuerst geleert werden, damit ein neues Repository geklont werden kann.
                    </p>
                    <button
                      type="button"
                      onClick={handleClearPipelines}
                      disabled={clearPipelinesMutation.isPending}
                      className="clear-pipelines-button"
                    >
                      {clearPipelinesMutation.isPending ? 'Leert...' : 'Pipelines-Verzeichnis leeren'}
                    </button>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
