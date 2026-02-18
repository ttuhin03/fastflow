import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation } from '@tanstack/react-query'
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
  const [encryptPlaintext, setEncryptPlaintext] = useState('')
  const [encryptResult, setEncryptResult] = useState<string | null>(null)

  const { data: secrets, isLoading } = useQuery<Secret[]>({
    queryKey: ['secrets'],
    queryFn: async () => {
      const response = await apiClient.get('/secrets')
      return response.data
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

  return (
    <div className="secrets">
      <div className="secrets-header">
        <h2>{t('secrets.title')}</h2>
      </div>
      <p className="secrets-readonly-hint">
        {t('secrets.intro')}
      </p>

      {!isReadonly && (
        <div className="encrypt-for-pipeline-section card">
          <h3 className="section-title">{t('secrets.encryptSection')}</h3>
          <p className="encrypt-hint">
            {t('secrets.encryptHint')}
          </p>
          <div className="form-group">
            <label htmlFor="encrypt-plaintext" className="form-label">{t('secrets.plaintext')}</label>
            <textarea
              id="encrypt-plaintext"
              className="form-input"
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
                  className="form-input encrypt-result-value"
                />
                <button type="button" className="btn btn-secondary" onClick={handleCopyEncrypted}>
                  {t('secrets.copy')}
                </button>
              </div>
              <p className="encrypt-result-hint">
                {t('secrets.encryptResultHint')}
              </p>
            </div>
          )}
        </div>
      )}

      <section className="secrets-db-section">
        <h3 className="section-title">{t('secrets.inDb')}</h3>
        {secrets && secrets.length > 0 ? (
          <table className="secrets-table">
            <thead>
              <tr>
                <th>{t('secrets.key')}</th>
                <th>{t('secrets.type')}</th>
                <th>{t('secrets.value')}</th>
                <th>{t('secrets.createdAt')}</th>
                <th>{t('secrets.updatedAt')}</th>
              </tr>
            </thead>
            <tbody>
              {secrets.map((secret) => (
                <tr key={secret.key}>
                  <td>{secret.key}</td>
                  <td>
                    <Tooltip content={secret.is_parameter 
                      ? t('secrets.typeParameterTooltip')
                      : t('secrets.typeSecretTooltip')}>
                      <span className={`type-badge ${secret.is_parameter ? 'parameter' : 'secret'}`}>
                        {secret.is_parameter ? t('secrets.typeParameter') : t('secrets.typeSecret')}
                      </span>
                    </Tooltip>
                  </td>
                  <td>
                    <div className="value-cell">
                      {showValues[secret.key] ? (
                        <span className="secret-value">{secret.value}</span>
                      ) : (
                        <span className="secret-value-hidden">••••••••</span>
                      )}
                      <Tooltip content={t('secrets.showHideTooltip')}>
                        <button
                          onClick={() => toggleShowValue(secret.key)}
                          className="toggle-button"
                        >
                          {showValues[secret.key] ? t('secrets.hide') : t('secrets.show')}
                        </button>
                      </Tooltip>
                    </div>
                  </td>
                  <td>{new Date(secret.created_at).toLocaleString(getFormatLocale())}</td>
                  <td>{new Date(secret.updated_at).toLocaleString(getFormatLocale())}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="no-secrets">{t('secrets.noEntriesDb')}</p>
        )}
      </section>

      <section className="secrets-pipelines-section">
        <h3 className="section-title">{t('secrets.inPipelineJson')}</h3>
        <p className="secrets-pipelines-hint">
          {t('secrets.envKeysFromPipelines')}
        </p>
        {fromPipelines && fromPipelines.length > 0 ? (
          <table className="secrets-table">
            <thead>
              <tr>
                <th>{t('secrets.key')}</th>
                <th>{t('secrets.pipeline')}</th>
                <th>{t('secrets.source')}</th>
              </tr>
            </thead>
            <tbody>
              {fromPipelines.map((row, idx) => (
                <tr key={`${row.pipeline}-${row.key}-${row.run_config_id || ''}-${idx}`}>
                  <td>{row.key}</td>
                  <td>
                    {row.pipeline}
                    {row.run_config_id && (
                      <span className="run-config-badge" title={t('secrets.runConfigBadgeTitle')}>
                        {row.run_config_id}
                      </span>
                    )}
                  </td>
                  <td>
                    <span className={`type-badge ${row.source === 'encrypted_env' ? 'secret' : 'parameter'}`}>
                      {row.source === 'encrypted_env' ? 'encrypted_env' : 'default_env'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="no-secrets">{t('secrets.noEntriesPipeline')}</p>
        )}
      </section>
    </div>
  )
}
