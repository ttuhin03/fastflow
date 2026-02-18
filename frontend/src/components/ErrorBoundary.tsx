import { Component, ErrorInfo, ReactNode } from 'react'
import { withTranslation, WithTranslation } from 'react-i18next'
import { captureException } from '../utils/posthog'

interface Props extends WithTranslation {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

/**
 * Fängt React-Render-Fehler, sendet sie an PostHog (wenn Phase 2a aktiv) und zeigt Fallback.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    captureException(error, {
      $react_error_boundary: true,
      componentStack: info.componentStack || undefined,
    })
  }

  render(): ReactNode {
    const { t } = this.props
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) return this.props.fallback
      return (
        <div style={{ padding: '1.5rem', textAlign: 'center', color: '#aaa' }}>
          <p>{t('errors.generic')}</p>
          <button
            type="button"
            onClick={() => this.setState({ hasError: false, error: null })}
            style={{ marginTop: '0.5rem', padding: '0.25rem 0.5rem' }}
          >
            {t('errors.retry')}
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

export default withTranslation()(ErrorBoundary)
