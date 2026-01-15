import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Pipelines from './pages/Pipelines'
import PipelineDetail from './pages/PipelineDetail'
import Runs from './pages/Runs'
import RunDetail from './pages/RunDetail'
import Scheduler from './pages/Scheduler'
import Secrets from './pages/Secrets'
import Sync from './pages/Sync'
import Settings from './pages/Settings'
import Layout from './components/Layout'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import './App.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
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
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
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
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

export default App
