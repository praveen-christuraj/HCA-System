import { useEffect, useState } from 'react'
import { apiGet, apiPost, apiPut, apiDownload, buildQuery } from '../api/apiClient'
import { useAuth } from '../context/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import {
  PageHead,
  KpiCard,
  StatusTag,
  Alert,
  Loading,
  EmptyState,
  Pagination,
  formatDateTime,
} from '../components/common/Ui'
import { EntryDialog } from '../components/operationLayouts/EntryFeedback'
import { logUiAction } from '../utils/actionLogger'

// ============================================================================
// 1. Permission Master (/permissions)
// ============================================================================
export function PermissionMasterPage() {
  const [filters, setFilters] = useState({
    search: '',
    module_name: '',
    category: '',
    action: '',
    status: '',
    date_from: '',
    date_to: '',
  })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1, modules: [], categories: [], actions: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/permissions${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((err) => {
        if (active) setError(err.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Permission Master', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize])

  const setFilter = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setPage(1)
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="USER MANAGEMENT / RBAC CATALOG"
        title="Permission Master"
        description="Canonical resource:action permission catalog governing API endpoints, navigation items, and module capabilities."
        actions={
          <div className="toolbar-actions">
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/permissions/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
                    setError(e.message),
                  )
                }
              >
                Export {fmt.toUpperCase()}
              </button>
            ))}
          </div>
        }
      />

      <div className="kpi-grid">
        <KpiCard label="Total Permissions" value={data.total || 0} context="Matching current filters" />
        <KpiCard label="Modules Covered" value={(data.modules || []).length} context="Registered RBAC domains" />
        <KpiCard label="Categories" value={(data.categories || []).length} context="Resource groupings" />
        <KpiCard label="Standard Actions" value={(data.actions || []).length} context="read / create / update / delete" />
      </div>

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Quick Search</label>
            <input
              className="input"
              placeholder="Search permission key, module, description…"
              value={filters.search}
              onChange={(e) => setFilter('search', e.target.value)}
            />
          </div>
          <div className="filter-group">
            <label>Module</label>
            <select className="select" value={filters.module_name} onChange={(e) => setFilter('module_name', e.target.value)}>
              <option value="">All Modules</option>
              {(data.modules || []).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Action</label>
            <select className="select" value={filters.action} onChange={(e) => setFilter('action', e.target.value)}>
              <option value="">All Actions</option>
              {(data.actions || []).map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Status</label>
            <select className="select" value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
              <option value="">All</option>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </div>
          <div className="filter-group">
            <label>Created From</label>
            <input type="date" className="input" value={filters.date_from} onChange={(e) => setFilter('date_from', e.target.value)} />
          </div>
          <div className="filter-group">
            <label>Created To</label>
            <input type="date" className="input" value={filters.date_to} onChange={(e) => setFilter('date_to', e.target.value)} />
          </div>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setFilters({ search: '', module_name: '', category: '', action: '', status: '', date_from: '', date_to: '' })
              setPage(1)
            }}
          >
            Reset
          </button>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <EmptyState title="No permissions match the selected filters" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Permission Key</th>
                  <th>Module</th>
                  <th>Category</th>
                  <th>Action</th>
                  <th>Description</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id}>
                    <td className="mono">{item.permission_name}</td>
                    <td>{item.module_name}</td>
                    <td>{item.category}</td>
                    <td>
                      <span className="tag tag-info">{item.action}</span>
                    </td>
                    <td>{item.description}</td>
                    <td>
                      <StatusTag status={item.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <Pagination
          page={page}
          pageSize={pageSize}
          pages={data.pages || 1}
          total={data.total || 0}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n)
            setPage(1)
          }}
          disabled={loading}
        />
      </section>
    </div>
  )
}

// ============================================================================
// 2. User Location Assignment (/user-locations)
// ============================================================================
export function UserLocationAssignmentPage() {
  const { hasPermission } = usePermissions()
  const canWrite = hasPermission('assignments:write')
  const [filters, setFilters] = useState({
    search: '',
    status: '',
    location_id: '',
    role_id: '',
    date_from: '',
    date_to: '',
  })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1, locations: [], roles: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editingUser, setEditingUser] = useState(null)
  const [selectedLocIds, setSelectedLocIds] = useState([])
  const [allLocationsAccess, setAllLocationsAccess] = useState(false)
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/user-locations${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((err) => {
        if (active) setError(err.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('User Location Assignment', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize, refresh])

  const setFilter = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setPage(1)
  }

  const openEditor = (row) => {
    setEditingUser(row)
    setSelectedLocIds(row.direct_location_ids || [])
    setAllLocationsAccess(Boolean(row.all_locations_access))
  }

  const handleSave = async () => {
    if (!editingUser) return
    setSaving(true)
    setError('')
    try {
      await apiPut(`/user-locations/${editingUser.user_id}`, {
        location_ids: selectedLocIds,
        all_locations_access: allLocationsAccess,
      })
      setEditingUser(null)
      setRefresh((r) => r + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="USER MANAGEMENT / LOCATION SCOPING"
        title="User Location Assignment"
        description="Assign direct operational locations or unrestricted all-location access per user. Effective scope is the union of role locations and direct user locations."
        actions={
          <div className="toolbar-actions">
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/user-locations/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
                    setError(e.message),
                  )
                }
              >
                Export {fmt.toUpperCase()}
              </button>
            ))}
          </div>
        }
      />

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Quick Search</label>
            <input
              className="input"
              placeholder="Username, name, email, department…"
              value={filters.search}
              onChange={(e) => setFilter('search', e.target.value)}
            />
          </div>
          <div className="filter-group">
            <label>Location</label>
            <select className="select" value={filters.location_id} onChange={(e) => setFilter('location_id', e.target.value)}>
              <option value="">All Locations</option>
              {(data.locations || []).map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.location_code} — {loc.location_name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Role</label>
            <select className="select" value={filters.role_id} onChange={(e) => setFilter('role_id', e.target.value)}>
              <option value="">All Roles</option>
              {(data.roles || []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.role_name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Status</label>
            <select className="select" value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
              <option value="">All</option>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </div>
          <div className="filter-group">
            <label>From</label>
            <input type="date" className="input" value={filters.date_from} onChange={(e) => setFilter('date_from', e.target.value)} />
          </div>
          <div className="filter-group">
            <label>To</label>
            <input type="date" className="input" value={filters.date_to} onChange={(e) => setFilter('date_to', e.target.value)} />
          </div>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Roles</th>
                  <th>All Locations</th>
                  <th>Direct Locations</th>
                  <th>Role Locations</th>
                  <th>Effective Scope</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.user_id}>
                    <td>
                      <strong>{row.full_name}</strong>
                      <div className="muted small mono">{row.username}</div>
                    </td>
                    <td>{(row.roles || []).join(', ') || '—'}</td>
                    <td>
                      <StatusTag status={row.all_locations_access || row.is_admin ? 'Unrestricted' : 'Scoped'} tone={row.all_locations_access || row.is_admin ? 'info' : 'neutral'} />
                    </td>
                    <td>{(row.direct_locations || []).map((l) => l.location_code).join(', ') || '—'}</td>
                    <td>{(row.role_locations || []).map((l) => l.location_code).join(', ') || '—'}</td>
                    <td>
                      {row.all_locations_access || row.is_admin
                        ? 'All Active Locations'
                        : (row.effective_locations || []).map((l) => l.location_code).join(', ') || 'Unrestricted'}
                    </td>
                    <td>
                      <StatusTag status={row.status} />
                    </td>
                    <td>
                      {canWrite && (
                        <button type="button" className="btn btn-secondary" onClick={() => openEditor(row)}>
                          Assign Locations
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <Pagination
          page={page}
          pageSize={pageSize}
          pages={data.pages || 1}
          total={data.total || 0}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n)
            setPage(1)
          }}
        />
      </section>

      {editingUser && (
        <EntryDialog
          title={`Assign Locations — ${editingUser.full_name} (${editingUser.username})`}
          footer={
            <>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setEditingUser(null)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={handleSave}>
                {saving ? 'Saving…' : 'Save Location Scope'}
              </button>
            </>
          }
        >
          <div className="stack">
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={allLocationsAccess}
                onChange={(e) => setAllLocationsAccess(e.target.checked)}
              />
              <span>Grant unrestricted access to all operational locations</span>
            </label>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Include</th>
                    <th>Location Code</th>
                    <th>Location Name</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.locations || []).map((loc) => {
                    const checked = selectedLocIds.includes(loc.id)
                    return (
                      <tr key={loc.id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedLocIds((prev) => [...prev, loc.id])
                              } else {
                                setSelectedLocIds((prev) => prev.filter((id) => id !== loc.id))
                              }
                            }}
                          />
                        </td>
                        <td className="mono">{loc.location_code}</td>
                        <td>{loc.location_name}</td>
                        <td>
                          <StatusTag status={loc.status} />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 3. Access Summary (/access-summary)
// ============================================================================
export function AccessSummaryPage() {
  const [filters, setFilters] = useState({ search: '', status: '', location_id: '', role_id: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1, kpis: {}, locations: [], roles: [] })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedRow, setSelectedRow] = useState(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/access-summary${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((err) => {
        if (active) setError(err.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Access Summary', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize])

  const setFilter = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setPage(1)
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="USER MANAGEMENT / EFFECTIVE ACCESS MATRIX"
        title="Access Summary"
        description="Consolidated audit view of every user's assigned roles, effective permissions, direct and role-inherited locations, and 2FA posture."
        actions={
          <div className="toolbar-actions">
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/access-summary/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
                    setError(e.message),
                  )
                }
              >
                Export {fmt.toUpperCase()}
              </button>
            ))}
          </div>
        }
      />

      <div className="kpi-grid">
        <KpiCard label="Total Users" value={data.kpis?.total_users ?? 0} context="In identity directory" />
        <KpiCard label="Active Users" value={data.kpis?.active_users ?? 0} context="Permitted to sign in" />
        <KpiCard label="Active Roles" value={data.kpis?.active_roles ?? 0} context="RBAC roles" />
        <KpiCard label="Active Locations" value={data.kpis?.active_locations ?? 0} context="Operational sites" />
      </div>

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Quick Search</label>
            <input
              className="input"
              placeholder="Search user, email, department…"
              value={filters.search}
              onChange={(e) => setFilter('search', e.target.value)}
            />
          </div>
          <div className="filter-group">
            <label>Role</label>
            <select className="select" value={filters.role_id} onChange={(e) => setFilter('role_id', e.target.value)}>
              <option value="">All Roles</option>
              {(data.roles || []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.role_name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Location</label>
            <select className="select" value={filters.location_id} onChange={(e) => setFilter('location_id', e.target.value)}>
              <option value="">All Locations</option>
              {(data.locations || []).map((l) => (
                <option key={l.id} value={l.id}>
                  {l.location_code} — {l.location_name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Status</label>
            <select className="select" value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
              <option value="">All</option>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </div>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Department</th>
                  <th>Roles</th>
                  <th>Effective Permissions</th>
                  <th>Effective Locations</th>
                  <th>2FA</th>
                  <th>Status</th>
                  <th>Inspect</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.user_id}>
                    <td>
                      <strong>{row.full_name}</strong>
                      <div className="muted small mono">{row.username}</div>
                    </td>
                    <td>{row.department || '—'}</td>
                    <td>{(row.roles || []).join(', ') || 'None'}</td>
                    <td>
                      <span className="tag tag-info">{row.permission_count} permissions</span>
                    </td>
                    <td>
                      {row.all_locations_access || row.is_admin
                        ? 'All Locations'
                        : (row.effective_locations || []).map((l) => l.location_code).join(', ') || 'All Locations'}
                    </td>
                    <td>
                      <StatusTag status={row.totp_enabled ? 'Enabled' : 'Disabled'} tone={row.totp_enabled ? 'success' : 'neutral'} />
                    </td>
                    <td>
                      <StatusTag status={row.status} />
                    </td>
                    <td>
                      <button type="button" className="btn btn-ghost" onClick={() => setSelectedRow(row)}>
                        View Capabilities
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <Pagination
          page={page}
          pageSize={pageSize}
          pages={data.pages || 1}
          total={data.total || 0}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n)
            setPage(1)
          }}
        />
      </section>

      {selectedRow && (
        <EntryDialog
          title={`Effective Capabilities — ${selectedRow.full_name} (${selectedRow.username})`}
          footer={
            <button type="button" className="btn btn-secondary" onClick={() => setSelectedRow(null)}>
              Close
            </button>
          }
        >
          <div className="stack">
            <div>
              <strong>Roles:</strong> {(selectedRow.roles || []).join(', ') || 'None'}
            </div>
            <div>
              <strong>Effective Locations:</strong>{' '}
              {selectedRow.all_locations_access || selectedRow.is_admin
                ? 'All Active Locations'
                : (selectedRow.effective_locations || []).map((l) => `${l.location_code} (${l.location_name})`).join(', ') ||
                  'All Active Locations'}
            </div>
            <div>
              <strong>Permissions ({selectedRow.permission_count}):</strong>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px', maxHeight: '280px', overflowY: 'auto' }}>
                {(selectedRow.permissions || []).map((p) => (
                  <span key={p} className="tag mono">
                    {p}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 4. Profile & Security (/profile-security)
// ============================================================================
export function ProfileSecurityPage() {
  const { loggedInUser } = useAuth()
  const user = loggedInUser
  const { hasPermission } = usePermissions()
  const isAdmin = hasPermission('users:update')

  const [pwForm, setPwForm] = useState({ current_password: '', new_password: '', confirm_password: '' })
  const [pwMessage, setPwMessage] = useState('')
  const [pwError, setPwError] = useState('')
  const [pwBusy, setPwBusy] = useState(false)

  const [totpEnabled, setTotpEnabled] = useState(Boolean(user?.totp_enabled))
  const [totpSetup, setTotpSetup] = useState(null)
  const [totpCode, setTotpCode] = useState('')
  const [disableForm, setDisableForm] = useState({ current_password: '', code: '' })
  const [backupCodes, setBackupCodes] = useState([])
  const [totpMessage, setTotpMessage] = useState('')
  const [totpError, setTotpError] = useState('')

  const [resetRequests, setResetRequests] = useState([])
  const [resetLoading, setResetLoading] = useState(false)

  useEffect(() => {
    if (!isAdmin) return
    setResetLoading(true)
    apiGet('/auth/password-reset-requests?page_size=20')
      .then((res) => setResetRequests(res.items || []))
      .catch(() => {})
      .finally(() => setResetLoading(false))
  }, [isAdmin])

  const handleChangePassword = async (e) => {
    e.preventDefault()
    setPwError('')
    setPwMessage('')
    if (pwForm.new_password !== pwForm.confirm_password) {
      setPwError('New password and confirmation do not match.')
      return
    }
    setPwBusy(true)
    try {
      await apiPost('/auth/change-password', {
        current_password: pwForm.current_password,
        new_password: pwForm.new_password,
      })
      setPwMessage('Password updated successfully.')
      setPwForm({ current_password: '', new_password: '', confirm_password: '' })
    } catch (err) {
      setPwError(err.message)
    } finally {
      setPwBusy(false)
    }
  }

  const handleStart2FA = async () => {
    setTotpError('')
    setTotpMessage('')
    try {
      const res = await apiPost('/auth/2fa/setup', {})
      setTotpSetup(res)
      setBackupCodes(res.backup_codes || [])
    } catch (err) {
      setTotpError(err.message)
    }
  }

  const handleEnable2FA = async () => {
    setTotpError('')
    try {
      const res = await apiPost('/auth/2fa/enable', { code: totpCode })
      setBackupCodes(res.backup_codes || backupCodes)
      setTotpMessage('Two-factor authentication is now enabled.')
      setTotpEnabled(true)
      setTotpSetup(null)
      setTotpCode('')
    } catch (err) {
      setTotpError(err.message)
    }
  }

  const handleDisable2FA = async () => {
    setTotpError('')
    try {
      await apiPost('/auth/2fa/disable', disableForm)
      setTotpMessage('Two-factor authentication has been disabled.')
      setTotpEnabled(false)
      setDisableForm({ current_password: '', code: '' })
    } catch (err) {
      setTotpError(err.message)
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="IDENTITY / PROFILE & SECURITY"
        title="Profile & Security"
        description="Manage your account credentials, TOTP two-factor authentication, single-use recovery backup codes, and password reset requests."
      />

      <div className="kpi-grid">
        <KpiCard label="Username" value={user?.username || '—'} context={user?.full_name || ''} />
        <KpiCard label="Email" value={user?.email || '—'} context={user?.department || 'Enterprise User'} />
        <KpiCard label="Two-Factor Status" value={totpEnabled ? 'Enabled' : 'Disabled'} context="RFC-6238 Authenticator" />
        <KpiCard label="Account Status" value={user?.status || 'Active'} context="RBAC verified" />
      </div>

      <div className="grid-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '16px' }}>
        <section className="card">
          <header className="card-header">
            <div>
              <h2 className="card-title">Change Password</h2>
              <p className="card-subtitle">Minimum 10 characters with uppercase, lowercase, digit, and special character.</p>
            </div>
          </header>
          <form className="stack" onSubmit={handleChangePassword}>
            <label>
              Current Password
              <input
                type="password"
                className="input"
                required
                value={pwForm.current_password}
                onChange={(e) => setPwForm((f) => ({ ...f, current_password: e.target.value }))}
              />
            </label>
            <label>
              New Password
              <input
                type="password"
                className="input"
                required
                value={pwForm.new_password}
                onChange={(e) => setPwForm((f) => ({ ...f, new_password: e.target.value }))}
              />
            </label>
            <label>
              Confirm New Password
              <input
                type="password"
                className="input"
                required
                value={pwForm.confirm_password}
                onChange={(e) => setPwForm((f) => ({ ...f, confirm_password: e.target.value }))}
              />
            </label>
            {pwError && <Alert tone="danger">{pwError}</Alert>}
            {pwMessage && <Alert tone="success">{pwMessage}</Alert>}
            <div>
              <button type="submit" className="btn btn-primary" disabled={pwBusy}>
                {pwBusy ? 'Updating…' : 'Update Password'}
              </button>
            </div>
          </form>
        </section>

        <section className="card">
          <header className="card-header">
            <div>
              <h2 className="card-title">Two-Factor Authentication (TOTP)</h2>
              <p className="card-subtitle">Protect custody transfer approvals and account sign-in with an authenticator code.</p>
            </div>
          </header>
          <div className="stack">
            {totpError && <Alert tone="danger">{totpError}</Alert>}
            {totpMessage && <Alert tone="success">{totpMessage}</Alert>}

            {!totpEnabled ? (
              <>
                {!totpSetup ? (
                  <div>
                    <p className="muted">Two-factor authentication is currently disabled on your account.</p>
                    <button type="button" className="btn btn-primary" onClick={handleStart2FA}>
                      Generate 2FA Secret & Setup
                    </button>
                  </div>
                ) : (
                  <div className="stack">
                    <div>
                      <strong>Secret Key (Base32):</strong>
                      <div className="mono" style={{ padding: '8px', background: 'var(--bg-subtle)', borderRadius: '4px' }}>
                        {totpSetup.secret}
                      </div>
                    </div>
                    <div>
                      <strong>Provisioning URI:</strong>
                      <div className="mono small" style={{ wordBreak: 'break-all' }}>
                        {totpSetup.otpauth_uri}
                      </div>
                    </div>
                    <label>
                      Enter 6-digit code from Authenticator to activate
                      <input
                        className="input mono"
                        placeholder="123456"
                        value={totpCode}
                        onChange={(e) => setTotpCode(e.target.value)}
                      />
                    </label>
                    <div className="toolbar-actions">
                      <button type="button" className="btn btn-primary" onClick={handleEnable2FA}>
                        Verify & Enable 2FA
                      </button>
                      <button type="button" className="btn btn-secondary" onClick={() => setTotpSetup(null)}>
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="stack">
                <Alert tone="info">Two-factor authentication is active on your account.</Alert>
                <label>
                  Current Password
                  <input
                    type="password"
                    className="input"
                    value={disableForm.current_password}
                    onChange={(e) => setDisableForm((f) => ({ ...f, current_password: e.target.value }))}
                  />
                </label>
                <label>
                  6-Digit TOTP or Backup Code
                  <input
                    className="input mono"
                    value={disableForm.code}
                    onChange={(e) => setDisableForm((f) => ({ ...f, code: e.target.value }))}
                  />
                </label>
                <div>
                  <button type="button" className="btn btn-secondary" onClick={handleDisable2FA}>
                    Disable 2FA
                  </button>
                </div>
              </div>
            )}

            {backupCodes.length > 0 && (
              <div>
                <strong>Recovery Backup Codes (save securely):</strong>
                <div className="mono" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '6px', marginTop: '8px' }}>
                  {backupCodes.map((c) => (
                    <span key={c} className="tag">
                      {c}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
      </div>

      {isAdmin && (
        <section className="card" style={{ marginTop: '16px' }}>
          <header className="card-header">
            <div>
              <h2 className="card-title">Password Reset Requests (Admin Queue)</h2>
              <p className="card-subtitle">Self-service password reset requests submitted from the login screen.</p>
            </div>
          </header>
          {resetLoading ? (
            <Loading />
          ) : resetRequests.length === 0 ? (
            <EmptyState title="No password reset requests recorded" />
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Identifier</th>
                    <th>Matched User</th>
                    <th>Status</th>
                    <th>Requested At</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {resetRequests.map((r) => (
                    <tr key={r.id}>
                      <td>{r.id}</td>
                      <td className="mono">{r.identifier}</td>
                      <td>{r.matched_username || '—'}</td>
                      <td>
                        <StatusTag status={r.status} />
                      </td>
                      <td>{formatDateTime(r.created_at)}</td>
                      <td>
                        {r.status === 'Pending' && (
                          <button
                            type="button"
                            className="btn btn-secondary"
                            onClick={async () => {
                              await apiPost(`/auth/password-reset-requests/${r.id}/resolve`, {
                                status: 'Resolved',
                                resolution_notes: 'Processed by administrator',
                              })
                              const res = await apiGet('/auth/password-reset-requests?page_size=20')
                              setResetRequests(res.items || [])
                            }}
                          >
                            Mark Resolved
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
