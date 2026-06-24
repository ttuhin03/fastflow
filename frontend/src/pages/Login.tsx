import { useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { LuCode } from 'react-icons/lu'
import Tooltip from '../components/Tooltip'
import LoginAttributionFooter from '../components/LoginAttributionFooter'
import LoginGameOfLifeBackground from '../components/LoginGameOfLifeBackground'
import { useUiPreferences } from '../contexts/UiPreferencesContext'
import { getApiOrigin } from '../config'
import { useAuthProviders, type ProviderId } from '../hooks/useAuthProviders'
import './Login.css'

export default function Login() {
  const { t } = useTranslation()
  const videoRef = useRef<HTMLVideoElement>(null)
  const { loginBackground } = useUiPreferences()
  const { providers, orderedProviderIds } = useAuthProviders()

  useEffect(() => {
    if (videoRef.current && loginBackground === 'video') {
      videoRef.current.playbackRate = 0.5
    }
  }, [loginBackground])

  const handleGitHubLogin = () => {
    if (providers.github) window.location.href = `${getApiOrigin()}/api/auth/github/authorize`
  }

  const handleGoogleLogin = () => {
    if (providers.google) window.location.href = `${getApiOrigin()}/api/auth/google/authorize`
  }

  const handleMicrosoftLogin = () => {
    if (providers.microsoft) window.location.href = `${getApiOrigin()}/api/auth/microsoft/authorize`
  }

  const handleCustomLogin = () => {
    if (providers.custom) window.location.href = `${getApiOrigin()}/api/auth/custom/authorize`
  }

  const wrapIfUnavailable = (enabled: boolean | undefined, content: React.ReactNode) =>
    enabled === false ? (
      <Tooltip content={t('auth.providerUnavailable')} position="top">
        {content}
      </Tooltip>
    ) : (
      content
    )

  const renderProvider = (id: ProviderId) => {
    switch (id) {
      case 'github':
        return wrapIfUnavailable(
          providers.github,
          <button
            type="button"
            onClick={handleGitHubLogin}
            disabled={providers.github === false}
            className={`login-btn login-btn-github${providers.github === false ? ' login-btn-unconfigured' : ''}`}
            aria-label={providers.github ? t('auth.signInGitHub') : t('auth.githubNotConfigured')}
          >
            <svg className="login-btn-github-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
            </svg>
            {t('auth.signInGitHub')}
          </button>
        )
      case 'google':
        return wrapIfUnavailable(
          providers.google,
          <button
            type="button"
            onClick={handleGoogleLogin}
            disabled={providers.google === false}
            className={`login-btn login-btn-google${providers.google === false ? ' login-btn-unconfigured' : ''}`}
            aria-label={providers.google ? t('auth.signInGoogle') : t('auth.googleNotConfigured')}
          >
            <svg className="login-btn-google-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            {t('auth.signInGoogle')}
          </button>
        )
      case 'microsoft':
        return wrapIfUnavailable(
          providers.microsoft,
          <button
            type="button"
            onClick={handleMicrosoftLogin}
            disabled={providers.microsoft === false}
            className={`login-btn login-btn-microsoft${providers.microsoft === false ? ' login-btn-unconfigured' : ''}`}
            aria-label={providers.microsoft ? t('auth.signInMicrosoft') : t('auth.microsoftNotConfigured')}
          >
            <svg className="login-btn-microsoft-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
              <path d="M11.4 24H0V12.6h11.4V24zM24 24H12.6V12.6H24V24zM11.4 11.4H0V0h11.4v11.4zm12.6 0H12.6V0H24v11.4z" />
            </svg>
            {t('auth.signInMicrosoft')}
          </button>
        )
      case 'custom':
        return wrapIfUnavailable(
          providers.custom,
          <button
            type="button"
            onClick={handleCustomLogin}
            disabled={providers.custom === false}
            className={`login-btn login-btn-custom${providers.custom === false ? ' login-btn-unconfigured' : ''}`}
            aria-label={
              providers.custom
                ? t('auth.signInNamedProvider', {
                    name: providers.custom_display_name || t('auth.customProviderFallback'),
                  })
                : t('auth.customNotConfigured')
            }
          >
            {providers.custom_oauth_icon_url ? (
              <img
                src={providers.custom_oauth_icon_url}
                alt=""
                className="login-btn-custom-icon"
                loading="lazy"
                decoding="async"
              />
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <rect x="3" y="11" width="18" height="11" rx="2"/>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              </svg>
            )}
            {providers.custom
              ? t('auth.signInNamedProvider', {
                  name: providers.custom_display_name || t('auth.customProviderFallback'),
                })
              : t('auth.signInCustom')}
          </button>
        )
      default:
        return null
    }
  }

  const standardIds = orderedProviderIds.filter((id): id is 'github' | 'google' | 'microsoft' => id !== 'custom')
  const hasCustom = orderedProviderIds.includes('custom')
  const showDivider = standardIds.length > 0 && hasCustom

  return (
    <div className="login-container login-container--split">

      {/* Animated background (kept by design decision) — sits behind the brand panel */}
      <div className="login-background" aria-hidden="true">
        {loginBackground === 'video' ? (
          <video
            ref={videoRef}
            className="login-background-video"
            autoPlay
            loop
            muted
            playsInline
          >
            <source src="/background.mp4" type="video/mp4" />
          </video>
        ) : (
          <LoginGameOfLifeBackground />
        )}
        <div className="login-background-mesh" aria-hidden />
        <div className="login-background-overlay" />
      </div>

      {/* LEFT: Brand Panel */}
      <div className="login-brand" aria-hidden="true">
        <div className="login-brand-grid" />

        <div className="login-brand-logo">
          <div className="login-brand-mark">
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 5l5 7-5 7"/>
              <path d="M13 12h6"/>
            </svg>
          </div>
          <span className="login-brand-name">FastFlow</span>
        </div>

        <div className="login-brand-body">
          <h1 className="login-brand-headline">{t('auth.brandHeadline')}</h1>
          <p className="login-brand-sub">{t('auth.brandSub')}</p>
          <div className="login-brand-stats">
            <div className="login-brand-stat">
              <div className="login-brand-stat__value">{t('auth.brandStatOneValue', 'Container-native')}</div>
              <div className="login-brand-stat__label">{t('auth.brandStatOneLabel', 'Execution model')}</div>
            </div>
            <div className="login-brand-stat__divider" />
            <div className="login-brand-stat">
              <div className="login-brand-stat__value">{t('auth.brandStatTwoValue', 'Git-synced')}</div>
              <div className="login-brand-stat__label">{t('auth.brandStatTwoLabel', 'Pipeline definitions')}</div>
            </div>
          </div>
        </div>

        <div className="login-brand-version">
          <LuCode size={13} />
          <span>container-native · open source</span>
        </div>
      </div>

      {/* RIGHT: Auth Panel */}
      <div className="login-content">
        <div className="login-card">
          {providers.login_branding_logo_url ? (
            <div className="login-branding-logo-wrap">
              <img
                src={providers.login_branding_logo_url}
                alt=""
                className="login-branding-logo"
                loading="lazy"
                decoding="async"
              />
            </div>
          ) : null}

          <div className="login-header">
            <h2 className="login-welcome">{t('auth.welcomeBack')}</h2>
            <p className="login-subtitle">{t('auth.signInWorkspace')}</p>
          </div>

          <div className="login-form login-form-oauth">
            {standardIds.map((id) => (
              <div
                key={id}
                className={`login-provider-row${providers[id] === true ? ' login-provider-row--active' : ' login-provider-row--inactive'}`}
              >
                {renderProvider(id)}
              </div>
            ))}

            {showDivider && (
              <div className="login-divider" role="presentation">
                <span>{t('auth.orSeparator')}</span>
              </div>
            )}

            {hasCustom && (
              <div className={`login-provider-row${providers.custom === true ? ' login-provider-row--active' : ' login-provider-row--inactive'}`}>
                {renderProvider('custom')}
              </div>
            )}
          </div>

          <p className="login-request-access">
            {t('auth.noAccountYet', 'No account yet?')}{' '}
            <span className="login-request-access__hint">
              {t('auth.requestAccessHint', 'Sign in with a provider to request access.')}
            </span>
          </p>
        </div>

        <div className="login-footer">
          <a
            href="https://github.com/ttuhin03/fastflow"
            target="_blank"
            rel="noopener noreferrer"
            className="github-link"
            aria-label={t('auth.viewOnGitHub')}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" style={{ flexShrink: 0 }}>
              <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
            </svg>
            <span>{t('auth.viewOnGitHub')}</span>
          </a>
          <LoginAttributionFooter />
        </div>
      </div>
    </div>
  )
}
