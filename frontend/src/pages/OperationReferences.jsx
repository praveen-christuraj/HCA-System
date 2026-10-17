import { useEffect, useState } from 'react'
import { apiGet, apiPost, apiPut, apiDelete, apiDownload, apiUpload, buildQuery } from '../api/apiClient'
import { entryLookup } from '../api/operationEntryApi'
import { usePermissions } from '../hooks/usePermissions'
import { PageHead, Alert, Pagination, StatusTag } from '../components/common/Ui'
import MasterImportDialog from '../components/common/MasterImportDialog'
import EntryFeedback, { EntryDialog, useConfirm } from '../components/operationLayouts/EntryFeedback'
import EntryLookup from '../components/operationLayouts/EntryLookup'
import { logUiAction } from '../utils/actionLogger'
import '../styles/operation-entry.css'

const TYPES = ['', 'TANK_OPERATIONS','BARGE_OPERATIONS','SHUTTLE_OPERATIONS','FSO_OPERATIONS','TANKER_OPERATIONS','FLOWMETER_OPERATIONS']
const ASSETS = ['', 'STORAGE_TANK','BARGE','SHUTTLE_VESSEL','FSO','TANKER_TRAILER','FLOWMETER']
const CONFIG = {
  table11: { title: 'Table 11 Factors', resource: 'operation_references', description: 'Upload the reference API@60 / LT factors used by your operation. No factors are generated or presented as certified by HCA.', fields: { api60: 'number', lt_factor: 'number' }, defaults: {} },
  meters: { title: 'Flowmeter Config', resource: 'operation_references', description: 'Configure the meters, factors and units for a flowmeter stream. The entry page reads these values; operators cannot override the factor in a ticket.',
    fields: { location_id: 'location', asset_id: 'asset', meter_asset_id: 'optional-asset', stream_name: 'text', meter_label: 'text', meter_factor: 'number', meter_unit: ['bbls','m3'], calibration_date: 'date', remarks: 'text', status: ['Active','Inactive'] }, defaults: { meter_factor: 1, meter_unit: 'bbls', status: 'Active' } },
  seals: { title: 'Barge Seal Master', resource: 'operation_references', description: 'Permanent master seals by declared tank and position. Entry captures observed seals separately and requires remarks for submission mismatches.',
    fields: { asset_id: 'barge', tank_id: 'tank', seal_position: ['MH1','MH2','LOCK','DIPHATCH'], seal_number: 'text', effective_date: 'date', remarks: 'text', status: ['Active','Inactive'] }, defaults: { seal_position: 'MH1', status: 'Active' } },
  policies: { title: 'Workflow Policies', resource: 'operation_policies', description: 'Optional extra gate after capability and location checks. No matching policy: normal RBAC applies. Matching policies: allowed roles or user overrides are required. Admin cannot be locked out.',
    fields: { policy_name: 'text', action_code: ['CREATE_ENTRY','EDIT_ENTRY','REVIEW','SUBMIT','RECALL','APPROVE','REJECT','CANCEL'], operation_type_code: TYPES, asset_type_code: ASSETS, location_id: 'optional-location', payload_code: 'text', priority: 'number', role_ids: 'ids', allow_user_ids: 'ids', deny_user_ids: 'ids', status: ['Active','Inactive'] }, defaults: { priority: 100, action_code: 'CREATE_ENTRY', status: 'Active' } },
  voyages: { title: 'Voyage Controls', resource: 'operation_voyages', description: 'Trips are created by operation tickets. Close only after open tickets are finished or cancelled. Closed shuttle discharges can then be fetched by FSO entry. Tracking reports are a separate module.',
    fields: { status: ['OPEN','CLOSED'], closure_remarks: 'text' }, defaults: {}, generated: true },
}
const label = key => key.replaceAll('_',' ').replace(/\b\w/g, c => c.toUpperCase())
function ReferenceEditor({ kind, row, onSaved, onCancel }) {
  const config = CONFIG[kind]
  const [form, setForm] = useState(Object.fromEntries(Object.keys(config.fields).map(k => [k, Array.isArray(row?.[k]) ? row[k].join(';') : row?.[k] ?? config.defaults[k] ?? ''])))
  const [chosen, setChosen] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    for (const [key, type] of Object.entries(config.fields)) {
      if (row?.[key] && /asset|barge|location/.test(type)) entryLookup(type.includes('location') ? 'locations' : 'assets', { id: row[key] }).then(r => setChosen(c => ({ ...c, [key]: r.items[0] }))).catch(e => setError(e.message))
    }
  }, [])
  const save = async () => {
    setBusy(true); setError('')
    try {
      const body = Object.fromEntries(Object.entries(form).map(([key,value]) => [key, config.fields[key] === 'ids' ? String(value).split(';').filter(Boolean).map(Number) : value === '' ? null : config.fields[key] === 'number' || key.endsWith('_id') ? Number(value) : value]))
      const r = row ? await apiPut(`/operation-references/${kind}/${row.id}`, body) : await apiPost(`/operation-references/${kind}`, body)
      onSaved(r)
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  const set = (key,value) => setForm(f => ({ ...f, [key]: value }))
  return <EntryDialog title={`${row ? 'Edit' : 'Add'} ${config.title}`} footer={<><button className="btn btn-secondary" disabled={busy} onClick={onCancel}>Cancel</button><button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save reference'}</button></>}>
    <div className="entry-header-grid">{Object.entries(config.fields).map(([key,type]) => {
      if (typeof type === 'string' && /asset|barge|location/.test(type)) return <EntryLookup key={key} kind={type.includes('location') ? 'locations' : 'assets'} label={label(key)} required={!type.startsWith('optional')} selected={chosen[key]}
        params={type === 'barge' ? { asset_type_code: 'BARGE' } : type.includes('asset') ? { asset_type_code: 'FLOWMETER' } : {}} onPick={r => { setChosen(c => ({ ...c, [key]: r })); set(key,r?.id || ''); if (key === 'asset_id') set('tank_id','') }} />
      return <label key={key}>{label(key)}{Array.isArray(type) ? <select value={form[key] ?? ''} onChange={e => set(key,e.target.value)}>{type.map(v => <option key={v} value={v}>{v || 'Any / unrestricted'}</option>)}</select> : type === 'tank' ? <select value={form[key] ?? ''} onChange={e => set(key,e.target.value)}><option value="">Select declared tank</option>{chosen.asset_id?.tanks?.map(t => <option key={t.id} value={t.id}>{t.tank_name}</option>)}</select> : <input type={type === 'number' ? 'number' : type === 'date' ? 'date' : 'text'} step="any" value={form[key] ?? ''} onChange={e => set(key,e.target.value)} />}
        {type === 'ids' && <small>Existing IDs separated by semicolons. Empty means no grants in this list.</small>}
      </label>
    })}</div>{error && <Alert tone="danger">{error}</Alert>}
  </EntryDialog>
}
function ReferencesPage() {
  const { hasPermission } = usePermissions()
  const confirm = useConfirm()
  const tabs = Object.keys(CONFIG).filter(k => hasPermission(CONFIG[k].resource + ':read'))
  const [kind, setKind] = useState(tabs[0] || 'table11')
  const config = CONFIG[kind]
  const [filters, setFilters] = useState({ search: '', status: '', asset_id: '', location_id: '', date_from: '', date_to: '' })
  const [data, setData] = useState({ items: [], total: 0, pages: 0 })
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(null)
  const [importing, setImporting] = useState(false)
  const [refresh, setRefresh] = useState(0)
  useEffect(() => {
    let active = true; setBusy(true); setError('')
    const timer = setTimeout(() => apiGet(`/operation-references/${kind}${buildQuery({ ...filters, page, page_size: size })}`).then(r => { if (active) setData(r) })
      .catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setBusy(false) }), 200)
    logUiAction(config.title, 'Apply Filter', { ...filters, page, page_size: size })
    return () => { active = false; clearTimeout(timer) }
  }, [kind, filters, page, size, refresh])
  const refreshData = () => { setRefresh(v => v+1); setEditing(null); setImporting(false) }
  const setFilter = (key,v) => { setFilters(f => ({ ...f, [key]: v })); setPage(1) }
  const columns = kind === 'voyages' ? ['reference','operation_type_code','asset_name','status','closed_at'] : ['id', ...Object.keys(config.fields).filter(k => !['remarks','allow_user_ids','deny_user_ids'].includes(k))]
  return <div className="page operation-entry">
    <PageHead eyebrow="CONFIGURATIONS / OPERATION REFERENCES" title="Operation References" description="Reference data and controls consumed by the fixed Operation Entry layouts." />
    <div className="entry-form-actions" role="tablist" aria-label="Operation reference modules">{tabs.map(k => <button role="tab" aria-selected={kind === k} key={k} className={`btn ${kind === k ? 'btn-primary' : 'btn-secondary'}`} onClick={() => { setKind(k); setPage(1); setFilters({ search: '',status:'',asset_id:'',location_id:'',date_from:'',date_to:'' }) }}>{CONFIG[k].title}</button>)}</div>
    <section className="card"><header className="card-header"><div><h2 className="card-title">{config.title}</h2><p className="card-subtitle">{config.description}</p></div></header>
      <div className="entry-list-toolbar"><label>Quick search<input value={filters.search} onChange={e => setFilter('search',e.target.value)} placeholder={kind === 'table11' ? 'API @60 value' : 'Reference / name / number…'} /></label>
        {kind !== 'table11' && <label>Status<select value={filters.status} onChange={e => setFilter('status',e.target.value)}><option value="">All</option>{(kind === 'voyages' ? ['OPEN','CLOSED'] : ['Active','Inactive']).map(s => <option key={s}>{s}</option>)}</select></label>}
        {!config.generated && hasPermission(config.resource + ':create') && <><button className="btn btn-primary" onClick={() => setEditing({ row: null })}>Add reference</button><button className="btn btn-secondary" onClick={() => setImporting(true)}>Import CSV / XLSX</button></>}
        {['csv','xlsx','pdf'].map(format => <button key={format} className="btn btn-secondary" onClick={async () => { try { await apiDownload(`/operation-references/${kind}/export${buildQuery({ ...filters, format })}`) } catch (e) { setError(e.message) } }}>Export {format.toUpperCase()}</button>)}
      </div>
      {['meters','seals','voyages'].includes(kind) && <details className="entry-list-toolbar"><summary>Advanced filters</summary><label>Asset ID<input type="number" min="1" value={filters.asset_id} onChange={e => setFilter('asset_id',e.target.value)} /></label>{kind !== 'seals' && <label>Location ID<input type="number" min="1" value={filters.location_id} onChange={e => setFilter('location_id',e.target.value)} /></label>}</details>}
      <div className="entry-date-filters"><strong>Created dates</strong><label>From<input type="date" value={filters.date_from} onChange={e => setFilter('date_from',e.target.value)} /></label><label>To<input type="date" value={filters.date_to} onChange={e => setFilter('date_to',e.target.value)} /></label><button className="btn btn-ghost" onClick={() => { setFilters({search:'',status:'',asset_id:'',location_id:'',date_from:'',date_to:''}); setPage(1) }}>Reset filters</button></div>
      <div className="entry-active-filters">{Object.entries(filters).filter(([,v]) => v).map(([k,v]) => <button key={k} className="tag" onClick={() => setFilter(k,'')}>{label(k)}: {v} ×</button>)}</div>
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="table-wrap"><table className="data-table" aria-busy={busy}><thead><tr>{columns.map(k => <th key={k}>{label(k)}</th>)}<th>Actions</th></tr></thead><tbody>{data.items.map(row => <tr key={row.id}>{columns.map(k => <td key={k}>{k === 'status' ? <StatusTag status={row[k]} /> : Array.isArray(row[k]) ? row[k].join('; ') : String(row[k] ?? '—')}</td>)}<td><div className="entry-row-actions">
        {hasPermission(config.resource + ':update') && <button className="btn btn-ghost" onClick={() => setEditing({ row })}>{config.generated ? 'Close / reopen' : 'Edit'}</button>}
        {!config.generated && hasPermission(config.resource + ':delete') && <button className="btn btn-ghost" onClick={async () => {
          if (!await confirm({ title: kind === 'table11' ? 'Delete factor' : 'Deactivate reference', message: 'Existing ticket snapshots are preserved. New entry lookups will use the remaining active references.', confirmLabel: 'Confirm' })) return
          try { await apiDelete(`/operation-references/${kind}/${row.id}`); refreshData() } catch (e) { setError(e.message) }
        }}>{kind === 'table11' ? 'Delete' : 'Deactivate'}</button>}
      </div></td></tr>)}{!data.items.length && <tr><td colSpan={columns.length+1}>{busy ? 'Loading…' : 'No references configured for these filters.'}</td></tr>}</tbody></table></div>
      <Pagination page={page} pageSize={size} total={data.total} pages={data.pages} onPageChange={setPage} onPageSizeChange={n => { setSize(n); setPage(1) }} disabled={busy} />
    </section>
    {config.generated && <Alert>Voyages cannot be imported: they are generated from operation tickets. Use close/reopen controls with audited remarks.</Alert>}
    {editing && <ReferenceEditor key={`${kind}-${editing.row?.id || 'new'}`} kind={kind} row={editing.row} onSaved={refreshData} onCancel={() => setEditing(null)} />}
    {importing && <MasterImportDialog title={config.title} templateHeaders={Object.keys(config.fields)} templateFilename={`${kind}-template.csv`} onClose={() => setImporting(false)} onImported={refreshData} importFile={(file, confirm) => {
      const d = new FormData(); d.append('file', file); d.append('confirm', confirm); return apiUpload(`/operation-references/${kind}/import`, d)
    }} />}
  </div>
}
export default function OperationReferences() { return <EntryFeedback><ReferencesPage /></EntryFeedback> }
