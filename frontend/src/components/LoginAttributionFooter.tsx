import { useTranslation } from 'react-i18next'
import { useUiPreferences } from '../contexts/UiPreferencesContext'

const FOOTER_AUTHOR = 'ttuhin03'

/** Footer line for login-style pages: attribution + build version (both optional via Settings). */
export default function LoginAttributionFooter() {
  const { t } = useTranslation()
  const { showAttribution, showVersion } = useUiPreferences()
  if (!showAttribution && !showVersion) return null
  return (
    <p className="login-footer-text">
      {showAttribution && (
        <>
          {t('loginFooter.madeWith')} <span className="heart">❤️</span> {t('loginFooter.by')} <strong>{FOOTER_AUTHOR}</strong>
        </>
      )}
      {showVersion && (
        <span
          style={{
            marginLeft: showAttribution ? '8px' : 0,
            opacity: 0.5,
            fontSize: '10px',
          }}
        >
          v{__APP_VERSION__}
        </span>
      )}
    </p>
  )
}
