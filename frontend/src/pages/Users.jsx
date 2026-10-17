import { useCallback, useEffect, useMemo, useState } from 'react'
import { downloadUsersExport, listRoles, listUsers } from '../api/usersApi'
import Icon from '../components/common/Icon'
import {
  Alert,
  EmptyState,
  formatDateTime,
  Loading,
  PageHead,
  Pagination,
  StatusTag,
} from '../components/common/Ui'
import ImportUsersDialog from '../components/users/ImportUsersDialog'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'

const EMPTY_FILTERS = {
  search: '',
  status: '',
  department: '',
  role_id: '',
  date_from: '',
  date_to: '',
}

function UserDetailDialog({ user, onClose }) {
  if (!user) return null
  return (
    <div className="dialog-backdrop">
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="user-detail-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-head">
          <h2 id="user-detail-title" className="dialog-title">
            {user.full_name}
          </h2>
          <p className="dialog-subtitle">
            @{user.username} · {user.status}
          </p>
        </div>
        <div className="dialog-body">
          <div className="filters-grid">
            {[
              ['Email', user.email],
              ['Phone', user.phone || '—'],
              ['Department', user.department || '—'],
              ['Designation', user.designation || '—'],
              ['Roles', user.roles?.map((role) => role.role_name).join(', ') || 'No role'],
              ['Last sign-in', formatDateTime(user.last_login_at)],
              ['Created', formatDateTime(user.created_at)],
              ['Password change required', user.force_password_change ? 'Yes' : 'No'],
            ].map(([label, value]) => (
              <div className="field" key={label}>
                <span className="field-label">{label}</span>
                <span>{value}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Users() {
  const { isAdmin, hasPermission } = usePermissions()
  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [data, setData] = useState({ items: [], total: 0, pages: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [roles, setRoles] = useState([])
  const [exporting, setExporting] = useState('')
  const [selectedUser, setSelectedUser] = useState(null)
  const [showImport, setShowImport] = useState(false)
  const [notice, setNotice] = useState('')

  const canExport = isAdmin || hasPermission('Export User')
  const canImport = isAdmin || hasPermission('Create User')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await listUsers({ ...applied, page, page_size: pageSize })
      setData(response)
    } catch (loadError) {
      setError(loadError.message || 'Unable to load users')
      setData({ items: [], total: 0, pages: 0 })
    } finally {
      setLoading(false)
    }
  }, [applied, page, pageSize])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    let active = true
    if (isAdmin || hasPermission('View Role')) {
      listRoles({ page: 1, page_size: 200 })
        .then((response) => {
          if (active) setRoles(response.items || [])
        })
        .catch(() => undefined)
    }
    return () => {
      active = false
    }
  }, [isAdmin, hasPermission])

  const activeChips = useMemo(() => {
    const chips = []
    if (applied.search) chips.push({ key: 'search', label: `Search: ${applied.search}` })
    if (applied.status) chips.push({ key: 'status', label: `Status: ${applied.status}` })
    if (applied.department) chips.push({ key: 'department', label: `Department: ${applied.department}` })
    if (applied.role_id) {
      const role = roles.find((item) => String(item.id) === String(applied.role_id))
      chips.push({ key: 'role_id', label: `Role: ${role?.role_name || applied.role_id}` })
    }
    if (applied.date_from) chips.push({ key: 'date_from', label: `Created from: ${applied.date_from}` })
    if (applied.date_to) chips.push({ key: 'date_to', label: `Created to: ${applied.date_to}` })
    return chips
  }, [applied, roles])

  const applyFilters = () => {
    setApplied({ ...draft })
    setPage(1)
    logUiAction('User Master', 'Apply Filter', {
      status: draft.status || 'any',
      department: draft.department || 'any',
      has_date_range: Boolean(draft.date_from || draft.date_to),
    })
  }

  const resetFilters = () => {
    setDraft(EMPTY_FILTERS)
    setApplied(EMPTY_FILTERS)
    setPage(1)
    logUiAction('User Master', 'Reset Filter')
  }

  const removeChip = (key) => {
    const next = { ...applied, [key]: '' }
    setApplied(next)
    setDraft((current) => ({ ...current, [key]: '' }))
    setPage(1)
  }

  const handleExport = async (format) => {
    setExporting(format)
    setError('')
    try {
      await downloadUsersExport(format, applied)
    } catch (exportError) {
      setError(exportError.message || 'Export failed')
    } finally {
      setExporting('')
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="USER MANAGEMENT / USER MASTER"
        title="User Master"
        description="Read-only register for v0.1. Server-side pagination, quick and advanced filters, a dedicated created-date range and audited exports are enabled. Create and edit screens ship in the next increment."
        actions={
          <button type="button" className="btn btn-secondary" onClick={load} disabled={loading}>
            <Icon name="refresh" size={15} />
            Refresh
          </button>
        }
      />

      {error && <Alert tone="danger">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}

      <section className="card">
        <div className="toolbar">
          <div className="toolbar-group">
            <form
              className="toolbar-group"
              onSubmit={(event) => {
                event.preventDefault()
                applyFilters()
              }}
            >
              <div className="search-field">
                <Icon name="search" size={15} className="search-icon" />
                <input
                  className="input"
                  type="search"
                  value={draft.search}
                  onChange={(event) => setDraft({ ...draft, search: event.target.value })}
                  placeholder="Search name, username, email or department"
                  aria-label="Quick search users"
                />
              </div>
              <button type="submit" className="btn btn-primary">
                Search
              </button>
            </form>
            <button
              type="button"
              className={`btn btn-secondary ${showAdvanced ? 'is-active' : ''}`.trim()}
              onClick={() => setShowAdvanced((value) => !value)}
              aria-expanded={showAdvanced}
            >
              <Icon name="filter" size={15} />
              Advanced filters
            </button>
          </div>

          <div className="toolbar-spacer" />

          {canImport && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setNotice('')
                setShowImport(true)
              }}
            >
              <Icon name="upload" size={15} />
              Import
            </button>
          )}

          {canExport && (
            <div className="toolbar-group" role="group" aria-label="Export users">
              <span className="muted small">Export</span>
              {['csv', 'xlsx', 'pdf'].map((format) => (
                <button
                  key={format}
                  type="button"
                  className="btn btn-secondary btn-compact"
                  onClick={() => handleExport(format)}
                  disabled={Boolean(exporting)}
                >
                  <Icon name="download" size={14} />
                  {exporting === format ? 'Exporting…' : format.toUpperCase()}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="filters-panel">
          {showAdvanced && (
            <div className="filters-grid">
              <label className="field">
                <span className="field-label">Status</span>
                <select
                  className="select"
                  value={draft.status}
                  onChange={(event) => setDraft({ ...draft, status: event.target.value })}
                >
                  <option value="">All statuses</option>
                  {(data.statuses?.length ? data.statuses : ['Active', 'Inactive']).map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span className="field-label">Department</span>
                <select
                  className="select"
                  value={draft.department}
                  onChange={(event) => setDraft({ ...draft, department: event.target.value })}
                >
                  <option value="">All departments</option>
                  {(data.departments || []).map((department) => (
                    <option key={department} value={department}>
                      {department}
                    </option>
                  ))}
                </select>
              </label>

              {roles.length > 0 && (
                <label className="field">
                  <span className="field-label">Role</span>
                  <select
                    className="select"
                    value={draft.role_id}
                    onChange={(event) => setDraft({ ...draft, role_id: event.target.value })}
                  >
                    <option value="">All roles</option>
                    {roles.map((role) => (
                      <option key={role.id} value={role.id}>
                        {role.role_name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          )}

          <div className="date-group">
            <div className="date-group-title">
              <Icon name="calendar" size={14} />
              Created date range
            </div>
            <div className="date-grid">
              <label className="field">
                <span className="field-label">From date</span>
                <input
                  className="input"
                  type="date"
                  value={draft.date_from}
                  onChange={(event) => setDraft({ ...draft, date_from: event.target.value })}
                />
              </label>
              <label className="field">
                <span className="field-label">To date</span>
                <input
                  className="input"
                  type="date"
                  value={draft.date_to}
                  onChange={(event) => setDraft({ ...draft, date_to: event.target.value })}
                />
              </label>
            </div>
          </div>

          <div className="filter-actions">
            <button type="button" className="btn btn-primary btn-compact" onClick={applyFilters}>
              Apply filters
            </button>
            <button type="button" className="btn btn-secondary btn-compact" onClick={resetFilters}>
              Reset
            </button>
            <span className="muted small">
              Date filters are applied separately from the general filters.
            </span>
          </div>

          {activeChips.length > 0 && (
            <div className="chip-row" aria-label="Active filters">
              {activeChips.map((chip) => (
                <span key={chip.key} className="filter-chip">
                  {chip.label}
                  <button
                    type="button"
                    onClick={() => removeChip(chip.key)}
                    aria-label={`Remove filter ${chip.label}`}
                  >
                    <Icon name="close" size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {loading ? (
          <Loading label="Loading users…" />
        ) : data.items.length === 0 ? (
          <EmptyState
            title="No users match the current filters"
            description="Adjust the search, advanced filters or created-date range."
          />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Email</th>
                    <th>Department</th>
                    <th>Roles</th>
                    <th>Status</th>
                    <th>Last sign-in</th>
                    <th>Created</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <div className="cell-primary">{user.full_name}</div>
                        <div className="cell-sub">@{user.username}</div>
                      </td>
                      <td>{user.email}</td>
                      <td>
                        <div>{user.department || '—'}</div>
                        <div className="cell-sub">{user.designation || ''}</div>
                      </td>
                      <td>
                        {user.roles?.length
                          ? user.roles.map((role) => role.role_name).join(', ')
                          : 'No role'}
                      </td>
                      <td>
                        <StatusTag status={user.status} />
                      </td>
                      <td className="nowrap">{formatDateTime(user.last_login_at)}</td>
                      <td className="nowrap">{formatDateTime(user.created_at)}</td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-ghost btn-compact"
                          onClick={() => {
                            setSelectedUser(user)
                            logUiAction('User Master', 'View User', { username: user.username })
                          }}
                          aria-label={`View ${user.username}`}
                        >
                          <Icon name="eye" size={15} />
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <Pagination
              page={data.page || page}
              pageSize={data.page_size || pageSize}
              pages={data.pages || 0}
              total={data.total || 0}
              onPageChange={(nextPage) => {
                setPage(nextPage)
                logUiAction('User Master', 'Change Page', { page: nextPage })
              }}
              onPageSizeChange={(nextSize) => {
                setPageSize(nextSize)
                setPage(1)
                logUiAction('User Master', 'Change Page Size', { page_size: nextSize })
              }}
              disabled={loading}
            />
          </>
        )}
      </section>

      {selectedUser && (
        <UserDetailDialog user={selectedUser} onClose={() => setSelectedUser(null)} />
      )}

      {showImport && (
        <ImportUsersDialog
          onClose={() => setShowImport(false)}
          onImported={(result) => {
            setShowImport(false)
            setNotice(result.message || 'Users imported successfully')
            setPage(1)
            load()
          }}
        />
      )}
    </div>
  )
}
