import { useCallback, useEffect, useMemo, useState } from 'react'
import { downloadUserRolesExport, importUserRolesFile, listUserRoles, saveUserRoles } from '../api/assignmentApi'
import { listRoles } from '../api/rolesApi'
import Icon from '../components/common/Icon'
import MasterImportDialog from '../components/common/MasterImportDialog'
import { Alert, EmptyState, formatDateTime, Loading, PageHead, Pagination, StatusTag } from '../components/common/Ui'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'

const EMPTY_FILTERS = { search: '', status: '', department: '', role_id: '', date_from: '', date_to: '' }
const isAdminUser = (user) => user?.username?.trim().toLowerCase() === 'admin' || user?.roles?.some((role) => role.role_name?.trim().toLowerCase() === 'admin')

function UserRoleDialog({ user, roles, onClose, onSaved }) {
  const [selected, setSelected] = useState((user.roles || []).map((role) => role.id))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const toggle = (id) => setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  const allSelected = roles.length > 0 && roles.every((role) => selected.includes(role.id))
  const save = async () => {
    setBusy(true); setError('')
    try { const result = await saveUserRoles(user.id, selected); onSaved(result) }
    catch (saveError) { setError(saveError.message || 'Unable to save user roles') }
    finally { setBusy(false) }
  }

  return (
    <div className="dialog-backdrop">
      <div className="dialog dialog-lg" role="dialog" aria-modal="true" aria-labelledby="user-role-title">
        <div className="dialog-head"><h2 id="user-role-title" className="dialog-title">Assign roles — {user.full_name}</h2><p className="dialog-subtitle">Select active roles for @{user.username}. The reserved Admin role is managed only by system bootstrap.</p></div>
        <div className="dialog-body">{error && <Alert tone="danger">{error}</Alert>}<div className="assignment-select-all"><span className="muted small">{selected.length} of {roles.length} roles selected</span><button type="button" className="btn btn-ghost btn-compact" onClick={() => setSelected(allSelected ? [] : roles.map((role) => role.id))} disabled={!roles.length}>{allSelected ? 'Clear all' : 'Select all'}</button></div>{roles.length ? <div className="role-options">{roles.map((role) => <label key={role.id} className="role-option"><input type="checkbox" checked={selected.includes(role.id)} onChange={() => toggle(role.id)} /><span><strong>{role.role_name}</strong><small>{role.description || 'No description'} · {role.permission_count} permissions</small></span></label>)}</div> : <EmptyState title="No active roles" description="Create an active role in Role Master first." />}</div>
        <div className="dialog-foot"><button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button><button type="button" className="btn btn-primary" onClick={save} disabled={busy || user.status !== 'Active'}><Icon name="checkCircle" size={15} />{busy ? 'Saving…' : 'Save assignments'}</button></div>
      </div>
    </div>
  )
}

export default function UserRoles() {
  const { isAdmin, hasPermission } = usePermissions()
  const canAssign = isAdmin || hasPermission('assignments:write')
  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [data, setData] = useState({ items: [], total: 0, pages: 0 })
  const [roles, setRoles] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editingUser, setEditingUser] = useState(null)
  const [showImport, setShowImport] = useState(false)
  const [exporting, setExporting] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await listUserRoles({ ...applied, page, page_size: pageSize })) }
    catch (loadError) { setError(loadError.message || 'Unable to load user role assignments'); setData({ items: [], total: 0, pages: 0 }) }
    finally { setLoading(false) }
  }, [applied, page, pageSize])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    let active = true
    listRoles({ page: 1, page_size: 200, status: 'Active' }).then((response) => {
      if (active) setRoles((response.items || []).filter((role) => !role.is_reserved && role.role_name?.toLowerCase() !== 'admin'))
    }).catch(() => undefined)
    return () => { active = false }
  }, [])

  const chips = useMemo(() => [
    ...(applied.search ? [{ key: 'search', label: `Search: ${applied.search}` }] : []),
    ...(applied.status ? [{ key: 'status', label: `Status: ${applied.status}` }] : []),
    ...(applied.department ? [{ key: 'department', label: `Department: ${applied.department}` }] : []),
    ...(applied.role_id ? [{ key: 'role_id', label: `Role: ${roles.find((role) => String(role.id) === String(applied.role_id))?.role_name || applied.role_id}` }] : []),
    ...(applied.date_from ? [{ key: 'date_from', label: `Created from: ${applied.date_from}` }] : []),
    ...(applied.date_to ? [{ key: 'date_to', label: `Created to: ${applied.date_to}` }] : []),
  ], [applied, roles])
  const apply = () => { setApplied({ ...draft }); setPage(1); logUiAction('User Role Assignment', 'Apply Filter') }
  const reset = () => { setDraft(EMPTY_FILTERS); setApplied(EMPTY_FILTERS); setPage(1); logUiAction('User Role Assignment', 'Reset Filter') }
  const remove = (key) => { const next = { ...applied, [key]: '' }; setApplied(next); setDraft(next); setPage(1) }
  const exportRows = async (format) => { setExporting(format); setError(''); try { await downloadUserRolesExport(format, applied) } catch (exportError) { setError(exportError.message || 'Export failed') } finally { setExporting('') } }

  return (
    <div className="page">
      <PageHead eyebrow="USER MANAGEMENT / USER ROLE ASSIGNMENT" title="User Role Assignment" description="Assign one or more active access roles to each user. CSV/XLSX imports replace each listed user's role set using semicolon-separated role names; changes are audited." actions={<>{canAssign && <button type="button" className="btn btn-secondary" onClick={() => setShowImport(true)}><Icon name="upload" size={15} /> Import</button>}<button type="button" className="btn btn-secondary" onClick={load} disabled={loading}><Icon name="refresh" size={15} /> Refresh</button></>} />
      {error && <Alert tone="danger">{error}</Alert>}{notice && <Alert tone="success">{notice}</Alert>}
      <section className="card">
        <div className="toolbar"><div className="toolbar-group"><form className="toolbar-group" onSubmit={(event) => { event.preventDefault(); apply() }}><div className="search-field"><Icon name="search" size={15} className="search-icon" /><input className="input" type="search" value={draft.search} onChange={(event) => setDraft({ ...draft, search: event.target.value })} placeholder="Search name, username, email or department" aria-label="Search users" /></div><button type="submit" className="btn btn-primary">Search</button></form><button type="button" className={`btn btn-secondary ${showAdvanced ? 'is-active' : ''}`} onClick={() => setShowAdvanced((value) => !value)} aria-expanded={showAdvanced}><Icon name="filter" size={15} /> Advanced filters</button></div><div className="toolbar-spacer" /><div className="toolbar-group" role="group" aria-label="Export user role assignments"><span className="muted small">Export</span>{['csv', 'xlsx', 'pdf'].map((format) => <button key={format} type="button" className="btn btn-secondary btn-compact" onClick={() => exportRows(format)} disabled={Boolean(exporting)}><Icon name="download" size={14} />{exporting === format ? 'Exporting…' : format.toUpperCase()}</button>)}</div></div>
        <div className="filters-panel">{showAdvanced && <div className="filters-grid"><label className="field"><span className="field-label">Status</span><select className="select" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="">All statuses</option>{(data.statuses || ['Active', 'Inactive']).map((status) => <option key={status} value={status}>{status}</option>)}</select></label><label className="field"><span className="field-label">Department</span><select className="select" value={draft.department} onChange={(event) => setDraft({ ...draft, department: event.target.value })}><option value="">All departments</option>{(data.departments || []).map((department) => <option key={department} value={department}>{department}</option>)}</select></label><label className="field"><span className="field-label">Role</span><select className="select" value={draft.role_id} onChange={(event) => setDraft({ ...draft, role_id: event.target.value })}><option value="">All roles</option>{roles.map((role) => <option key={role.id} value={role.id}>{role.role_name}</option>)}</select></label></div>}<div className="date-group"><div className="date-group-title"><Icon name="calendar" size={14} /> User created date range</div><div className="date-grid"><label className="field"><span className="field-label">From date</span><input className="input" type="date" value={draft.date_from} onChange={(event) => setDraft({ ...draft, date_from: event.target.value })} /></label><label className="field"><span className="field-label">To date</span><input className="input" type="date" value={draft.date_to} onChange={(event) => setDraft({ ...draft, date_to: event.target.value })} /></label></div></div><div className="filter-actions"><button type="button" className="btn btn-primary btn-compact" onClick={apply}>Apply filters</button><button type="button" className="btn btn-secondary btn-compact" onClick={reset}>Reset</button><span className="muted small">Date filters apply independently from general filters.</span></div>{chips.length > 0 && <div className="chip-row" aria-label="Active filters">{chips.map((chip) => <span key={chip.key} className="filter-chip">{chip.label}<button type="button" onClick={() => remove(chip.key)} aria-label={`Remove ${chip.label}`}><Icon name="close" size={12} /></button></span>)}</div>}</div>
        {loading ? <Loading label="Loading user roles…" /> : data.items.length === 0 ? <EmptyState title="No users match the current filters" description="Adjust your search or filters." /> : <><div className="table-wrap"><table className="data-table"><thead><tr><th>User</th><th>Department</th><th>Assigned roles</th><th>Status</th><th>Created</th><th aria-label="Actions" /></tr></thead><tbody>{data.items.map((user) => <tr key={user.id}><td><div className="cell-primary">{user.full_name}</div><div className="cell-sub">@{user.username} · {user.email}</div></td><td>{user.department || '—'}</td><td>{user.roles?.length ? <div className="location-chip-list">{user.roles.map((role) => <span className="location-chip" key={role.id}>{role.role_name}<small>{role.status}</small></span>)}</div> : <span className="muted">No role assigned</span>}</td><td><StatusTag status={user.status} /></td><td className="nowrap">{formatDateTime(user.created_at)}</td><td><div className="table-actions">{canAssign && user.status === 'Active' && !isAdminUser(user) && <button type="button" className="btn btn-ghost btn-compact" onClick={() => { setEditingUser(user); setNotice('') }}><Icon name="settings" size={14} /> Assign roles</button>}</div></td></tr>)}</tbody></table></div><Pagination page={data.page || page} pageSize={data.page_size || pageSize} pages={data.pages || 0} total={data.total || 0} onPageChange={(next) => { setPage(next); logUiAction('User Role Assignment', 'Change Page', { page: next }) }} onPageSizeChange={(next) => { setPageSize(next); setPage(1); logUiAction('User Role Assignment', 'Change Page Size', { page_size: next }) }} disabled={loading} /></>}
      </section>
      {editingUser && <UserRoleDialog user={editingUser} roles={roles} onClose={() => setEditingUser(null)} onSaved={() => { setEditingUser(null); setNotice(`Roles saved for ${editingUser.username}.`); load() }} />}
      {showImport && <MasterImportDialog title="User role assignments" templateHeaders={["username", "role_names"]} templateFilename="user-role-import-template.csv" importFile={importUserRolesFile} onClose={() => setShowImport(false)} onImported={(result) => { setShowImport(false); setNotice(result.message || 'User role assignments imported successfully'); load() }} />}
    </div>
  )
}
