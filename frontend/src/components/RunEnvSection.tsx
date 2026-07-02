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

  // Heuristic: redacted values (***) are secrets; everything else is plain
  const kindOf = (value: string): 'secret' | 'plain' =>
    /^\*+$/.test(value.trim()) || value.includes('***') ? 'secret' : 'plain'

  return (
    <div className="env-container">
      {hasEnv && (
        <div className="env-card">
          <div className="env-card-head">
            <h3>{t('runEnv.envVars')}</h3>
            <p className="env-vars-note">{t('runEnv.secretsNote')}</p>
          </div>
          <div className="env-grid">
            {Object.entries(envVars).map(([key, value]) => (
              <div key={key} className="env-row">
                <span className="env-key mono">{key}</span>
                <span className="env-value mono">{value}</span>
                <span className={`env-kind env-kind-${kindOf(value)}`}>{kindOf(value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasParams && (
        <div className="env-card">
          <div className="env-card-head">
            <h3>{t('runEnv.parameters')}</h3>
          </div>
          <div className="env-grid">
            {Object.entries(parameters).map(([key, value]) => (
              <div key={key} className="env-row">
                <span className="env-key mono">{key}</span>
                <span className="env-value mono">{value}</span>
                <span className="env-kind env-kind-param">{t('runEnv.paramKind', 'param')}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!hasEnv && !hasParams && (
        <div className="env-card">
          <p className="no-env-vars">{t('runEnv.none')}</p>
        </div>
      )}
    </div>
  )
}
