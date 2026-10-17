import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { createLocation, deactivateLocation, downloadLocationsExport, importLocationsFile, listLocations, updateLocation } from '../api/locationsApi'
import Icon from '../components/common/Icon'
import MasterImportDialog from '../components/common/MasterImportDialog'
import { Alert, EmptyState, formatDateTime, Loading, PageHead, Pagination, StatusTag } from '../components/common/Ui'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'

const EMPTY_FILTERS = { search: '', status: '', location_type: '', parent_location_id: '', date_from: '', date_to: '' }
const LOCATION_TEMPLATE = ['location_name', 'location_code', 'location_type', 'parent_location_code', 'description', 'status']

function LocationDialog({ location, locations, onClose, onSaved }) {
  const [form, setForm] = useState({
    location_name: location?.location_name || '',
    location_code: location?.location_code || '',
    location_type: location?.location_type || '',
    parent_location_id: location?.parent_location_id ? String(location.parent_location_id) : '',
    description: location?.description || '',
    status: location?.status || 'Active',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const parentOptions = locations.filter((item) => item.status === 'Active' && item.id !== location?.id)

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    const payload = {
      ...form,
      location_code: form.location_code.trim().toUpperCase(),
      parent_location_id: form.parent_location_id ? Number(form.parent_location_id) : null,
      description: form.description.trim() || null,
    }
    try {
      const result = location ? await updateLocation(location.id, payload) : await createLocation(payload)
      onSaved(result, location ? 'Location updated successfully' : 'Location created successfully')
    } catch (saveError) {
      setError(saveError.message || 'Unable to save the location')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <form className="dialog dialog-lg" role="dialog" aria-modal="true" aria-labelledby="location-dialog-title" onSubmit={submit}>
        <div className="dialog-head">
          <h2 id="location-dialog-title" className="dialog-title">{location ? 'Edit location' : 'Add location'}</h2>
          <p className="dialog-subtitle">Define an operational location and, optionally, its parent in the location hierarchy.</p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="form-grid-2" style={{ marginTop: error ? 14 : 0 }}>
            <label className="field"><span className="field-label">Location name</span><input className="input" required minLength={2} maxLength={150} autoFocus value={form.location_name} onChange={(event) => setForm({ ...form, location_name: event.target.value })} /></label>
            <label className="field"><span className="field-label">Location code</span><input className="input" required minLength={1} maxLength={50} pattern="[A-Za-z0-9._-]+" value={form.location_code} onChange={(event) => setForm({ ...form, location_code: event.target.value.toUpperCase() })} /><span className="field-help">Letters, numbers, periods, underscores and hyphens.</span></label>
            <label className="field"><span className="field-label">Location type</span><input className="input" required minLength={2} maxLength={100} value={form.location_type} onChange={(event) => setForm({ ...form, location_type: event.target.value })} placeholder="Terminal, plant, tank farm…" /></label>
            <label className="field"><span className="field-label">Parent location</span><select className="select" value={form.parent_location_id} onChange={(event) => setForm({ ...form, parent_location_id: event.target.value })}><option value="">No parent</option>{parentOptions.map((parent) => <option key={parent.id} value={parent.id}>{parent.location_name} ({parent.location_code})</option>)}</select></label>
            <label className="field"><span className="field-label">Status</span><select className="select" value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="Active">Active</option><option value="Inactive">Inactive</option></select></label>
            <label className="field"><span className="field-label">Description</span><textarea className="textarea" maxLength={2000} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
          </div>
        </div>
        <div className="dialog-foot"><button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button><button type="submit" className="btn btn-primary" disabled={busy}><Icon name="checkCircle" size={15} /> {busy ? 'Saving…' : location ? 'Save changes' : 'Create location'}</button></div>
      </form>
    </div>
  )
}

export default function Locations() {
  const { isAdmin, hasPermission } = usePermissions()
  const canCreate = isAdmin || hasPermission('locations:create')
  const canUpdate = isAdmin || hasPermission('locations:update')
  const canDelete = isAdmin || hasPermission('locations:delete')
  const canViewRoleLocations = isAdmin || hasPermission('roles:read')
  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [data, setData] = useState({ items: [], total: 0, pages: 0 })
  const [parentOptions, setParentOptions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editingLocation, setEditingLocation] = useState(null)
  const [showDialog, setShowDialog] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [exporting, setExporting] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await listLocations({ ...applied, page, page_size: pageSize })
      setData(response)
    } catch (loadError) {
      setError(loadError.message || 'Unable to load locations')
      setData({ items: [], total: 0, pages: 0 })
    } finally { setLoading(false) }
  }, [applied, page, pageSize])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    let active = true
    listLocations({ page: 1, page_size: 200, status: 'Active' })
      .then((response) => { if (active) setParentOptions(response.items || []) })
      .catch(() => undefined)
    return () => { active = false }
  }, [])

  const activeChips = useMemo(() => [
    ...(applied.search ? [{ key: 'search', label: `Search: ${applied.search}` }] : []),
    ...(applied.status ? [{ key: 'status', label: `Status: ${applied.status}` }] : []),
    ...(applied.location_type ? [{ key: 'location_type', label: `Type: ${applied.location_type}` }] : []),
    ...(applied.parent_location_id ? [{ key: 'parent_location_id', label: `Parent: ${parentOptions.find((item) => String(item.id) === String(applied.parent_location_id))?.location_name || applied.parent_location_id}` }] : []),
    ...(applied.date_from ? [{ key: 'date_from', label: `Created from: ${applied.date_from}` }] : []),
    ...(applied.date_to ? [{ key: 'date_to', label: `Created to: ${applied.date_to}` }] : []),
  ], [applied, parentOptions])

  const applyFilters = () => { setApplied({ ...draft }); setPage(1); logUiAction('Location Master', 'Apply Filter') }
  const resetFilters = () => { setDraft(EMPTY_FILTERS); setApplied(EMPTY_FILTERS); setPage(1); logUiAction('Location Master', 'Reset Filter') }
  const removeChip = (key) => { const next = { ...applied, [key]: '' }; setApplied(next); setDraft(next); setPage(1) }

  const exportRows = async (format) => {
    setExporting(format); setError('')
    try { await downloadLocationsExport(format, applied) }
    catch (exportError) { setError(exportError.message || 'Export failed') }
    finally { setExporting('') }
  }

  const saveComplete = (location, message) => {
    setShowDialog(false); setEditingLocation(null); setNotice(message); setPage(1); load()
  }
  const handleDeactivate = async (location) => {
    if (!window.confirm(`Deactivate “${location.location_name}”?`)) return
    setError('')
    try { await deactivateLocation(location.id); setNotice(`${location.location_name} has been deactivated.`); load() }
    catch (deactivateError) { setError(deactivateError.message || 'Unable to deactivate the location') }
  }

  return (
    <div className="page">
      <PageHead eyebrow="MASTER DATA / LOCATION MASTER" title="Location Master" description="Configure operational locations and their parent hierarchy. Active locations can be assigned to roles; deactivation preserves master history." actions={<>{canViewRoleLocations && <Link to="/role-locations" className="btn btn-secondary"><Icon name="mapPin" size={15} /> Role locations</Link>}{canCreate && <button type="button" className="btn btn-primary" onClick={() => { setEditingLocation(null); setShowDialog(true); setNotice('') }}><Icon name="mapPin" size={15} /> Add location</button>}<button type="button" className="btn btn-secondary" onClick={load} disabled={loading}><Icon name="refresh" size={15} /> Refresh</button></>} />
      {error && <Alert tone="danger">{error}</Alert>}{notice && <Alert tone="success">{notice}</Alert>}

      <section className="card">
        <div className="toolbar"><div className="toolbar-group"><form className="toolbar-group" onSubmit={(event) => { event.preventDefault(); applyFilters() }}><div className="search-field"><Icon name="search" size={15} className="search-icon" /><input className="input" type="search" value={draft.search} onChange={(event) => setDraft({ ...draft, search: event.target.value })} placeholder="Search name, code, type or description" aria-label="Search locations" /></div><button type="submit" className="btn btn-primary">Search</button></form><button type="button" className={`btn btn-secondary ${showAdvanced ? 'is-active' : ''}`} onClick={() => setShowAdvanced((value) => !value)} aria-expanded={showAdvanced}><Icon name="filter" size={15} /> Advanced filters</button></div><div className="toolbar-spacer" />{canCreate && <button type="button" className="btn btn-secondary" onClick={() => setShowImport(true)}><Icon name="upload" size={15} /> Import</button>}<div className="toolbar-group" role="group" aria-label="Export locations"><span className="muted small">Export</span>{['csv', 'xlsx', 'pdf'].map((format) => <button key={format} type="button" className="btn btn-secondary btn-compact" onClick={() => exportRows(format)} disabled={Boolean(exporting)}><Icon name="download" size={14} />{exporting === format ? 'Exporting…' : format.toUpperCase()}</button>)}</div></div>
        <div className="filters-panel">
          {showAdvanced && <div className="filters-grid"><label className="field"><span className="field-label">Status</span><select className="select" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="">All statuses</option>{(data.statuses || ['Active', 'Inactive']).map((status) => <option key={status} value={status}>{status}</option>)}</select></label><label className="field"><span className="field-label">Location type</span><select className="select" value={draft.location_type} onChange={(event) => setDraft({ ...draft, location_type: event.target.value })}><option value="">All types</option>{(data.location_types || []).map((type) => <option key={type} value={type}>{type}</option>)}</select></label><label className="field"><span className="field-label">Parent location</span><select className="select" value={draft.parent_location_id} onChange={(event) => setDraft({ ...draft, parent_location_id: event.target.value })}><option value="">All parent locations</option>{parentOptions.map((parent) => <option key={parent.id} value={parent.id}>{parent.location_name}</option>)}</select></label></div>}
          <div className="date-group"><div className="date-group-title"><Icon name="calendar" size={14} /> Created date range</div><div className="date-grid"><label className="field"><span className="field-label">From date</span><input className="input" type="date" value={draft.date_from} onChange={(event) => setDraft({ ...draft, date_from: event.target.value })} /></label><label className="field"><span className="field-label">To date</span><input className="input" type="date" value={draft.date_to} onChange={(event) => setDraft({ ...draft, date_to: event.target.value })} /></label></div></div>
          <div className="filter-actions"><button type="button" className="btn btn-primary btn-compact" onClick={applyFilters}>Apply filters</button><button type="button" className="btn btn-secondary btn-compact" onClick={resetFilters}>Reset</button><span className="muted small">Date filters apply independently from general filters.</span></div>
          {activeChips.length > 0 && <div className="chip-row" aria-label="Active filters">{activeChips.map((chip) => <span key={chip.key} className="filter-chip">{chip.label}<button type="button" onClick={() => removeChip(chip.key)} aria-label={`Remove ${chip.label}`}><Icon name="close" size={12} /></button></span>)}</div>}
        </div>
        {loading ? <Loading label="Loading locations…" /> : data.items.length === 0 ? <EmptyState title="No locations match the current filters" description="Adjust your search or filters, or add a location." /> : <><div className="table-wrap"><table className="data-table"><thead><tr><th>Location</th><th>Type</th><th>Parent</th><th>Status</th><th>Created</th><th aria-label="Actions" /></tr></thead><tbody>{data.items.map((location) => <tr key={location.id}><td><div className="cell-primary">{location.location_name}</div><div className="cell-sub cell-mono">{location.location_code}</div></td><td>{location.location_type}</td><td>{location.parent_location_name ? <><div>{location.parent_location_name}</div><div className="cell-sub cell-mono">{location.parent_location_code}</div></> : '—'}</td><td><StatusTag status={location.status} /></td><td className="nowrap">{formatDateTime(location.created_at)}</td><td><div className="table-actions">{canUpdate && <button type="button" className="btn btn-ghost btn-compact" onClick={() => { setEditingLocation(location); setShowDialog(true) }}><Icon name="settings" size={14} /> Edit</button>}{canDelete && location.status === 'Active' && <button type="button" className="btn btn-ghost btn-compact" onClick={() => handleDeactivate(location)}><Icon name="close" size={14} /> Deactivate</button>}</div></td></tr>)}</tbody></table></div><Pagination page={data.page || page} pageSize={data.page_size || pageSize} pages={data.pages || 0} total={data.total || 0} onPageChange={(next) => { setPage(next); logUiAction('Location Master', 'Change Page', { page: next }) }} onPageSizeChange={(next) => { setPageSize(next); setPage(1); logUiAction('Location Master', 'Change Page Size', { page_size: next }) }} disabled={loading} /></>}
      </section>
      {showDialog && <LocationDialog location={editingLocation} locations={parentOptions} onClose={() => { setShowDialog(false); setEditingLocation(null) }} onSaved={saveComplete} />}
      {showImport && <MasterImportDialog title="Locations" templateHeaders={LOCATION_TEMPLATE} templateFilename="location-import-template.csv" importFile={importLocationsFile} onClose={() => setShowImport(false)} onImported={(result) => { setShowImport(false); setNotice(result.message || 'Locations imported successfully'); setPage(1); load(); listLocations({ page: 1, page_size: 200, status: 'Active' }).then((response) => setParentOptions(response.items || [])).catch(() => undefined) }} />}
    </div>
  )
}
