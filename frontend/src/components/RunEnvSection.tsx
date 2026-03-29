import { useTranslation } from 'react-i18next'

interface RunEnvSectionProps {
  envVars: Record<string, string>
  parameters: Record<string, string>
}

/**
 * Zeigt Environment-Variablen und Parameter eines Runs.
 * Hinweis: Werte für Secrets können serverseitig redigiert werden (***).
 */
export function RunEnvSection({ envVars, parameters }: RunEnvSectionProps) {
  const { t } = useTranslation()
  const hasEnv = Object.keys(envVars || {}).length > 0
  const hasParams = Object.keys(parameters || {}).length > 0

  return (
    <div className="env-container">
      {hasEnv && (
        <div className="run-info-card">
          <h3>{t('runEnv.envVars')}</h3>
          <p className="env-vars-note">
            {t('runEnv.secretsNote')}
          </p>
          <div className="env-vars">
            {Object.entries(envVars).map(([key, value]) => (
              <div key={key} className="env-var">
                <span className="env-key">{key}:</span>
                <span className="env-value">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasParams && (
        <div className="run-info-card">
          <h3>{t('runEnv.parameters')}</h3>
          <div className="parameters">
            {Object.entries(parameters).map(([key, value]) => (
              <div key={key} className="parameter">
                <span className="param-key">{key}:</span>
                <span className="param-value">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!hasEnv && !hasParams && (
        <div className="run-info-card">
          <p className="no-env-vars">{t('runEnv.none')}</p>
        </div>
      )}
    </div>
  )
}
