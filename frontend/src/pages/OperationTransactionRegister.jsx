import { useCallback, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { exportTransactions, listTransactions } from '../api/operationTrackingApi'
import { getEntry } from '../api/operationEntryApi'
import Icon from '../components/common/Icon'
import { Alert, EmptyState, Loading, PageHead, Pagination, StatusTag, formatDate, formatDateTime } from '../components/common/Ui'
import { WorkflowDialog, statusTone, workflowActions } from '../components/operationTracking/TicketWorkflow'
import { ExportGroup, LookupFilter, filterParams, OPERATION_TYPES, RegisterFilters, TabStrip, useRegister } from '../components/operationTracking/TrackingKit'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'
import '../styles/operation-entry.css'
import '../styles/operation-tracking.css'

const MODULE = 'Operation Transaction Register'
const STATUSES = ['All', 'Draft', 'Submitted', 'Approved', 'Rejected', 'Cancelled']
const INITIAL = { search: '', operation_type_code: '', location: null, asset: null, product_name: '', date_from: '', date_to: '' }

/**
 * OTMS Operation Transaction Register: every ticket in the user's location
 * scope with status tabs. Workflow actions (submit, recall, approve, reject,
 * cancel) happen here and on the detail page — not on Operation Entry.
 */
export default function OperationTransactionRegister() {
  const { hasPermission } = usePermissions()
  const navigate = useNavigate()
  const [status, setStatus] = useState('All')
  const [workflow, setWorkflow] = useState(null)
  const [notice, setNotice] = useState(null)
  const fetcher = useCallback(
    (params, page, pageSize) => listTransactions({ ...params, status: status === 'All' ? '' : status, page, page_size: pageSize }),
    [status],
  )
  const register = useRegister(INITIAL, fetcher, MODULE)
  const { data, loading, error, draft, setDraft } = register
  const counts = data?.status_counts || {}

  const openAction = async (row, action) => {
    setNotice(null)
    try {
      const ticket = await getEntry(row.id)
      setWorkflow({ ticket, action })
      logUiAction(MODULE, 'Open Workflow Action', { ticket: row.ticket_number, action })
    } catch (actionError) {
      setNotice({ tone: 'danger', text: actionError.message })
    }
  }

  return (
    <div className="page operation-tracking">
      <PageHead
        eyebrow="OPERATION TRACKING / TRANSACTION REGISTER"
        title="Operation Transaction Register"
        description="All operation tickets in your locations. Review, submit, approve, reject, recall and cancel tickets here; Operation Entry is used only to create and edit Draft / Rejected tickets."
        actions={
          <>
            {(hasPermission('operation_entries:create') || hasPermission('operation_entries:read')) && (
              <Link to="/operation-entry" className="btn btn-secondary">
                <Icon name="layers" size={15} />
                Operation Entry
              </Link>
            )}
            <button type="button" className="btn btn-secondary" onClick={register.refresh} disabled={loading}>
              <Icon name="refresh" size={15} />
              Refresh
            </button>
          </>
        }
      />

      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      {error && <Alert tone="danger">{error}</Alert>}

      <section className="card">
        <TabStrip
          label="Ticket status"
          value={status}
          onChange={(key) => {
            setStatus(key)
            register.setPage(1)
            logUiAction(MODULE, 'Change Status Tab', { status: key })
          }}
          tabs={STATUSES.map((key) => ({ key, label: key, count: counts[key] ?? null }))}
        />
        <RegisterFilters
          register={register}
          searchPlaceholder="Search ticket, asset, convoy or product"
          chipLabels={{ search: 'Search', operation_type_code: 'Type', location: 'Location', asset: 'Asset', product_name: 'Product', date_from: 'From', date_to: 'To' }}
          exportSlot={<ExportGroup label="Export register" onExport={(format) => exportTransactions(format, { ...filterParams(register.applied), status: status === 'All' ? '' : status })} />}
          advanced={
            <>
              <label className="field">
                <span className="field-label">Operation type</span>
                <select className="select" value={draft.operation_type_code} onChange={(event) => setDraft({ ...draft, operation_type_code: event.target.value })}>
                  <option value="">All operation types</option>
                  {OPERATION_TYPES.map((type) => <option key={type.code} value={type.code}>{type.name}</option>)}
                </select>
              </label>
              <LookupFilter kind="locations" label="Location" value={draft.location} onChange={(location) => setDraft({ ...draft, location })} />
              <LookupFilter kind="assets" label="Asset" value={draft.asset} onChange={(asset) => setDraft({ ...draft, asset })} params={{ location_id: draft.location?.id }} />
              <label className="field">
                <span className="field-label">Product</span>
                <input className="input" value={draft.product_name} maxLength={100} onChange={(event) => setDraft({ ...draft, product_name: event.target.value })} placeholder="Product contains" />
              </label>
            </>
          }
        />

        {loading && !data ? (
          <Loading label="Loading operation tickets…" />
        ) : !data?.items?.length ? (
          <EmptyState title={`No ${status === 'All' ? '' : status.toLowerCase() + ' '}tickets match the current filters`} description="Change the status tab, search, location, asset or date range." />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table" aria-busy={loading}>
                <thead>
                  <tr>
                    <th>Ticket / Date</th>
                    <th>Operation</th>
                    <th>Asset</th>
                    <th>Location</th>
                    <th>Convoy / Voyage</th>
                    <th>Product</th>
                    <th>Status</th>
                    <th>Created / Submitted</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <div className="cell-primary cell-mono">{row.ticket_number}</div>
                        <div className="cell-sub">{formatDate(row.operation_date)}</div>
                      </td>
                      <td>
                        <div className="cell-primary">{row.operation_type_name}</div>
                        <div className="cell-sub">{row.operation_code || row.entry_layout_type}</div>
                      </td>
                      <td>
                        <div className="cell-primary">{row.asset_name}</div>
                        <div className="cell-sub cell-mono">{row.asset_code}</div>
                      </td>
                      <td>{row.location_code}</td>
                      <td className="cell-mono">{row.convoy_number || '—'}</td>
                      <td>{row.product_name || '—'}</td>
                      <td>
                        <StatusTag status={row.status} tone={statusTone(row.status)} />
                        {row.status_remarks && <div className="cell-sub">{row.status_remarks}</div>}
                      </td>
                      <td>
                        <div className="cell-primary">{row.created_by || '—'}</div>
                        <div className="cell-sub">{row.submitted_at ? `Submitted ${formatDateTime(row.submitted_at)}` : formatDateTime(row.created_at)}</div>
                      </td>
                      <td>
                        <div className="table-actions">
                          <button
                            type="button"
                            className="btn btn-ghost btn-compact"
                            onClick={() => {
                              logUiAction(MODULE, 'View Ticket', { ticket: row.ticket_number })
                              navigate(`/operation-transactions/${row.id}`)
                            }}
                          >
                            <Icon name="eye" size={14} />
                            View
                          </button>
                          {workflowActions(row, hasPermission).map((item) => (
                            <button
                              key={item.action}
                              type="button"
                              className={`btn btn-compact ${item.tone === 'danger' ? 'btn-ghost' : 'btn-secondary'}`}
                              onClick={() => openAction(row, item.action)}
                            >
                              {item.label}
                            </button>
                          ))}
                        </div>
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

      {workflow && (
        <div className="operation-entry">
        <WorkflowDialog
          {...workflow}
          onCancel={() => setWorkflow(null)}
          onDone={(ticket) => {
            setWorkflow(null)
            setNotice({ tone: 'success', text: `${ticket.ticket_number} is now ${ticket.status}.` })
            register.refresh()
          }}
        />
        </div>
      )}
    </div>
  )
}
