import { useState, useEffect, useRef, useLayoutEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { MdSave, MdRefresh, MdInfo, MdWarning, MdEmail, MdGroup, MdLink, MdCheck, MdPerson, MdSync, MdStorage, MdPlayCircle, MdNotifications, MdPeople } from 'react-icons/md'
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

export type SettingsSection = 'account' | 'system' | 'pipeline' | 'notifications' | 'git-sync' | 'nutzer'

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
  const { isReadonly, isAdmin } = useAuth()
  const [localSettings, setLocalSettings] = useState<Settings | null>(null)
  const [showCleanupInfo, setShowCleanupInfo] = useState(false)
  const [localDependencyAuditCron, setLocalDependencyAuditCron] = useState<string | null>(null)

  const [searchParams, setSearchParams] = useSearchParams()
  const section = (searchParams.get('section') as SettingsSection) || 'account'
  const setSection = (s: SettingsSection) => {
    const np = new URLSearchParams(searchParams)
    np.set('section', s)
    setSearchParams(np, { replace: true })
  }

  const sectionItems: { id: SettingsSection; label: string; icon: React.ReactNode }[] = [
    { id: 'account', label: 'Mein Konto', icon: <MdPerson /> },
    { id: 'system', label: 'System', icon: <MdStorage /> },
    { id: 'pipeline', label: 'Pipeline & Runs', icon: <MdPlayCircle /> },
    { id: 'notifications', label: 'Benachrichtigungen', icon: <MdNotifications /> },
    { id: 'git-sync', label: 'Git Sync', icon: <MdSync /> },
    ...(isAdmin ? [{ id: 'nutzer' as const, label: 'Nutzer', icon: <MdPeople /> }] : []),
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

  useEffect(() => {
    const linked = searchParams.get('linked')
    if (linked === 'google' || linked === 'github' || linked === 'microsoft' || linked === 'custom') {
      const msg =
        linked === 'google'
          ? 'Google-Konto verknüpft.'
          : linked === 'github'
            ? 'GitHub-Konto verknüpft.'
            : linked === 'microsoft'
              ? 'Microsoft-Konto verknüpft.'
              : 'Custom-Konto verknüpft.'
      showSuccess(msg)
      const np = new URLSearchParams(searchParams)
      np.delete('linked')
      setSearchParams(Object.fromEntries(np.entries()), { replace: true })
      refetchMe()
    }
  }, [searchParams, setSearchParams, refetchMe])

  const { data: systemSettings } = useQuery<{
    is_setup_completed: boolean
    enable_telemetry: boolean
    enable_error_reporting: boolean
    dependency_audit_enabled: boolean
    dependency_audit_cron: string
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
    }) => {
      const response = await apiClient.put('/settings/system', patch)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings-system'] })
      showSuccess('System-Konfiguration gespeichert.')
    },
    onError: (err: unknown) => {
      const e = err as { response?: { data?: { detail?: string }; status?: number }; message?: string }
      showError(e?.response?.data?.detail || e?.message || 'Speichern fehlgeschlagen.')
    },
  })

  const updateSettingsMutation = useMutation({
    mutationFn: async (updatedSettings: Partial<Settings>) => {
      const response = await apiClient.put('/settings', updatedSettings)
      return response.data
    },
    onSuccess: (data) => {
      showSuccess(data.message || 'Einstellungen aktualisiert (Neustart erforderlich)')
      queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (error: any) => {
      showError(`Fehler beim Aktualisieren: ${error.response?.data?.detail || error.message}`)
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
      showError(`Fehler beim Cleanup: ${error.response?.data?.detail || error.message}`)
    },
  })

  const testEmailMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/settings/test-email')
      return response.data
    },
    onSuccess: (data) => {
      showSuccess(data.message || 'Test-E-Mail erfolgreich gesendet')
    },
    onError: (error: any) => {
      showError(`Fehler beim Senden der Test-E-Mail: ${error.response?.data?.detail || error.message}`)
    },
  })

  const testTeamsMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post('/settings/test-teams')
      return response.data
    },
    onSuccess: (data) => {
      showSuccess(data.message || 'Test-Teams-Nachricht erfolgreich gesendet')
    },
    onError: (error: any) => {
      showError(`Fehler beim Senden der Test-Teams-Nachricht: ${error.response?.data?.detail || error.message}`)
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
    showSuccess('Test-Exception an PostHog gesendet (Frontend). In PostHog prüfen.')
  }

  const triggerTestExceptionBackendMutation = useMutation({
    mutationFn: async () => {
      const r = await apiClient.post('/settings/trigger-test-exception')
      return r.data as { message?: string }
    },
    onSuccess: (d) => {
      showSuccess(d?.message || 'Test-Exception an PostHog gesendet (Backend).')
    },
    onError: (err: unknown) => {
      const e = err as { response?: { data?: { detail?: string }; status?: number }; message?: string }
      showError(e?.response?.data?.detail || e?.message || 'Backend-Test fehlgeschlagen.')
    },
  })

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Laden...</p>
      </div>
    )
  }

  const currentSettings = localSettings || settings

  const renderNav = () => (
    <nav className="settings-nav" role="tablist" aria-label="Einstellungsbereiche">
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
            <span>{item.label}</span>
          </button>
        ))}
      </div>
    </nav>
  )

  if (section === 'git-sync') {
    return (
      <div className="settings-page">
        {renderNav()}
        <div className="settings-content settings-embedded">
          <Sync />
        </div>
      </div>
    )
  }

  if (section === 'nutzer') {
    return (
      <div className="settings-page">
        {renderNav()}
        <div className="settings-content settings-embedded">
          <Users />
        </div>
      </div>
    )
  }

  return (
    <div className="settings-page">
      {renderNav()}
      <div className="settings-content">
        {section === 'account' && (
          <div className="settings">
            <div className="settings-header card">
              <h2>Mein Konto</h2>
              <p className="settings-info">
                <MdInfo />
                Einstellungen werden aktuell nur aus Environment-Variablen geladen.
                Änderungen erfordern einen Neustart der Anwendung.
              </p>
            </div>

            <div className="settings-section card">
              <h3 className="section-title">Verknüpfte Konten</h3>
        <p className="setting-hint" style={{ marginBottom: '1rem' }}>
          Verknüpfe Konten, um mit mehreren Providern einzuloggen. E-Mail kann je Provider abweichen; Verknüpfung funktioniert über „Jetzt verbinden“.
        </p>
        <div className="accounts-list" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div className="account-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.5rem 0', borderBottom: '1px solid var(--color-border)' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <strong>GitHub</strong>
              {me?.has_github ? <MdCheck style={{ color: 'var(--color-success)' }} aria-label="Verknüpft" /> : null}
            </span>
            {me?.has_github ? (
              <span style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem' }}>Verknüpft</span>
            ) : (
              <a href={`${getApiOrigin()}/api/auth/link/github`} className="btn btn-outlined" style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}>
                <MdLink style={{ marginRight: '0.25rem' }} />
                Jetzt verbinden
              </a>
            )}
          </div>
          <div className="account-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.5rem 0' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <strong>Google</strong>
              {me?.has_google ? <MdCheck style={{ color: 'var(--color-success)' }} aria-label="Verknüpft" /> : null}
            </span>
            {me?.has_google ? (
              <span style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem' }}>Verknüpft</span>
            ) : (
              <a href={`${getApiOrigin()}/api/auth/link/google`} className="btn btn-outlined" style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}>
                <MdLink style={{ marginRight: '0.25rem' }} />
                Jetzt verbinden
              </a>
            )}
          </div>
          <div className="account-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.5rem 0' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <strong>Microsoft</strong>
              {me?.has_microsoft ? <MdCheck style={{ color: 'var(--color-success)' }} aria-label="Verknüpft" /> : null}
            </span>
            {me?.has_microsoft ? (
              <span style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem' }}>Verknüpft</span>
            ) : (
              <a href={`${getApiOrigin()}/api/auth/link/microsoft`} className="btn btn-outlined" style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}>
                <MdLink style={{ marginRight: '0.25rem' }} />
                Jetzt verbinden
              </a>
            )}
          </div>
          <div className="account-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.5rem 0' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <strong>Custom</strong>
              {me?.has_custom ? <MdCheck style={{ color: 'var(--color-success)' }} aria-label="Verknüpft" /> : null}
            </span>
            {me?.has_custom ? (
              <span style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem' }}>Verknüpft</span>
            ) : (
              <a href={`${getApiOrigin()}/api/auth/link/custom`} className="btn btn-outlined" style={{ fontSize: '0.875rem', padding: '0.25rem 0.5rem' }}>
                <MdLink style={{ marginRight: '0.25rem' }} />
                Jetzt verbinden
              </a>
            )}
          </div>
        </div>
      </div>
          </div>
        )}

        {section === 'system' && (
          <div className="settings">
      <div className="settings-section card executor-info-card">
        <h3 className="section-title">Pipeline-Executor</h3>
        <p className="setting-hint" style={{ marginBottom: 0 }}>
          {health?.pipeline_executor === 'kubernetes' ? (
            <>Aktiv: <strong className="executor-kubernetes">Kubernetes (Jobs)</strong> – Pipeline-Runs laufen als K8s-Jobs.</>
          ) : (
            <>Aktiv: <strong className="executor-docker">Docker (Socket-Proxy)</strong> – Pipeline-Runs laufen als Docker-Container.</>
          )}
        </p>
      </div>
      {isAdmin && (
        <div className="settings-section card">
          <h3 className="section-title">
            Global Privacy & Telemetry
            <InfoIcon content="Phase 1: Fehlerberichte. Phase 2: Nutzungsstatistiken (Product Analytics). Session Recording (Replay) wird ausdrücklich nicht verwendet." />
          </h3>
          <div className="settings-telemetry-toggles">
            <label className="settings-telemetry-toggle">
              <input
                type="checkbox"
                checked={systemSettings?.enable_telemetry ?? false}
                disabled={updateSystemSettingsMutation.isPending}
                onChange={(e) => updateSystemSettingsMutation.mutate({ enable_telemetry: e.target.checked })}
              />
              Nutzungsstatistiken (Product Analytics, anonym). Kein Session Recording.
            </label>
            <label className="settings-telemetry-toggle">
              <input
                type="checkbox"
                checked={systemSettings?.enable_error_reporting ?? false}
                disabled={updateSystemSettingsMutation.isPending}
                onChange={(e) => updateSystemSettingsMutation.mutate({ enable_error_reporting: e.target.checked })}
              />
              Fehlerberichte (PostHog Error-Tracking)
            </label>
          </div>
          <p className="settings-telemetry-note">
            Session Recording (Bildschirmaufzeichnung / Replay) wird ausdrücklich nicht verwendet.
          </p>
        </div>
      )}

      {isAdmin && (
        <div className="settings-section card">
          <h3 className="section-title">
            Abhängigkeiten – automatische Sicherheitsprüfung
            <InfoIcon content="Täglich (pip-audit) werden alle Pipelines mit requirements.txt auf bekannte Schwachstellen (CVE) geprüft. Bei Fund: E-Mail und/oder Teams (wie unter Benachrichtigungen konfiguriert)." />
          </h3>
          <div className="settings-telemetry-toggles">
            <label className="settings-telemetry-toggle">
              <input
                type="checkbox"
                checked={systemSettings?.dependency_audit_enabled ?? false}
                disabled={updateSystemSettingsMutation.isPending || isReadonly}
                onChange={(e) =>
                  updateSystemSettingsMutation.mutate({ dependency_audit_enabled: e.target.checked })
                }
              />
              Automatische Sicherheitsprüfung (täglich in der Nacht)
            </label>
          </div>
          <div className="setting-item" style={{ marginTop: '0.75rem' }}>
            <label htmlFor="dependency_audit_cron" className="setting-label">
              Zeitpunkt (Cron)
              <span className="setting-hint">(z. B. 0 3 * * * = täglich 3:00 Uhr)</span>
              <InfoIcon content="Cron mit 5 Feldern: Minute Stunde Tag Monat Wochentag. Standard: 0 3 * * * (täglich 3:00 Uhr)." />
            </label>
            <input
              id="dependency_audit_cron"
              type="text"
              className="form-input"
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
              disabled={updateSystemSettingsMutation.isPending || isReadonly}
              style={{ maxWidth: '12rem', fontFamily: 'monospace' }}
            />
          </div>
          <p className="settings-telemetry-note">
            Bei gefundenen Schwachstellen werden E-Mail und/oder Microsoft Teams (wie unter
            Benachrichtigungen konfiguriert) benachrichtigt.
          </p>
        </div>
      )}

      <div className="storage-section-settings">
        <h3 className="section-title">Speicherplatz-Statistiken</h3>
        <StorageStats />
      </div>

      <div className="system-metrics-section">
        <SystemMetrics />
      </div>

      {health?.environment === 'development' && (
        <div className="settings-section card" style={{ marginTop: '1rem' }}>
          <h3 className="section-title">Entwicklung</h3>
          <p className="setting-hint" style={{ marginBottom: '0.75rem' }}>
            Sichtbar, wenn in der .env <code>ENVIRONMENT=development</code>. Sendet Test-Exceptions an PostHog. Auswählen: Backend oder Frontend.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            <button
              type="button"
              onClick={handleTestFrontendException}
              className="btn btn-outlined"
            >
              Test-Exception (Frontend) senden
            </button>
            <button
              type="button"
              onClick={() => triggerTestExceptionBackendMutation.mutate()}
              disabled={triggerTestExceptionBackendMutation.isPending}
              className="btn btn-outlined"
            >
              {triggerTestExceptionBackendMutation.isPending ? 'Sende…' : 'Test-Exception (Backend) senden'}
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
            <p>Einstellungen werden geladen...</p>
          </div>
        ) : (
        <div className="settings-sections">
          {/* Log Retention Settings */}
          <div className="settings-section card">
            <h3 className="section-title">Log Retention</h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label htmlFor="log_retention_runs" className="setting-label">
                  Maximale Runs pro Pipeline
                  <span className="setting-hint">(None = unbegrenzt)</span>
                  <InfoIcon content="Maximale Anzahl Runs, die pro Pipeline behalten werden. Ältere werden gelöscht." />
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
                  <InfoIcon content="Runs älter als X Tage werden automatisch gelöscht" />
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
                  <InfoIcon content="Log-Dateien größer als X MB werden gekürzt oder gelöscht" />
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
            <div className="backup-last-run">
              <span className="setting-label">Letztes S3-Backup</span>
              <span className="backup-last-run-value">
                {backupStatus?.last_backup_at
                  ? new Date(backupStatus.last_backup_at).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' })
                  : '–'}
              </span>
              <InfoIcon content="Zeitpunkt des letzten erfolgreichen Uploads von Logs nach S3/MinIO (wird beim Neustart zurückgesetzt)." />
            </div>
          </div>

          {/* Runtime Settings */}
          <div className="settings-section card">
            <h3 className="section-title">Runtime-Einstellungen</h3>
            <div className="settings-grid">
              <div className="setting-item">
                <label htmlFor="max_concurrent_runs" className="setting-label">
                  Maximale gleichzeitige Runs
                  <InfoIcon content="Wie viele Pipelines gleichzeitig ausgeführt werden können" />
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
                  <InfoIcon content="Maximale Laufzeit eines Containers in Sekunden. None = unbegrenzt." />
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
                  <InfoIcon content="Anzahl automatischer Wiederholungsversuche bei Fehlschlag" />
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
                  <InfoIcon content="Aktiviert automatisches Git-Sync in konfigurierten Intervallen" />
                </label>
              </div>

              <div className="setting-item">
                <label htmlFor="auto_sync_interval" className="setting-label">
                  Auto-Sync Intervall (Sekunden)
                  <span className="setting-hint">(None = deaktiviert)</span>
                  <InfoIcon content="Intervall in Sekunden (Minimum: 60)" />
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
                <Tooltip content="Führt sofortiges Cleanup durch: Löscht alte Logs gemäß Retention-Regeln, bereinigt verwaiste Docker-Container. Kann nicht rückgängig gemacht werden.">
                  <button
                    onClick={handleForceCleanup}
                    disabled={forceCleanupMutation.isPending}
                    className="btn btn-warning"
                  >
                    <MdRefresh />
                    {forceCleanupMutation.isPending ? 'Cleanup läuft...' : 'Force Flush (Cleanup)'}
                  </button>
                </Tooltip>
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
          </div>
        )}

        {section === 'notifications' && (
          <div className="settings">
        {!currentSettings ? (
          <div className="loading-container">
            <div className="spinner"></div>
            <p>Einstellungen werden geladen...</p>
          </div>
        ) : (
          <>
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
                  <InfoIcon content="Passwort muss über Environment-Variable SMTP_PASSWORD gesetzt werden" />
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
                  <InfoIcon content="Komma-separierte Liste von E-Mail-Adressen für Benachrichtigungen" />
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
                  <InfoIcon content="Webhook-URL aus Teams-Kanal Connectors. Wird für Benachrichtigungen verwendet." />
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
          </>
        )}
          </div>
        )}
      </div>

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
