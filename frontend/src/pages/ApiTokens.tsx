import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { LuKey, LuCopy, LuTrash2, LuTriangleAlert, LuCheck } from 'react-icons/lu'
import apiClient from '../api/client'
import { showError, showSuccess, showConfirm } from '../utils/toast'
import { formatDateTime, formatRelativeTime } from '../utils/locale'
import { getErrorDetail } from '../utils/apiError'
import { useAuth } from '../contexts/AuthContext'
import Tooltip from '../components/Tooltip'
import './ApiTokens.css'

/** Scope-Werte des Backends (app.models.ApiTokenScope). */
type Scope = 'read' | 'logs' | 'source' | 'run'

/** Risikoklasse je Scope – steuert die farbliche Kennzeichnung in der UI. */
const SCOPE_RISK: Record<Scope, 'low' | 'medium' | 'high'> = {
  read: 'low',
  logs: 'medium',
  source: 'medium',
  run: 'high',
}

interface ApiTokenItem {
  id: string
  label: string
  prefix: string
  scopes: string[]
  created_at: string
  expires_at: string
  last_used_at: string | null
  revoked_at: string | null
  expired: boolean
  username: string | null
}

interface ApiTokenListResponse {
  tokens: ApiTokenItem[]
  available_scopes: string[]
  max_expiry_days: number
  default_expiry_days: number
}

interface CreatedToken {
  token: string
  id: string
  label: string
  prefix: string
  scopes: string[]
  expires_at: string
}

/**
 * Zeitstempel-Zelle: relative Angabe sichtbar, exakte Zeit im Tooltip.
 *
 * formatDateTime/formatRelativeTime liefern null für nicht parsebare Werte –
 * ohne diese Abfrage entstünde ein Tooltip mit leerem Inhalt.
 */
function TimestampCell({ value, fallback }: Readonly<{ value?: string | null; fallback: string }>) {
  const exact = formatDateTime(value)
  const relative = formatRelativeTime(value)
  if (!exact || !relative) {
    return <span className="api-tokens-state">{fallback}</span>
  }
  return (
    <Tooltip content={exact}>
      <span>{relative}</span>
    </Tooltip>
  )
}

/**
 * Zustandsspalte eines Tokens: Widerruf und Ablauf verdrängen das Ablaufdatum.
 *
 * Die drei Fälle schließen einander aus und stehen deshalb als Frühausstiege
 * untereinander – als verschachteltes Ternär in der Tabelle ließ sich ihre
 * Reihenfolge nicht mehr auf einen Blick lesen.
 */
function TokenStateCell({ token }: Readonly<{ token: ApiTokenItem }>) {
  const { t } = useTranslation()
  if (token.revoked_at) {
    return <span className="api-tokens-state">{t('apiTokens.stateRevoked')}</span>
  }
  if (token.expired) {
    return <span className="api-tokens-state">{t('apiTokens.stateExpired')}</span>
  }
  return <TimestampCell value={token.expires_at} fallback="–" />
}

export default function ApiTokens() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { isAdmin } = useAuth()

  const [includeRevoked, setIncludeRevoked] = useState(false)
  const [label, setLabel] = useState('')
  const [selectedScopes, setSelectedScopes] = useState<Scope[]>(['read'])
  const [expiresInDays, setExpiresInDays] = useState(90)
  /**
   * Der Klartext des frisch erzeugten Tokens. Existiert ausschließlich hier im
   * Komponenten-State: das Backend speichert nur den Digest, und ein Reload
   * lässt ihn bewusst verschwinden.
   */
  const [created, setCreated] = useState<CreatedToken | null>(null)

  const { data, isLoading, isError } = useQuery<ApiTokenListResponse>({
    queryKey: ['api-tokens', includeRevoked],
    queryFn: async () => {
      const response = await apiClient.get<ApiTokenListResponse>('/tokens', {
        params: { include_revoked: includeRevoked },
      })
      return response.data
    },
  })

  const availableScopes = (data?.available_scopes ?? []) as Scope[]
  const maxExpiryDays = data?.max_expiry_days ?? 365

  const createMutation = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<CreatedToken>('/tokens', {
        label: label.trim(),
        scopes: selectedScopes,
        expires_in_days: expiresInDays,
      })
      return response.data
    },
    onSuccess: (token) => {
      queryClient.invalidateQueries({ queryKey: ['api-tokens'] })
      setCreated(token)
      setLabel('')
      setSelectedScopes(['read'])
      showSuccess(t('apiTokens.created'))
    },
    onError: (error) => {
      showError(getErrorDetail(error) || t('apiTokens.createError'))
    },
  })

  const revokeMutation = useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`/tokens/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-tokens'] })
      showSuccess(t('apiTokens.revoked'))
    },
    onError: (error) => {
      showError(getErrorDetail(error) || t('apiTokens.revokeError'))
    },
  })

  const toggleScope = (scope: Scope) => {
    setSelectedScopes((current) =>
      current.includes(scope) ? current.filter((s) => s !== scope) : [...current, scope]
    )
  }

  const handleRevoke = async (token: ApiTokenItem) => {
    const confirmed = await showConfirm(t('apiTokens.revokeConfirm', { label: token.label }))
    if (confirmed) revokeMutation.mutate(token.id)
  }

  const copyToken = async () => {
    if (!created) return
    try {
      await navigator.clipboard.writeText(created.token)
      showSuccess(t('apiTokens.copied'))
    } catch {
      // Clipboard kann ohne sicheren Kontext oder Nutzerfreigabe fehlschlagen –
      // das Token steht weiterhin sichtbar zum manuellen Kopieren bereit.
      showError(t('apiTokens.copyFailed'))
    }
  }

  const canSubmit =
    label.trim().length > 0 &&
    selectedScopes.length > 0 &&
    expiresInDays >= 1 &&
    expiresInDays <= maxExpiryDays &&
    !createMutation.isPending

  return (
    <div className="api-tokens-page">
      <p className="api-tokens-intro">{t('apiTokens.intro')}</p>

      {created && (
        <div className="api-tokens-reveal" role="alert">
          <div className="api-tokens-reveal-header">
            <LuTriangleAlert aria-hidden="true" />
            <strong>{t('apiTokens.shownOnceTitle')}</strong>
          </div>
          <p className="api-tokens-reveal-hint">{t('apiTokens.shownOnceHint')}</p>
          <div className="api-tokens-reveal-row">
            <code className="api-tokens-reveal-code">{created.token}</code>
            <button type="button" className="btn btn-secondary btn-sm" onClick={copyToken}>
              <LuCopy /> {t('apiTokens.copy')}
            </button>
          </div>
          <button
            type="button"
            className="btn btn-primary btn-sm api-tokens-reveal-dismiss"
            onClick={() => setCreated(null)}
          >
            <LuCheck /> {t('apiTokens.storedIt')}
          </button>
        </div>
      )}

      <form
        className="api-tokens-form"
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit) createMutation.mutate()
        }}
      >
        <h3 className="api-tokens-form-title">{t('apiTokens.newTokenTitle')}</h3>

        <div className="api-tokens-field">
          <label htmlFor="api-token-label" className="setting-label">
            {t('apiTokens.labelField')}
          </label>
          <input
            id="api-token-label"
            type="text"
            className="form-input"
            maxLength={100}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t('apiTokens.labelPlaceholder')}
            required
          />
        </div>

        <fieldset className="api-tokens-field api-tokens-scopes">
          <legend className="setting-label">{t('apiTokens.scopesField')}</legend>
          {availableScopes.map((scope) => (
            <label key={scope} className="api-tokens-scope" htmlFor={`scope-${scope}`}>
              {/*
                Der Name der Checkbox ist der Scope selbst, Risiko und Erklärung
                hängen als Beschreibung daran. Ohne aria-label wäre der Name der
                gesamte Fließtext der Zeile ("run hoch Runs starten, abbrechen
                …") – vorgelesen bei jedem Fokuswechsel und nicht mehr von den
                anderen Zeilen zu unterscheiden.
              */}
              <input
                id={`scope-${scope}`}
                type="checkbox"
                checked={selectedScopes.includes(scope)}
                onChange={() => toggleScope(scope)}
                aria-label={scope}
                aria-describedby={`scope-${scope}-risk scope-${scope}-desc`}
              />
              <span className="api-tokens-scope-body">
                <span className="api-tokens-scope-head">
                  <code className="api-tokens-scope-name">{scope}</code>
                  <span
                    id={`scope-${scope}-risk`}
                    className={`api-tokens-risk api-tokens-risk--${SCOPE_RISK[scope]}`}
                  >
                    {t(`apiTokens.risk.${SCOPE_RISK[scope]}`)}
                  </span>
                </span>
                <span id={`scope-${scope}-desc`} className="api-tokens-scope-desc">
                  {t(`apiTokens.scopeDesc.${scope}`)}
                </span>
              </span>
            </label>
          ))}
          {availableScopes.length === 0 && !isLoading && (
            <p className="setting-hint">{t('apiTokens.noScopes')}</p>
          )}
        </fieldset>

        <div className="api-tokens-field api-tokens-field--narrow">
          <label htmlFor="api-token-expiry" className="setting-label">
            {t('apiTokens.expiryField')}
          </label>
          <input
            id="api-token-expiry"
            type="number"
            className="form-input"
            min={1}
            max={maxExpiryDays}
            value={expiresInDays}
            onChange={(e) => setExpiresInDays(Number(e.target.value))}
          />
          <span className="setting-hint">{t('apiTokens.expiryHint', { max: maxExpiryDays })}</span>
        </div>

        <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
          <LuKey /> {t('apiTokens.createButton')}
        </button>
      </form>

      <div className="api-tokens-list-header">
        <h3 className="api-tokens-form-title">{t('apiTokens.existingTitle')}</h3>
        <label className="api-tokens-toggle" htmlFor="api-tokens-include-revoked">
          <input
            id="api-tokens-include-revoked"
            type="checkbox"
            checked={includeRevoked}
            onChange={(e) => setIncludeRevoked(e.target.checked)}
          />
          {t('apiTokens.showRevoked')}
        </label>
      </div>

      {isLoading && <p className="setting-hint">{t('common.loading')}</p>}
      {isError && <p className="setting-hint">{t('apiTokens.loadError')}</p>}

      {!isLoading && !isError && (data?.tokens.length ?? 0) === 0 && (
        <p className="setting-hint">{t('apiTokens.empty')}</p>
      )}

      {!isLoading && !isError && (data?.tokens.length ?? 0) > 0 && (
        <div className="api-tokens-table-wrap">
          <table className="settings-table settings-table--full api-tokens-table">
            <thead>
              <tr>
                <th>{t('apiTokens.colLabel')}</th>
                {isAdmin && <th>{t('apiTokens.colOwner')}</th>}
                <th>{t('apiTokens.colScopes')}</th>
                <th>{t('apiTokens.colExpires')}</th>
                <th>{t('apiTokens.colLastUsed')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data?.tokens.map((token) => {
                const inactive = token.expired || Boolean(token.revoked_at)
                return (
                  <tr
                    key={token.id}
                    className={inactive ? 'api-tokens-row--inactive' : undefined}
                  >
                    <td>
                      <span className="api-tokens-label">{token.label}</span>
                      <code className="api-tokens-prefix">ffp_{token.prefix}…</code>
                    </td>
                    {isAdmin && <td>{token.username ?? '–'}</td>}
                    <td>
                      <span className="api-tokens-scope-chips">
                        {token.scopes.map((scope) => (
                          <span
                            key={scope}
                            className={`api-tokens-risk api-tokens-risk--${
                              SCOPE_RISK[scope as Scope] ?? 'low'
                            }`}
                          >
                            {scope}
                          </span>
                        ))}
                      </span>
                    </td>
                    <td>
                      <TokenStateCell token={token} />
                    </td>
                    <td>
                      <TimestampCell
                        value={token.last_used_at}
                        fallback={t('apiTokens.neverUsed')}
                      />
                    </td>
                    <td>
                      {!token.revoked_at && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleRevoke(token)}
                          disabled={revokeMutation.isPending}
                        >
                          <LuTrash2 /> {t('apiTokens.revoke')}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
