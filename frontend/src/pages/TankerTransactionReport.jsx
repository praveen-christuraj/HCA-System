import { useCallback } from 'react'
import { Link } from 'react-router-dom'
import { exportTankerReport, tankerReport } from '../api/operationTrackingApi'
import Icon from '../components/common/Icon'
import { Alert, EmptyState, Loading, PageHead, Pagination, StatusTag, formatDate } from '../components/common/Ui'
import { statusTone } from '../components/operationTracking/TicketWorkflow'
import { ExportGroup, LookupFilter, RegisterFilters, filterParams, fmt, useRegister } from '../components/operationTracking/TrackingKit'
import { usePermissions } from '../hooks/usePermissions'
import '../styles/operation-entry.css'
import '../styles/operation-tracking.css'

const MODULE = 'Tanker Transaction Report'
const INITIAL = { search: '', status: 'Approved', convoy_number: '', location: null, asset: null, date_from: '', date_to: '' }
const STATUS_OPTIONS = [
  ['Approved', 'Approved'],
  ['Submitted', 'Submitted'],
  ['Approved,Submitted', 'Approved + Submitted'],
  ['Draft,Submitted,Approved,Rejected', 'All except Cancelled'],
]
const COLUMNS = [['gov_bbl', 'GOV'], ['gsv_bbl', 'GSV'], ['nsv_bbl', 'NSV'], ['lt', 'LT'], ['mt', 'MT']]

/** OTMS Tanker Transaction Report: one row per tanker ticket with volumes and weights. */
export default function TankerTransactionReport() {
  const { hasPermission } = usePermissions()
  const fetcher = useCallback((p, page, pageSize) => tankerReport({ ...p, page, page_size: pageSize }), [])
  const register = useRegister(INITIAL, fetcher, MODULE)
  const { data, loading, error, draft, setDraft } = register
  const canOpen = hasPermission('operation_transactions:read')
  return (
    <div className="page operation-tracking">
      <PageHead
        eyebrow="OPERATION TRACKING / TANKER TRANSACTION REPORT"
        title="Tanker Transaction Report"
        description="Tanker tickets with their prime mover, convoy, cargo, destination, volumes (bbl) and weights. Totals cover every row that matches the filters, not just this page."
        actions={
          <button type="button" className="btn btn-secondary" onClick={register.refresh} disabled={loading}>
            <Icon name="refresh" size={15} />
            Refresh
          </button>
        }
      />
      {error && <Alert tone="danger">{error}</Alert>}
      <section className="card">
        <RegisterFilters
          register={register}
          searchPlaceholder="Search ticket, convoy, tanker or cargo"
          chipLabels={{ search: 'Search', status: 'Status', convoy_number: 'Convoy', location: 'Location', asset: 'Tanker', date_from: 'From', date_to: 'To' }}
          exportSlot={<ExportGroup label="Export report" onExport={(format) => exportTankerReport(format, filterParams(register.applied))} />}
          advanced={
            <>
              <label className="field">
                <span className="field-label">Ticket status</span>
                <select className="select" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
                  {STATUS_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
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
          <Loading label="Loading tanker transactions…" />
        ) : !data?.items?.length ? (
          <EmptyState title="No tanker transactions match the current filters" description="Change the status, location, tanker or date range." />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table" aria-busy={loading}>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Ticket</th>
                    <th>Location</th>
                    <th>Tanker / Prime mover</th>
                    <th>Convoy</th>
                    <th>Cargo</th>
                    <th>Destination</th>
                    {COLUMNS.map(([key, label]) => <th key={key} className="num">{label}</th>)}
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <tr key={row.id}>
                      <td className="nowrap">{formatDate(row.operation_date)}</td>
                      <td className="cell-mono">{canOpen ? <Link to={`/operation-transactions/${row.id}`}>{row.ticket_number}</Link> : row.ticket_number}</td>
                      <td>{row.location_code}</td>
                      <td>
                        <div className="cell-primary">{row.asset_code}</div>
                        <div className="cell-sub">{row.prime_mover_code || '—'}</div>
                      </td>
                      <td className="cell-mono">{row.convoy_number || '—'}</td>
                      <td>{row.product_name || '—'}</td>
                      <td>{row.receiver_location_code || row.destination_location_code || '—'}</td>
                      {COLUMNS.map(([key]) => <td key={key} className="num tnum">{fmt(row[key])}</td>)}
                      <td><StatusTag status={row.status} tone={statusTone(row.status)} /></td>
                    </tr>
                  ))}
                </tbody>
                {data.totals && (
                  <tfoot>
                    <tr className="tracking-total-row">
                      <td colSpan={7}>Total ({data.total} tickets)</td>
                      {COLUMNS.map(([key]) => <td key={key} className="num tnum">{fmt(data.totals[key])}</td>)}
                      <td />
                    </tr>
                  </tfoot>
                )}
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
