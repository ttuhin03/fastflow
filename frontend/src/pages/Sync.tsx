import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRefetchInterval } from '../hooks/useRefetchInterval'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import { getFormatLocale } from '../utils/locale'
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
  auth_mode?: 'pat' | 'deploy_key'
}

function isSshUrl(url: string): boolean {
  const u = (url || '').trim()
  return u.startsWith('git@') || u.startsWith('ssh://')
}

export default function Sync() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const formatLocale = getFormatLocale()
  const [syncBranch, setSyncBranch] = useState('')
  const [activeTab, setActiveTab] = useState<'status' | 'settings' | 'logs' | 'repository'>('status')
  const [settingsForm, setSettingsForm] = useState<SyncSettings>({
    auto_sync_enabled: false,
    auto_sync_interval: null,
  })

  const [repoForm, setRepoForm] = useState({
    repo_url: '',
    token: '',
    deploy_key: '',
    branch: 'main',
    pipelines_subdir: '',
  })
  const [generatedPublicKey, setGeneratedPublicKey] = useState<string | null>(null)
  const [showManualDeployKey, setShowManualDeployKey] = useState(false)

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
        deploy_key: '',
        branch: repoConfig.branch || 'main',
        pipelines_subdir: repoConfig.pipelines_subdir ?? '',
      })
    }
  }, [repoConfig, activeTab])

  useEffect(() => {
    if (!isSshUrl(repoForm.repo_url)) {
      setGeneratedPublicKey(null)
      setShowManualDeployKey(false)
    }
  }, [repoForm.repo_url])

  const syncMutation = useMutation({
    mutationFn: async (branch?: string) => {
      const response = await apiClient.post('/sync', branch ? { branch } : {})
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
      showSuccess(t('sync.syncSuccess'))
    },
    onError: (error: any) => {
      showError(t('sync.syncError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const updateSettingsMutation = useMutation({
    mutationFn: async (newSettings: SyncSettings) => {
      const response = await apiClient.put('/sync/settings', newSettings)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sync-settings'] })
      showSuccess(t('sync.settingsUpdated'))
    },
    onError: (error: any) => {
      showError(t('sync.updateError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const saveRepoConfigMutation = useMutation({
    mutationFn: async (data: {
      repo_url: string
      token?: string
      deploy_key?: string
      branch?: string
      pipelines_subdir?: string
    }) => {
      const response = await apiClient.post('/sync/repo-config', data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['repo-config'] })
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      showSuccess(t('sync.repoSaved'))
      setRepoForm((f) => ({ ...f, token: '', deploy_key: '' }))
      queryClient.invalidateQueries({ queryKey: ['pipelines'] })
    },
    onError: (error: any) => {
      showError(t('sync.repoSaveError', { detail: error.response?.data?.detail || error.message }))
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
      showError(t('sync.testError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const generateDeployKeyMutation = useMutation({
    mutationFn: async (data: { repo_url: string; branch?: string; pipelines_subdir?: string }) => {
      const response = await apiClient.post('/sync/repo-config/generate-deploy-key', data)
      return response.data as { success: boolean; public_key: string }
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['repo-config'] })
      queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      if (data.public_key) {
        setGeneratedPublicKey(data.public_key)
        showSuccess(t('sync.deployKeyGenerated'))
      }
    },
    onError: (error: any) => {
      showError(t('sync.deployKeyError', { detail: error.response?.data?.detail || error.message }))
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
      showSuccess(t('sync.repoDeleted'))
      setRepoForm({ repo_url: '', token: '', deploy_key: '', branch: 'main', pipelines_subdir: '' })
      setGeneratedPublicKey(null)
    },
    onError: (error: any) => {
      showError(t('sync.deleteError', { detail: error.response?.data?.detail || error.message }))
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
      showSuccess(t('sync.clearSuccess'))
    },
    onError: (error: any) => {
      showError(t('sync.clearError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const handleSync = async () => {
    if (syncMutation.isPending) return
    const confirmed = await showConfirm(t('dashboard.syncConfirm'))
    if (confirmed) {
      syncMutation.mutate(syncBranch || undefined)
    }
  }

  const handleSaveSettings = () => {
    if (settingsForm.auto_sync_interval !== null && settingsForm.auto_sync_interval < 60) {
      showError(t('sync.minIntervalError'))
      return
    }
    updateSettingsMutation.mutate(settingsForm)
  }

  const handleSaveRepoConfig = () => {
    const url = repoForm.repo_url.trim()
    if (!url) {
      showError(t('sync.enterRepoUrl'))
      return
    }
    if (
      !url.startsWith('https://') &&
      !url.startsWith('http://') &&
      !url.startsWith('git@') &&
      !url.startsWith('ssh://')
    ) {
      showError(t('sync.urlMustStart'))
      return
    }
    if (isSshUrl(url)) {
      saveRepoConfigMutation.mutate({
        repo_url: url,
        deploy_key: repoForm.deploy_key.trim() || undefined,
        branch: repoForm.branch.trim() || undefined,
        pipelines_subdir: repoForm.pipelines_subdir.trim() || undefined,
      })
    } else {
      saveRepoConfigMutation.mutate({
        repo_url: url,
        token: repoForm.token.trim() || undefined,
        branch: repoForm.branch.trim() || undefined,
        pipelines_subdir: repoForm.pipelines_subdir.trim() || undefined,
      })
    }
  }

  const handleTestRepoConfig = () => {
    testRepoConfigMutation.mutate()
  }

  const handleGenerateDeployKey = () => {
    const url = repoForm.repo_url.trim()
    if (!url) {
      showError(t('sync.enterSshUrl'))
      return
    }
    if (!isSshUrl(url)) {
      showError(t('sync.deployKeyOnlySsh'))
      return
    }
    generateDeployKeyMutation.mutate({
      repo_url: url,
      branch: repoForm.branch.trim() || undefined,
      pipelines_subdir: repoForm.pipelines_subdir.trim() || undefined,
    })
  }

  const handleCopyPublicKey = () => {
    if (generatedPublicKey && navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(generatedPublicKey)
      showSuccess(t('sync.publicKeyCopied'))
    }
  }

  const handleClearPipelines = async () => {
    const confirmed = await showConfirm(t('sync.clearConfirm'))
    if (confirmed) {
      clearPipelinesMutation.mutate()
    }
  }

  const handleDeleteRepoConfig = async () => {
    const confirmed = await showConfirm(t('sync.repoDeleteConfirm'))
    if (confirmed) {
      deleteRepoConfigMutation.mutate()
    }
  }

  if (isLoading) {
    return <div>{t('common.loading')}</div>
  }

  return (
    <div className="sync">
      <h2>Git Sync</h2>

      <div className="sync-tabs">
        <button
          className={activeTab === 'status' ? 'active' : ''}
          onClick={() => setActiveTab('status')}
        >
          {t('sync.status')}
        </button>
        <button
          className={activeTab === 'settings' ? 'active' : ''}
          onClick={() => setActiveTab('settings')}
        >
          {t('sync.settings')}
        </button>
        <button
          className={activeTab === 'logs' ? 'active' : ''}
          onClick={() => setActiveTab('logs')}
        >
          {t('sync.logs')}
        </button>
        <button
          className={activeTab === 'repository' ? 'active' : ''}
          onClick={() => setActiveTab('repository')}
        >
          {t('sync.repository')}
        </button>
      </div>

      {activeTab === 'status' && (
        <>
      <div className="sync-status-card">
        <h3>{t('sync.status')}</h3>
        <div className="status-info">
          <div className="status-row">
            <span className="status-label">
              {t('sync.branchLabel')}
              <InfoIcon content={t('sync.branchInfo')} />
            </span>
            <span className="status-value">{syncStatus?.branch || '-'}</span>
          </div>
          {syncStatus?.remote_url && (
            <div className="status-row">
              <span className="status-label">
                {t('sync.remoteUrl')}
                <InfoIcon content={t('sync.remoteUrlInfo')} />
              </span>
              <span className="status-value">{syncStatus.remote_url}</span>
            </div>
          )}
          {formatLastCommit(syncStatus?.last_commit) && (
            <div className="status-row">
              <span className="status-label">
                {t('sync.lastCommit')}
                <InfoIcon content={t('sync.lastCommitInfo')} />
              </span>
              <span className="status-value">{formatLastCommit(syncStatus?.last_commit)}</span>
            </div>
          )}
          {syncStatus?.last_sync && (
            <div className="status-row">
              <span className="status-label">{t('sync.lastSync')}:</span>
              <span className="status-value">
                {new Date(syncStatus.last_sync).toLocaleString(formatLocale)}
              </span>
            </div>
          )}
          {syncStatus?.status && (
            <div className="status-row">
              <span className="status-label">{t('sync.status')}:</span>
              <span className={`status-badge ${syncStatus.status.toLowerCase()}`}>
                {syncStatus.status}
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="sync-actions-card">
        <h3>{t('sync.runSync')}</h3>
        <div className="sync-form">
          <div className="form-group">
            <label htmlFor="sync-branch">{t('sync.branchOptional')}</label>
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
              {syncMutation.isPending ? t('dashboard.syncRunning') : t('sync.runSync')}
            </button>
          )}
        </div>
      </div>

      {syncStatus?.pipelines_cached && syncStatus.pipelines_cached.length > 0 && (
        <div className="cache-status-card">
          <h3>
            {t('sync.cachedPipelines')}
            <InfoIcon content={t('sync.cachedPipelinesTooltip')} />
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
          <h3>{t('sync.syncSettings')}</h3>
          {settingsLoading ? (
            <div>{t('sync.loadingSettings')}</div>
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
                  {t('sync.autoSyncEnable')}
                  <InfoIcon content={t('sync.saveSettingsNote')} />
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
                    {updateSettingsMutation.isPending ? t('common.saving') : t('sync.saveSettings')}
                  </button>
                </div>
              )}
              <p className="settings-note">
                {t('sync.saveSettingsNote')}
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
                        ? new Date(log.timestamp).toLocaleString(formatLocale)
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
                      {t('sync.cachedPipelinesLabel')} {log.pipelines_cached.join(', ')}
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
        <div className="sync-repo-card settings-section card">
          <h3 className="section-title">Repository verbinden</h3>
          <p className="repo-config-intro setting-hint">
            <strong>HTTPS:</strong> URL + optional Personal Access Token. — <strong>SSH:</strong> URL + Deploy-Key (empfohlen: vom Server erzeugen).
          </p>
          {repoConfigLoading ? (
            <div className="setting-hint">Lade Konfiguration...</div>
          ) : (
            <>
              {repoConfig?.configured && (
                <div className="repo-configured-badge">
                  Repository ist konfiguriert: {repoConfig.repo_url}
                </div>
              )}
              <div className="sync-repo-form">
                <div className="setting-item">
                  <label htmlFor="repo-url" className="setting-label">
                    Repository-URL (HTTPS oder SSH):
                    <InfoIcon content="HTTPS: https://github.com/org/repo.git — SSH: git@github.com:org/repo.git" />
                  </label>
                  <input
                    id="repo-url"
                    type="text"
                    className="form-input"
                    value={repoForm.repo_url}
                    onChange={(e) => setRepoForm({ ...repoForm, repo_url: e.target.value })}
                    placeholder="https://github.com/org/repo.git oder git@github.com:org/repo.git"
                    disabled={isReadonly}
                  />
                </div>
                {!isSshUrl(repoForm.repo_url) && (
                  <div className="setting-item">
                    <label htmlFor="repo-token" className="setting-label">
                      Token (optional, für private Repos):
                      <InfoIcon content="Personal Access Token mit repo-Berechtigung. Leer lassen bei öffentlichen Repos." />
                    </label>
                    <input
                      id="repo-token"
                      type="password"
                      className="form-input"
                      value={repoForm.token}
                      onChange={(e) => setRepoForm({ ...repoForm, token: e.target.value })}
                      placeholder="ghp_..."
                      disabled={isReadonly}
                      autoComplete="off"
                    />
                  </div>
                )}
                {isSshUrl(repoForm.repo_url) && (
                  <>
                    {!isReadonly && (
                      <div className="deploy-key-generate-section">
                        <h4 className="deploy-key-generate-heading">Deploy-Key (empfohlen)</h4>
                        <p className="deploy-key-generate-hint setting-hint">
                          Server erzeugt ein Key-Paar. Nur den öffentlichen Key bei GitHub (Settings → Deploy keys) eintragen – kein privater Key nötig.
                        </p>
                        <div className="sync-repo-form-actions">
                          <button
                            type="button"
                            onClick={handleGenerateDeployKey}
                            disabled={generateDeployKeyMutation.isPending}
                            className="btn btn-primary"
                          >
                            {generateDeployKeyMutation.isPending ? 'Erzeuge...' : repoConfig?.configured ? 'Deploy-Key neu erzeugen' : 'Deploy-Key erzeugen und speichern'}
                          </button>
                        </div>
                        {generatedPublicKey && (
                          <div className="setting-item generated-public-key-box">
                            <label className="setting-label">Öffentlicher Key (bei GitHub eintragen):</label>
                            <textarea
                              readOnly
                              value={generatedPublicKey}
                              rows={3}
                              className="form-input repo-deploy-key-display"
                            />
                            <button
                              type="button"
                              onClick={handleCopyPublicKey}
                              className="btn btn-outlined"
                            >
                              In Zwischenablage kopieren
                            </button>
                            <p className="generated-key-hint setting-hint">
                              In GitHub: Settings → Deploy keys → Add deploy key. Danach „Konfiguration testen“ oder Sync ausführen.
                            </p>
                          </div>
                        )}
                        <button
                          type="button"
                          className="manual-key-toggle"
                          onClick={() => setShowManualDeployKey((v) => !v)}
                        >
                          {showManualDeployKey ? '− Manuellen Key ausblenden' : '+ Eigenen privaten Key manuell eintragen'}
                        </button>
                      </div>
                    )}
                    {showManualDeployKey && (
                      <div className="setting-item manual-deploy-key-section">
                        <label htmlFor="repo-deploy-key" className="setting-label">
                          Privater SSH-Key (z. B. mit ssh-keygen erzeugt):
                          <InfoIcon content="Inhalt des privaten Keys einfügen, falls Sie keinen Key vom Server verwenden." />
                        </label>
                        <textarea
                          id="repo-deploy-key"
                          value={repoForm.deploy_key}
                          onChange={(e) => setRepoForm({ ...repoForm, deploy_key: e.target.value })}
                          placeholder="-----BEGIN OPENSSH PRIVATE KEY-----..."
                          disabled={isReadonly}
                          rows={4}
                          className="form-input repo-deploy-key-input"
                          autoComplete="off"
                        />
                      </div>
                    )}
                  </>
                )}
                <div className="setting-item">
                  <label htmlFor="repo-branch" className="setting-label">Branch:</label>
                  <input
                    id="repo-branch"
                    type="text"
                    className="form-input"
                    value={repoForm.branch}
                    onChange={(e) => setRepoForm({ ...repoForm, branch: e.target.value })}
                    placeholder="main"
                    disabled={isReadonly}
                  />
                </div>
                <div className="setting-item">
                  <label htmlFor="repo-pipelines-subdir" className="setting-label">
                    Pipelines-Unterordner (optional):
                    <InfoIcon content="Wenn Ihre Pipelines im Repo in einem Unterordner liegen (z. B. pipelines/), hier den Ordnernamen eintragen. Leer = Repo-Root." />
                  </label>
                  <input
                    id="repo-pipelines-subdir"
                    type="text"
                    className="form-input"
                    value={repoForm.pipelines_subdir}
                    onChange={(e) => setRepoForm({ ...repoForm, pipelines_subdir: e.target.value })}
                    placeholder="z. B. pipelines"
                    disabled={isReadonly}
                  />
                </div>
                {!isReadonly && (
                  <div className="sync-repo-form-actions">
                    <button
                      onClick={handleSaveRepoConfig}
                      disabled={saveRepoConfigMutation.isPending}
                      className="btn btn-primary"
                    >
                      {saveRepoConfigMutation.isPending ? t('common.saving') : t('sync.save')}
                    </button>
                    <Tooltip content="Testet die Verbindung (git ls-remote)">
                      <button
                        onClick={handleTestRepoConfig}
                        disabled={testRepoConfigMutation.isPending}
                        className="btn btn-outlined"
                      >
                        {testRepoConfigMutation.isPending ? t('common.saving') : t('sync.testConfig')}
                      </button>
                    </Tooltip>
                    {repoConfig?.configured && (
                      <button
                        onClick={handleDeleteRepoConfig}
                        disabled={deleteRepoConfigMutation.isPending}
                        className="btn btn-outlined delete-button"
                      >
                        {deleteRepoConfigMutation.isPending ? 'Löscht...' : 'Löschen'}
                      </button>
                    )}
                  </div>
                )}
                <div className="sync-repo-help">
                  <h4 className="setting-label">Kurz</h4>
                  <ul>
                    <li><strong>HTTPS:</strong> URL + optional PAT (private Repos). <strong>SSH:</strong> URL + Deploy-Key (am einfachsten: „Deploy-Key erzeugen“, öffentlichen Key bei GitHub eintragen).</li>
                    <li>Branch und optional Pipelines-Unterordner eintragen, dann Speichern und „Konfiguration testen“.</li>
                  </ul>
                </div>
                {!isReadonly && (
                  <div className="clear-pipelines-section">
                    <h4 className="setting-label">Neues Repo verbinden</h4>
                    <p className="setting-hint">
                      Wenn bereits Pipelines (z. B. Beispiele) im Verzeichnis liegen, muss es zuerst geleert werden, damit ein neues Repository geklont werden kann.
                    </p>
                    <button
                      type="button"
                      onClick={handleClearPipelines}
                      disabled={clearPipelinesMutation.isPending}
                      className="btn btn-outlined"
                    >
                      {clearPipelinesMutation.isPending ? t('sync.clearing') : t('sync.clearPipelinesDir')}
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
