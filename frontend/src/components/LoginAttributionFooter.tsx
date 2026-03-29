import { useUiPreferences } from '../contexts/UiPreferencesContext'

/** Footer line for login-style pages: attribution + build version (both optional via Settings). */
export default function LoginAttributionFooter() {
  const { showAttribution, showVersion } = useUiPreferences()
  if (!showAttribution && !showVersion) return null
  return (
    <p className="login-footer-text">
      {showAttribution && (
        <>
          Made with <span className="heart">❤️</span> by <strong>ttuhin03</strong>
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
