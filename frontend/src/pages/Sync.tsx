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

interface SyncProps {
  /** Gesperrt aus den Einstellungen (Schloss): keine Änderungen bis Entsperren */
  editLocked?: boolean
}

export default function Sync({ editLocked = false }: SyncProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { isReadonly } = useAuth()
  const fieldDisabled = isReadonly || editLocked
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
        showSuccess(t('sync.testMessagePrefixOk') + data.message)
      } else {
        showError(t('sync.testMessagePrefixFail') + data.message)
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
      <h2>{t('dashboard.gitSync')}</h2>

      <div className="tab-strip sync-page-tabs">
        <button
          type="button"
          className={`tab-strip__tab${activeTab === 'status' ? ' active' : ''}`}
          onClick={() => setActiveTab('status')}
        >
          {t('sync.status')}
        </button>
        <button
          type="button"
          className={`tab-strip__tab${activeTab === 'settings' ? ' active' : ''}`}
          onClick={() => setActiveTab('settings')}
        >
          {t('sync.settings')}
        </button>
        <button
          type="button"
          className={`tab-strip__tab${activeTab === 'logs' ? ' active' : ''}`}
          onClick={() => setActiveTab('logs')}
        >
          {t('sync.logs')}
        </button>
        <button
          type="button"
          className={`tab-strip__tab${activeTab === 'repository' ? ' active' : ''}`}
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
              placeholder={syncStatus?.branch || t('sync.branchPlaceholderDefault')}
              disabled={fieldDisabled}
            />
          </div>
          {!isReadonly && (
            <button
              type="button"
              onClick={handleSync}
              disabled={syncMutation.isPending || fieldDisabled}
              className="btn btn-primary sync-form-submit"
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
                    disabled={fieldDisabled}
                  />
                  {t('sync.autoSyncEnable')}
                  <InfoIcon content={t('sync.saveSettingsNote')} />
                </label>
              </div>
              <div className="form-group">
                <label htmlFor="sync-interval">
                  {t('sync.autoSyncIntervalLabel')}
                  <InfoIcon content={t('sync.autoSyncIntervalHint')} />
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
                  disabled={fieldDisabled || !settingsForm.auto_sync_enabled}
                />
              </div>
              {!isReadonly && (
                <div className="form-actions">
                  <button
                    type="button"
                    onClick={handleSaveSettings}
                    disabled={updateSettingsMutation.isPending || fieldDisabled}
                    className="btn btn-primary"
                  >
                    {updateSettingsMutation.isPending ? t('common.saving') : t('sync.saveSettings')}
                  </button>
                </div>
              )}
              <p className="settings-note">
                {t('sync.saveSettingsNote')} {t('sync.settingsEnvPersistNote')}
              </p>
            </div>
          )}
        </div>
      )}

      {activeTab === 'logs' && (
        <div className="sync-logs-card">
          <h3>{t('sync.syncLogsTitle')}</h3>
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
                      {log.status || log.event || t('sync.logStatusUnknown')}
                    </span>
                  </div>
                  {log.message && (
                    <div className="log-message">{log.message}</div>
                  )}
                  {log.error && (
                    <div className="log-error">{t('sync.logErrorLine', { detail: log.error })}</div>
                  )}
                  {log.branch && (
                    <div className="log-details">{t('sync.logBranchLine', { branch: log.branch })}</div>
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
            <p className="no-logs">{t('sync.noSyncLogs')}</p>
          )}
        </div>
      )}

      {activeTab === 'repository' && (
        <div className="sync-repo-card settings-section card">
          <h3 className="section-title">{t('sync.connectRepository')}</h3>
          <p className="repo-config-intro setting-hint">
            {t('sync.repoIntroPlain')}
          </p>
          {repoConfigLoading ? (
            <div className="setting-hint">{t('sync.loadingRepoConfig')}</div>
          ) : (
            <>
              {repoConfig?.configured && (
                <div className="repo-configured-badge">
                  {t('sync.repoConfiguredBadge', { url: repoConfig.repo_url })}
                </div>
              )}
              <div className="sync-repo-form">
                <div className="setting-item">
                  <label htmlFor="repo-url" className="setting-label">
                    {t('sync.repoUrlLabel')}
                    <InfoIcon content={t('sync.repoUrlHint')} />
                  </label>
                  <input
                    id="repo-url"
                    type="text"
                    className="form-input"
                    value={repoForm.repo_url}
                    onChange={(e) => setRepoForm({ ...repoForm, repo_url: e.target.value })}
                    placeholder={t('sync.repoUrlPlaceholder')}
                    disabled={fieldDisabled}
                  />
                </div>
                {!isSshUrl(repoForm.repo_url) && (
                  <div className="setting-item">
                    <label htmlFor="repo-token" className="setting-label">
                      {t('sync.repoTokenLabel')}
                      <InfoIcon content={t('sync.repoTokenHint')} />
                    </label>
                    <input
                      id="repo-token"
                      type="password"
                      className="form-input"
                      value={repoForm.token}
                      onChange={(e) => setRepoForm({ ...repoForm, token: e.target.value })}
                      placeholder={t('sync.tokenPlaceholder')}
                      disabled={fieldDisabled}
                      autoComplete="off"
                    />
                  </div>
                )}
                {isSshUrl(repoForm.repo_url) && (
                  <>
                    {!isReadonly && (
                      <div className="deploy-key-generate-section">
                        <h4 className="deploy-key-generate-heading">{t('sync.deployKeySectionTitle')}</h4>
                        <p className="deploy-key-generate-hint setting-hint">
                          {t('sync.deployKeySectionHint')}
                        </p>
                        <div className="sync-repo-form-actions">
                          <button
                            type="button"
                            onClick={handleGenerateDeployKey}
                            disabled={generateDeployKeyMutation.isPending || fieldDisabled}
                            className="btn btn-primary"
                          >
                            {generateDeployKeyMutation.isPending ? t('sync.deployKeyGenerating') : repoConfig?.configured ? t('sync.deployKeyRegenerate') : t('sync.deployKeyGeneratedSave')}
                          </button>
                        </div>
                        {generatedPublicKey && (
                          <div className="setting-item generated-public-key-box">
                            <label className="setting-label">{t('sync.publicKeyLabel')}</label>
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
                              {t('sync.copyToClipboard')}
                            </button>
                            <p className="generated-key-hint setting-hint">
                              {t('sync.deployKeyGithubHint')}
                            </p>
                          </div>
                        )}
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm manual-key-toggle"
                          onClick={() => setShowManualDeployKey((v) => !v)}
                          disabled={fieldDisabled}
                        >
                          {showManualDeployKey ? t('sync.manualKeyHide') : t('sync.manualKeyShow')}
                        </button>
                      </div>
                    )}
                    {showManualDeployKey && (
                      <div className="setting-item manual-deploy-key-section">
                        <label htmlFor="repo-deploy-key" className="setting-label">
                          {t('sync.sshPrivateKeyLabel')}
                          <InfoIcon content={t('sync.manualPrivateKeyHint')} />
                        </label>
                        <textarea
                          id="repo-deploy-key"
                          value={repoForm.deploy_key}
                          onChange={(e) => setRepoForm({ ...repoForm, deploy_key: e.target.value })}
                          placeholder={t('sync.sshKeyPlaceholder')}
                          disabled={fieldDisabled}
                          rows={4}
                          className="form-input repo-deploy-key-input"
                          autoComplete="off"
                        />
                      </div>
                    )}
                  </>
                )}
                <div className="setting-item">
                  <label htmlFor="repo-branch" className="setting-label">{t('sync.branchLabel')}</label>
                  <input
                    id="repo-branch"
                    type="text"
                    className="form-input"
                    value={repoForm.branch}
                    onChange={(e) => setRepoForm({ ...repoForm, branch: e.target.value })}
                    placeholder={t('sync.branchPlaceholderDefault')}
                    disabled={fieldDisabled}
                  />
                </div>
                <div className="setting-item">
                  <label htmlFor="repo-pipelines-subdir" className="setting-label">
                    {t('sync.pipelinesSubdir')}
                    <InfoIcon content={t('sync.pipelinesSubdirTooltip')} />
                  </label>
                  <input
                    id="repo-pipelines-subdir"
                    type="text"
                    className="form-input"
                    value={repoForm.pipelines_subdir}
                    onChange={(e) => setRepoForm({ ...repoForm, pipelines_subdir: e.target.value })}
                    placeholder={t('sync.pipelinesSubdirPlaceholder')}
                    disabled={fieldDisabled}
                  />
                </div>
                {!isReadonly && (
                  <div className="sync-repo-form-actions">
                    <button
                      onClick={handleSaveRepoConfig}
                      disabled={saveRepoConfigMutation.isPending || fieldDisabled}
                      className="btn btn-primary"
                    >
                      {saveRepoConfigMutation.isPending ? t('common.saving') : t('sync.save')}
                    </button>
                    <Tooltip content={t('sync.testConnectionTooltip')}>
                      <button
                        onClick={handleTestRepoConfig}
                        disabled={testRepoConfigMutation.isPending || fieldDisabled}
                        className="btn btn-outlined"
                      >
                        {testRepoConfigMutation.isPending ? t('common.saving') : t('sync.testConfig')}
                      </button>
                    </Tooltip>
                    {repoConfig?.configured && (
                      <button
                        type="button"
                        onClick={handleDeleteRepoConfig}
                        disabled={deleteRepoConfigMutation.isPending || fieldDisabled}
                        className="btn btn-error btn-sm"
                      >
                        {deleteRepoConfigMutation.isPending ? t('sync.deleting') : t('sync.delete')}
                      </button>
                    )}
                  </div>
                )}
                <div className="sync-repo-help">
                  <h4 className="setting-label">{t('sync.helpShortTitle')}</h4>
                  <ul>
                    <li>{t('sync.helpBulletHttpsSsh')}</li>
                    <li>{t('sync.stepBranch')}</li>
                  </ul>
                </div>
                {!isReadonly && (
                  <div className="clear-pipelines-section">
                    <h4 className="setting-label">{t('sync.connectNewRepoTitle')}</h4>
                    <p className="setting-hint">
                      {t('sync.connectNewRepoHint')}
                    </p>
                    <button
                      type="button"
                      onClick={handleClearPipelines}
                      disabled={clearPipelinesMutation.isPending || fieldDisabled}
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
