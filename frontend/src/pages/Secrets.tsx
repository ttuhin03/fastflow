import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useAuth } from '../contexts/AuthContext'
import apiClient from '../api/client'
import { showError, showSuccess } from '../utils/toast'
import Tooltip from '../components/Tooltip'
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
      showSuccess('Wert verschlüsselt. In pipeline.json unter encrypted_env eintragen.')
    },
    onError: (error: any) => {
      showError(`Verschlüsselung fehlgeschlagen: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleCopyEncrypted = async () => {
    if (!encryptResult) return
    try {
      await navigator.clipboard.writeText(encryptResult)
      showSuccess('Verschlüsselten Wert in Zwischenablage kopiert')
    } catch {
      showError('Kopieren fehlgeschlagen')
    }
  }

  const toggleShowValue = (key: string) => {
    setShowValues((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  if (isLoading) {
    return <div>Laden...</div>
  }

  return (
    <div className="secrets">
      <div className="secrets-header">
        <h2>Secrets & Parameter</h2>
      </div>
      <p className="secrets-readonly-hint">
        Secrets kommen aus der Datenbank oder aus pipeline.json (<code>encrypted_env</code> / <code>default_env</code>). Unten siehst du beides: DB-Einträge und Keys, die in Pipelines verwendet werden.
      </p>

      {!isReadonly && (
        <div className="encrypt-for-pipeline-section card">
          <h3 className="section-title">Für pipeline.json verschlüsseln</h3>
          <p className="encrypt-hint">
            Klartext eingeben, verschlüsseln lassen und den Ciphertext manuell in die pipeline.json unter <code>encrypted_env.&lt;KEY&gt;</code> eintragen.
          </p>
          <div className="form-group">
            <label htmlFor="encrypt-plaintext" className="form-label">Klartext</label>
            <textarea
              id="encrypt-plaintext"
              className="form-input"
              value={encryptPlaintext}
              onChange={(e) => {
                setEncryptPlaintext(e.target.value)
                setEncryptResult(null)
              }}
              rows={3}
              placeholder="Geheimer Wert, der verschlüsselt werden soll"
            />
          </div>
          <div className="form-actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!encryptPlaintext || encryptForPipelineMutation.isPending}
              onClick={() => encryptForPipelineMutation.mutate(encryptPlaintext)}
            >
              {encryptForPipelineMutation.isPending ? 'Verschlüsseln…' : 'Verschlüsseln'}
            </button>
          </div>
          {encryptResult && (
            <div className="encrypt-result">
              <label className="form-label">Verschlüsselter Wert (in pipeline.json eintragen)</label>
              <div className="encrypt-result-row">
                <textarea
                  readOnly
                  value={encryptResult}
                  rows={2}
                  className="form-input encrypt-result-value"
                />
                <button type="button" className="btn btn-secondary" onClick={handleCopyEncrypted}>
                  Kopieren
                </button>
              </div>
              <p className="encrypt-result-hint">
                In pipeline.json unter <code>encrypted_env</code> eintragen, z. B.: <code>&quot;KEY&quot;: &quot;&lt;Ciphertext hier&gt;&quot;</code>
              </p>
            </div>
          )}
        </div>
      )}

      <section className="secrets-db-section">
        <h3 className="section-title">In Datenbank</h3>
        {secrets && secrets.length > 0 ? (
          <table className="secrets-table">
            <thead>
              <tr>
                <th>Key</th>
                <th>Type</th>
                <th>Value</th>
                <th>Erstellt</th>
                <th>Aktualisiert</th>
              </tr>
            </thead>
            <tbody>
              {secrets.map((secret) => (
                <tr key={secret.key}>
                  <td>{secret.key}</td>
                  <td>
                    <Tooltip content={secret.is_parameter 
                      ? "Nicht verschlüsselt, für Konfiguration"
                      : "Verschlüsselt gespeichert"}>
                      <span className={`type-badge ${secret.is_parameter ? 'parameter' : 'secret'}`}>
                        {secret.is_parameter ? 'Parameter' : 'Secret'}
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
                      <Tooltip content="Tippen, um den Wert anzuzeigen/zu verbergen">
                        <button
                          onClick={() => toggleShowValue(secret.key)}
                          className="toggle-button"
                        >
                          {showValues[secret.key] ? 'Verbergen' : 'Anzeigen'}
                        </button>
                      </Tooltip>
                    </div>
                  </td>
                  <td>{new Date(secret.created_at).toLocaleString('de-DE')}</td>
                  <td>{new Date(secret.updated_at).toLocaleString('de-DE')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="no-secrets">Keine Einträge in der Datenbank</p>
        )}
      </section>

      <section className="secrets-pipelines-section">
        <h3 className="section-title">In pipeline.json verwendet</h3>
        <p className="secrets-pipelines-hint">
          Env-Keys aus <code>encrypted_env</code> und <code>default_env</code> aller Pipelines (Werte werden hier nicht angezeigt).
        </p>
        {fromPipelines && fromPipelines.length > 0 ? (
          <table className="secrets-table">
            <thead>
              <tr>
                <th>Key</th>
                <th>Pipeline</th>
                <th>Quelle</th>
              </tr>
            </thead>
            <tbody>
              {fromPipelines.map((row, idx) => (
                <tr key={`${row.pipeline}-${row.key}-${row.run_config_id || ''}-${idx}`}>
                  <td>{row.key}</td>
                  <td>
                    {row.pipeline}
                    {row.run_config_id && (
                      <span className="run-config-badge" title="Run-Konfiguration (schedules[].id)">
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
          <p className="no-secrets">Keine Env-Keys in pipeline.json gefunden</p>
        )}
      </section>
    </div>
  )
}
