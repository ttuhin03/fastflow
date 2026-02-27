import { Suspense, lazy } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import Layout from './components/Layout'

// Lazy-loaded pages (Code-Splitting für kleinere Initial-Bundles)
const Login = lazy(() => import('./pages/Login'))
const Invite = lazy(() => import('./pages/Invite'))
const AuthCallback = lazy(() => import('./pages/AuthCallback'))
const RequestSent = lazy(() => import('./pages/RequestSent'))
const RequestRejected = lazy(() => import('./pages/RequestRejected'))
const AccountBlocked = lazy(() => import('./pages/AccountBlocked'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Pipelines = lazy(() => import('./pages/Pipelines'))
const PipelineDetail = lazy(() => import('./pages/PipelineDetail'))
const RunDetail = lazy(() => import('./pages/RunDetail'))
const Settings = lazy(() => import('./pages/Settings'))
const Audit = lazy(() => import('./pages/Audit'))
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { NotificationProvider } from './contexts/NotificationContext'
import { useRunNotifications } from './hooks/useRunNotifications'
import { useBackupFailurePolling } from './hooks/useBackupFailurePolling'
import './App.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (failureCount, error: any) => {
        // Don't retry on 401 Unauthorized errors
        if (error?.response?.status === 401) {
          return false
        }
        // Retry once for other errors
        return failureCount < 1
      },
    },
  },
})

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth()
  const { t } = useTranslation()

  if (loading) {
    return <div>{t('common.loading')}</div>
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function PageFallback() {
  const { t } = useTranslation()
  return <div className="loading-fallback">{t('common.loading')}</div>
}

function AppRoutes() {
  useRunNotifications()
  useBackupFailurePolling()

  return (
    <Suspense fallback={<PageFallback />}>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/invite" element={<Invite />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route path="/request-sent" element={<RequestSent />} />
      <Route path="/request-rejected" element={<RequestRejected />} />
      <Route path="/account-blocked" element={<AccountBlocked />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="pipelines" element={<Pipelines />} />
        <Route path="pipelines/:name" element={<PipelineDetail />} />
        <Route path="runs" element={<Navigate to="/pipelines?section=runs" replace />} />
        <Route path="runs/:runId" element={<RunDetail />} />
        <Route path="scheduler" element={<Navigate to="/pipelines?section=scheduler" replace />} />
        <Route path="secrets" element={<Navigate to="/pipelines?section=secrets" replace />} />
        <Route path="sync" element={<Navigate to="/settings?section=git-sync" replace />} />
        <Route path="dependencies" element={<Navigate to="/pipelines?section=dependencies" replace />} />
        <Route path="settings" element={<Settings />} />
        <Route path="users" element={<Navigate to="/settings?section=nutzer" replace />} />
        <Route path="audit" element={<Audit />} />
      </Route>
    </Routes>
    </Suspense>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <NotificationProvider>
          <BrowserRouter>
            <AppRoutes />
            <Toaster
            position="top-right"
            toastOptions={{
              duration: 4000,
              style: {
                background: 'var(--color-surface)',
                color: 'var(--color-text-primary)',
                border: '1px solid color-mix(in srgb, var(--color-border) 60%, transparent)',
                borderRadius: 'var(--radius-lg)',
                boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04), 0 12px 32px rgba(0,0,0,0.3), 0 0 0 1px rgba(0,0,0,0.08)',
              },
              success: {
                iconTheme: {
                  primary: 'var(--color-success)',
                  secondary: '#fff',
                },
              },
              error: {
                iconTheme: {
                  primary: 'var(--color-error)',
                  secondary: '#fff',
                },
              },
            }}
          />
          </BrowserRouter>
        </NotificationProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}

export default App
