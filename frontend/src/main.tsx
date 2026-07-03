import './i18n'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import { initPostHog } from './utils/posthog'
import ErrorBoundary from './components/ErrorBoundary'
import './index.css'

function bootstrap(): void {
  const el = document.getElementById('root')
  if (!el) return
  ReactDOM.createRoot(el).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  )
  // Telemetrie außerhalb des kritischen Render-Pfads initialisieren (fire-and-forget):
  // weder der Status-Fetch noch posthog-js blockieren so den ersten Paint.
  void initPostHog()
}

bootstrap()
