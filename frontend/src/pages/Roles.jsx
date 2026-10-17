import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { createRole, deactivateRole, downloadRolesExport, importRolesFile, listRoles, updateRole } from '../api/rolesApi'
import Icon from '../components/common/Icon'
import MasterImportDialog from '../components/common/MasterImportDialog'
import { Alert, EmptyState, formatDateTime, Loading, PageHead, Pagination, StatusTag } from '../components/common/Ui'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'

const EMPTY_FILTERS = { search: '', status: '', date_from: '', date_to: '' }
const ROLE_TEMPLATE = ['role_name', 'description', 'status']

function RoleDialog({ role, onClose, onSaved }) {
  const [form, setForm] = useState({ role_name: role?.role_name || '', description: role?.description || '', status: role?.status || 'Active' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = role
        ? await updateRole(role.id, form)
        : await createRole(form)
      onSaved(result, role ? 'Role updated successfully' : 'Role created successfully')
    } catch (saveError) {
      setError(saveError.message || 'Unable to save the role')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="role-dialog-title" onSubmit={submit}>
        <div className="dialog-head">
          <h2 id="role-dialog-title" className="dialog-title">{role ? 'Edit role' : 'Create role'}</h2>
          <p className="dialog-subtitle">Roles bundle standard permissions and can be assigned to users.</p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="form-grid" style={{ marginTop: error ? 14 : 0 }}>
            <label className="field">
              <span className="field-label">Role name</span>
              <input className="input" required minLength={2} maxLength={100} autoFocus value={form.role_name} onChange={(event) => setForm({ ...form, role_name: event.target.value })} />
            </label>
            <label className="field">
              <span className="field-label">Description</span>
              <textarea className="textarea" maxLength={500} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
            </label>
            <label className="field">
              <span className="field-label">Status</span>
              <select className="select" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
                <option value="Active">Active</option>
                <option value="Inactive">Inactive</option>
              </select>
            </label>
          </div>
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Icon name="checkCircle" size={15} /> {busy ? 'Saving…' : role ? 'Save changes' : 'Create role'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default function Roles() {
  const { isAdmin, hasPermission } = usePermissions()
  const canCreate = isAdmin || hasPermission('roles:create')
  const canUpdate = isAdmin || hasPermission('roles:update')
  const canDelete = isAdmin || hasPermission('roles:delete')
  const canViewPermissions = isAdmin || hasPermission('permissions:read')
  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [data, setData] = useState({ items: [], total: 0, pages: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editingRole, setEditingRole] = useState(null)
  const [showRoleDialog, setShowRoleDialog] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [exporting, setExporting] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await listRoles({ ...applied, page, page_size: pageSize }))
    } catch (loadError) {
      setError(loadError.message || 'Unable to load roles')
      setData({ items: [], total: 0, pages: 0 })
    } finally {
      setLoading(false)
    }
  }, [applied, page, pageSize])

  useEffect(() => { load() }, [load])

  const activeChips = useMemo(() => [
    ...(applied.search ? [{ key: 'search', label: `Search: ${applied.search}` }] : []),
    ...(applied.status ? [{ key: 'status', label: `Status: ${applied.status}` }] : []),
    ...(applied.date_from ? [{ key: 'date_from', label: `Created from: ${applied.date_from}` }] : []),
    ...(applied.date_to ? [{ key: 'date_to', label: `Created to: ${applied.date_to}` }] : []),
  ], [applied])

  const applyFilters = () => { setApplied({ ...draft }); setPage(1); logUiAction('Role Master', 'Apply Filter') }
  const resetFilters = () => { setDraft(EMPTY_FILTERS); setApplied(EMPTY_FILTERS); setPage(1); logUiAction('Role Master', 'Reset Filter') }
  const removeChip = (key) => { const next = { ...applied, [key]: '' }; setApplied(next); setDraft(next); setPage(1) }

  const exportRows = async (format) => {
    setExporting(format)
    setError('')
    try { await downloadRolesExport(format, applied) }
    catch (exportError) { setError(exportError.message || 'Export failed') }
    finally { setExporting('') }
  }

  const saveComplete = (role, message) => {
    setShowRoleDialog(false)
    setEditingRole(null)
    setNotice(message)
    setPage(1)
    load()
  }

  const handleDeactivate = async (role) => {
    if (!window.confirm(`Deactivate “${role.role_name}”? Existing assignments will be retained.`)) return
    setError('')
    try {
      await deactivateRole(role.id)
      setNotice(`${role.role_name} has been deactivated.`)
      load()
    } catch (deactivateError) {
      setError(deactivateError.message || 'Unable to deactivate the role')
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="USER MANAGEMENT / ROLE MASTER"
        title="Role Master"
        description="Configure reusable access roles. Role permissions and assignment history are retained when a role is deactivated."
        actions={
          <>
            {canViewPermissions && <Link to="/role-permissions" className="btn btn-secondary"><Icon name="shieldCheck" size={15} /> Role permissions</Link>}
            {canCreate && <button type="button" className="btn btn-primary" onClick={() => { setEditingRole(null); setShowRoleDialog(true); setNotice('') }}><Icon name="users" size={15} /> Add role</button>}
            <button type="button" className="btn btn-secondary" onClick={load} disabled={loading}><Icon name="refresh" size={15} /> Refresh</button>
          </>
        }
      />
      {error && <Alert tone="danger">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}

      <section className="card">
        <div className="toolbar">
          <div className="toolbar-group">
            <form className="toolbar-group" onSubmit={(event) => { event.preventDefault(); applyFilters() }}>
              <div className="search-field"><Icon name="search" size={15} className="search-icon" /><input className="input" type="search" value={draft.search} onChange={(event) => setDraft({ ...draft, search: event.target.value })} placeholder="Search role name or description" aria-label="Search roles" /></div>
              <button type="submit" className="btn btn-primary">Search</button>
            </form>
            <button type="button" className={`btn btn-secondary ${showAdvanced ? 'is-active' : ''}`} onClick={() => setShowAdvanced((value) => !value)} aria-expanded={showAdvanced}><Icon name="filter" size={15} /> Advanced filters</button>
          </div>
          <div className="toolbar-spacer" />
          {canCreate && <button type="button" className="btn btn-secondary" onClick={() => setShowImport(true)}><Icon name="upload" size={15} /> Import</button>}
          <div className="toolbar-group" role="group" aria-label="Export roles">
            <span className="muted small">Export</span>
            {['csv', 'xlsx', 'pdf'].map((format) => <button key={format} type="button" className="btn btn-secondary btn-compact" onClick={() => exportRows(format)} disabled={Boolean(exporting)}><Icon name="download" size={14} />{exporting === format ? 'Exporting…' : format.toUpperCase()}</button>)}
          </div>
        </div>

        <div className="filters-panel">
          {showAdvanced && <div className="filters-grid">
            <label className="field"><span className="field-label">Status</span><select className="select" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="">All statuses</option>{(data.statuses || ['Active', 'Inactive']).map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
          </div>}
          <div className="date-group">
            <div className="date-group-title"><Icon name="calendar" size={14} /> Created date range</div>
            <div className="date-grid">
              <label className="field"><span className="field-label">From date</span><input className="input" type="date" value={draft.date_from} onChange={(event) => setDraft({ ...draft, date_from: event.target.value })} /></label>
              <label className="field"><span className="field-label">To date</span><input className="input" type="date" value={draft.date_to} onChange={(event) => setDraft({ ...draft, date_to: event.target.value })} /></label>
            </div>
          </div>
          <div className="filter-actions"><button type="button" className="btn btn-primary btn-compact" onClick={applyFilters}>Apply filters</button><button type="button" className="btn btn-secondary btn-compact" onClick={resetFilters}>Reset</button><span className="muted small">Date filters apply independently from general filters.</span></div>
          {activeChips.length > 0 && <div className="chip-row" aria-label="Active filters">{activeChips.map((chip) => <span key={chip.key} className="filter-chip">{chip.label}<button type="button" onClick={() => removeChip(chip.key)} aria-label={`Remove ${chip.label}`}><Icon name="close" size={12} /></button></span>)}</div>}
        </div>

        {loading ? <Loading label="Loading roles…" /> : data.items.length === 0 ? <EmptyState title="No roles match the current filters" description="Adjust your search or filters, or create a role." /> : <>
          <div className="table-wrap"><table className="data-table"><thead><tr><th>Role</th><th>Status</th><th>Users</th><th>Permissions</th><th>Locations</th><th>Created</th><th aria-label="Actions" /></tr></thead><tbody>
            {data.items.map((role) => <tr key={role.id}>
              <td><div className="cell-primary">{role.role_name}{role.is_reserved && <span className="tag tag-info" style={{ marginLeft: 8 }}>Reserved</span>}</div><div className="cell-sub">{role.description || 'No description'}</div></td>
              <td><StatusTag status={role.status} /></td><td>{role.user_count}</td><td>{role.permission_count}</td><td>{role.location_count}</td><td className="nowrap">{formatDateTime(role.created_at)}</td>
              <td><div className="table-actions">{!role.is_reserved && canUpdate && <button type="button" className="btn btn-ghost btn-compact" onClick={() => { setEditingRole(role); setShowRoleDialog(true) }}><Icon name="settings" size={14} /> Edit</button>}{!role.is_reserved && role.status === 'Active' && canDelete && <button type="button" className="btn btn-ghost btn-compact" onClick={() => handleDeactivate(role)}><Icon name="close" size={14} /> Deactivate</button>}</div></td>
            </tr>)}
          </tbody></table></div>
          <Pagination page={data.page || page} pageSize={data.page_size || pageSize} pages={data.pages || 0} total={data.total || 0} onPageChange={(next) => { setPage(next); logUiAction('Role Master', 'Change Page', { page: next }) }} onPageSizeChange={(next) => { setPageSize(next); setPage(1); logUiAction('Role Master', 'Change Page Size', { page_size: next }) }} disabled={loading} />
        </>}
      </section>

      {showRoleDialog && <RoleDialog role={editingRole} onClose={() => { setShowRoleDialog(false); setEditingRole(null) }} onSaved={saveComplete} />}
      {showImport && <MasterImportDialog title="Roles" templateHeaders={ROLE_TEMPLATE} templateFilename="role-import-template.csv" importFile={importRolesFile} onClose={() => setShowImport(false)} onImported={(result) => { setShowImport(false); setNotice(result.message || 'Roles imported successfully'); setPage(1); load() }} />}
    </div>
  )
}
