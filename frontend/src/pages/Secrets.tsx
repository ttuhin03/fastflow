import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation } from '@tanstack/react-query'
import { LuLock, LuEye, LuEyeOff } from 'react-icons/lu'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError, showSuccess } from '../utils/toast'
import Tooltip from '../components/Tooltip'
import { getFormatLocale } from '../utils/locale'
import './Secrets.css'

interface Secret {
  key: string
  value: string
  is_parameter?: boolean
  created_at: string
  updated_at: string
}

interface SecretFromPipeline {
  key: string
  pipeline: string
  source: 'encrypted_env' | 'default_env'
  run_config_id: string | null
}

export default function Secrets() {
  const { t } = useTranslation()
  const { isReadonly } = useAuth()
  const [showValues, setShowValues] = useState<Record<string, boolean>>({})
  const [encryptOpen, setEncryptOpen] = useState(false)
  const [encryptPlaintext, setEncryptPlaintext] = useState('')
  const [encryptResult, setEncryptResult] = useState<string | null>(null)

  const { data: secrets, isLoading } = useQuery<Secret[]>({
    queryKey: ['secrets'],
    queryFn: async () => {
      const response = await apiClient.get('/secrets')
      return response.data.secrets ?? response.data
    },
  })

  const { data: fromPipelines } = useQuery<SecretFromPipeline[]>({
    queryKey: ['secrets-from-pipelines'],
    queryFn: async () => {
      const response = await apiClient.get('/secrets/from-pipelines')
      return response.data
    },
  })

  const encryptForPipelineMutation = useMutation({
    mutationFn: async (value: string) => {
      const response = await apiClient.post<{ encrypted: string }>('/secrets/encrypt-for-pipeline', { value })
      return response.data
    },
    onSuccess: (data) => {
      setEncryptResult(data.encrypted)
      showSuccess(t('secrets.encryptSuccess'))
    },
    onError: (error: any) => {
      showError(t('secrets.encryptError', { detail: error.response?.data?.detail || error.message }))
    },
  })

  const handleCopyEncrypted = async () => {
    if (!encryptResult) return
    try {
      await navigator.clipboard.writeText(encryptResult)
      showSuccess(t('secrets.copySuccess'))
    } catch {
      showError(t('secrets.copyError'))
    }
  }

  const toggleShowValue = (key: string) => {
    setShowValues((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  if (isLoading) {
    return <div>{t('common.loading')}</div>
  }

  const dbSecrets = secrets ?? []

  return (
    <div className="secrets">
      <div className="secrets-header">
        <div>
          <h1 className="secrets-title">{t('secrets.title')}</h1>
          <p className="secrets-subtitle">
            {t('secrets.subtitle', 'Encrypted at rest (Fernet) · values are never displayed')}
          </p>
        </div>
        {!isReadonly && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setEncryptOpen((v) => !v)}
          >
            <LuLock aria-hidden />
            {t('secrets.newSecret', 'Encrypt value')}
          </button>
        )}
      </div>

      {!isReadonly && encryptOpen && (
        <div className="encrypt-for-pipeline-section card">
          <h3 className="section-title">{t('secrets.encryptSection')}</h3>
          <p className="encrypt-hint">{t('secrets.encryptHint')}</p>
          <div className="form-group">
            <label htmlFor="encrypt-plaintext" className="form-label">{t('secrets.plaintext')}</label>
            <textarea
              id="encrypt-plaintext"
              className="form-textarea"
              value={encryptPlaintext}
              onChange={(e) => {
                setEncryptPlaintext(e.target.value)
                setEncryptResult(null)
              }}
              rows={3}
              placeholder={t('secrets.placeholder')}
            />
          </div>
          <div className="form-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!encryptPlaintext || encryptForPipelineMutation.isPending}
              onClick={() => encryptForPipelineMutation.mutate(encryptPlaintext)}
            >
              {encryptForPipelineMutation.isPending ? t('common.saving') : t('secrets.encrypt')}
            </button>
          </div>
          {encryptResult && (
            <div className="encrypt-result">
              <label className="form-label">{t('secrets.encryptedValueLabel')}</label>
              <div className="encrypt-result-row">
                <textarea
                  readOnly
                  value={encryptResult}
                  rows={2}
                  className="form-textarea encrypt-result-value"
                />
                <button type="button" className="btn btn-secondary" onClick={handleCopyEncrypted}>
                  {t('secrets.copy')}
                </button>
              </div>
              <p className="encrypt-result-hint">{t('secrets.encryptResultHint')}</p>
            </div>
          )}
        </div>
      )}

      <section className="secrets-db-section">
        <h3 className="section-title">{t('secrets.inDb')}</h3>
        {dbSecrets.length > 0 ? (
          <div className="table secrets-table">
            <div className="table__head">
              <span>{t('secrets.key')}</span>
              <span>{t('secrets.type')}</span>
              <span>{t('secrets.scope', 'Scope')}</span>
              <span>{t('secrets.updatedAt')}</span>
              <span className="secrets-cell-actions">{t('scheduler.actions')}</span>
            </div>
            {dbSecrets.map((secret) => {
              const revealed = showValues[secret.key]
              return (
                <div key={secret.key} className="table__row secrets-row">
                  <span className="secrets-cell-name">
                    <LuLock className="secrets-lock-icon" aria-hidden />
                    <span className="secrets-name-inner">
                      <span className="mono secrets-name-text" title={secret.key}>{secret.key}</span>
                      <span className="mono secrets-name-value">
                        {revealed ? secret.value : '••••••••••••'}
                      </span>
                    </span>
                  </span>
                  <span className="secrets-cell-type">
                    <Tooltip content={secret.is_parameter
                      ? t('secrets.typeParameterTooltip')
                      : t('secrets.typeSecretTooltip')}>
                      <span className={`badge ${secret.is_parameter ? 'badge-primary' : 'badge-error'}`}>
                        {secret.is_parameter ? t('secrets.typeParameter') : t('secrets.typeSecret')}
                      </span>
                    </Tooltip>
                  </span>
                  <span className="secrets-cell-scope">
                    {/* TODO(redesign): needs backend — no scope field exists yet.
                        Derive a placeholder scope from the entry type. */}
                    <span className="badge badge-secondary">
                      {secret.is_parameter ? t('secrets.scopeApp', 'app') : t('secrets.scopeGlobal', 'global')}
                    </span>
                  </span>
                  <span className="mono secrets-cell-updated">
                    {new Date(secret.updated_at).toLocaleString(getFormatLocale())}
                  </span>
                  <span className="secrets-cell-actions secrets-cell-actions--row">
                    <Tooltip content={t('secrets.showHideTooltip')}>
                      <button
                        type="button"
                        onClick={() => toggleShowValue(secret.key)}
                        className="btn btn-icon btn-sm"
                        aria-label={revealed ? t('secrets.hide') : t('secrets.show')}
                      >
                        {revealed ? <LuEyeOff aria-hidden /> : <LuEye aria-hidden />}
                      </button>
                    </Tooltip>
                  </span>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="card secrets-empty">
            <p className="no-secrets">{t('secrets.noEntriesDb')}</p>
          </div>
        )}
      </section>

      <section className="secrets-pipelines-section">
        <h3 className="section-title">{t('secrets.inPipelineJson')}</h3>
        <p className="secrets-pipelines-hint">{t('secrets.envKeysFromPipelines')}</p>
        {fromPipelines && fromPipelines.length > 0 ? (
          <div className="table secrets-table secrets-table--pipelines">
            <div className="table__head">
              <span>{t('secrets.key')}</span>
              <span>{t('secrets.pipeline')}</span>
              <span>{t('secrets.source')}</span>
            </div>
            {fromPipelines.map((row, idx) => (
              <div
                key={`${row.pipeline}-${row.key}-${row.run_config_id || ''}-${idx}`}
                className="table__row secrets-pipeline-row"
              >
                <span className="mono secrets-name-text" title={row.key}>{row.key}</span>
                <span className="secrets-cell-pipeline">
                  <span className="mono">{row.pipeline}</span>
                  {row.run_config_id && (
                    <span className="badge badge-secondary" title={t('secrets.runConfigBadgeTitle')}>
                      {row.run_config_id}
                    </span>
                  )}
                </span>
                <span>
                  <span className={`badge ${row.source === 'encrypted_env' ? 'badge-error' : 'badge-primary'}`}>
                    {row.source === 'encrypted_env' ? 'encrypted_env' : 'default_env'}
                  </span>
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="card secrets-empty">
            <p className="no-secrets">{t('secrets.noEntriesPipeline')}</p>
          </div>
        )}
      </section>
    </div>
  )
}
