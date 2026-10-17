import { useEffect, useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { getCurrentUser, logoutUser } from './api/authApi'
import AppShell from './components/layout/AppShell'
import PermissionGuard from './components/PermissionGuard'
import { AuthProvider } from './context/AuthContext'
import AuditTrail from './pages/AuditTrail'
import Home from './pages/Home'
import LoginPage from './pages/LoginPage'
import ModuleDashboard from './pages/ModuleDashboard'
import NotFound from './pages/NotFound'
import Users from './pages/Users'
import {
  flushPendingUiEvents,
  logUiAction,
  setActionLogUser,
} from './utils/actionLogger'

function App() {
  const [loggedInUser, setLoggedInUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)

  useEffect(() => {
    let active = true
    getCurrentUser()
      .then((user) => {
        if (!active) return
        if (user) {
          setActionLogUser(user)
          setLoggedInUser(user)
          flushPendingUiEvents()
        }
      })
      .finally(() => {
        if (active) setAuthLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const handleLogin = (user) => {
    setActionLogUser(user)
    setLoggedInUser(user)
    flushPendingUiEvents()
    logUiAction('Session', 'Session Established', { username: user.username })
  }

  const handleLogout = async () => {
    await logoutUser()
    setActionLogUser(null)
    setLoggedInUser(null)
  }

  if (authLoading) {
    return (
      <div className="auth-splash">
        <div className="auth-splash-inner">
          <span className="spinner" aria-hidden="true" />
          Checking your session…
        </div>
      </div>
    )
  }

  if (!loggedInUser) {
    return <LoginPage onLogin={handleLogin} />
  }

  return (
    <AuthProvider value={{ loggedInUser }}>
      <BrowserRouter>
        <AppShell loggedInUser={loggedInUser} onLogout={handleLogout}>
          <Routes>
            <Route
              path="/"
              element={
                <PermissionGuard
                  loggedInUser={loggedInUser}
                  requiredPermission="View System Dashboard"
                >
                  <Home />
                </PermissionGuard>
              }
            />
            <Route
              path="/users"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="View User">
                  <Users />
                </PermissionGuard>
              }
            />
            <Route
              path="/audit"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="View Audit Log">
                  <AuditTrail />
                </PermissionGuard>
              }
            />
            <Route path="/modules/:moduleKey" element={<ModuleDashboard />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AppShell>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
