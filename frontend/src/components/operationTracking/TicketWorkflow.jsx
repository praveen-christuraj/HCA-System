import { useEffect, useState } from 'react'
import { apiGet, buildQuery } from '../../api/apiClient'
import { transitionEntry } from '../../api/operationEntryApi'
import { Alert, Pagination, formatDateTime } from '../common/Ui'
import { logUiAction } from '../../utils/actionLogger'
import { EntryDialog } from '../operationLayouts/EntryFeedback'
import TankerPayloadPreview from '../operationLayouts/TankerPayloadPreview'

/**
 * Ticket review, workflow and history building blocks shared by Operation Entry
 * (read-only snapshot + history of the ticket being edited) and the Operation
 * Transaction Register / Detail pages, which own every workflow action
 * (submit, recall, approve, reject, cancel) as in OTMS.
 */
const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 20, pages: 0 }
export const human = key => String(key).replace(/([a-z])([A-Z])/g, '$1 $2').replaceAll('_', ' ')
export const valueText = v => v === null || v === undefined || v === '' ? '—' : typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 10 }) : String(v)

export function SavedBlock({ value }) {
  if (!value || typeof value !== 'object') return <span>{valueText(value)}</span>
  return <dl className="entry-review-values">{Object.entries(value).map(([k,v]) => <div key={k} className={v && typeof v === 'object' ? 'full-width-field' : ''}>
    <dt>{human(k)}</dt><dd>{v && typeof v === 'object' ? <SavedBlock value={v} /> : valueText(v)}</dd>
  </div>)}</dl>
}
export function Review({ ticket }) {
  const p = ticket.payload || {}
  if (ticket.payload_code === 'tanker_payload') return <TankerPayloadPreview entry={{ values: [{ fieldCode: 'tanker_payload', fieldValue: p }] }} />
  return <div className="entry-snapshot"><Alert>Saved ticket snapshot. Quantities are not recalculated from a subsequently replaced chart or master.</Alert>
    {Object.entries(p).map(([key, value]) => <details key={key} open={['inputs','calculated','seals'].includes(key)}><summary>{human(key)}</summary><SavedBlock value={value} /></details>)}
  </div>
}
export function WorkflowDialog({ ticket, action, onCancel, onDone }) {
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

export function TicketHistory({ ticket, module = 'Operation Entry', defaultOpen = false }) {
  // OTMS detail pages show the history expanded; Operation Entry keeps it collapsed.
  const [open, setOpen] = useState(defaultOpen)
  const [page, setPage] = useState(1)
  const [size, setSize] = useState(20)
  const [data, setData] = useState(EMPTY_PAGE)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    let active = true
    apiGet(`/operation-entries/${ticket.id}/history${buildQuery({ page, page_size: size })}`).then(r => { if(active) setData(r) }).catch(e => { if(active) setError(e.message) })
    logUiAction(module, 'View Status History', { ticket: ticket.ticket_number, page })
    return () => { active = false }
  }, [open, page, size, ticket.id, ticket.version])
  return <details className="card entry-history" open={defaultOpen || undefined} onToggle={e => setOpen(e.currentTarget.open)}><summary>Ticket status history</summary>
    {error && <Alert tone="danger">{error}</Alert>}
    <div className="table-wrap"><table className="data-table"><thead><tr><th>Action</th><th>From</th><th>To</th><th>Actor</th><th>Remarks</th><th>Time</th></tr></thead><tbody>{data.items.map(h => <tr key={h.id}><td>{h.action}</td><td>{h.from_status || '—'}</td><td>{h.to_status}</td><td>{h.actor_name}</td><td>{h.remarks || '—'}</td><td className="nowrap tnum">{formatDateTime(h.created_at)}</td></tr>)}</tbody></table></div>
    <Pagination page={page} pageSize={size} pages={data.pages} total={data.total} onPageChange={setPage} onPageSizeChange={n => { setSize(n); setPage(1) }} />
  </details>
}


export const WORKFLOW_LABELS = { submit: 'Submit', recall: 'Recall', approve: 'Approve', reject: 'Reject', cancel: 'Cancel ticket' }

/** OTMS detail actions: Draft -> Submit/Cancel; Submitted -> Approve/Reject/Recall; Rejected -> Re-submit/Cancel. */
export function workflowActions(ticket, hasPermission) {
  if (!ticket) return []
  const canReview = hasPermission('operation_reviews:create')
  const actions = []
  if (['Draft', 'Rejected'].includes(ticket.status)) {
    if (canReview && hasPermission('operation_submissions:create')) actions.push({ action: 'submit', label: ticket.status === 'Rejected' ? 'Re-submit' : 'Submit', tone: 'primary' })
    if (hasPermission('operation_entries:delete')) actions.push({ action: 'cancel', label: 'Cancel ticket', tone: 'danger' })
  }
  if (ticket.status === 'Submitted') {
    if (canReview && hasPermission('operation_approvals:create')) actions.push({ action: 'approve', label: 'Approve', tone: 'primary' })
    if (hasPermission('operation_approvals:update')) actions.push({ action: 'reject', label: 'Reject', tone: 'danger' })
    if (hasPermission('operation_submissions:delete')) actions.push({ action: 'recall', label: 'Recall', tone: 'secondary' })
  }
  return actions
}

export const statusTone = status => ({ Submitted: 'warning', Approved: 'success', Rejected: 'danger', Cancelled: 'neutral', Draft: 'info' }[status] || 'neutral')
