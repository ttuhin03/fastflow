import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import { initPostHog } from './utils/posthog'
import { ErrorBoundary } from './components/ErrorBoundary'
import './index.css'

async function bootstrap(): Promise<void> {
  await initPostHog()
  const el = document.getElementById('root')
  if (!el) return
  ReactDOM.createRoot(el).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  )
}

bootstrap()
