import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  acknowledgeBargeReceipt,
  closeBargeConvoy,
  exportBargeConvoy,
  exportBargeVoyages,
  fixBargeTimeline,
  getBargeConvoy,
  listBargeVoyages,
  reopenBargeConvoy,
  revokeBargeReceipt,
} from '../api/operationTrackingApi'
import Icon from '../components/common/Icon'
import { Alert, EmptyState, Loading, PageHead, Pagination, StatusTag, formatDate, formatDateTime } from '../components/common/Ui'
import { statusTone } from '../components/operationTracking/TicketWorkflow'
import {
  ExportGroup,
  FactGrid,
  LookupFilter,
  RegisterFilters,
  RemarksDialog,
  TabStrip,
  TrackingTag,
  filterParams,
  fmt,
  humanCode,
  useRegister,
} from '../components/operationTracking/TrackingKit'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'
import '../styles/operation-entry.css'
import '../styles/operation-tracking.css'

const MODULE = 'Barge Tracking'
const INITIAL = { search: '', location: null, date_from: '', date_to: '' }
const EVENT_TYPES = ['LOAD_1', 'LOAD_2_TOPUP', 'UNLOAD', 'STS']

/** OTMS Barge Tracking: convoy voyages (OPEN / CLOSED) and the convoy MTR view. */
export default function BargeTracking() {
  const [params, setParams] = useSearchParams()
  const convoy = params.get('convoy')
  return convoy ? (
    <ConvoyDetail convoy={convoy} onBack={() => setParams({})} />
  ) : (
    <BargeVoyages onOpen={(number) => setParams({ convoy: number })} />
  )
}

function BargeVoyages({ onOpen }) {
  const [tab, setTab] = useState('OPEN')
  const fetcher = useCallback((p, page, pageSize) => listBargeVoyages({ ...p, tab, page, page_size: pageSize }), [tab])
  const register = useRegister(INITIAL, fetcher, MODULE)
  const { data, loading, error, draft, setDraft } = register
  return (
    <div className="page operation-tracking">
      <PageHead
        eyebrow="OPERATION TRACKING / BARGE TRACKING"
        title="Barge Tracking"
        description="Barge convoys built from Approved barge tickets. Open a convoy to acknowledge receipt, create the receiving ticket, fix the load / unload timeline, compare LOAD AFTER vs UNLOAD BEFORE and close the movement."
        actions={
          <button type="button" className="btn btn-secondary" onClick={register.refresh} disabled={loading}>
            <Icon name="refresh" size={15} />
            Refresh
          </button>
        }
      />
      {error && <Alert tone="danger">{error}</Alert>}
      <section className="card">
        <TabStrip
          label="Convoy status"
          value={tab}
          onChange={(key) => {
            setTab(key)
            register.setPage(1)
            logUiAction(MODULE, 'Change Tab', { tab: key })
          }}
          tabs={[
            { key: 'OPEN', label: 'Open', count: data?.open_count },
            { key: 'CLOSED', label: 'Closed', count: data?.closed_count },
          ]}
        />
        <RegisterFilters
          register={register}
          searchPlaceholder="Search convoy, barge or ticket"
          chipLabels={{ search: 'Search', location: 'Location', date_from: 'From', date_to: 'To' }}
          exportSlot={<ExportGroup label="Export voyages" onExport={(format) => exportBargeVoyages(format, { ...filterParams(register.applied), tab })} />}
          advanced={<LookupFilter kind="locations" label="Location" value={draft.location} onChange={(location) => setDraft({ ...draft, location })} />}
        />
        {loading && !data ? (
          <Loading label="Loading barge convoys…" />
        ) : !data?.items?.length ? (
          <EmptyState title={`No ${tab.toLowerCase()} convoys`} description="Convoys appear once a barge ticket with a convoy number is Approved." />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table" aria-busy={loading}>
                <thead>
                  <tr>
                    <th>Convoy</th>
                    <th>Status</th>
                    <th>Barges</th>
                    <th>Tickets</th>
                    <th>Route</th>
                    <th>Dates</th>
                    <th>{tab === 'CLOSED' ? 'Closed' : 'Remarks'}</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <tr key={row.convoy_number}>
                      <td className="cell-primary cell-mono">{row.convoy_number}</td>
                      <td><TrackingTag value={row.status} /></td>
                      <td>{row.barges.map((barge) => barge.asset_code).join(', ')}</td>
                      <td className="tnum">{row.ticket_count}</td>
                      <td>
                        {row.origin_location_codes.join(', ') || '—'} → {row.destination_location_codes.join(', ') || '—'}
                      </td>
                      <td className="nowrap">
                        {formatDate(row.first_operation_date)}
                        {row.last_operation_date !== row.first_operation_date && ` – ${formatDate(row.last_operation_date)}`}
                      </td>
                      <td>
                        {tab === 'CLOSED' ? (
                          <>
                            <div className="cell-primary">{row.closed_by || '—'}</div>
                            <div className="cell-sub">{formatDateTime(row.closed_at)}</div>
                          </>
                        ) : (
                          row.closure_remarks || '—'
                        )}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-secondary btn-compact"
                          onClick={() => {
                            logUiAction(MODULE, 'Open Convoy', { convoy: row.convoy_number })
                            onOpen(row.convoy_number)
                          }}
                        >
                          <Icon name="eye" size={14} />
                          Open
                        </button>
                      </td>
                    </tr>
                  ))}
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
    </div>
  )
}

function ConvoyDetail({ convoy, onBack }) {
  const navigate = useNavigate()
  const { hasPermission } = usePermissions()
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [dialog, setDialog] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setState(await getBargeConvoy(convoy))
    } catch (loadError) {
      setError(loadError.message || 'Unable to load the convoy')
    } finally {
      setLoading(false)
    }
  }, [convoy])

  useEffect(() => {
    load()
  }, [load])

  const canReceive = hasPermission('barge_tracking:update') || hasPermission('shipment_receipts:create')
  const canRevoke = hasPermission('barge_tracking:update') || hasPermission('shipment_receipts:delete')
  const canFix = hasPermission('barge_tracking:update')
  const canCloseVoyage = hasPermission('operation_voyages:update')
  const canCreateReceiver = hasPermission('receiving_tickets:create') || hasPermission('operation_entries:create')
  const open = state?.status === 'OPEN'

  const finish = (next, message) => {
    setState(next || state)
    setDialog(null)
    setNotice(message)
    if (!next) load()
  }

  return (
    <div className="page operation-tracking">
      <PageHead
        eyebrow="OPERATION TRACKING / BARGE TRACKING / CONVOY"
        title={`Convoy ${convoy}`}
        description="Approved barge tickets, the per-barge load / unload timeline and the LOAD AFTER vs UNLOAD BEFORE comparison (delta = left − right)."
        actions={
          <>
            <button type="button" className="btn btn-secondary" onClick={onBack}>Back to voyages</button>
            <button type="button" className="btn btn-secondary" onClick={() => window.print()} disabled={!state}>Print</button>
            <button type="button" className="btn btn-secondary" onClick={load} disabled={loading}>
              <Icon name="refresh" size={15} />
              Refresh
            </button>
          </>
        }
      />
      {error && <Alert tone="danger">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}
      {loading && !state ? (
        <Loading label="Loading convoy…" />
      ) : state ? (
        <>
          <section className="card">
            <div className="card-head">
              <div>
                <h2 className="card-title">Movement summary</h2>
                <p className="card-subtitle"><TrackingTag value={state.status} /></p>
              </div>
              <div className="toolbar-group tracking-actions">
                {open && canCloseVoyage && (
                  <button type="button" className="btn btn-primary" disabled={!state.can_close} onClick={() => setDialog({ type: 'close' })}>
                    Close movement
                  </button>
                )}
                {!open && canCloseVoyage && (
                  <button type="button" className="btn btn-secondary" onClick={() => setDialog({ type: 'reopen' })}>Reopen movement</button>
                )}
              </div>
            </div>
            <div className="card-body">
              <FactGrid
                items={[
                  ['Barges', state.barges.length],
                  ['Tickets', state.tickets.length],
                  ['Comparisons', state.comparison_count],
                  ['Open tickets', state.open_ticket_count],
                  ['Closed', state.closed_at ? `${state.closed_by} · ${formatDateTime(state.closed_at)}` : null],
                  ['Closure / reopen remarks', state.closure_remarks],
                ]}
              />
              {open && state.close_blockers.length > 0 && (
                <Alert tone="warning">
                  <strong>Close is blocked</strong>
                  <ul>{state.close_blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>
                </Alert>
              )}
              <div className="tracking-export-row">
                <ExportGroup label="Movement Transaction Report (MTR)" onExport={(format) => exportBargeConvoy(convoy, format)} />
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head"><h2 className="card-title">Tickets</h2></div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Ticket</th>
                    <th>Date</th>
                    <th>Barge</th>
                    <th>Operation</th>
                    <th>Event</th>
                    <th>Route</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {state.tickets.map((ticket) => (
                    <tr key={ticket.id}>
                      <td className="cell-mono">
                        {hasPermission('operation_transactions:read') ? <Link to={`/operation-transactions/${ticket.id}`}>{ticket.ticket_number}</Link> : ticket.ticket_number}
                      </td>
                      <td className="nowrap">{formatDate(ticket.operation_date)}</td>
                      <td>{ticket.asset_code}</td>
                      <td>{ticket.operation_label || ticket.operation_code}</td>
                      <td>{ticket.event_type ? humanCode(ticket.event_type) : '—'}</td>
                      <td>{ticket.location_code} → {ticket.receiver_location_code || ticket.destination_location_code || '—'}</td>
                      <td><StatusTag status={ticket.status} tone={statusTone(ticket.status)} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {state.barges.map((barge) => (
            <section key={barge.asset_id} className="card">
              <div className="card-head">
                <div>
                  <h2 className="card-title">{barge.asset_name} ({barge.asset_code})</h2>
                  <p className="card-subtitle">
                    {barge.received ? (
                      <TrackingTag value="RECEIVED" label={`Received ${formatDateTime(barge.received_at)} by ${barge.received_by || '—'}`} />
                    ) : barge.pending_sender_ticket ? (
                      <TrackingTag value="PENDING_RECEIPT" label={`Awaiting receipt at ${barge.receipt_location_code || '—'}`} />
                    ) : (
                      <span className="muted">No load ticket awaiting receipt</span>
                    )}
                    {barge.receiver_ticket_exists && <span className="muted"> · Receiving ticket created</span>}
                  </p>
                </div>
                {open && (
                  <div className="toolbar-group tracking-actions">
                    {canReceive && !barge.received && barge.pending_sender_ticket && (
                      <button type="button" className="btn btn-primary btn-compact" onClick={() => setDialog({ type: 'receive', barge })}>
                        Acknowledge receipt
                      </button>
                    )}
                    {canRevoke && barge.received && !barge.receiver_ticket_exists && (
                      <button type="button" className="btn btn-ghost btn-compact" onClick={() => setDialog({ type: 'revoke', barge })}>
                        Revoke receipt
                      </button>
                    )}
                    {canCreateReceiver && barge.received && barge.pending_sender_ticket && !barge.receiver_ticket_exists && (
                      <button
                        type="button"
                        className="btn btn-secondary btn-compact"
                        onClick={() => {
                          logUiAction(MODULE, 'Create Receiving Ticket', { convoy, barge: barge.asset_code })
                          navigate(
                            `/operation-entry?source=barge-tracking&linked_ticket_id=${barge.pending_sender_ticket.id}&convoy_number=${encodeURIComponent(convoy)}&primary_asset_code=${encodeURIComponent(barge.asset_code)}`,
                          )
                        }}
                      >
                        Create receiving ticket
                      </button>
                    )}
                    {canFix && (
                      <button type="button" className="btn btn-secondary btn-compact" onClick={() => setDialog({ type: 'fix', barge })}>
                        Fix timeline
                      </button>
                    )}
                  </div>
                )}
              </div>
              <div className="card-body">
                {!barge.received && barge.pending_sender_ticket && (
                  <Alert>Acknowledge the receipt before creating the receiving (UNLOAD) ticket, as in OTMS.</Alert>
                )}
                <h3 className="section-title">Timeline</h3>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Event</th>
                        <th>Source</th>
                        <th>Date / time</th>
                        <th>Location</th>
                        <th>Ticket</th>
                        <th>Remarks</th>
                      </tr>
                    </thead>
                    <tbody>
                      {barge.timeline.map((row) => (
                        <tr key={`${row.kind}-${row.sequence_no}`}>
                          <td className="tnum">{row.sequence_no}</td>
                          <td>{humanCode(row.event_type)}</td>
                          <td>{humanCode(row.source)}</td>
                          <td className="nowrap">{formatDateTime(row.event_datetime)}</td>
                          <td>{row.location_code || '—'}</td>
                          <td className="cell-mono">{row.ticket_number || '—'}</td>
                          <td>{row.remarks || (row.recorded_by ? `By ${row.recorded_by}` : '—')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <h3 className="section-title">LOAD AFTER vs UNLOAD BEFORE comparison</h3>
                {barge.comparisons.length === 0 ? (
                  <p className="muted small">No comparison yet. It appears when an Approved multi-tank UNLOAD ticket follows an Approved load ticket for this barge.</p>
                ) : (
                  barge.comparisons.map((comparison) => <Comparison key={`${comparison.left_ticket.id}-${comparison.right_ticket.id}`} comparison={comparison} />)
                )}
              </div>
            </section>
          ))}
        </>
      ) : null}

      {dialog?.type === 'close' && (
        <RemarksDialog
          title={`Close convoy ${convoy}`}
          message="Closing locks the convoy: no new barge ticket can be created against it until it is reopened."
          confirmLabel="Close movement"
          onCancel={() => setDialog(null)}
          onConfirm={async (remarks) => finish(await closeBargeConvoy({ convoy_number: convoy, remarks }), `Convoy ${convoy} closed.`)}
        />
      )}
      {dialog?.type === 'reopen' && (
        <RemarksDialog
          title={`Reopen convoy ${convoy}`}
          confirmLabel="Reopen movement"
          onCancel={() => setDialog(null)}
          onConfirm={async (remarks) => finish(await reopenBargeConvoy({ convoy_number: convoy, remarks }), `Convoy ${convoy} reopened.`)}
        />
      )}
      {dialog?.type === 'receive' && (
        <RemarksDialog
          title={`Acknowledge receipt · ${dialog.barge.asset_code}`}
          message={`Confirm barge ${dialog.barge.asset_code} has arrived at ${dialog.barge.receipt_location_code || 'the receiving location'} (sender ticket ${dialog.barge.pending_sender_ticket?.ticket_number}).`}
          confirmLabel="Acknowledge receipt"
          optional
          onCancel={() => setDialog(null)}
          onConfirm={async (remarks) => {
            await acknowledgeBargeReceipt({ convoy_number: convoy, asset_id: dialog.barge.asset_id, remarks })
            finish(null, `Receipt acknowledged for ${dialog.barge.asset_code}.`)
          }}
        />
      )}
      {dialog?.type === 'revoke' && (
        <RemarksDialog
          title={`Revoke receipt · ${dialog.barge.asset_code}`}
          message="Revoking returns the barge to awaiting receipt. It is not allowed once a receiving ticket exists."
          confirmLabel="Revoke receipt"
          tone="danger"
          onCancel={() => setDialog(null)}
          onConfirm={async (remarks) => {
            await revokeBargeReceipt({ convoy_number: convoy, asset_id: dialog.barge.asset_id, remarks })
            finish(null, `Receipt revoked for ${dialog.barge.asset_code}.`)
          }}
        />
      )}
      {dialog?.type === 'fix' && (
        <FixTimelineDialog
          convoy={convoy}
          barge={dialog.barge}
          onCancel={() => setDialog(null)}
          onDone={(message) => finish(null, message)}
        />
      )}
    </div>
  )
}

function FixTimelineDialog({ convoy, barge, onCancel, onDone }) {
  const tickets = barge.timeline.filter((row) => row.kind === 'TICKET')
  const [entryId, setEntryId] = useState(tickets[0]?.ticket_id || '')
  const current = tickets.find((row) => row.ticket_id === Number(entryId))
  const [eventType, setEventType] = useState(current?.event_type || 'LOAD_1')
  return (
    <RemarksDialog
      title={`Fix timeline · ${barge.asset_code}`}
      message="Override the derived event type of an Approved ticket. The override is stored and audited; the ticket itself is not changed."
      confirmLabel="Save event type"
      onCancel={onCancel}
      onConfirm={async (remarks) => {
        await fixBargeTimeline({ convoy_number: convoy, entry_id: Number(entryId), event_type: eventType, remarks })
        onDone(`Timeline updated for ${barge.asset_code}.`)
      }}
    >
      <div className="form-grid form-grid-2">
        <label className="field">
          <span className="field-label">Ticket</span>
          <select
            className="select"
            value={entryId}
            onChange={(event) => {
              setEntryId(event.target.value)
              const row = tickets.find((item) => item.ticket_id === Number(event.target.value))
              if (row) setEventType(row.event_type)
            }}
          >
            {tickets.map((row) => (
              <option key={row.ticket_id} value={row.ticket_id}>
                {row.ticket_number} · {humanCode(row.event_type)} ({humanCode(row.source)})
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">Event type</span>
          <select className="select" value={eventType} onChange={(event) => setEventType(event.target.value)}>
            {EVENT_TYPES.map((type) => <option key={type} value={type}>{humanCode(type)}</option>)}
          </select>
        </label>
      </div>
    </RemarksDialog>
  )
}

function Comparison({ comparison }) {
  return (
    <div className="tracking-comparison">
      <div className="tracking-comparison-head">
        <strong>
          {comparison.left_ticket.ticket_number} (AFTER) → {comparison.right_ticket.ticket_number} (BEFORE)
        </strong>
        <span className={comparison.nsv_delta_bbl ? 'tag tag-warning' : 'tag tag-success'}>
          NSV delta {fmt(comparison.nsv_delta_bbl)} bbl ({fmt(comparison.nsv_delta_pct, 4)}%)
        </span>
        <span className={comparison.seal_issue_count ? 'tag tag-danger' : 'tag tag-success'}>
          {comparison.seal_issue_count ? `${comparison.seal_issue_count} seal issue(s)` : 'Seals match'}
        </span>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Parameter</th>
              <th className="num">Left (after)</th>
              <th className="num">Right (before)</th>
              <th className="num">Delta</th>
            </tr>
          </thead>
          <tbody>
            {comparison.totals.map((row) => (
              <tr key={row.parameter}>
                <td>{row.parameter}</td>
                <td className="num tnum">{fmt(row.left)}</td>
                <td className="num tnum">{fmt(row.right)}</td>
                <td className={`num tnum${row.delta ? ' tracking-delta' : ''}`}>{fmt(row.delta)}</td>
              </tr>
            ))}
            {comparison.quality.map((row) => (
              <tr key={row.parameter}>
                <td>{row.parameter}</td>
                <td className="num tnum">{fmt(row.left, 5)}</td>
                <td className="num tnum">{fmt(row.right, 5)}</td>
                <td className="num muted">—</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {comparison.per_tank.length > 0 && (
        <details className="tracking-details">
          <summary>Per-tank comparison ({comparison.per_tank.length} tanks)</summary>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Tank</th>
                  {['Total dip', 'Water dip', 'TOV corrected', 'FW corrected'].map((label) => <th key={label} className="num">{label} (L / R / Δ)</th>)}
                </tr>
              </thead>
              <tbody>
                {comparison.per_tank.map((tank) => (
                  <tr key={tank.tank}>
                    <td>{tank.tank}</td>
                    {['totalDip', 'waterDip', 'tovCorrected', 'fwCorrected'].map((key) => (
                      <td key={key} className="num tnum">
                        {fmt(tank[key].left)} / {fmt(tank[key].right)} / <strong>{fmt(tank[key].delta)}</strong>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      <details className="tracking-details" open={comparison.seal_issue_count > 0}>
        <summary>Seal checks</summary>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Seal</th>
                <th>Master</th>
                <th>Sender (after)</th>
                <th>Receiver</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {comparison.temporary_seal_checks.map((seal) => (
                <tr key={seal.key}>
                  <td>{seal.seal} (temporary)</td>
                  <td>—</td>
                  <td className="cell-mono">{seal.sender || '—'}</td>
                  <td className="cell-mono">{seal.receiver || '—'}</td>
                  <td><TrackingTag value={seal.status} /></td>
                </tr>
              ))}
              {comparison.permanent_seal_checks.map((seal) => (
                <tr key={`${seal.tank}-${seal.position}`}>
                  <td>Tank {seal.tank} · {seal.position}</td>
                  <td className="cell-mono">{seal.master || '—'}</td>
                  <td className="cell-mono">{seal.sender || '—'}</td>
                  <td className="cell-mono">{seal.receiver || '—'}</td>
                  <td><TrackingTag value={seal.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}
