import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import './App.css'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { Sidebar } from './components/Sidebar'
import { IntegrationSettingsPage } from './pages/IntegrationSettingsPage'
import { LoginPage } from './pages/LoginPage'
import { WebinarDetailPage } from './pages/WebinarDetailPage'
import { WebinarListPage } from './pages/WebinarListPage'
import { ViewerPage } from './pages/ViewerPage'

function AdminLayout() {
  const { tenant, signOut } = useAuth()
  if (!tenant) return <Navigate to="/login" replace />
  return (
    <div className="admin-shell">
      <Sidebar tenant={tenant} onLogout={signOut} />
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}

function RequireAuth() {
  const { tenant, checking } = useAuth()
  if (checking) return <div className="session-loading">セッションを確認中…</div>
  return tenant ? <Outlet /> : <Navigate to="/login" replace />
}

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/watch/:id" element={<ViewerPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<AdminLayout />}>
            <Route path="/" element={<WebinarListPage />} />
            <Route path="/webinars/:id" element={<WebinarDetailPage />} />
            <Route path="/settings/integrations" element={<IntegrationSettingsPage />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  )
}

export default App
