import { useState, useEffect, useRef, useLayoutEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import { UI_DISPLAY_QUERY_KEY } from '../contexts/UiPreferencesContext'
import apiClient from '../api/client'
import { MdSave, MdRefresh, MdInfo, MdWarning, MdEmail, MdGroup, MdLink, MdCheck, MdPerson, MdSync, MdStorage, MdPlayCircle, MdNotifications, MdPeople, MdKey, MdContentCopy, MdDelete, MdLock, MdLockOpen } from 'react-icons/md'
import { showError, showSuccess } from '../utils/toast'
import { captureException } from '../utils/posthog'
import { getApiOrigin } from '../config'
import Tooltip from '../components/Tooltip'
import InfoIcon from '../components/InfoIcon'
import StorageStats from '../components/StorageStats'
import SystemMetrics from '../components/SystemMetrics'
import Sync from './Sync'
import Users from './Users'
import './Settings.css'

/**
 * Account-Linking triggert eine volle Browser-Navigation; der Browser sendet keinen Authorization-Header.
 * Das Backend akzeptiert JWT per Query-Parameter (wie bei SSE), siehe get_current_user.
 */
function accountOAuthLinkUrl(path: '/link/github' | '/link/google' | '/link/microsoft' | '/link/custom'): string {
  const base = `${getApiOrigin()}/api/auth${path}`
  if (typeof window === 'undefined') return base
  const token = sessionStorage.getItem('auth_token')
  if (!token) return base
  return `${base}?token=${encodeURIComponent(token)}`
}

export type SettingsSection = 'account' | 'system' | 'pipeline' | 'notifications' | 'git-sync' | 'nutzer'

const SENSITIVE_SETTINGS_SECTIONS: SettingsSection[] = ['system', 'pipeline', 'notifications', 'git-sync', 'nutzer']

interface NotificationApiKeyItem {
  id: number
  label: string | null
  created_at: string
}

interface AuthProviders {
  github?: boolean
  google?: boolean
  microsoft?: boolean
  custom?: boolean
  login_branding_logo_url?: string
  custom_oauth_icon_url?: string
  custom_display_name?: string
}

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
  notification_api_enabled?: boolean
  notification_api_rate_limit_per_minute?: number
  notification_api_keys?: NotificationApiKeyItem[]
}

export default function Settings() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { isReadonly, isAdmin } = useAuth()
  const [localSettings, setLocalSettings] = useState<Settings | null>(null)
  const [showCleanupInfo, setShowCleanupInfo] = useState(false)
  const [localDependencyAuditCron, setLocalDependencyAuditCron] = useState<string | null>(null)
  const [generatedKey, setGeneratedKey] = useState<{ key: string; id: number; label?: string | null } | null>(null)
  const [newKeyLabel, setNewKeyLabel] = useState('')
  const [unlinkingProvider, setUnlinkingProvider] = useState<'github' | 'google' | 'microsoft' | 'custom' | null>(null)
  /** Geschützte Tabs: Eingaben erst nach Klick auf Schloss (verhindert versehentliche Änderungen). */
  const [sensitiveSettingsLocked, setSensitiveSettingsLocked] = useState(true)

  const [searchParams, setSearchParams] = useSearchParams()
  const section = (searchParams.get('section') as SettingsSection) || 'account'
  const setSection = (s: SettingsSection) => {
    const np = new URLSearchParams(searchParams)
    np.set('section', s)
    setSearchParams(np, { replace: true })
  }

  const sectionItems: { id: SettingsSection; labelKey: string; icon: React.ReactNode }[] = [
    { id: 'account', labelKey: 'settingsSections.account', icon: <MdPerson /> },
    { id: 'system', labelKey: 'settingsSections.system', icon: <MdStorage /> },
    { id: 'pipeline', labelKey: 'settingsSections.pipeline', icon: <MdPlayCircle /> },
    { id: 'notifications', labelKey: 'settingsSections.notifications', icon: <MdNotifications /> },
    { id: 'git-sync', labelKey: 'settingsSections.gitSync', icon: <MdSync /> },
    ...(isAdmin ? [{ id: 'nutzer' as const, labelKey: 'settingsSections.nutzer', icon: <MdPeople /> }] : []),
  ]

  const trayRef = useRef<HTMLDivElement>(null)
  const [indicator, setIndicator] = useState({ left: 0, width: 0 })

  useLayoutEffect(() => {
    const tray = trayRef.current
    if (!tray) return
    const pill = tray.querySelector<HTMLElement>(`[data-section="${section}"]`)
    if (!pill) return
    const tr = tray.getBoundingClientRect()
    const pr = pill.getBoundingClientRect()
    setIndicator({ left: pr.left - tr.left, width: pr.width })
  }, [section, sectionItems.length])

  useEffect(() => {
    setSensitiveSettingsLocked(true)
  }, [section])

  const { data: settings, isLoading } = useQuery<Settings>({
    queryKey: ['settings'],
    queryFn: async () => {
      const response = await apiClient.get('/settings')
      return response.data
    },
  })

  const { data: health } = useQuery<{ status?: string; environment?: string; pipeline_executor?: 'docker' | 'kubernetes' }>({
    queryKey: ['health'],
    queryFn: async () => { const r = await apiClient.get('/health'); return r.data },
    staleTime: 60 * 1000,
  })

  const { data: me, refetch: refetchMe } = useQuery({
    queryKey: ['auth/me'],
    queryFn: async () => {
      const response = await apiClient.get('/auth/me')
      return response.data as {
        has_github?: boolean
        has_google?: boolean
        has_microsoft?: boolean
        has_custom?: boolean
        email?: string
        avatar_url?: string
      }
    },
  })

  const { data: authProviders = {}, isLoading: authProvidersLoading } = useQuery<AuthProviders>({
    queryKey: ['auth/providers'],
    queryFn: async () => {
      try {
        const r = await apiClient.get('/auth/providers')
        return r.data
      } catch {
        return {}
      }
    },
    staleTime: 60_000,
    enabled: section === 'account',
  })

  useEffect(() => {
    const linked = searchParams.get('linked')
    const linkError = searchParams.get('link_error')
    const errorProvider = searchParams.get('provider')
    if (linked === 'google' || linked === 'github' || linked === 'microsoft' || linked === 'custom') {
      const msg =
        linked === 'google'
          ? t('settings.linkedGoogle')
          : linked === 'github'
            ? t('settings.linkedGithub')
            : linked === 'microsoft'
              ? t('settings.linkedMicrosoft')
              : t('settings.linkedCustom')
      showSuccess(msg)
      const np = new URLSearchParams(searchParams)
      np.delete('linked')
      setSearchParams(Object.fromEntries(np.entries()), { replace: true })
      refetchMe()
    }
    if (linkError === 'already_linked') {
      const providerName =
        errorProvider === 'google'
          ? 'Google'
          : errorProvider === 'github'
            ? 'GitHub'
            : errorProvider === 'microsoft'
              ? 'Microsoft'
              : errorProvider === 'custom'
                ? (authProviders.custom_display_name || '').trim() || t('auth.customProviderFallback')
                : t('settings.providerUnknown')
      showError(t('settings.linkErrorAlreadyLinked', { provider: providerName }))
      const np = new URLSearchParams(searchParams)
      np.delete('link_error')
      np.delete('provider')
      setSearchParams(Object.fromEntries(np.entries()), { replace: true })
    }
  }, [searchParams, setSearchParams, refetchMe, authProviders.custom_display_name, t])

  const [localBrandingLogoUrl, setLocalBrandingLogoUrl] = useState<string | null>(null)

  const { data: systemSettings } = useQuery<{
    is_setup_completed: boolean
    enable_telemetry: boolean
    enable_error_reporting: boolean
    dependency_audit_enabled: boolean
    dependency_audit_cron: string
    login_branding_logo_url?: string | null
    ui_show_attribution: boolean
    ui_show_version: boolean
    show_unconfigured_oauth_on_login: boolean
    ui_login_background: string
  }>({
    queryKey: ['settings-system'],
    queryFn: async () => {
      const response = await apiClient.get('/settings/system')
      return response.data
    },
    retry: false,
    staleTime: 2 * 60 * 1000,
    enabled: isAdmin,
  })

  const { data: backupStatus } = useQuery<{ failures: unknown[]; last_backup_at: string | null }>({
    queryKey: ['settings', 'backup-failures'],
    queryFn: async () => {
      const r = await apiClient.get('/settings/backup-failures')
      return r.data
    },
    staleTime: 90 * 1000,
  })

  const updateSystemSettingsMutation = useMutation({
    mutationFn: async (patch: {
      enable_telemetry?: boolean
      enable_error_reporting?: boolean
      dependency_audit_enabled?: boolean
      dependency_audit_cron?: string
      login_branding_logo_url?: string
      ui_show_attribution?: boolean
      ui_show_version?: boolean
      show_unconfigured_oauth_on_login?: boolean
      ui_login_background?: 'video' | 'game_of_life'
    }) => {
      const response = await apiClient.put('/settings/system', patch)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings-system'] })
      queryClient.invalidateQueries({ queryKey: UI_DISPLAY_QUERY_KEY })
      queryClient.invalidateQueries({ queryKey: ['auth/providers'] })
      showSuccess(t('settings.systemConfigSaved'))
    },
    onError: (err: unknown) => {
      const e = err as { response?: { data?: { detail?: string }; status?: number }; message?: string }
      showError(e?.response?.data?.detail || e?.message || t('settings.saveFailed'))
    },
  })

  const updateSettingsMutation = useMutation({
    mutationFn: async (updatedSettings: Partial<Settings>) => {
      const response = await apiClient.put('/settings', updatedSettings)
      return response.data
    },
    onSuccess: (data) => {
      showSuccess(data.message || t('settings.saved'))
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (error: any) => {
      showError(t('settings.updateError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const unlinkProviderMutation = useMutation({
    mutationFn: async (provider: 'github' | 'google' | 'microsoft' | 'custom') => {
      const response = await apiClient.delete(`/auth/link/${provider}`)
      return response.data as { message?: string }
    },
    onSuccess: (_data, provider) => {
      const providerName =
        provider === 'google'
          ? 'Google'
          : provider === 'github'
            ? 'GitHub'
            : provider === 'microsoft'
              ? 'Microsoft'
              : customProviderName
      showSuccess(t('settings.unlinkSuccess', { provider: providerName }))
      setUnlinkingProvider(null)
      refetchMe()
    },
    onError: (error: any) => {
      setUnlinkingProvider(null)
      showError(error.response?.data?.detail || error.message || t('settings.unlinkError'))
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
      
      showSuccess(message.replace(/\n/g, ' ')) // Replace newlines for toast
      queryClient.invalidateQueries({ queryKey: ['settings', 'backup-failures'] })
    },
    onError: (error: any) => {
      showError(t('settings.cleanupError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const testEmailMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/settings/test-email')
      return response.data
    },
    onSuccess: (data) => {
      showSuccess(data.message || t('settings.testEmailSuccess'))
    },
    onError: (error: any) => {
      showError(t('settings.testEmailError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const testTeamsMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/settings/test-teams')
      return response.data
    },
    onSuccess: (data) => {
      showSuccess(data.message || t('settings.testTeamsSuccess'))
    },
    onError: (error: any) => {
      showError(t('settings.testTeamsError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const createNotificationKeyMutation = useMutation<
      { key: string; id: number; label?: string | null; created_at: string },
      unknown,
      string | undefined
    >({
    mutationFn: async (label) => {
      const r = await apiClient.post('/settings/notification-api/keys', label ? { label: label.trim() } : {})
      return r.data as { key: string; id: number; label?: string | null; created_at: string }
    },
    onSuccess: (data) => {
      setGeneratedKey({ key: data.key, id: data.id, label: data.label })
      setNewKeyLabel('')
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      showSuccess(t('settings.notificationApiKeyCreated'))
    },
    onError: (error: any) => {
      showError(error.response?.data?.detail || error.message || t('settings.notificationApiKeyCreateError'))
    },
  })

  const deleteNotificationKeyMutation = useMutation({
    mutationFn: async (keyId: number) => {
      await apiClient.delete(`/settings/notification-api/keys/${keyId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      showSuccess(t('settings.notificationApiKeyDeleted'))
    },
    onError: (error: any) => {
      showError(error.response?.data?.detail || error.message || t('settings.notificationApiKeyDeleteError'))
    },
  })

  const handleInputChange = (field: keyof Settings, value: string | number | boolean | null) => {
    if (!settings) return
    
    let processedValue: number | boolean | null | string | string[]
    
    if (field === 'auto_sync_enabled' || field === 'email_enabled' || field === 'teams_enabled' || field === 'notification_api_enabled') {
      processedValue = typeof value === 'boolean' ? value : value === 'true'
    } else if (field === 'notification_api_rate_limit_per_minute') {
      processedValue = typeof value === 'number' ? value : (typeof value === 'string' && value !== '' ? parseInt(String(value), 10) : 30)
      if (typeof processedValue === 'number' && (isNaN(processedValue) || processedValue < 1 || processedValue > 300)) {
        processedValue = 30
      }
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
    // Konvertiere email_recipients Array zu komma-separiertem String für API; notification_api_keys nicht mitsenden
    const { email_recipients, notification_api_keys: _keys, ...restSettings } = localSettings
    const settingsToSave: Partial<Omit<Settings, 'email_recipients' | 'notification_api_keys'>> & { email_recipients?: string } = {
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

  const handleTestFrontendException = () => {
    captureException(
      new Error(
        'Fast-Flow Frontend-Test: Test-Exception für PostHog (nur Development). Kein echter Fehler – nur Verifikation. In PostHog anhand dieser Meldung bzw. $fastflow_frontend_test=True als Test erkennbar.'
      ),
      {
        $fastflow_frontend_test: true,
        description: 'Test-Button: Frontend Error-Tracking. Nur in DEV sichtbar.',
      }
    )
    showSuccess(t('settings.posthogFrontendSuccess'))
  }

  const triggerTestExceptionBackendMutation = useMutation({
    mutationFn: async () => {
      const r = await apiClient.post('/settings/trigger-test-exception')
      return r.data as { message?: string }
    },
    onSuccess: (d) => {
      showSuccess(d?.message || t('settings.posthogBackendSuccess'))
    },
    onError: (err: unknown) => {
      const e = err as { response?: { data?: { detail?: string }; status?: number }; message?: string }
      showError(e?.response?.data?.detail || e?.message || t('settings.backendTestFailed'))
    },
  })

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>{t('common.loading')}</p>
      </div>
    )
  }

  const currentSettings = localSettings || settings
  const customProviderName = (authProviders.custom_display_name || '').trim() || t('auth.customProviderFallback')
  const canUnlink = (
    provider: 'github' | 'google' | 'microsoft' | 'custom',
    linked: boolean,
  ) => {
    if (!linked) return false
    const linkedCount = [me?.has_github, me?.has_google, me?.has_microsoft, me?.has_custom].filter(Boolean).length
    return linkedCount > 1 && unlinkingProvider !== provider && !unlinkProviderMutation.isPending
  }
  const onUnlinkProvider = (provider: 'github' | 'google' | 'microsoft' | 'custom', providerLabel: string) => {
    if (!window.confirm(t('settings.unlinkConfirm', { provider: providerLabel }))) return
    setUnlinkingProvider(provider)
    unlinkProviderMutation.mutate(provider)
  }

  const isSensitiveSection = SENSITIVE_SETTINGS_SECTIONS.includes(section)
  const fieldLocked = isSensitiveSection && sensitiveSettingsLocked
  const fieldDisabled = isReadonly || fieldLocked

  const renderNav = () => (
    <nav className="settings-nav" role="tablist" aria-label={t('settings.navAriaSettings')}>
      <div ref={trayRef} className="settings-nav-tray">
        <div
          className="settings-nav-indicator"
          style={{
            left: indicator.left,
            width: indicator.width,
          }}
          aria-hidden
        />
        {sectionItems.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            data-section={item.id}
            aria-selected={section === item.id}
            className={`settings-nav-pill ${section === item.id ? 'active' : ''}`}
            onClick={() => setSection(item.id)}
          >
            {item.icon}
            <span>{t(item.labelKey)}</span>
          </button>
        ))}
      </div>
    </nav>
  )

  return (
    <div className="settings-page">
      {renderNav()}
      <div
        className={`settings-content${isSensitiveSection ? ' settings-content--sensitive' : ''}${
          section === 'git-sync' || section === 'nutzer' ? ' settings-embedded' : ''
        }`}
      >
        {isSensitiveSection && (
          <div className="settings-sensitive-bar">
            <Tooltip
              content={
                sensitiveSettingsLocked
                  ? t('settings.editLockTooltipLocked')
                  : t('settings.editLockTooltipUnlocked')
              }
              position="left"
            >
              <button
                type="button"
                className={`settings-edit-lock-btn ${sensitiveSettingsLocked ? 'is-locked' : 'is-unlocked'}`}
                onClick={() => setSensitiveSettingsLocked((v) => !v)}
                aria-pressed={!sensitiveSettingsLocked}
                aria-label={
                  sensitiveSettingsLocked ? t('settings.editLockUnlockAria') : t('settings.editLockLockAria')
                }
              >
                {sensitiveSettingsLocked ? <MdLock /> : <MdLockOpen />}
              </button>
            </Tooltip>
          </div>
        )}
        {section === 'account' && (
          <div className="settings">
            <div className="settings-header card">
              <h2>{t('settingsSections.account')}</h2>
              <p className="settings-info">
                <MdInfo />
                {t('settings.envOnly')}
                {t('settings.accountRestartNote')}
              </p>
            </div>

            <div className="settings-section card">
              <h3 className="section-title">{t('settings.linkedAccounts')}</h3>
        <p className="setting-hint settings-linked-accounts-hint">
          {t('settings.linkAccountsHint')}
        </p>
        <div className="settings-accounts-list">
          <div className="settings-account-row">
            <span className="settings-account-row__label">
              <strong>GitHub</strong>
              {me?.has_github ? <MdCheck className="icon-success" aria-label={t('settings.linked')} /> : null}
            </span>
            {me?.has_github ? (
              <div className="settings-account-row__actions">
                <span className="settings-linked-badge">{t('settings.linked')}</span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => onUnlinkProvider('github', 'GitHub')}
                  disabled={!canUnlink('github', !!me?.has_github)}
                  title={canUnlink('github', !!me?.has_github) ? '' : t('settings.unlinkLastProviderBlocked')}
                >
                  {unlinkingProvider === 'github' ? t('common.loading') : t('settings.unlink')}
                </button>
              </div>
            ) : authProvidersLoading ? (
              <span className="settings-provider-status">{t('common.loading')}</span>
            ) : authProviders.github ? (
              <a href={accountOAuthLinkUrl('/link/github')} className="btn btn-outlined btn-sm">
                <MdLink />
                {t('settings.connectNow')}
              </a>
            ) : (
              <span className="settings-provider-status" title={t('auth.githubNotConfigured')}>
                {t('auth.githubNotConfigured')}
              </span>
            )}
          </div>
          <div className="settings-account-row">
            <span className="settings-account-row__label">
              <strong>Google</strong>
              {me?.has_google ? <MdCheck className="icon-success" aria-label={t('settings.linked')} /> : null}
            </span>
            {me?.has_google ? (
              <div className="settings-account-row__actions">
                <span className="settings-linked-badge">{t('settings.linked')}</span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => onUnlinkProvider('google', 'Google')}
                  disabled={!canUnlink('google', !!me?.has_google)}
                  title={canUnlink('google', !!me?.has_google) ? '' : t('settings.unlinkLastProviderBlocked')}
                >
                  {unlinkingProvider === 'google' ? t('common.loading') : t('settings.unlink')}
                </button>
              </div>
            ) : authProvidersLoading ? (
              <span className="settings-provider-status">{t('common.loading')}</span>
            ) : authProviders.google ? (
              <a href={accountOAuthLinkUrl('/link/google')} className="btn btn-outlined btn-sm">
                <MdLink />
                {t('settings.connectNow')}
              </a>
            ) : (
              <span className="settings-provider-status" title={t('auth.googleNotConfigured')}>
                {t('auth.googleNotConfigured')}
              </span>
            )}
          </div>
          <div className="settings-account-row">
            <span className="settings-account-row__label">
              <strong>Microsoft</strong>
              {me?.has_microsoft ? <MdCheck className="icon-success" aria-label={t('settings.linked')} /> : null}
            </span>
            {me?.has_microsoft ? (
              <div className="settings-account-row__actions">
                <span className="settings-linked-badge">{t('settings.linked')}</span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => onUnlinkProvider('microsoft', 'Microsoft')}
                  disabled={!canUnlink('microsoft', !!me?.has_microsoft)}
                  title={canUnlink('microsoft', !!me?.has_microsoft) ? '' : t('settings.unlinkLastProviderBlocked')}
                >
                  {unlinkingProvider === 'microsoft' ? t('common.loading') : t('settings.unlink')}
                </button>
              </div>
            ) : authProvidersLoading ? (
              <span className="settings-provider-status">{t('common.loading')}</span>
            ) : authProviders.microsoft ? (
              <a href={accountOAuthLinkUrl('/link/microsoft')} className="btn btn-outlined btn-sm">
                <MdLink />
                {t('settings.connectNow')}
              </a>
            ) : (
              <span className="settings-provider-status" title={t('auth.microsoftNotConfigured')}>
                {t('auth.microsoftNotConfigured')}
              </span>
            )}
          </div>
          <div className="settings-account-row">
            <span className="settings-account-row__label">
              <strong>{customProviderName}</strong>
              {me?.has_custom ? <MdCheck className="icon-success" aria-label={t('settings.linked')} /> : null}
            </span>
            {me?.has_custom ? (
              <div className="settings-account-row__actions">
                <span className="settings-linked-badge">{t('settings.linked')}</span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => onUnlinkProvider('custom', customProviderName)}
                  disabled={!canUnlink('custom', !!me?.has_custom)}
                  title={canUnlink('custom', !!me?.has_custom) ? '' : t('settings.unlinkLastProviderBlocked')}
                >
                  {unlinkingProvider === 'custom' ? t('common.loading') : t('settings.unlink')}
                </button>
              </div>
            ) : authProvidersLoading ? (
              <span className="settings-provider-status">{t('common.loading')}</span>
            ) : authProviders.custom ? (
              <a href={accountOAuthLinkUrl('/link/custom')} className="btn btn-outlined btn-sm">
                <MdLink />
                {t('settings.connectNow')}
              </a>
            ) : (
              <span className="settings-provider-status" title={t('auth.customNotConfigured')}>
                {t('auth.customNotConfigured')}
              </span>
            )}
          </div>
        </div>
      </div>
          </div>
        )}

        {section === 'system' && (
          <div className="settings">
      <div className="settings-section card executor-info-card">
        <h3 className="section-title">{t('settings.executor')}</h3>
        <p className="setting-hint setting-hint--flush">
          {health?.pipeline_executor === 'kubernetes' ? (
            <>{t('settings.executorK8s')}</>
          ) : (
            <>{t('settings.executorDocker')}</>
          )}
        </p>
      </div>
      {isAdmin && (
        <div className="settings-section card">
          <h3 className="section-title">{t('settings.uiDisplayTitle')}</h3>
          <p className="setting-hint setting-hint--flush">{t('settings.uiDisplayHint')}</p>
          <div className="settings-telemetry-toggles">
            <label className="settings-telemetry-toggle">
              <input
                type="checkbox"
                checked={systemSettings?.ui_show_attribution ?? true}
                onChange={(e) => updateSystemSettingsMutation.mutate({ ui_show_attribution: e.target.checked })}
                disabled={updateSystemSettingsMutation.isPending || fieldDisabled}
              />
              {t('settings.showAttribution')}
            </label>
            <p className="setting-hint settings-ui-pref-hint">{t('settings.showAttributionHint')}</p>
            <label className="settings-telemetry-toggle">
              <input
                type="checkbox"
                checked={systemSettings?.ui_show_version ?? true}
                onChange={(e) => updateSystemSettingsMutation.mutate({ ui_show_version: e.target.checked })}
                disabled={updateSystemSettingsMutation.isPending || fieldDisabled}
              />
              {t('settings.showVersion')}
            </label>
            <p className="setting-hint settings-ui-pref-hint">{t('settings.showVersionHint')}</p>
            <p className="setting-hint setting-hint--flush setting-item--offset-top">{t('settings.loginBackgroundTitle')}</p>
            <p className="setting-hint settings-ui-pref-hint">{t('settings.loginBackgroundHint')}</p>
            <label className="settings-telemetry-toggle">
              <input
                type="radio"
                name="ui_login_background"
                checked={(systemSettings?.ui_login_background ?? 'video') === 'video'}
                onChange={() => updateSystemSettingsMutation.mutate({ ui_login_background: 'video' })}
                disabled={updateSystemSettingsMutation.isPending || fieldDisabled}
              />
              {t('settings.loginBackgroundVideo')}
            </label>
            <label className="settings-telemetry-toggle">
              <input
                type="radio"
                name="ui_login_background"
                checked={(systemSettings?.ui_login_background ?? 'video') === 'game_of_life'}
                onChange={() => updateSystemSettingsMutation.mutate({ ui_login_background: 'game_of_life' })}
                disabled={updateSystemSettingsMutation.isPending || fieldDisabled}
              />
              {t('settings.loginBackgroundGameOfLife')}
            </label>
          </div>
        </div>
      )}
      {isAdmin && (
        <div className="settings-section card">
          <h3 className="section-title">
            {t('settings.brandingLogoTitle')}
            <InfoIcon content={t('settings.brandingLogoInfo')} />
          </h3>
          <p className="setting-hint setting-hint--flush">{t('settings.brandingLogoHint')}</p>
          <div className="setting-item setting-item--offset-top">
            <label htmlFor="login_branding_logo_url" className="setting-label">
              {t('settings.brandingLogoUrlLabel')}
            </label>
            <input
              id="login_branding_logo_url"
              type="url"
              className="form-input"
              value={localBrandingLogoUrl !== null ? localBrandingLogoUrl : (systemSettings?.login_branding_logo_url ?? '')}
              onChange={(e) => setLocalBrandingLogoUrl(e.target.value)}
              onBlur={() => {
                const v = (localBrandingLogoUrl !== null ? localBrandingLogoUrl : (systemSettings?.login_branding_logo_url ?? '')).trim()
                const current = (systemSettings?.login_branding_logo_url ?? '').trim()
                if (v !== current) {
                  updateSystemSettingsMutation.mutate(
                    { login_branding_logo_url: v },
                    { onSettled: () => setLocalBrandingLogoUrl(null) }
                  )
                } else {
                  setLocalBrandingLogoUrl(null)
                }
              }}
              placeholder="https://example.com/logo.png"
              disabled={updateSystemSettingsMutation.isPending || fieldDisabled}
            />
          </div>
          <div className="settings-telemetry-toggles setting-item--offset-top">
            <label className="settings-telemetry-toggle">
              <input
                type="checkbox"
                checked={systemSettings?.show_unconfigured_oauth_on_login ?? true}
                onChange={(e) =>
                  updateSystemSettingsMutation.mutate({ show_unconfigured_oauth_on_login: e.target.checked })
                }
                disabled={updateSystemSettingsMutation.isPending || fieldDisabled}
              />
              {t('settings.showUnconfiguredOauthOnLogin')}
            </label>
            <p className="setting-hint settings-ui-pref-hint">{t('settings.showUnconfiguredOauthOnLoginHint')}</p>
          </div>
        </div>
      )}
      {isAdmin && (
        <div className="settings-section card">
          <h3 className="section-title">
            {t('settings.telemetryTitle')}
            <InfoIcon content={t('settings.telemetryInfo')} />
          </h3>
          <div className="settings-telemetry-toggles">
            <label className="settings-telemetry-toggle">
              <input
                type="checkbox"
                checked={systemSettings?.enable_telemetry ?? false}
                disabled={updateSystemSettingsMutation.isPending || fieldDisabled}
                onChange={(e) => updateSystemSettingsMutation.mutate({ enable_telemetry: e.target.checked })}
              />
              {t('settings.telemetryToggle')}
            </label>
            <label className="settings-telemetry-toggle">
              <input
                type="checkbox"
                checked={systemSettings?.enable_error_reporting ?? false}
                disabled={updateSystemSettingsMutation.isPending || fieldDisabled}
                onChange={(e) => updateSystemSettingsMutation.mutate({ enable_error_reporting: e.target.checked })}
              />
              {t('settings.errorReportingToggle')}
            </label>
          </div>
          <p className="settings-telemetry-note">
            {t('settings.noSessionRecording')}
          </p>
        </div>
      )}

      {isAdmin && (
        <div className="settings-section card">
          <h3 className="section-title">
            {t('settings.dependencyAuditTitle')}
            <InfoIcon content={t('settings.dependencyAuditInfo')} />
          </h3>
          <div className="settings-telemetry-toggles">
            <label className="settings-telemetry-toggle">
              <input
                type="checkbox"
                checked={systemSettings?.dependency_audit_enabled ?? true}
                disabled={updateSystemSettingsMutation.isPending || fieldDisabled}
                onChange={(e) =>
                  updateSystemSettingsMutation.mutate({ dependency_audit_enabled: e.target.checked })
                }
              />
              {t('settings.dependencyAuditToggle')}
            </label>
          </div>
          <div className="setting-item setting-item--offset-top">
            <label htmlFor="dependency_audit_cron" className="setting-label">
              {t('settings.cronLabel')}
              <span className="setting-hint">{t('settings.cronHint')}</span>
              <InfoIcon content={t('settings.cronInfo')} />
            </label>
            <input
              id="dependency_audit_cron"
              type="text"
              className="form-input form-input--cron"
              value={systemSettings?.dependency_audit_cron ?? '0 3 * * *'}
              onChange={(e) => setLocalDependencyAuditCron(e.target.value)}
              onBlur={() => {
                const v = (localDependencyAuditCron ?? systemSettings?.dependency_audit_cron ?? '0 3 * * *').trim() || '0 3 * * *'
                if (v !== (systemSettings?.dependency_audit_cron ?? '0 3 * * *')) {
                  updateSystemSettingsMutation.mutate(
                    { dependency_audit_cron: v },
                    { onSettled: () => setLocalDependencyAuditCron(null) }
                  )
                } else {
                  setLocalDependencyAuditCron(null)
                }
              }}
              placeholder="0 3 * * *"
              disabled={updateSystemSettingsMutation.isPending || fieldDisabled}
            />
          </div>
          <p className="settings-telemetry-note">
            {t('settings.dependencyNotifyNote')}
          </p>
        </div>
      )}

      <div className="storage-section-settings">
        <h3 className="section-title">{t('settings.storageStats')}</h3>
        <StorageStats />
      </div>

      <div className="system-metrics-section">
        <SystemMetrics />
      </div>

      {health?.environment === 'development' && (
        <div className="settings-section card settings-section--dev">
          <h3 className="section-title">{t('settings.development')}</h3>
          <p className="setting-hint setting-hint--dev-intro">
            {t('settings.devHint')}
          </p>
          <div className="settings-dev-actions">
            <button
              type="button"
              onClick={handleTestFrontendException}
              disabled={fieldDisabled}
              className="btn btn-outlined"
            >
              {t('settings.testExceptionFrontend')}
            </button>
            <button
              type="button"
              onClick={() => triggerTestExceptionBackendMutation.mutate()}
              disabled={triggerTestExceptionBackendMutation.isPending || fieldDisabled}
              className="btn btn-outlined"
            >
              {triggerTestExceptionBackendMutation.isPending ? t('settings.sending') : t('settings.testExceptionBackend')}
            </button>
          </div>
        </div>
      )}
          </div>
        )}

        {section === 'pipeline' && (
          <div className="settings">
        {!currentSettings ? (
          <div className="loading-container">
            <div className="spinner"></div>
            <p>{t('settings.loading')}</p>
          </div>
        ) : (
        <div className="settings-sections">
          {/* Log Retention Settings */}
          <div className="settings-section card">
            <h3 className="section-title">{t('settings.logRetention')}</h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label htmlFor="log_retention_runs" className="setting-label">
                  {t('settings.maxRunsPerPipeline')}
                  <span className="setting-hint">{t('settings.noneUnlimited')}</span>
                  <InfoIcon content={t('settings.maxRunsInfo')} />
                </label>
                <input
                  id="log_retention_runs"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.log_retention_runs || ''}
                  onChange={(e) => handleInputChange('log_retention_runs', e.target.value)}
                  placeholder={t('settings.noneUnlimited')}
                  disabled={fieldDisabled}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="log_retention_days" className="setting-label">
                  {t('settings.maxAgeDays')}
                  <span className="setting-hint">{t('settings.noneUnlimited')}</span>
                  <InfoIcon content={t('settings.maxAgeInfo')} />
                </label>
                <input
                  id="log_retention_days"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.log_retention_days || ''}
                  onChange={(e) => handleInputChange('log_retention_days', e.target.value)}
                  placeholder={t('settings.noneUnlimited')}
                  disabled={fieldDisabled}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="log_max_size_mb" className="setting-label">
                  {t('settings.maxLogSizeMb')}
                  <span className="setting-hint">{t('settings.noneUnlimited')}</span>
                  <InfoIcon content={t('settings.maxLogSizeInfo')} />
                </label>
                <input
                  id="log_max_size_mb"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.log_max_size_mb || ''}
                  onChange={(e) => handleInputChange('log_max_size_mb', e.target.value)}
                  placeholder={t('settings.noneUnlimited')}
                  disabled={fieldDisabled}
                />
              </div>
            </div>
            <div className="backup-last-run">
              <span className="setting-label">{t('settings.lastS3Backup')}</span>
              <span className="backup-last-run-value">
                {backupStatus?.last_backup_at
                  ? new Date(backupStatus.last_backup_at).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
                  : '–'}
              </span>
              <InfoIcon content={t('settings.lastBackupInfo')} />
            </div>
          </div>

          {/* Runtime Settings */}
          <div className="settings-section card">
            <h3 className="section-title">{t('settings.runtimeSettings')}</h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label htmlFor="max_concurrent_runs" className="setting-label">
                  {t('settings.maxConcurrentRuns')}
                  <InfoIcon content={t('settings.concurrentRunsTooltip')} />
                </label>
                <input
                  id="max_concurrent_runs"
                  type="number"
                  min="1"
                  className="form-input"
                  value={currentSettings.max_concurrent_runs}
                  onChange={(e) => handleInputChange('max_concurrent_runs', e.target.value)}
                  disabled={fieldDisabled}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="container_timeout" className="setting-label">
                  {t('settings.containerTimeout')}
                  <span className="setting-hint">{t('settings.noneUnlimited')}</span>
                  <InfoIcon content={t('settings.containerTimeoutInfo')} />
                </label>
                <input
                  id="container_timeout"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.container_timeout || ''}
                  onChange={(e) => handleInputChange('container_timeout', e.target.value)}
                  placeholder={t('settings.noneUnlimited')}
                  disabled={fieldDisabled}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="retry_attempts" className="setting-label">
                  {t('settings.retryAttempts')}
                  <InfoIcon content={t('settings.retryAttemptsInfo')} />
                </label>
                <input
                  id="retry_attempts"
                  type="number"
                  min="0"
                  className="form-input"
                  value={currentSettings.retry_attempts}
                  onChange={(e) => handleInputChange('retry_attempts', e.target.value)}
                  disabled={fieldDisabled}
                />
              </div>
            </div>
          </div>

          {/* Actions */}
          {!isReadonly && (
            <div className="settings-actions card">
              <h3 className="section-title">{t('settings.actions')}</h3>
              <div className="actions-grid">
                <button
                  onClick={handleSave}
                  disabled={updateSettingsMutation.isPending || !localSettings || fieldLocked}
                  className="btn btn-primary"
                >
                  <MdSave />
                  {t('settings.saveButton')}
                </button>
                <Tooltip content={t('settings.forceFlushTooltip')}>
                  <button
                    onClick={handleForceCleanup}
                    disabled={forceCleanupMutation.isPending || fieldLocked}
                    className="btn btn-warning"
                  >
                    <MdRefresh />
                    {forceCleanupMutation.isPending ? t('common.saving') : t('settings.forceFlush')}
                  </button>
                </Tooltip>
              </div>
              <div className="warning-box">
                <MdWarning />
                <p>
                  <strong>{t('settings.note')}</strong> {t('settings.envOnly')}
                  {t('settings.envHint')}
                  {t('settings.envVarRestart')}
                </p>
              </div>
            </div>
          )}
        </div>
        )}
          </div>
        )}

        {section === 'notifications' && (
          <div className="settings">
        {!currentSettings ? (
          <div className="loading-container">
            <div className="spinner"></div>
            <p>{t('settings.loading')}</p>
          </div>
        ) : (
          <>
          {/* Email Notifications */}
          <div className="settings-section card">
            <h3 className="section-title">
              <MdEmail />
              {t('settings.emailNotifications')}
            </h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label className="setting-label checkbox-label">
                  <input
                    type="checkbox"
                    checked={currentSettings.email_enabled}
                    onChange={(e) => handleInputChange('email_enabled', e.target.checked)}
                    className="checkbox-input"
                    disabled={fieldDisabled}
                  />
                  <span>{t('settings.enableEmail')}</span>
                </label>
              </div>

              <div className="setting-item">
                <label htmlFor="smtp_host" className="setting-label">
                  {t('settings.smtpHost')}
                </label>
                <input
                  id="smtp_host"
                  type="text"
                  className="form-input"
                  value={currentSettings.smtp_host || ''}
                  onChange={(e) => handleInputChange('smtp_host', e.target.value)}
                  placeholder="smtp.example.com"
                  disabled={fieldDisabled || !currentSettings.email_enabled}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="smtp_port" className="setting-label">
                  {t('settings.smtpPort')}
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
                  disabled={fieldDisabled || !currentSettings.email_enabled}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="smtp_user" className="setting-label">
                  {t('settings.smtpUser')}
                </label>
                <input
                  id="smtp_user"
                  type="text"
                  className="form-input"
                  value={currentSettings.smtp_user || ''}
                  onChange={(e) => handleInputChange('smtp_user', e.target.value)}
                  placeholder="user@example.com"
                  disabled={fieldDisabled || !currentSettings.email_enabled}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="smtp_password" className="setting-label">
                  {t('settings.smtpPassword')}
                  <span className="setting-hint">{t('settings.smtpPasswordHint')}</span>
                  <InfoIcon content={t('settings.smtpPasswordTitle')} />
                </label>
                <input
                  id="smtp_password"
                  type="password"
                  className="form-input"
                  placeholder={t('settings.smtpPasswordPlaceholder')}
                  disabled={true}
                  title={t('settings.smtpPasswordTitle')}
                />
              </div>

              <div className="setting-item">
                <label htmlFor="smtp_from" className="setting-label">
                  {t('settings.smtpFrom')}
                </label>
                <input
                  id="smtp_from"
                  type="email"
                  className="form-input"
                  value={currentSettings.smtp_from || ''}
                  onChange={(e) => handleInputChange('smtp_from', e.target.value)}
                  placeholder="noreply@example.com"
                  disabled={fieldDisabled || !currentSettings.email_enabled}
                />
              </div>

              <div className="setting-item full-width">
                <label htmlFor="email_recipients" className="setting-label">
                  {t('settings.recipients')}
                  <InfoIcon content={t('settings.recipientsHint')} />
                </label>
                <textarea
                  id="email_recipients"
                  className="form-input"
                  rows={3}
                  value={currentSettings.email_recipients.join(', ')}
                  onChange={(e) => handleInputChange('email_recipients', e.target.value)}
                  placeholder="admin@example.com, team@example.com"
                  disabled={fieldDisabled || !currentSettings.email_enabled}
                />
              </div>

              <div className="setting-item">
                {!isReadonly && (
                  <button
                    onClick={() => testEmailMutation.mutate()}
                    disabled={!currentSettings.email_enabled || testEmailMutation.isPending || fieldLocked}
                    className="btn btn-primary"
                  >
                  <MdEmail />
                  {testEmailMutation.isPending ? t('settings.sendingLabel') : t('settings.testEmailSend')}
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Teams Notifications */}
          <div className="settings-section card">
            <h3 className="section-title">
              <MdGroup />
              {t('settings.teamsNotifications')}
            </h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label className="setting-label checkbox-label">
                  <input
                    type="checkbox"
                    checked={currentSettings.teams_enabled}
                    onChange={(e) => handleInputChange('teams_enabled', e.target.checked)}
                    className="checkbox-input"
                    disabled={fieldDisabled}
                  />
                  <span>{t('settings.enableTeams')}</span>
                </label>
              </div>

              <div className="setting-item full-width">
                <label htmlFor="teams_webhook_url" className="setting-label">
                  {t('settings.teamsWebhookUrl')}
                  <span className="setting-hint">{t('settings.teamsWebhookHint')}</span>
                  <InfoIcon content={t('settings.recipientsHint')} />
                </label>
                <input
                  id="teams_webhook_url"
                  type="url"
                  className="form-input"
                  value={currentSettings.teams_webhook_url || ''}
                  onChange={(e) => handleInputChange('teams_webhook_url', e.target.value)}
                  placeholder="https://outlook.office.com/webhook/..."
                  disabled={fieldDisabled || !currentSettings.teams_enabled}
                />
              </div>

              <div className="setting-item">
                {!isReadonly && (
                  <button
                    onClick={() => testTeamsMutation.mutate()}
                    disabled={!currentSettings.teams_enabled || testTeamsMutation.isPending || fieldLocked}
                    className="btn btn-primary"
                  >
                    <MdGroup />
                    {testTeamsMutation.isPending ? t('settings.sendingLabel') : t('settings.testTeamsSend')}
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Notification API (Skripte) */}
          <div className="settings-section card">
            <h3 className="section-title">
              <MdKey />
              {t('settings.notificationApiTitle')}
            </h3>
            <p className="setting-hint setting-hint--spaced">{t('settings.notificationApiHint')}</p>
            <div className="settings-grid">
              <div className="setting-item">
                <label className="setting-label checkbox-label">
                  <input
                    type="checkbox"
                    checked={currentSettings.notification_api_enabled ?? false}
                    onChange={(e) => handleInputChange('notification_api_enabled', e.target.checked)}
                    className="checkbox-input"
                    disabled={fieldDisabled}
                  />
                  <span>{t('settings.notificationApiEnabled')}</span>
                </label>
              </div>
              <div className="setting-item">
                <label htmlFor="notification_api_rate_limit" className="setting-label">
                  {t('settings.notificationApiRateLimit')}
                </label>
                <input
                  id="notification_api_rate_limit"
                  type="number"
                  min={1}
                  max={300}
                  className="form-input"
                  value={currentSettings.notification_api_rate_limit_per_minute ?? 30}
                  onChange={(e) => handleInputChange('notification_api_rate_limit_per_minute', e.target.value)}
                  disabled={fieldDisabled || !(currentSettings.notification_api_enabled ?? false)}
                />
              </div>
              <div className="setting-item full-width">
                <label className="setting-label">{t('settings.notificationApiKeys')}</label>
                <div className="settings-grid settings-api-keys-nested">
                  {(currentSettings.notification_api_keys ?? []).length === 0 ? (
                    <p className="setting-hint">{t('settings.notificationApiKeysEmpty')}</p>
                  ) : (
                    <table className="settings-table settings-table--full">
                      <thead>
                        <tr>
                          <th>{t('settings.notificationApiKeyLabel')}</th>
                          <th>{t('settings.notificationApiKeyCreatedAt')}</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {(currentSettings.notification_api_keys ?? []).map((k) => (
                          <tr key={k.id}>
                            <td>{k.label || '–'}</td>
                            <td>{k.created_at ? new Date(k.created_at).toLocaleString() : '–'}</td>
                            <td>
                              {!isReadonly && (
                                <button
                                  type="button"
                                  className="btn btn-secondary btn-sm"
                                  onClick={() => deleteNotificationKeyMutation.mutate(k.id)}
                                  disabled={deleteNotificationKeyMutation.isPending || fieldLocked}
                                  aria-label={t('settings.removeKey')}
                                >
                                  <MdDelete /> {t('settings.removeKey')}
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {!isReadonly && (
                    <div className="settings-new-key-row">
                      <label htmlFor="new-key-label" className="setting-label">
                        {t('settings.notificationApiKeyLabel')} (optional)
                      </label>
                      <input
                        id="new-key-label"
                        type="text"
                        className="form-input form-input--key-label"
                        value={newKeyLabel}
                        onChange={(e) => setNewKeyLabel(e.target.value)}
                        placeholder={t('settings.notificationApiKeyLabelPlaceholder')}
                        disabled={fieldLocked}
                      />
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => createNotificationKeyMutation.mutate(newKeyLabel.trim() || undefined)}
                        disabled={createNotificationKeyMutation.isPending || fieldLocked}
                      >
                        <MdKey /> {t('settings.generateKey')}
                      </button>
                    </div>
                  )}
                </div>
                {generatedKey && (
                  <div className="settings-generated-key-card">
                    <p className="setting-hint">{t('settings.keyGeneratedOnce')}</p>
                    <div className="settings-generated-key-row">
                      <code className="settings-generated-key-code">{generatedKey.key}</code>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => { navigator.clipboard.writeText(generatedKey.key); showSuccess(t('settings.copied')); }}
                      >
                        <MdContentCopy /> {t('settings.copy')}
                      </button>
                    </div>
                    <button type="button" className="btn btn-secondary btn-sm settings-dismiss-generated" onClick={() => setGeneratedKey(null)}>
                      {t('settings.close')}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
          </>
        )}
          </div>
        )}

        {section === 'git-sync' && <Sync editLocked={fieldLocked} />}

        {section === 'nutzer' && <Users editLocked={fieldLocked} />}
      </div>

      {/* Cleanup Info Modal */}
      {showCleanupInfo && currentSettings && (
        <div className="modal-overlay" onClick={() => setShowCleanupInfo(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{t('settings.forceFlushModalTitle')}</h3>
              <button
                className="modal-close"
                onClick={() => setShowCleanupInfo(false)}
                aria-label={t('settings.close')}
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              <div className="cleanup-info-section">
                <h4>📁 {t('settings.logCleanup')}</h4>
                <p className="cleanup-description">
                  {t('settings.cleanupLogDesc')}
                </p>
                <ul className="cleanup-actions">
                  {currentSettings.log_retention_runs ? (
                    <li>
                      {t('settings.cleanupDeleteOldest', { count: currentSettings.log_retention_runs })}
                    </li>
                  ) : null}
                  {currentSettings.log_retention_days ? (
                    <li>
                      {t('settings.cleanupDeleteOlderThan', { days: currentSettings.log_retention_days })}
                    </li>
                  ) : null}
                  {currentSettings.log_max_size_mb ? (
                    <li>
                      {t('settings.cleanupTruncateLogs', { mb: currentSettings.log_max_size_mb })}
                    </li>
                  ) : null}
                  {!currentSettings.log_retention_runs && !currentSettings.log_retention_days && !currentSettings.log_max_size_mb && (
                    <li className="cleanup-disabled">{t('settings.noLogCleanupConfigured')}</li>
                  )}
                </ul>
              </div>

              <div className="cleanup-info-section">
                <h4>🐳 {t('settings.dockerCleanup')}</h4>
                <p className="cleanup-description">
                  {t('settings.cleanupDockerDesc')}
                </p>
                <ul className="cleanup-actions">
                  <li>{t('settings.cleanupOrphanContainers')}</li>
                  <li>{t('settings.cleanupFinishedContainers')}</li>
                  <li>{t('settings.cleanupOrphanVolumes')}</li>
                </ul>
              </div>

              <div className="cleanup-warning">
                <MdWarning />
                <p>
                  {t('settings.cleanupWarning')}
                </p>
              </div>
            </div>
            <div className="modal-footer">
              <button
                className="btn btn-secondary"
                onClick={() => setShowCleanupInfo(false)}
              >
                {t('common.cancel')}
              </button>
              <button
                className="btn btn-warning"
                onClick={confirmForceCleanup}
                disabled={forceCleanupMutation.isPending || isReadonly}
              >
                <MdRefresh />
                {forceCleanupMutation.isPending ? t('settings.cleanupRunning') : t('settings.cleanupExecute')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
