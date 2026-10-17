import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { apiGet, apiDownload, buildQuery } from '../api/apiClient'
import { entryOptions, entryLookup, getAssetContext, getEntry, listEntries, createEntry, updateEntry, transitionEntry, calculateEntry, linkedSender, exportEntries } from '../api/operationEntryApi'
import { PageHead, Alert, Loading, Pagination, StatusTag } from '../components/common/Ui'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'
import EntryFeedback, { EntryDialog, useConfirm } from '../components/operationLayouts/EntryFeedback'
import EntryLookup from '../components/operationLayouts/EntryLookup'
import TankGaugingLayout from '../components/operationLayouts/TankGaugingLayout'
import MultiTankBeforeAfterLayout from '../components/operationLayouts/MultiTankBeforeAfterLayout'
import TankerTruckLayout from '../components/operationLayouts/TankerTruckLayout'
import TankerPayloadPreview from '../components/operationLayouts/TankerPayloadPreview'
import ShuttleTrackingLayout from '../components/operationLayouts/ShuttleTrackingLayout'
import FSOTrackingLayout from '../components/operationLayouts/FSOTrackingLayout'
import FlowmeterReadingLayout from '../components/operationLayouts/FlowmeterReadingLayout'
import StockMovementLayout from '../components/operationLayouts/StockMovementLayout'
import VesselCycleLayout from '../components/operationLayouts/VesselCycleLayout'
import EntryImport from '../components/operationLayouts/EntryImport'
import '../styles/operation-entry.css'

const EMPTY = { operation_type_code: '', payload_code: '', operation_id: null, asset_id: null, location_id: null,
  destination_location_id: null, sender_location_id: null, receiver_location_id: null, linked_ticket_id: null,
  convoy_number: '', operation_date: '', operation_start_datetime: '', operation_end_datetime: '', product_name: '', remarks: '' }
const FILTERS = { search: '', status: 'Draft,Rejected', operation_type_code: '', location_id: '', asset_id: '', product_name: '', date_from: '', date_to: '' }
const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 20, pages: 0 }
const CALIBRATION_TEMPLATE = [{ id: 1, columns: [
  { columnName: 'tank_name', interpolationRole: 'Reference', unit: '' },
  { columnName: 'dip_cm', interpolationRole: 'Input X', unit: 'cm' },
  { columnName: 'volume_bbl', interpolationRole: 'Output', unit: 'bbl' },
] }]
const Layouts = { tank_gauging_payload: TankGaugingLayout, multi_tank_payload: MultiTankBeforeAfterLayout,
  tanker_payload: TankerTruckLayout, shuttle_payload: ShuttleTrackingLayout, fso_payload: FSOTrackingLayout,
  flowmeter_payload: FlowmeterReadingLayout, stock_movement: StockMovementLayout, vessel_cycle: VesselCycleLayout }
const human = key => String(key).replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ')
const valueText = v => v === null || v === undefined || v === '' ? '—' : typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 10 }) : String(v)

function SavedBlock({ value }) {
  if (!value || typeof value !== 'object') return <span>{valueText(value)}</span>
  return <dl className="entry-review-values">{Object.entries(value).map(([k,v]) => <div key={k} className={v && typeof v === 'object' ? 'full-width-field' : ''}>
    <dt>{human(k)}</dt><dd>{v && typeof v === 'object' ? <SavedBlock value={v} /> : valueText(v)}</dd>
  </div>)}</dl>
}
function Review({ ticket }) {
  const p = ticket.payload || {}
  if (ticket.payload_code === 'tanker_payload') return <TankerPayloadPreview entry={{ values: [{ fieldCode: 'tanker_payload', fieldValue: p }] }} />
  return <div className="entry-snapshot"><Alert>Saved ticket snapshot. Quantities are not recalculated from a subsequently replaced chart or master.</Alert>
    {Object.entries(p).map(([key, value]) => <details key={key} open={['inputs','calculated','seals'].includes(key)}><summary>{human(key)}</summary><SavedBlock value={value} /></details>)}
  </div>
}
function WorkflowDialog({ ticket, action, onCancel, onDone }) {
  const [remarks, setRemarks] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const reviewNeeded = ['submit','approve'].includes(action)
  const run = async () => {
    setBusy(true); setError('')
    try { const saved = await transitionEntry(ticket.id, action, { version: ticket.version, remarks: remarks || null, review_confirmed: reviewed }); onDone(saved) }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  return <EntryDialog title={`${human(action)} ticket · ${ticket.ticket_number}`} footer={<>
    <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
    <button className={`btn ${action === 'cancel' || action === 'reject' ? 'btn-danger' : 'btn-primary'}`} onClick={run} disabled={busy || (reviewNeeded && !reviewed) || (action === 'reject' && !remarks.trim())}>{busy ? 'Working…' : human(action)}</button>
  </>}>
    {reviewNeeded && <Review ticket={ticket} />}
    <label className="field"><span className="field-label">Remarks {action === 'reject' ? '(required)' : '(required for a seal mismatch)'}</span><textarea className="textarea" rows={3} value={remarks} onChange={e => setRemarks(e.target.value)} maxLength={2000} /></label>
    {reviewNeeded && <label className="entry-review-check"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} /> I have reviewed the saved readings, calculated quantities, route, seals, and cautions.</label>}
    {error && <Alert tone="danger">{error}</Alert>}
  </EntryDialog>
}

function TicketHistory({ ticket }) {
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [data, setData] = useState(EMPTY_PAGE)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    let active = true
    apiGet(`/operation-entries/${ticket.id}/history${buildQuery({ page, page_size: size })}`).then(r => { if(active) setData(r) }).catch(e => { if(active) setError(e.message) })
    logUiAction('Operation Entry', 'View Status History', { ticket: ticket.ticket_number, page })
    return () => { active = false }
  }, [open, page, size, ticket.id, ticket.version])
  return <details className="card entry-history" onToggle={e => setOpen(e.currentTarget.open)}><summary>Ticket status history</summary>
    {error && <Alert tone="danger">{error}</Alert>}
    <div className="table-wrap"><table className="data-table"><thead><tr><th>Action</th><th>From</th><th>To</th><th>Actor</th><th>Remarks</th><th>Time</th></tr></thead><tbody>{data.items.map(h => <tr key={h.id}><td>{h.action}</td><td>{h.from_status || '—'}</td><td>{h.to_status}</td><td>{h.actor_name}</td><td>{h.remarks || '—'}</td><td>{h.created_at}</td></tr>)}</tbody></table></div>
    <Pagination page={page} pageSize={size} pages={data.pages} total={data.total} onPageChange={setPage} onPageSizeChange={n => { setSize(n); setPage(1) }} />
  </details>
}

function OperationEntryPage() {
  const { hasPermission } = usePermissions()
  const confirm = useConfirm()
  const [params] = useSearchParams()
  const [definitions, setDefinitions] = useState([])
  const [defaultLocation, setDefaultLocation] = useState(null)
  const [locationCount, setLocationCount] = useState(0)
  const [form, setForm] = useState(EMPTY)
  const [selected, setSelected] = useState({})
  const [values, setValues] = useState([])
  const [context, setContext] = useState(null)
  const [contextBusy, setContextBusy] = useState(false)
  const [contextError, setContextError] = useState('')
  const [saved, setSaved] = useState(null)
  const [sender, setSender] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [seed, setSeed] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [validation, setValidation] = useState(null)
  const [validating, setValidating] = useState(false)
  const [filters, setFilters] = useState(FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState(EMPTY_PAGE)
  const [listError, setListError] = useState('')
  const [listBusy, setListBusy] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [workflow, setWorkflow] = useState(null)
  const [savePreview, setSavePreview] = useState(null)
  const [importing, setImporting] = useState(false)
  const layoutRef = useRef(null)
  const generation = useRef(0)
  const definition = definitions.find(d => d.operation_type_code === form.operation_type_code)
  const variant = definition?.alternatives?.find(d => d.payload_field_code === form.payload_code)
  const layoutDefinition = variant || definition
  const fields = variant?.fields
  const locked = saved && !['Draft','Rejected'].includes(saved.status)
  const canCreate = hasPermission('operation_entries:create') || (form.linked_ticket_id && hasPermission('receiving_tickets:create'))
  const writable = !locked && (saved ? hasPermission('operation_entries:update') : canCreate)
  const payload = useMemo(() => fields
    ? { inputs: Object.fromEntries(values.map(v => [v.fieldCode, v.fieldValue])) }
    : values.find(v => v.fieldCode === form.payload_code)?.fieldValue || { inputs: {} }, [values, fields, form.payload_code])
  const inputKey = JSON.stringify({ inputs: payload.inputs, meta: fields ? undefined : payload.meta })

  useEffect(() => {
    let active = true
    Promise.all([entryOptions(), entryLookup('locations')]).then(([o,l]) => {
      if (!active) return
      setDefinitions(o.entry_definitions)
      setLocationCount(l.total)
      if (l.total === 1) {
        setDefaultLocation(l.items[0])
        setSelected(s => ({ ...s, location: l.items[0], sender: l.items[0] }))
        setForm(f => ({ ...f, location_id: l.items[0].id, sender_location_id: l.items[0].id }))
      }
    }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [])
  useEffect(() => {
    const warn = e => { if (dirty) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  useEffect(() => {
    let active = true
    setContext(null); setContextError('')
    if (!form.asset_id || locked) return
    setContextBusy(true)
    getAssetContext(form.asset_id, form.linked_ticket_id).then(r => { if (active) { setContext(r); setSelected(s => ({ ...s, asset: r.asset })) } }).catch(e => { if (active) setContextError(e.message) }).finally(() => { if (active) setContextBusy(false) })
    return () => { active = false }
  }, [form.asset_id, form.linked_ticket_id, seed, locked])
  // Server validates the same values used by the original live cards. A stale request
  // may never replace the result for a new asset or a more recent set of readings.
  useEffect(() => {
    let active = true
    setValidation(null)
    if (!form.asset_id || !form.location_id || !form.operation_type_code || locked || contextBusy) return
    setValidating(true)
    const timer = setTimeout(() => calculateEntry({ operation_type_code: form.operation_type_code, payload_code: form.payload_code,
      asset_id: form.asset_id, location_id: form.location_id, linked_ticket_id: form.linked_ticket_id || null, payload }).then(r => { if (active) setValidation(r.validation) })
      .catch(e => { if (active) setValidation({ errors: [e.message], warnings: [] }) }).finally(() => { if (active) setValidating(false) }), 400)
    return () => { active = false; clearTimeout(timer) }
  }, [inputKey, form.asset_id, form.location_id, form.operation_type_code, form.payload_code, locked, contextBusy])
  useEffect(() => {
    let active = true
    setListBusy(true); setListError('')
    const timer = setTimeout(async () => {
      try { const r = await listEntries({ ...filters, page, page_size: pageSize }); if (active) setData(r) }
      catch (e) { if (active) setListError(e.message) }
      finally { if (active) setListBusy(false) }
      logUiAction('Operation Entry', 'Apply Filter', { ...filters, page, pageSize })
    }, 200)
    return () => { active = false; clearTimeout(timer) }
  }, [filters, page, pageSize, refresh])
  // The source's labels precede controls without IDs. Link them without changing
  // JSX geometry; this also covers generated stage cells and their accessible names.
  useEffect(() => {
    const root = layoutRef.current
    if (!root) return
    const associate = () => {
      root.querySelectorAll('label').forEach((label, index) => {
        if (label.htmlFor || label.querySelector('input,select,textarea')) return
        const control = label.parentElement.querySelector('input,select,textarea')
        if (control) { control.id ||= `entry-layout-${seed}-${index}`; label.htmlFor = control.id }
      })
      root.querySelectorAll('td input').forEach((input, index) => {
        if (input.getAttribute('aria-label') || input.id) return
        const row = input.closest('tr'); const column = input.closest('td')?.cellIndex
        const title = input.closest('table')?.querySelectorAll('thead th')[column]?.textContent
        input.setAttribute('aria-label', `${row?.cells[0]?.textContent || 'Tank'} ${title || 'Reading'} ${index}`)
      })
    }
    associate(); const observer = new MutationObserver(associate); observer.observe(root, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [form.payload_code, form.asset_id, context, seed])

  const chooseOperation = useCallback(operation => {
    setSelected(s => ({ ...s, operation })); setForm(f => ({ ...f, operation_id: operation?.id || null })); setDirty(true)
    if (operation) setValues(current => current.map(v => {
      if (v.fieldCode === 'vessel_operation_code') return { ...v, fieldValue: operation.operation_code }
      if (v.fieldCode === 'tank_gauging_payload') return { ...v, fieldValue: { ...(v.fieldValue || {}), inputs: { ...v.fieldValue?.inputs,
        tankOperationCode: operation.operation_code, tankOperationLabel: operation.operation_label,
        tankOperationCategory: operation.operation_category, tankOperationSign: operation.operation_sign } } }
      if (v.fieldCode === 'shuttle_payload' || v.fieldCode === 'fso_payload') {
        const prefix = v.fieldCode === 'shuttle_payload' ? 'vessel_operation_' : 'operation_'
        return { ...v, fieldValue: { ...(v.fieldValue || {}), meta: { ...v.fieldValue?.meta,
          ...Object.fromEntries(['code','label','category','sign'].map(k => [prefix + k, operation['operation_' + k]])) } } }
      }
      return v
    }))
  }, [])
  const operationCodeChanged = useCallback(async code => {
    if (!code) { chooseOperation(null); return }
    try {
      const r = await entryLookup('operations', { location_id: form.location_id, operation_type_code: form.operation_type_code, search: code })
      chooseOperation(r.items.find(o => o.operation_code === code) || null)
    } catch (e) { setError(e.message) }
  }, [form.location_id, form.operation_type_code, chooseOperation])
  const handleValueChange = useCallback((fieldCode, fieldValue) => {
    setValues(current => {
      const old = current.find(v => v.fieldCode === fieldCode)
      if (JSON.stringify(old?.fieldValue) === JSON.stringify(fieldValue)) return current
      return old ? current.map(v => v.fieldCode === fieldCode ? { ...v, fieldValue } : v) : [...current, { fieldCode, fieldValue }]
    })
  }, [])
  const change = (key, value) => { setForm(f => ({ ...f, [key]: value })); setDirty(true); setSuccess('') }
  const setEntryField = useCallback((field, value) => {
    const key = { convoyNumber: 'convoy_number', operationDate: 'operation_date' }[field]
    if (key) setForm(f => ({ ...f, [key]: value }))
  }, [])
  const initializeValues = (code, p = null, stage = '') => {
    const alt = definitions.flatMap(d => d.alternatives || []).find(d => d.payload_field_code === code)
    if (alt) return alt.fields.map(fieldCode => ({ fieldCode, fieldValue: p?.inputs?.[fieldCode] ?? p?.calculated?.[fieldCode] ?? '' }))
    return [{ fieldCode: code, fieldValue: p || { inputs: {} } }, ...(code === 'multi_tank_payload' ? [{ fieldCode: 'barge_event_type', fieldValue: stage }] : [])]
  }
  const changeType = type => {
    const d = definitions.find(x => x.operation_type_code === type)
    setForm(f => ({ ...f, operation_type_code: type, payload_code: d?.payload_field_code || '', asset_id: null, operation_id: null, receiver_location_id: null, destination_location_id: null }))
    setSelected(s => ({ ...s, asset: null, operation: null, receiver: null, destination: null })); setValues(d ? initializeValues(d.payload_field_code) : []); setSeed(v => v+1); setDirty(true)
  }
  const pickLocation = loc => {
    change('location_id', loc?.id || null); change('sender_location_id', loc?.id || null); chooseOperation(null)
    setSelected(s => ({ ...s, location: loc, sender: loc, asset: s.asset?.asset_scope === 'Local' && s.asset.location_id !== loc?.id ? null : s.asset }))
    if (selected.asset?.asset_scope === 'Local' && selected.asset.location_id !== loc?.id) change('asset_id', null)
    setValues(initializeValues(form.payload_code)); setSeed(v => v+1)
  }
  const pickAsset = async asset => {
    if (asset?.asset_scope !== 'Global') {
      change('receiver_location_id', null); change('destination_location_id', null)
      setSelected(s => ({ ...s, receiver: null, destination: null }))
    }
    chooseOperation(null)
    change('asset_id', asset?.id || null); setSelected(s => ({ ...s, asset })); setValues(initializeValues(form.payload_code)); setSeed(v => v+1)
    if (asset?.asset_scope === 'Local' && asset.location_id !== form.location_id) {
      const r = await entryLookup('locations', { id: asset.location_id }); pickLocation(r.items[0]); setSelected(s => ({ ...s, asset })); change('asset_id', asset.id)
    }
  }
  const hydrate = async ticket => {
    const run = ++generation.current
    const [a,o,...locs] = await Promise.all([
      entryLookup('assets', { id: ticket.asset_id }), entryLookup('operations', { id: ticket.operation_id }),
      ...['location_id','destination_location_id','sender_location_id','receiver_location_id'].map(key => ticket[key] ? entryLookup('all-locations', { id: ticket[key] }) : Promise.resolve({ items: [] })),
    ])
    if (run !== generation.current) return
    setSaved(ticket); setSender(null); setForm({ ...EMPTY, ...Object.fromEntries(Object.keys(EMPTY).map(k => [k, ticket[k] ?? EMPTY[k]])),
      operation_start_datetime: ticket.operation_start_datetime?.slice(0,16) || '', operation_end_datetime: ticket.operation_end_datetime?.slice(0,16) || '' })
    setSelected({ asset: a.items[0] || { id: ticket.asset_id, asset_code: ticket.asset_code, asset_name: ticket.asset_name, asset_type_code: ticket.asset_type_code, status: 'Inactive' }, operation: o.items[0],
      location: locs[0].items[0], destination: locs[1].items[0], sender: locs[2].items[0] || locs[0].items[0], receiver: locs[3].items[0] })
    setValues(initializeValues(ticket.payload_code, ticket.payload, ticket.barge_event_type))
    setSeed(v => v+1); setDirty(false); setError('')
    if (ticket.linked_ticket_id) setSender(await linkedSender(ticket.linked_ticket_id))
  }
  const openTicket = async (row, action = null) => {
    setListError('')
    try {
      if (dirty && !action && !await confirm({ title: 'Open ticket', message: 'Replace the unsaved form with this saved ticket?', confirmLabel: 'Open ticket' })) return
      const t = await getEntry(row.id)
      if (action) setWorkflow({ action, ticket: t })
      else { await hydrate(t); window.scrollTo({ top: 0 }); logUiAction('Operation Entry', 'Open Ticket', { ticket: t.ticket_number }) }
    } catch (e) { setListError(e.message) }
  }
  const receive = async id => {
    try {
      if (dirty && !await confirm({ title: 'Create receiving ticket', message: 'Replace the current form with the locked sender route and asset?', confirmLabel: 'Create receiving ticket' })) return
      const t = await linkedSender(id)
      const target = t.receiver_location_id || t.destination_location_id
      const [loc, origin] = await Promise.all([entryLookup('locations', { id: target }), entryLookup('all-locations', { id: t.location_id })])
      if (!loc.items.length) throw new Error('You need the receiving terminal in your role-location scope.')
      await hydrate({ ...t, linked_ticket_id: t.id, location_id: target, destination_location_id: target, sender_location_id: t.location_id, receiver_location_id: target })
      setSaved(null); setSender(t)
      setSelected(s => ({ ...s, location: loc.items[0], destination: loc.items[0], sender: origin.items[0], receiver: loc.items[0], operation: null }))
      setForm(f => ({ ...f, linked_ticket_id: t.id, location_id: target, destination_location_id: target, sender_location_id: t.location_id,
        receiver_location_id: target, operation_id: null, operation_date: '', operation_start_datetime: '', operation_end_datetime: '' }))
      setValues(initializeValues(t.payload_code, null, t.payload_code === 'multi_tank_payload' ? 'UNLOAD' : ''))
      setSeed(v => v+1); setDirty(false); setSuccess('Sender route loaded. Enter independently measured receiving values.')
    } catch (e) { setError(e.message) }
  }
  const prefilled = useRef(false)
  useEffect(() => {
    if (!definitions.length || prefilled.current) return
    prefilled.current = true
    const senderId = params.get('linked_ticket_id') || params.get('sender_transaction_id')
    if (senderId) receive(Number(senderId))
    else if (params.get('ticket_id')) openTicket({ id: Number(params.get('ticket_id')) })
    else if (params.get('primary_asset_code') || params.get('operation_type_code') || params.get('convoy_number')) {
      // OTMS tracking links can prefill a new ticket without introducing an editable
      // template. Every lookup is still scoped, and the API revalidates on save.
      const run = ++generation.current
      ;(async () => {
        try {
          const code = params.get('primary_asset_code')
          const asset = code ? (await entryLookup('assets', { asset_code: code })).items[0] : null
          if (code && !asset) throw new Error('The prefilled asset is not active or is outside your location scope.')
          const requested = params.get('operation_type_code')
          const d = definitions.find(x => x.operation_type_code === requested) || definitions.find(x => x.asset_type_code === asset?.asset_type_code)
          if (!d) throw new Error('Select a supported fixed Operation Type for this reference.')
          const locations = {}
          for (const role of ['origin','destination','sender','receiver']) {
            const locCode = params.get(role + '_location_code')
            if (locCode) {
              const kind = role === 'origin' || role === 'sender' ? 'locations' : 'all-locations'
              const r = await entryLookup(kind, { search: locCode })
              locations[role] = r.items.find(l => l.location_code === locCode)
              if (!locations[role]) throw new Error(`The prefilled ${role} location is unavailable.`)
            }
          }
          if (!locations.origin && asset?.location_id) locations.origin = (await entryLookup('locations', { id: asset.location_id })).items[0]
          locations.origin ||= locations.sender || defaultLocation
          locations.sender ||= locations.origin
          locations.receiver ||= locations.destination
          const opCode = params.get('operation_code')
          const ops = locations.origin ? await entryLookup('operations', { location_id: locations.origin.id, operation_type_code: d.operation_type_code, search: opCode || '' }) : {items:[],total:0}
          const operation = opCode ? ops.items.find(o => o.operation_code === opCode) : ops.total === 1 ? ops.items[0] : null
          if (run !== generation.current) return
          setSelected({ asset, operation, location: locations.origin, destination: locations.destination, sender: locations.sender, receiver: locations.receiver })
          setForm({ ...EMPTY, operation_type_code: d.operation_type_code, payload_code: d.payload_field_code, asset_id: asset?.id || null,
            operation_id: operation?.id || null, location_id: locations.origin?.id || null, destination_location_id: locations.destination?.id || null,
            sender_location_id: locations.sender?.id || null, receiver_location_id: locations.receiver?.id || null,
            convoy_number: params.get('convoy_number') || '', product_name: params.get('product_name') || '', remarks: params.get('remarks') || '' })
          setValues(initializeValues(d.payload_field_code, null, params.get('barge_event_type') || params.get('auto_event_type') || ''))
          setSeed(v => v+1)
          logUiAction('Operation Entry', 'Prefill Tracking Reference', { source: params.get('source'), asset: code })
        } catch (e) { setError(e.message) }
      })()
    }
  }, [definitions])
  const reset = async () => {
    if (dirty && !await confirm({ title: 'New operation ticket', message: 'Discard unsaved changes and start a new ticket?', confirmLabel: 'Start new ticket' })) return
    generation.current++; setSaved(null); setSender(null); setForm({ ...EMPTY, location_id: defaultLocation?.id || null, sender_location_id: defaultLocation?.id || null }); setSelected({ location: defaultLocation, sender: defaultLocation }); setValues([]); setContext(null); setDirty(false); setSeed(v => v+1); setSuccess(''); setError('')
  }
  const buildRequest = () => ({ ...form, sender_location_id: form.sender_location_id || form.location_id, payload: { ...payload, inputs: { ...payload.inputs,
    ...(form.payload_code === 'tanker_payload' ? { convoyNumber: form.convoy_number, cargo: form.product_name } : {}) } },
    barge_event_type: form.payload_code === 'multi_tank_payload' ? values.find(v => v.fieldCode === 'barge_event_type')?.fieldValue || null : null,
    payload_code: form.payload_code || null, convoy_number: form.convoy_number || null,
    operation_start_datetime: form.operation_start_datetime || null, operation_end_datetime: form.operation_end_datetime || null,
  })
  const prepareSave = e => {
    e.preventDefault(); setError('')
    if (!writable) return
    if (!form.operation_type_code || !form.operation_id || !form.asset_id || !form.location_id || !form.operation_date) {
      setError('Operation Type, Operation, Primary Asset, Sender Location and Operation Date are required.'); return
    }
    if (selected.asset?.asset_scope === 'Global' && !form.receiver_location_id) { setError('Select a Receiver Location for this global asset.'); return }
    if (validation?.errors?.length) { setError('Resolve the validation errors beside the entry before saving.'); return }
    setSavePreview(buildRequest())
  }
  const save = async () => {
    setBusy(true); setError('')
    try {
      let r
      if (saved) {
        const { operation_type_code, payload_code, linked_ticket_id, ...update } = savePreview
        r = await updateEntry(saved.id, { ...update, version: saved.version })
      } else r = await createEntry(savePreview)
      setSavePreview(null); await hydrate(r); setSuccess(`Draft saved: ${r.ticket_number}`); setRefresh(v => v+1)
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  const Layout = Layouts[form.payload_code]
  const selectedAsset = useMemo(() => selected.asset ? { ...selected.asset, assetCode: selected.asset.asset_code, assetName: selected.asset.asset_name,
    assetTypeCode: selected.asset.asset_type_code, activeLink: context?.link, sealMasterRows: context?.seals, serialNumber: selected.asset.serial_number, status: selected.asset.status || 'Active' } : null, [selected.asset, context])
  const layoutEntry = useMemo(() => ({ values, operationTemplateId: form.payload_code, primaryAssetCode: selectedAsset?.assetCode || '',
    originLocationCode: selected.location?.location_code || '', operationDate: form.operation_date, convoyNumber: form.convoy_number,
    productName: form.product_name, selectedOperation: selected.operation, onOperationCodeChange: operationCodeChanged,
    status: saved?.status || 'Draft' }), [values, form.payload_code, form.operation_date, form.convoy_number, form.product_name, selectedAsset, selected.location, selected.operation, operationCodeChanged, saved?.status])
  const charts = useMemo(() => context?.chart ? [context.chart] : [], [context])
  const senderReference = useMemo(() => sender?.payload_code === 'tanker_payload' ? {
    ...sender.payload.calculated, ...sender.payload.inputs, transactionId: sender.id, ticketNumber: sender.ticket_number,
    operationTypeName: sender.operation_type_name, operationTypeCode: sender.operation_type_code, productName: sender.product_name, operationNumber: sender.ticket_number,
    convoyNumber: sender.convoy_number, tankerAssetCode: sender.asset_code, primeMoverAssetCode: sender.payload.inputs.primeMoverNumber,
  } : null, [sender])
  const setFilter = (key, value) => { setFilters(f => ({ ...f, [key]: value })); setPage(1) }
  const canReview = hasPermission('operation_reviews:create')
  const rowActions = row => <div className="entry-row-actions">
    <button type="button" className="btn btn-ghost btn-sm" onClick={() => openTicket(row)}>{['Draft','Rejected'].includes(row.status) && hasPermission('operation_entries:update') ? 'Edit' : 'View'}</button>
    {['Draft','Rejected'].includes(row.status) && <>
      {canReview && hasPermission('operation_submissions:create') && <button className="btn btn-secondary btn-sm" onClick={() => openTicket(row, 'submit')}>Submit</button>}
      {hasPermission('operation_entries:delete') && <button className="btn btn-ghost btn-sm" onClick={() => openTicket(row, 'cancel')}>Cancel</button>}
    </>}
    {row.status === 'Submitted' && <>
      {hasPermission('operation_submissions:delete') && <button className="btn btn-secondary btn-sm" onClick={() => openTicket(row, 'recall')}>Recall</button>}
      {canReview && hasPermission('operation_approvals:create') && <button className="btn btn-secondary btn-sm" onClick={() => openTicket(row, 'approve')}>Approve</button>}
      {hasPermission('operation_approvals:update') && <button className="btn btn-ghost btn-sm" onClick={() => openTicket(row, 'reject')}>Reject</button>}
    </>}
    {row.status === 'Approved' && !row.linked_ticket_id && ['BARGE_OPERATIONS','TANKER_OPERATIONS'].includes(row.operation_type_code) && (hasPermission('receiving_tickets:create') || hasPermission('operation_entries:create')) && <button className="btn btn-secondary btn-sm" onClick={() => receive(row.id)}>Receive</button>}
  </div>
  return <div className="page operation-entry">
    <PageHead eyebrow="BUSINESS / OPERATION ENTRY" title="Operation Entry" description="Create operation tickets or edit Draft / Rejected tickets using the fixed OTMS module payloads."
      actions={<><button className="btn btn-secondary" onClick={reset}>New ticket</button>{hasPermission('operation_entries:create') && <button className="btn btn-secondary" onClick={() => setImporting(true)}>Import CSV / XLSX</button>}</>} />
    {!writable && !locked && <Alert>You have view-only access to this form. Creation, editing, review, submission and approval have separate permissions.</Alert>}
    <form onSubmit={prepareSave} className="entry-form" onBlurCapture={e => { if (['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)) logUiAction('Operation Entry', 'Edit Field', { field: e.target.name || e.target.getAttribute('aria-label') || e.target.id }) }}>
      <fieldset disabled={!writable || busy} className="entry-header-grid">
        {form.linked_ticket_id && <div className="full-width-field info-box"><strong>Receiving Ticket</strong> · Linked to {sender?.ticket_number || form.linked_ticket_id}. Route, convoy, and asset are locked to the Approved sender; measure receiver dips and seals independently.</div>}
        <label>Operation Type<select aria-label="Operation Type" name="operation_type_code" required value={form.operation_type_code} disabled={Boolean(saved) || Boolean(sender)} onChange={e => changeType(e.target.value)}>
          <option value="">Select Operation Type</option>{definitions.map(d => <option key={d.operation_type_code} value={d.operation_type_code}>{d.operation_type_name} ({d.asset_type_name})</option>)}
        </select></label>
        <EntryLookup kind="assets" label="Primary Asset" required selected={selected.asset} onPick={pickAsset} disabled={!writable || !definition || Boolean(sender)} params={{ asset_type_code: definition?.asset_type_code, location_id: form.location_id }} />
        <div>
          <EntryLookup kind={sender ? 'all-locations' : 'locations'} label="Sender Location" required selected={selected.sender || selected.location} onPick={pickLocation} disabled={!writable || Boolean(sender) || locationCount === 1} />
          <small>{sender ? 'Route locked to the approved sender ticket.' : locationCount === 1 ? 'Your assigned location is filled automatically.' : 'Select one of your accessible locations.'}</small>
        </div>
        {selected.asset?.asset_scope === 'Global' && <EntryLookup kind="all-locations" label="Receiver Location" required selected={selected.receiver} disabled={!writable || Boolean(sender)} onPick={loc => {
          change('receiver_location_id', loc?.id || null); change('destination_location_id', loc?.id || null)
          setSelected(s => ({ ...s, receiver: loc, destination: loc }))
        }} />}
        <div>
          <label htmlFor="operation-date">Operation Date *</label>
          <div className="entry-date-control"><input id="operation-date" name="operation_date" type="date" required value={form.operation_date} onChange={e => change('operation_date', e.target.value)} />
            <button type="button" className="btn btn-secondary" onClick={() => {
              const now = new Date()
              change('operation_date', `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`)
              logUiAction('Operation Entry', 'Set Current Date')
            }}>Today</button></div>
        </div>
        <label className="full-width-field">Remarks<textarea name="remarks" rows={3} maxLength={4000} value={form.remarks} onChange={e => change('remarks', e.target.value)} /></label>
      </fieldset>
      <fieldset disabled={!writable || busy} className="entry-layout-container" ref={layoutRef} onClickCapture={e => {
        const action = e.target.closest('button, summary'); if (action) logUiAction('Operation Entry', 'Layout Action', { action: action.textContent?.trim() })
      }} onChange={() => { setDirty(true); setSuccess('') }}>
        {definition && <div className="full-width-field operation-layout-banner">
          <div><span>Entry Layout</span>{definition.alternatives?.length && !saved ? <select aria-label="Fixed entry layout" value={form.payload_code} onChange={e => {
            change('payload_code', e.target.value); setValues(initializeValues(e.target.value)); setSeed(v => v+1)
          }}><option value={definition.payload_field_code}>{definition.entry_layout_type}</option>{definition.alternatives.map(d => <option key={d.payload_field_code} value={d.payload_field_code}>{d.entry_layout_type}</option>)}</select> : <strong>{layoutDefinition?.entry_layout_type}</strong>}</div>
          <div><span>Calculation Engine</span><strong>{layoutDefinition?.calculation_engine}</strong></div>
          <div><span>Fixed Payload · no template setup</span><strong>{form.payload_code}</strong></div>
        </div>}
        {!locked && <div className="entry-payload-controls">
          {['multi_tank_payload','tanker_payload','flowmeter_payload'].includes(form.payload_code) && <EntryLookup kind="operations" label="Operation" required selected={selected.operation} onPick={chooseOperation} disabled={!writable || !form.location_id || !form.operation_type_code}
            params={{ location_id: form.location_id, operation_type_code: form.operation_type_code }} />}
        {definition?.requires_convoy_number && !variant && <label>{definition.convoy_label}<input name="convoy_number" maxLength={50} value={form.convoy_number} disabled={Boolean(sender)} onChange={e => change('convoy_number', e.target.value)} /></label>}
        </div>}
        {locked ? <Review ticket={saved} /> : (contextBusy || (form.asset_id && !context && !contextError)) ? <Loading label="Loading selected asset calibration and link…" /> : contextError ? <Alert tone="danger">{contextError}</Alert> : Layout && selectedAsset ?
          <Layout key={`${saved?.id || 'new'}-${seed}-${form.asset_id}-${form.payload_code}`} entry={layoutEntry} editId={saved?.id || null} selectedAsset={selectedAsset}
            assetCalibrationTables={charts} calibrationTemplates={CALIBRATION_TEMPLATE} handleValueChange={handleValueChange} setEntryField={setEntryField}
            receiverMode={Boolean(sender)} senderReference={senderReference} assets={[selectedAsset]} locations={Object.values(selected).filter(s => s?.location_code)} />
          : <div className="info-box">Select an operation type, sender location and primary asset to load its fixed entry layout.</div>}
      </fieldset>
      {!locked && validation && <div className="entry-server-validation" aria-live="polite">
        {validation.errors?.length > 0 && <Alert tone="danger"><strong>Validation errors</strong><ul>{validation.errors.map((message,i) => <li key={i}>{message}</li>)}</ul></Alert>}
        {validation.warnings?.length > 0 && <Alert tone="warning"><strong>Cautions</strong><ul>{validation.warnings.map((message,i) => <li key={i}>{message}</li>)}</ul></Alert>}
      </div>}
      {error && !savePreview && <Alert tone="danger">{error}</Alert>}{success && <Alert tone="success">{success}</Alert>}
      <div className="entry-form-actions">
        {!locked && <button className="btn btn-primary" type="submit" disabled={!writable || busy || contextBusy || validating}>{busy ? 'Saving…' : validating ? 'Validating…' : saved ? 'Update Draft' : 'Save Draft'}</button>}
        {saved && <button className="btn btn-secondary" type="button" onClick={reset}>Close Edit</button>}
        {saved && !dirty && !locked && canReview && hasPermission('operation_submissions:create') && <button type="button" className="btn btn-secondary" onClick={() => setWorkflow({ action: 'submit', ticket: saved })}>Review & Submit</button>}
        {saved && ['csv','xlsx','pdf'].map(format => <button key={format} type="button" className="btn btn-ghost" onClick={async () => {
          try { await apiDownload(`/operation-entries/${saved.id}/export?format=${format}`) } catch(e) { setError(e.message) }
        }}>Ticket {format.toUpperCase()}</button>)}
        {dirty && <small>Unsaved changes</small>}
      </div>
    </form>
    <section className="card entry-register">
      <header className="card-header"><div><h2 className="card-title">{filters.status === 'Draft,Rejected' ? 'Editable Operation Entries' : 'Operation Ticket Register'}</h2>
        <p className="card-subtitle">Draft and Rejected tickets are editable. Submitted tickets must be recalled first. Approved and Cancelled tickets are locked.</p></div></header>
      <div className="entry-list-toolbar">
        <label>Quick search<input placeholder="Ticket / asset / convoy / product…" value={filters.search} onChange={e => setFilter('search', e.target.value)} /></label>
        <label>Status<select value={filters.status} onChange={e => setFilter('status', e.target.value)}><option value="Draft,Rejected">Editable: Draft / Rejected</option><option value="">All tickets</option>{['Draft','Rejected','Submitted','Approved','Cancelled'].map(s => <option key={s}>{s}</option>)}</select></label>
        <button className="btn btn-secondary" onClick={() => setAdvanced(v => !v)} aria-expanded={advanced}>Advanced filters</button>
        <button className="btn btn-ghost" onClick={() => { setFilters(FILTERS); setPage(1) }}>Reset filters</button>
        {['csv','xlsx','pdf'].map(format => <button key={format} className="btn btn-secondary" onClick={async () => { try { await exportEntries(format, filters) } catch (e) { setListError(e.message) } }}>Export {format.toUpperCase()}</button>)}
      </div>
      {advanced && <div className="entry-list-toolbar">
        <label>Operation Type<select value={filters.operation_type_code} onChange={e => setFilter('operation_type_code', e.target.value)}><option value="">All types</option>{definitions.map(d => <option key={d.operation_type_code} value={d.operation_type_code}>{d.operation_type_name}</option>)}</select></label>
        <label>Origin location ID<input type="number" min="1" value={filters.location_id} onChange={e => setFilter('location_id', e.target.value)} /></label>
        <label>Asset ID<input type="number" min="1" value={filters.asset_id} onChange={e => setFilter('asset_id', e.target.value)} /></label>
        <label>Product contains<input value={filters.product_name} onChange={e => setFilter('product_name', e.target.value)} /></label>
      </div>}
      <div className="entry-date-filters"><strong>Operation date</strong><label>From<input type="date" value={filters.date_from} onChange={e => setFilter('date_from', e.target.value)} /></label><label>To<input type="date" value={filters.date_to} onChange={e => setFilter('date_to', e.target.value)} /></label></div>
      <div className="entry-active-filters">{Object.entries(filters).filter(([k,v]) => v && !(k === 'status' && v === 'Draft,Rejected')).map(([k,v]) => <button className="tag" key={k} onClick={() => setFilter(k, '')} aria-label={`Remove ${human(k)} filter`}>{human(k)}: {v} ×</button>)}</div>
      {listError && <Alert tone="danger">{listError}</Alert>}
      <div className="table-wrap"><table className="data-table entry-ticket-table" aria-label="Saved operation tickets" aria-busy={listBusy}><thead><tr>{['Ticket / Date','Operation / Layout','Primary Asset','Sender','Product','Status','Actions'].map(h => <th scope="col" key={h}>{h}</th>)}</tr></thead>
        <tbody>{data.items.map(row => <tr key={row.id}>
          <td><strong className="mono">{row.ticket_number}</strong><small>{row.operation_date}</small></td>
          <td><strong>{row.operation_type_name}</strong><small>{row.entry_layout_type}</small></td>
          <td><strong>{row.asset_name}</strong><small className="mono">{row.asset_code}</small></td>
          <td>{row.location_code}</td><td>{row.product_name || '—'}</td>
          <td><StatusTag status={row.status} tone={row.status === 'Submitted' ? 'warning' : row.status === 'Approved' ? 'success' : row.status === 'Rejected' ? 'danger' : 'info'} /></td>
          <td>{rowActions(row)}</td></tr>)}
          {!data.items.length && <tr><td colSpan={7}>{listBusy ? 'Loading tickets…' : 'No tickets match the current filters.'}</td></tr>}</tbody></table></div>
      <Pagination page={page} pageSize={pageSize} pages={data.pages} total={data.total} onPageChange={setPage} onPageSizeChange={n => { setPageSize(n); setPage(1) }} disabled={listBusy} />
    </section>
    {saved && <TicketHistory key={saved.id} ticket={saved} />}

    {savePreview && <EntryDialog title={saved ? 'Update Draft ticket' : 'Save Draft ticket'} footer={<>
      <button className="btn btn-secondary" disabled={busy} onClick={() => { setSavePreview(null); setError('') }}>Cancel</button>
      <button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : saved ? 'Update Draft' : 'Save Draft'}</button>
    </>}><p>Confirm {layoutDefinition?.entry_layout_type} for <strong>{selectedAsset?.assetCode}</strong> on <strong>{form.operation_date}</strong>. The API validates and recalculates the fixed payload before saving.</p>{error && <Alert tone="danger">{error}</Alert>}</EntryDialog>}
    {workflow && <WorkflowDialog {...workflow} onCancel={() => setWorkflow(null)} onDone={ticket => { setWorkflow(null); setRefresh(v => v+1); if (saved?.id === ticket.id) hydrate(ticket); setSuccess(`${ticket.ticket_number}: ${ticket.status}`) }} />}
    {importing && <EntryImport definitions={definitions} onCancel={() => setImporting(false)} onImported={() => { setImporting(false); setRefresh(v => v+1) }} />}
  </div>
}
export default function OperationEntry() { return <EntryFeedback><OperationEntryPage /></EntryFeedback> }
