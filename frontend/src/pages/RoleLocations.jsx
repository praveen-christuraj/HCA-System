import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { downloadRoleLocationsExport, importRoleLocationsFile, listRoleLocations, saveRoleLocations } from '../api/assignmentApi'
import { listLocations } from '../api/locationsApi'
import Icon from '../components/common/Icon'
import MasterImportDialog from '../components/common/MasterImportDialog'
import { Alert, EmptyState, formatDateTime, Loading, PageHead, Pagination, StatusTag } from '../components/common/Ui'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'

const EMPTY_FILTERS = { search: '', status: '', date_from: '', date_to: '' }

function LocationAssignmentDialog({ assignment, locations, onClose, onSaved }) {
  const [selected, setSelected] = useState(assignment.location_ids || [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const toggle = (id) => setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  const allSelected = locations.length > 0 && locations.every((location) => selected.includes(location.id))

  const save = async () => {
    setBusy(true); setError('')
    try { const result = await saveRoleLocations(assignment.role_id, selected); onSaved(result) }
    catch (saveError) { setError(saveError.message || 'Unable to save role locations') }
    finally { setBusy(false) }
  }

  return (
    <div className="dialog-backdrop">
      <div className="dialog dialog-lg" role="dialog" aria-modal="true" aria-labelledby="location-assignment-title">
        <div className="dialog-head"><h2 id="location-assignment-title" className="dialog-title">Assign locations — {assignment.role_name}</h2><p className="dialog-subtitle">Select the active locations available to this role. This replaces the existing set.</p></div>
        <div className="dialog-body">{error && <Alert tone="danger">{error}</Alert>}
          <div className="assignment-select-all"><span className="muted small">{selected.length} of {locations.length} locations selected</span><button type="button" className="btn btn-ghost btn-compact" onClick={() => setSelected(allSelected ? [] : locations.map((item) => item.id))} disabled={!locations.length}>{allSelected ? 'Clear all' : 'Select all'}</button></div>
          {locations.length ? <div className="location-options">{locations.map((location) => <label key={location.id} className="role-option"><input type="checkbox" checked={selected.includes(location.id)} onChange={() => toggle(location.id)} /><span><strong>{location.location_name}</strong><small>{location.location_code} · {location.location_type}{location.parent_location_name ? ` · ${location.parent_location_name}` : ''}</small></span></label>)}</div> : <EmptyState title="No active locations" description="Create an active location in Location Master first." />}
        </div>
        <div className="dialog-foot"><button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button><button type="button" className="btn btn-primary" onClick={save} disabled={busy || !assignment.role_id}><Icon name="checkCircle" size={15} />{busy ? 'Saving…' : 'Save assignments'}</button></div>
      </div>
    </div>
  )
}

export default function RoleLocations() {
  const { isAdmin, hasPermission } = usePermissions()
  const canAssign = isAdmin || hasPermission('assignments:write')
  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [data, setData] = useState({ items: [], total: 0, pages: 0 })
  const [locations, setLocations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editingAssignment, setEditingAssignment] = useState(null)
  const [showImport, setShowImport] = useState(false)
  const [exporting, setExporting] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await listRoleLocations({ ...applied, page, page_size: pageSize })) }
    catch (loadError) { setError(loadError.message || 'Unable to load role locations'); setData({ items: [], total: 0, pages: 0 }) }
    finally { setLoading(false) }
  }, [applied, page, pageSize])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    let active = true
    listLocations({ page: 1, page_size: 200, status: 'Active' }).then((response) => { if (active) setLocations(response.items || []) }).catch(() => undefined)
    return () => { active = false }
  }, [])

  const chips = useMemo(() => [
    ...(applied.search ? [{ key: 'search', label: `Search: ${applied.search}` }] : []),
    ...(applied.status ? [{ key: 'status', label: `Status: ${applied.status}` }] : []),
    ...(applied.date_from ? [{ key: 'date_from', label: `Created from: ${applied.date_from}` }] : []),
    ...(applied.date_to ? [{ key: 'date_to', label: `Created to: ${applied.date_to}` }] : []),
  ], [applied])
  const apply = () => { setApplied({ ...draft }); setPage(1); logUiAction('Role Location Assignment', 'Apply Filter') }
  const reset = () => { setDraft(EMPTY_FILTERS); setApplied(EMPTY_FILTERS); setPage(1); logUiAction('Role Location Assignment', 'Reset Filter') }
  const remove = (key) => { const next = { ...applied, [key]: '' }; setApplied(next); setDraft(next); setPage(1) }
  const exportRows = async (format) => { setExporting(format); setError(''); try { await downloadRoleLocationsExport(format, applied) } catch (exportError) { setError(exportError.message || 'Export failed') } finally { setExporting('') } }

  return (
    <div className="page">
      <PageHead eyebrow="USER MANAGEMENT / ROLE LOCATION ASSIGNMENT" title="Role Location Assignment" description="Control the active operational locations available to each role. CSV/XLSX imports replace each listed role's set using semicolon-separated location codes." actions={<>{canAssign && <button type="button" className="btn btn-secondary" onClick={() => setShowImport(true)}><Icon name="upload" size={15} /> Import</button>}<Link to="/locations" className="btn btn-secondary"><Icon name="mapPin" size={15} /> Location Master</Link><button type="button" className="btn btn-secondary" onClick={load} disabled={loading}><Icon name="refresh" size={15} /> Refresh</button></>} />
      {error && <Alert tone="danger">{error}</Alert>}{notice && <Alert tone="success">{notice}</Alert>}
      <section className="card">
        <div className="toolbar"><div className="toolbar-group"><form className="toolbar-group" onSubmit={(event) => { event.preventDefault(); apply() }}><div className="search-field"><Icon name="search" size={15} className="search-icon" /><input className="input" type="search" value={draft.search} onChange={(event) => setDraft({ ...draft, search: event.target.value })} placeholder="Search role name or description" aria-label="Search roles" /></div><button type="submit" className="btn btn-primary">Search</button></form><button type="button" className={`btn btn-secondary ${showAdvanced ? 'is-active' : ''}`} onClick={() => setShowAdvanced((value) => !value)} aria-expanded={showAdvanced}><Icon name="filter" size={15} /> Advanced filters</button></div><div className="toolbar-spacer" /><div className="toolbar-group" role="group" aria-label="Export role locations"><span className="muted small">Export</span>{['csv', 'xlsx', 'pdf'].map((format) => <button key={format} type="button" className="btn btn-secondary btn-compact" onClick={() => exportRows(format)} disabled={Boolean(exporting)}><Icon name="download" size={14} />{exporting === format ? 'Exporting…' : format.toUpperCase()}</button>)}</div></div>
        <div className="filters-panel">{showAdvanced && <div className="filters-grid"><label className="field"><span className="field-label">Role status</span><select className="select" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="">All statuses</option>{(data.statuses || ['Active', 'Inactive']).map((status) => <option key={status} value={status}>{status}</option>)}</select></label></div>}<div className="date-group"><div className="date-group-title"><Icon name="calendar" size={14} /> Role created date range</div><div className="date-grid"><label className="field"><span className="field-label">From date</span><input className="input" type="date" value={draft.date_from} onChange={(event) => setDraft({ ...draft, date_from: event.target.value })} /></label><label className="field"><span className="field-label">To date</span><input className="input" type="date" value={draft.date_to} onChange={(event) => setDraft({ ...draft, date_to: event.target.value })} /></label></div></div><div className="filter-actions"><button type="button" className="btn btn-primary btn-compact" onClick={apply}>Apply filters</button><button type="button" className="btn btn-secondary btn-compact" onClick={reset}>Reset</button><span className="muted small">Date filters apply independently from general filters.</span></div>{chips.length > 0 && <div className="chip-row" aria-label="Active filters">{chips.map((chip) => <span key={chip.key} className="filter-chip">{chip.label}<button type="button" onClick={() => remove(chip.key)} aria-label={`Remove ${chip.label}`}><Icon name="close" size={12} /></button></span>)}</div>}</div>
        {loading ? <Loading label="Loading role locations…" /> : data.items.length === 0 ? <EmptyState title="No roles found" description="Create roles and locations before configuring location access." /> : <><div className="table-wrap"><table className="data-table"><thead><tr><th>Role</th><th>Status</th><th>Assigned locations</th><th>Count</th><th>Updated</th><th aria-label="Actions" /></tr></thead><tbody>{data.items.map((assignment) => <tr key={assignment.role_id}><td><div className="cell-primary">{assignment.role_name}{assignment.is_reserved && <span className="tag tag-info" style={{ marginLeft: 8 }}>Reserved</span>}</div></td><td><StatusTag status={assignment.status} /></td><td>{assignment.locations.length ? <div className="location-chip-list">{assignment.locations.slice(0, 4).map((location) => <span className="location-chip" key={location.id}>{location.location_name} <small>{location.location_code}</small></span>)}{assignment.locations.length > 4 && <span className="tag">+{assignment.locations.length - 4} more</span>}</div> : <span className="muted">No locations assigned</span>}</td><td>{assignment.location_count}</td><td className="nowrap">{formatDateTime(assignment.updated_at)}</td><td><div className="table-actions">{canAssign && !assignment.is_reserved && assignment.status === 'Active' && <button type="button" className="btn btn-ghost btn-compact" onClick={() => { setEditingAssignment(assignment); setNotice('') }}><Icon name="settings" size={14} /> Assign</button>}</div></td></tr>)}</tbody></table></div><Pagination page={data.page || page} pageSize={data.page_size || pageSize} pages={data.pages || 0} total={data.total || 0} onPageChange={(next) => { setPage(next); logUiAction('Role Location Assignment', 'Change Page', { page: next }) }} onPageSizeChange={(next) => { setPageSize(next); setPage(1); logUiAction('Role Location Assignment', 'Change Page Size', { page_size: next }) }} disabled={loading} /></>}
      </section>
      {editingAssignment && <LocationAssignmentDialog assignment={editingAssignment} locations={locations} onClose={() => setEditingAssignment(null)} onSaved={() => { setEditingAssignment(null); setNotice(`Locations saved for ${editingAssignment.role_name}.`); load() }} />}
      {showImport && <MasterImportDialog title="Role location assignments" templateHeaders={["role_name", "location_codes"]} templateFilename="role-location-import-template.csv" importFile={importRoleLocationsFile} onClose={() => setShowImport(false)} onImported={(result) => { setShowImport(false); setNotice(result.message || 'Role location assignments imported successfully'); load() }} />}
    </div>
  )
}
