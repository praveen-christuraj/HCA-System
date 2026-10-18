import { lazy, Suspense, useEffect, useState } from 'react'
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
import PermissionPresets from './pages/PermissionPresets'
import AssetCalibration from './pages/AssetCalibration'
import Assets from './pages/Assets'
import Locations from './pages/Locations'
import OperationMaster from './pages/OperationMaster'
import OperationTypes from './pages/OperationTypes'
import PrimeMoverTankerLinkMaster from './pages/PrimeMoverTankerLinkMaster'
import RoleLocations from './pages/RoleLocations'
import RolePermissions from './pages/RolePermissions'
import Roles from './pages/Roles'
import UserRoles from './pages/UserRoles'
import Users from './pages/Users'
import {
  PermissionMasterPage,
  UserLocationAssignmentPage,
  AccessSummaryPage,
  ProfileSecurityPage,
} from './pages/UserAccessModules'
import {
  AssetAssignmentPage,
  AssetAssignmentSummaryPage,
} from './pages/AssetAssignmentModules'
import {
  LocationOperationAvailabilityPage,
  LocationOperationSummaryPage,
  LocationAccountingDaySettingPage,
  CompanyReportProfileMasterPage,
  MaterialBalanceTemplateMasterPage,
} from './pages/ConfigurationModules'
import {
  FlowmeterRecordEntryPage,
  MovementMappingPage,
  OperationTaskManagerPage,
  CorrectionRequestsPage,
} from './pages/BusinessExtendedModules'
import {
  ExportDashboardPage,
  ExportTransactionsPage,
  ExportReportsPage,
  ExportPermitsPage,
  ExportLocationsPage,
  ExportEntitiesPage,
  ExportBlocksPage,
  ExportConsigneesPage,
  ExportSettingsPage,
} from './pages/ExportOperationsModules'
import {
  TankOperationSummaryPage,
  OutTurnSummaryPage,
  MaterialBalanceReportPage,
} from './pages/ReportModules'
import {
  BackupRecoveryPage,
  SystemNotificationMasterPage,
  DatabaseBrowserPage,
} from './pages/BackupAndSystemModules'
import {
  flushPendingUiEvents,
  logUiAction,
  setActionLogUser,
} from './utils/actionLogger'

const OperationEntry = lazy(() => import('./pages/OperationEntry'))
const OperationReferences = lazy(() => import('./pages/OperationReferences'))
const OperationTransactionRegister = lazy(() => import('./pages/OperationTransactionRegister'))
const OperationTransactionDetail = lazy(() => import('./pages/OperationTransactionDetail'))
const BargeTracking = lazy(() => import('./pages/BargeTracking'))
const TankerTracking = lazy(() => import('./pages/TankerTracking'))
const ShuttleTracking = lazy(() => import('./pages/ShuttleTracking'))
const FSOTracking = lazy(() => import('./pages/FSOTracking'))
const TankerTransactionReport = lazy(() => import('./pages/TankerTransactionReport'))

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
          <Suspense fallback={<div className="loading" role="status">Loading module…</div>}><Routes>
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
              path="/permission-presets"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="permission_presets:read">
                  <PermissionPresets />
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
              path="/permissions"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="permissions:read">
                  <PermissionMasterPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/user-locations"
              element={
                <PermissionGuard loggedInUser={loggedInUser} allOfPermissions={["users:read", "locations:read"]}>
                  <UserLocationAssignmentPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/access-summary"
              element={
                <PermissionGuard loggedInUser={loggedInUser} allOfPermissions={["users:read", "roles:read", "permissions:read", "locations:read"]}>
                  <AccessSummaryPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/profile-security"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="profile:read">
                  <ProfileSecurityPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/asset-calibration"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="assets:read">
                  <AssetCalibration />
                </PermissionGuard>
              }
            />
            <Route
              path="/asset-assignments"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="asset_assignments:read">
                  <AssetAssignmentPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/asset-assignment-summary"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="asset_assignments:read">
                  <AssetAssignmentSummaryPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/prime-mover-tanker-links"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="prime_mover_tanker_links:read">
                  <PrimeMoverTankerLinkMaster />
                </PermissionGuard>
              }
            />
            <Route
              path="/operation-types"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="operation_types:read">
                  <OperationTypes />
                </PermissionGuard>
              }
            />
            <Route
              path="/operations"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="operations:read">
                  <OperationMaster />
                </PermissionGuard>
              }
            />
            <Route
              path="/location-operation-availability"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="location_operation_availability:read">
                  <LocationOperationAvailabilityPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/location-operation-summary"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="location_operation_availability:read">
                  <LocationOperationSummaryPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/location-accounting-day-settings"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="location_accounting_day_settings:read">
                  <LocationAccountingDaySettingPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/company-report-profiles"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="company_report_profiles:read">
                  <CompanyReportProfileMasterPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/material-balance-template-master"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="material_balance_templates:read">
                  <MaterialBalanceTemplateMasterPage />
                </PermissionGuard>
              }
            />
            <Route
              path="/table11-factors"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="operation_references:read">
                  <OperationReferences defaultKind="table11" />
                </PermissionGuard>
              }
            />
            <Route
              path="/flowmeter-configs"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="operation_references:read">
                  <OperationReferences defaultKind="meters" />
                </PermissionGuard>
              }
            />
            <Route
              path="/barge-seal-master"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="operation_references:read">
                  <OperationReferences defaultKind="seals" />
                </PermissionGuard>
              }
            />
            <Route
              path="/operation-workflow-policies"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="operation_policies:read">
                  <OperationReferences defaultKind="policies" />
                </PermissionGuard>
              }
            />
            <Route
              path="/assets"
              element={
                <PermissionGuard loggedInUser={loggedInUser} requiredPermission="assets:read">
                  <Assets />
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
            <Route path="/operation-entry" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="operation_entries:read"><OperationEntry /></PermissionGuard>} />
            <Route path="/flowmeter-records" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="flowmeter_records:read"><FlowmeterRecordEntryPage /></PermissionGuard>} />
            <Route path="/movement-mappings" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="movement_mappings:read"><MovementMappingPage /></PermissionGuard>} />
            <Route path="/operation-tasks" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="operation_tasks:read"><OperationTaskManagerPage /></PermissionGuard>} />
            <Route path="/operation-references" element={<PermissionGuard loggedInUser={loggedInUser} anyOfPermissions={['operation_references:read','operation_policies:read','operation_voyages:read']}><OperationReferences /></PermissionGuard>} />
            <Route path="/operation-transactions" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="operation_transactions:read"><OperationTransactionRegister /></PermissionGuard>} />
            <Route path="/operation-transactions/:id" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="operation_transactions:read"><OperationTransactionDetail /></PermissionGuard>} />
            <Route path="/barge-tracking" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="barge_tracking:read"><BargeTracking /></PermissionGuard>} />
            <Route path="/tanker-tracking" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="tanker_tracking:read"><TankerTracking /></PermissionGuard>} />
            <Route path="/shuttle-tracking" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="shuttle_tracking:read"><ShuttleTracking /></PermissionGuard>} />
            <Route path="/fso-tracking" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="fso_tracking:read"><FSOTracking /></PermissionGuard>} />
            <Route path="/tanker-transaction-report" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="tanker_transaction_reports:read"><TankerTransactionReport /></PermissionGuard>} />
            <Route path="/correction-requests" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="correction_requests:read"><CorrectionRequestsPage /></PermissionGuard>} />

            <Route path="/export-operations/dashboard" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="export_operations:read"><ExportDashboardPage /></PermissionGuard>} />
            <Route path="/export-operations/transactions" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="export_operations:read"><ExportTransactionsPage /></PermissionGuard>} />
            <Route path="/export-operations/reports" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="export_operations:read"><ExportReportsPage /></PermissionGuard>} />
            <Route path="/export-operations/permits" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="export_operations:read"><ExportPermitsPage /></PermissionGuard>} />
            <Route path="/export-operations/locations" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="export_operations:read"><ExportLocationsPage /></PermissionGuard>} />
            <Route path="/export-operations/entities" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="export_operations:read"><ExportEntitiesPage /></PermissionGuard>} />
            <Route path="/export-operations/blocks" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="export_operations:read"><ExportBlocksPage /></PermissionGuard>} />
            <Route path="/export-operations/consignees" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="export_operations:read"><ExportConsigneesPage /></PermissionGuard>} />
            <Route path="/export-operations/settings" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="export_operations:read"><ExportSettingsPage /></PermissionGuard>} />

            <Route path="/tank-operation-summary" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="reports:read"><TankOperationSummaryPage /></PermissionGuard>} />
            <Route path="/out-turn-summary" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="reports:read"><OutTurnSummaryPage /></PermissionGuard>} />
            <Route path="/material-balance-report" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="reports:read"><MaterialBalanceReportPage /></PermissionGuard>} />

            <Route path="/backup-recovery" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="backup_recovery:read"><BackupRecoveryPage /></PermissionGuard>} />
            <Route path="/system-notifications" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="system_notifications:read"><SystemNotificationMasterPage /></PermissionGuard>} />
            <Route path="/database-browser" element={<PermissionGuard loggedInUser={loggedInUser} requiredPermission="database_browser:read"><DatabaseBrowserPage /></PermissionGuard>} />

            <Route path="/modules/:moduleKey" element={<ModuleDashboard />} />
            <Route path="*" element={<NotFound />} />
          </Routes></Suspense>
        </AppShell>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
