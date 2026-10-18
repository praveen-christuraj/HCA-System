import { useCallback, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { acknowledgeTanker, closeTanker, exportTankerTracking, listTankerTracking, revokeTanker } from '../api/operationTrackingApi'
import Icon from '../components/common/Icon'
import { Alert, EmptyState, Loading, PageHead, Pagination, formatDate, formatDateTime } from '../components/common/Ui'
import { EntryDialog } from '../components/operationLayouts/EntryFeedback'
import {
  ExportGroup,
  FactGrid,
  LookupFilter,
  RegisterFilters,
  RemarksDialog,
  TrackingTag,
  filterParams,
  fmt,
  useRegister,
} from '../components/operationTracking/TrackingKit'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'
import '../styles/operation-entry.css'
import '../styles/operation-tracking.css'

const MODULE = 'Tanker Tracking'
const KPIS = [
  ['ALL', 'All', 'all'],
  ['PENDING_RECEIPT', 'Pending receipt', 'pending_receipt'],
  ['ACKNOWLEDGED', 'Acknowledged', 'acknowledged'],
  ['SEAL_MISMATCH', 'Seal mismatch', 'seal_mismatch'],
  ['QUANTITY_VARIANCE', 'Quantity variance', 'quantity_variance'],
  ['MATCHED', 'Matched', 'matched'],
  ['CLOSED', 'Closed', 'closed'],
]
const CLOSABLE = ['SEAL_MISMATCH', 'QUANTITY_VARIANCE', 'MATCHED', 'RECEIVED']

/**
 * OTMS Tanker Tracking: each Approved tanker sender ticket with its receipt
 * acknowledgement, the latest Approved receiver ticket, seal cross-check and
 * receiver − sender quantity variance.
 */
export default function TankerTracking() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { hasPermission } = usePermissions()
  const [status, setStatus] = useState('ALL')
  const [dialog, setDialog] = useState(null)
  const [notice, setNotice] = useState('')
  const initial = { search: params.get('search') || '', convoy_number: '', location: null, asset: null, date_from: '', date_to: '' }
  const fetcher = useCallback((p, page, pageSize) => listTankerTracking({ ...p, status, page, page_size: pageSize }), [status])
  const register = useRegister(initial, fetcher, MODULE)
  const { data, loading, error, draft, setDraft } = register
  const summary = data?.summary || {}

  const canAcknowledge = hasPermission('tanker_tracking:update') || hasPermission('shipment_receipts:create')
  const canRevoke = hasPermission('tanker_tracking:update') || hasPermission('shipment_receipts:delete')
  const canClose = hasPermission('tanker_tracking:update')
  const canCreateReceiver = hasPermission('receiving_tickets:create') || hasPermission('operation_entries:create')

  const done = (message) => {
    setDialog(null)
    setNotice(message)
    register.refresh()
  }

  return (
    <div className="page operation-tracking">
      <PageHead
        eyebrow="OPERATION TRACKING / TANKER TRACKING"
        title="Tanker Tracking"
        description="Approved tanker dispatches with receipt acknowledgement, receiver ticket, seal cross-check and receiver − sender quantity variance. Acknowledge the receipt before the receiving terminal creates its receiver entry."
        actions={
          <button type="button" className="btn btn-secondary" onClick={register.refresh} disabled={loading}>
            <Icon name="refresh" size={15} />
            Refresh
          </button>
        }
      />
      {error && <Alert tone="danger">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}

      <div className="kpi-grid tracking-kpis" role="group" aria-label="Tracking status">
        {KPIS.map(([key, label, field]) => (
          <button
            key={key}
            type="button"
            className={`kpi-card tracking-kpi${status === key ? ' is-active' : ''}`}
            aria-pressed={status === key}
            onClick={() => {
              setStatus(key)
              register.setPage(1)
              logUiAction(MODULE, 'Filter Status', { status: key })
            }}
          >
            <span className="kpi-label">{label}</span>
            <span className="kpi-value">{summary[field] ?? '—'}</span>
          </button>
        ))}
      </div>

      <section className="card">
        <RegisterFilters
          register={register}
          searchPlaceholder="Search ticket, convoy or tanker"
          chipLabels={{ search: 'Search', convoy_number: 'Convoy', location: 'Location', asset: 'Tanker', date_from: 'From', date_to: 'To' }}
          exportSlot={<ExportGroup label="Export tracking" onExport={(format) => exportTankerTracking(format, { ...filterParams(register.applied), status })} />}
          advanced={
            <>
              <label className="field">
                <span className="field-label">Convoy number</span>
                <input className="input" maxLength={50} value={draft.convoy_number} onChange={(event) => setDraft({ ...draft, convoy_number: event.target.value })} />
              </label>
              <LookupFilter kind="locations" label="Location" value={draft.location} onChange={(location) => setDraft({ ...draft, location })} />
              <LookupFilter kind="assets" label="Tanker" value={draft.asset} onChange={(asset) => setDraft({ ...draft, asset })} params={{ asset_type_code: 'TANKER_TRAILER' }} />
            </>
          }
        />
        {loading && !data ? (
          <Loading label="Loading tanker movements…" />
        ) : !data?.items?.length ? (
          <EmptyState title="No tanker movements match the current filters" description="Movements appear once a tanker dispatch ticket is Approved." />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table" aria-busy={loading}>
                <thead>
                  <tr>
                    <th>Date / Convoy</th>
                    <th>Tanker</th>
                    <th>Sender ticket</th>
                    <th>Receiving</th>
                    <th>Receiver ticket</th>
                    <th className="num">Sender NSV</th>
                    <th className="num">Receiver NSV</th>
                    <th className="num">Variance</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => {
                    const quantity = row.quantity_comparison
                    const ack = row.acknowledgement
                    return (
                      <tr key={row.group_key}>
                        <td>
                          <div className="cell-primary">{formatDate(row.operation_date)}</div>
                          <div className="cell-sub cell-mono">{row.convoy_number || '—'}</div>
                        </td>
                        <td>
                          <div className="cell-primary">{row.tanker_asset_code}</div>
                          <div className="cell-sub">{[row.prime_mover_asset_code, row.tanker_chassis_number].filter(Boolean).join(' · ') || '—'}</div>
                        </td>
                        <td className="cell-mono">{row.sender_ticket?.ticket_number || '—'}</td>
                        <td>{row.receiving_location_code || '—'}</td>
                        <td className="cell-mono">
                          {row.latest_receiver_ticket?.ticket_number || (row.receiver_in_progress ? `${row.receiver_in_progress.ticket_number} (${row.receiver_in_progress.status})` : '—')}
                        </td>
                        <td className="num tnum">{fmt(quantity?.sender_nsv ?? row.sender_ticket?.nsv_bbl)}</td>
                        <td className="num tnum">{fmt(quantity?.receiver_nsv ?? row.latest_receiver_ticket?.nsv_bbl)}</td>
                        <td className={`num tnum${quantity?.nsv_variance ? ' tracking-delta' : ''}`}>{quantity ? fmt(quantity.nsv_variance) : '—'}</td>
                        <td>
                          <TrackingTag value={row.tracking_status} />
                          {row.warning_messages.length > 0 && <div className="cell-sub">{row.warning_messages[0]}</div>}
                        </td>
                        <td>
                          <div className="table-actions">
                            <button type="button" className="btn btn-ghost btn-compact" onClick={() => setDialog({ type: 'view', row })}>
                              <Icon name="eye" size={14} />
                              View
                            </button>
                            {canAcknowledge && row.tracking_status === 'PENDING_RECEIPT' && (
                              <button type="button" className="btn btn-primary btn-compact" onClick={() => setDialog({ type: 'ack', row })}>Acknowledge</button>
                            )}
                            {canCreateReceiver && row.can_create_receiver && (
                              <button
                                type="button"
                                className="btn btn-secondary btn-compact"
                                onClick={() => {
                                  logUiAction(MODULE, 'Create Receiver Entry', { sender: row.sender_ticket.ticket_number })
                                  navigate(`/operation-entry?source=tanker-tracking&linked_ticket_id=${row.sender_ticket.id}`)
                                }}
                              >
                                Create receiver entry
                              </button>
                            )}
                            {canRevoke && ack?.status === 'Acknowledged' && row.tracking_status === 'ACKNOWLEDGED' && !row.receiver_in_progress && (
                              <button type="button" className="btn btn-ghost btn-compact" onClick={() => setDialog({ type: 'revoke', row })}>Revoke</button>
                            )}
                            {canClose && ack?.status === 'Acknowledged' && CLOSABLE.includes(row.tracking_status) && (
                              <button type="button" className="btn btn-secondary btn-compact" onClick={() => setDialog({ type: 'close', row })}>Close</button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <Pagination
              page={register.page}
              pageSize={register.pageSize}
              pages={data.pages}
              total={data.total}
              onPageChange={register.setPage}
              onPageSizeChange={register.setPageSize}
              disabled={loading}
            />
          </>
        )}
      </section>

      {dialog?.type === 'view' && <MovementDialog row={dialog.row} onCancel={() => setDialog(null)} canOpenTicket={hasPermission('operation_transactions:read')} />}
      {dialog?.type === 'ack' && (
        <RemarksDialog
          title={`Acknowledge receipt · ${dialog.row.tanker_asset_code}`}
          message={`Confirm tanker ${dialog.row.tanker_asset_code} (sender ticket ${dialog.row.sender_ticket.ticket_number}) has arrived at ${dialog.row.receiving_location_code || 'the receiving terminal'}.`}
          confirmLabel="Acknowledge receipt"
          optional
          onCancel={() => setDialog(null)}
          onConfirm={async (remarks) => {
            await acknowledgeTanker({ sender_entry_id: dialog.row.sender_ticket.id, receiver_location_id: dialog.row.receiving_location_id, remarks })
            done(`Receipt acknowledged for ${dialog.row.tanker_asset_code}.`)
          }}
        />
      )}
      {dialog?.type === 'revoke' && (
        <RemarksDialog
          title={`Revoke acknowledgement · ${dialog.row.tanker_asset_code}`}
          message="Revoking returns the movement to pending receipt. It is blocked once a receiver ticket exists."
          confirmLabel="Revoke"
          tone="danger"
          onCancel={() => setDialog(null)}
          onConfirm={async (remarks) => {
            await revokeTanker(dialog.row.acknowledgement.id, { remarks })
            done(`Acknowledgement revoked for ${dialog.row.tanker_asset_code}.`)
          }}
        />
      )}
      {dialog?.type === 'close' && (
        <RemarksDialog
          title={`Close movement · ${dialog.row.tanker_asset_code}`}
          message="Closing records that the sender vs receiver comparison has been reviewed."
          confirmLabel="Close movement"
          onCancel={() => setDialog(null)}
          onConfirm={async (remarks) => {
            await closeTanker(dialog.row.acknowledgement.id, { remarks })
            done(`Movement closed for ${dialog.row.tanker_asset_code}.`)
          }}
        />
      )}
    </div>
  )
}

function TicketLink({ ticket, canOpen }) {
  if (!ticket) return '—'
  return canOpen ? <Link to={`/operation-transactions/${ticket.id}`}>{ticket.ticket_number}</Link> : ticket.ticket_number
}

/** Movement Transaction Report (MTR) view for one tanker movement; printable. */
function MovementDialog({ row, onCancel, canOpenTicket }) {
  const quantity = row.quantity_comparison
  const ack = row.acknowledgement
  return (
    <EntryDialog
      title={`Tanker movement · ${row.tanker_asset_code}`}
      footer={
        <>
          <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              logUiAction(MODULE, 'Print MTR', { sender: row.sender_ticket?.ticket_number })
              window.print()
            }}
          >
            Print MTR
          </button>
        </>
      }
    >
      <div className="tracking-print-area">
        <p><TrackingTag value={row.tracking_status} /></p>
        {row.warning_messages.map((message) => <Alert key={message} tone="warning">{message}</Alert>)}
        <FactGrid
          items={[
            ['Convoy', row.convoy_number],
            ['Product', row.product_name],
            ['Prime mover', row.prime_mover_asset_code ? `${row.prime_mover_asset_name || ''} (${row.prime_mover_asset_code})` : null],
            ['Tanker', `${row.tanker_asset_name} (${row.tanker_asset_code})`],
            ['Chassis', row.tanker_chassis_number],
            ['Sender ticket', <TicketLink key="s" ticket={row.sender_ticket} canOpen={canOpenTicket} />],
            ['Receiving location', row.receiving_location_code],
            ['Receiver ticket', <TicketLink key="r" ticket={row.latest_receiver_ticket} canOpen={canOpenTicket} />],
            ['Acknowledged', ack?.acknowledged_at ? `${ack.acknowledged_by} · ${formatDateTime(ack.acknowledged_at)}` : null],
            ['Acknowledgement status', ack?.status],
            ['Closed', ack?.closed_at ? `${ack.closed_by} · ${formatDateTime(ack.closed_at)}` : null],
            ['Remarks', ack?.closure_remarks || ack?.revoke_remarks || ack?.remarks],
          ]}
        />
        <h3 className="section-title">Quantity comparison (receiver − sender)</h3>
        {quantity ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th className="num">Sender</th>
                  <th className="num">Receiver</th>
                  <th className="num">Variance</th>
                </tr>
              </thead>
              <tbody>
                {[['gov', 'GOV (bbl)'], ['gsv', 'GSV (bbl)'], ['nsv', 'NSV (bbl)'], ['lt', 'Long tons'], ['mt', 'Metric tons']].map(([key, label]) => (
                  <tr key={key}>
                    <td>{label}</td>
                    <td className="num tnum">{fmt(quantity[`sender_${key}`])}</td>
                    <td className="num tnum">{fmt(quantity[`receiver_${key}`])}</td>
                    <td className={`num tnum${quantity[`${key}_variance`] ? ' tracking-delta' : ''}`}>{fmt(quantity[`${key}_variance`])}</td>
                  </tr>
                ))}
                <tr>
                  <td>NSV variance %</td>
                  <td />
                  <td />
                  <td className="num tnum">{fmt(quantity.nsv_variance_pct, 4)}%</td>
                </tr>
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted small">The comparison appears once the receiver ticket is Approved.</p>
        )}
        <h3 className="section-title">Seal cross-check</h3>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Seal</th>
                <th>Sender</th>
                <th>Receiver</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {row.seal_checks.map((seal) => (
                <tr key={seal.seal_name}>
                  <td>{seal.seal_name}</td>
                  <td className="cell-mono">{seal.sender_value || '—'}</td>
                  <td className="cell-mono">{seal.receiver_value || '—'}</td>
                  <td><TrackingTag value={seal.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </EntryDialog>
  )
}
