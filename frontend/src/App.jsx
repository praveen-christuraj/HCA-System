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
import Locations from './pages/Locations'
import RoleLocations from './pages/RoleLocations'
import RolePermissions from './pages/RolePermissions'
import Roles from './pages/Roles'
import UserRoles from './pages/UserRoles'
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
                  requiredPermission="dashboard:read"
                >
                  <Home />
                </PermissionGuard>
              }
            />
              <Route
              path="/users"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="users:read">
                  <Users />
                </PermissionGuard>
              }
            />
            <Route
              path="/roles"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="roles:read">
                  <Roles />
                </PermissionGuard>
              }
            />
            <Route
              path="/locations"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="locations:read">
                  <Locations />
                </PermissionGuard>
              }
            />
            <Route
              path="/role-permissions"
              element={
                <PermissionGuard loggedInUser={loggedInUser} allOfPermissions={["roles:read", "permissions:read"]}>
                  <RolePermissions />
                </PermissionGuard>
              }
            />
            <Route
              path="/role-locations"
              element={
                <PermissionGuard loggedInUser={loggedInUser} allOfPermissions={["roles:read", "locations:read"]}>
                  <RoleLocations />
                </PermissionGuard>
              }
            />
            <Route
              path="/user-roles"
              element={
                <PermissionGuard loggedInUser={loggedInUser} allOfPermissions={["users:read", "roles:read"]}>
                  <UserRoles />
                </PermissionGuard>
              }
            />
            <Route
              path="/audit"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="audit:read">
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
