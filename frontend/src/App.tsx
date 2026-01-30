import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import Login from './pages/Login'
import Invite from './pages/Invite'
import AuthCallback from './pages/AuthCallback'
import RequestSent from './pages/RequestSent'
import RequestRejected from './pages/RequestRejected'
import AccountBlocked from './pages/AccountBlocked'
import Dashboard from './pages/Dashboard'
import Pipelines from './pages/Pipelines'
import PipelineDetail from './pages/PipelineDetail'
import Runs from './pages/Runs'
import RunDetail from './pages/RunDetail'
import Scheduler from './pages/Scheduler'
import Secrets from './pages/Secrets'
import Sync from './pages/Sync'
import Settings from './pages/Settings'
import Users from './pages/Users'
import Dependencies from './pages/Dependencies'
import Layout from './components/Layout'
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

  if (loading) {
    return <div>Laden...</div>
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function AppRoutes() {
  useRunNotifications()
  useBackupFailurePolling()

  return (
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
        <Route path="runs" element={<Runs />} />
        <Route path="runs/:runId" element={<RunDetail />} />
        <Route path="scheduler" element={<Scheduler />} />
        <Route path="secrets" element={<Secrets />} />
        <Route path="sync" element={<Sync />} />
        <Route path="dependencies" element={<Dependencies />} />
        <Route path="settings" element={<Settings />} />
        <Route path="users" element={<Users />} />
      </Route>
    </Routes>
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
                background: '#2a2a2a',
                color: '#fff',
                border: '1px solid #444',
              },
              success: {
                iconTheme: {
                  primary: '#4caf50',
                  secondary: '#fff',
                },
              },
              error: {
                iconTheme: {
                  primary: '#f44336',
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
