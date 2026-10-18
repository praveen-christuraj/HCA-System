import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { apiDownload } from '../api/apiClient'
import { getEntry } from '../api/operationEntryApi'
import Icon from '../components/common/Icon'
import { Alert, Loading, PageHead, StatusTag, formatDate, formatDateTime } from '../components/common/Ui'
import { Review, TicketHistory, WorkflowDialog, statusTone, workflowActions } from '../components/operationTracking/TicketWorkflow'
import { ExportGroup, FactGrid } from '../components/operationTracking/TrackingKit'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'
import '../styles/operation-entry.css'
import '../styles/operation-tracking.css'

const MODULE = 'Operation Transaction Register'

/** OTMS transaction detail: saved snapshot, workflow actions, history, print/export. */
export default function OperationTransactionDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { hasPermission } = usePermissions()
  const [ticket, setTicket] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [workflow, setWorkflow] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setTicket(await getEntry(id))
    } catch (loadError) {
      setError(loadError.message || 'Unable to load the ticket')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const actions = workflowActions(ticket, hasPermission)
  const editable = ticket && ['Draft', 'Rejected'].includes(ticket.status) && hasPermission('operation_entries:update')
  const trackingLink =
    ticket?.status === 'Approved' && ticket.operation_type_code === 'BARGE_OPERATIONS' && ticket.convoy_number && hasPermission('barge_tracking:read')
      ? { to: `/barge-tracking?convoy=${encodeURIComponent(ticket.convoy_number)}`, label: 'Open in Barge Tracking' }
      : ticket?.status === 'Approved' && ticket.operation_type_code === 'TANKER_OPERATIONS' && hasPermission('tanker_tracking:read')
        ? { to: `/tanker-tracking?search=${encodeURIComponent(ticket.ticket_number)}`, label: 'Open in Tanker Tracking' }
        : null

  return (
    <div className="page operation-tracking">
      <PageHead
        eyebrow="OPERATION TRACKING / TRANSACTION DETAIL"
        title={ticket ? `Ticket ${ticket.ticket_number}` : 'Operation ticket'}
        description="Saved ticket snapshot with its workflow actions and status history. Quantities are shown as saved and are not recalculated."
        actions={
          <>
            <button type="button" className="btn btn-secondary" onClick={() => navigate('/operation-transactions')}>
              Back to register
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                logUiAction(MODULE, 'Print Ticket', { ticket: ticket?.ticket_number })
                window.print()
              }}
              disabled={!ticket}
            >
              Print
            </button>
            <button type="button" className="btn btn-secondary" onClick={load} disabled={loading}>
              <Icon name="refresh" size={15} />
              Refresh
            </button>
          </>
        }
      />

      {error && <Alert tone="danger">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}

      {loading && !ticket ? (
        <Loading label="Loading ticket…" />
      ) : ticket ? (
        <>
          <section className="card">
            <div className="card-head">
              <div>
                <h2 className="card-title">
                  {ticket.operation_type_name} · {ticket.entry_layout_type}
                </h2>
                <p className="card-subtitle">
                  <StatusTag status={ticket.status} tone={statusTone(ticket.status)} />
                  {ticket.status_remarks && <span className="muted"> · {ticket.status_remarks}</span>}
                </p>
              </div>
              <div className="toolbar-group tracking-actions">
                {actions.map((item) => (
                  <button
                    key={item.action}
                    type="button"
                    className={`btn ${item.tone === 'danger' ? 'btn-danger' : item.tone === 'primary' ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => {
                      setNotice('')
                      setWorkflow({ ticket, action: item.action })
                      logUiAction(MODULE, 'Open Workflow Action', { ticket: ticket.ticket_number, action: item.action })
                    }}
                  >
                    {item.label}
                  </button>
                ))}
                {editable && (
                  <Link className="btn btn-secondary" to={`/operation-entry?ticket_id=${ticket.id}`}>
                    Edit in Operation Entry
                  </Link>
                )}
                {trackingLink && (
                  <Link className="btn btn-secondary" to={trackingLink.to}>
                    {trackingLink.label}
                  </Link>
                )}
              </div>
            </div>
            <div className="card-body">
              <FactGrid
                items={[
                  ['Operation date', formatDate(ticket.operation_date)],
                  ['Operation', ticket.operation_code],
                  ['Category / sign', [ticket.operation_category, ticket.operation_sign].filter(Boolean).join(' / ')],
                  ['Primary asset', `${ticket.asset_name} (${ticket.asset_code})`],
                  ['Location', `${ticket.location_name} (${ticket.location_code})`],
                  ['Convoy / voyage', ticket.convoy_number],
                  ['Product', ticket.product_name],
                  ['Linked sender ticket', ticket.linked_ticket_id ? <Link to={`/operation-transactions/${ticket.linked_ticket_id}`}>Open sender</Link> : null],
                  ['Created by', `${ticket.created_by || '—'} · ${formatDateTime(ticket.created_at)}`],
                  ['Submitted', ticket.submitted_at ? `${ticket.submitted_by || '—'} · ${formatDateTime(ticket.submitted_at)}` : null],
                  ['Approved at', ticket.approved_at ? formatDateTime(ticket.approved_at) : null],
                  ['Version', ticket.version],
                  ['Remarks', ticket.remarks],
                ]}
              />
              <div className="tracking-export-row">
                <ExportGroup
                  label="Export ticket"
                  onExport={(format) => apiDownload(`/operation-entries/${ticket.id}/export?format=${format}`)}
                />
              </div>
            </div>
          </section>
          <section className="card">
            <div className="card-head">
              <h2 className="card-title">Saved readings and calculated quantities</h2>
            </div>
            <div className="card-body operation-entry">
              <Review ticket={ticket} />
            </div>
          </section>
          <div className="operation-entry">
            <TicketHistory key={`${ticket.id}-${ticket.version}`} ticket={ticket} module={MODULE} defaultOpen />
          </div>
        </>
      ) : null}

      {workflow && (
        <div className="operation-entry">
        <WorkflowDialog
          {...workflow}
          onCancel={() => setWorkflow(null)}
          onDone={(saved) => {
            setWorkflow(null)
            setTicket(saved)
            setNotice(`${saved.ticket_number} is now ${saved.status}.`)
          }}
        />
        </div>
      )}
    </div>
  )
}
