import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import ErrorBoundary from './components/ErrorBoundary'
import './i18n'
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
}

bootstrap()
