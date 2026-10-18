import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { changeVoyage, exportVoyage, exportVoyages, getVoyage, listVoyages } from '../../api/operationTrackingApi'
import Icon from '../common/Icon'
import { Alert, EmptyState, Loading, Pagination, formatDate, formatDateTime } from '../common/Ui'
import { usePermissions } from '../../hooks/usePermissions'
import { logUiAction } from '../../utils/actionLogger'
import { ExportGroup, FactGrid, LookupFilter, RegisterFilters, RemarksDialog, TabStrip, TrackingTag, filterParams, fmt, useRegister } from './TrackingKit'

const INITIAL = { search: '', shuttle_number: '', location: null, asset: null, date_from: '', date_to: '' }

export const VOYAGE_CONFIG = {
  shuttle: {
    module: 'Shuttle Tracking',
    assetLabel: 'Shuttle vessel',
    assetType: 'SHUTTLE_VESSEL',
    columns: [
      ['net_receipt_bbl', 'Net receipt'],
      ['net_discharge_bbl', 'Net discharge'],
      ['transfer_in_bbl', 'Transfer in'],
      ['transfer_out_bbl', 'Transfer out'],
      ['last_closing_stock_bbl', 'Last closing stock'],
    ],
    totals: [
      ['net_receipt_bbl', 'Net receipt (bbl)'],
      ['net_discharge_bbl', 'Net discharge (bbl)'],
      ['transfer_in_bbl', 'Transfer in (bbl)'],
      ['transfer_out_bbl', 'Transfer out (bbl)'],
      ['tov_bbl', 'TOV (bbl)'],
      ['fw_bbl', 'Free water (bbl)'],
      ['nsv_bbl', 'NSV (bbl)'],
      ['last_closing_stock_bbl', 'Last closing stock (bbl)'],
      ['last_closing_water_bbl', 'Last closing water (bbl)'],
    ],
  },
  fso: {
    module: 'FSO Tracking',
    assetLabel: 'FSO',
    assetType: 'FSO',
    columns: [
      ['fso_receipt_bbl', 'FSO receipt'],
      ['fso_export_bbl', 'FSO export'],
      ['shuttle_discharge_bbl', 'Shuttle discharge'],
      ['variance_bbl', 'Variance'],
      ['variance_pct', 'Variance %'],
    ],
    totals: [
      ['fso_receipt_bbl', 'FSO receipt (bbl)'],
      ['fso_export_bbl', 'FSO export (bbl)'],
      ['water_in_bbl', 'Water in (bbl)'],
      ['water_out_bbl', 'Water out (bbl)'],
      ['shuttle_discharge_bbl', 'Shuttle discharge (bbl)'],
      ['variance_bbl', 'Discharge − receipt (bbl)'],
      ['variance_pct', 'Variance %'],
      ['last_closing_stock_bbl', 'Last closing stock (bbl)'],
    ],
  },
}

/** Shuttle / FSO voyages grouped by location + vessel + shuttle number, OPEN / CLOSED. */
export function VoyageList({ kind, onOpen }) {
  const config = VOYAGE_CONFIG[kind]
  const [tab, setTab] = useState('OPEN')
  const fetcher = useCallback((p, page, pageSize) => listVoyages(kind, { ...p, tab, page, page_size: pageSize }), [kind, tab])
  const register = useRegister(INITIAL, fetcher, config.module)
  const { data, loading, error, draft, setDraft } = register
  return (
    <>
      {error && <Alert tone="danger">{error}</Alert>}
      <section className="card">
        <TabStrip
          label="Voyage status"
          value={tab}
          onChange={(key) => {
            setTab(key)
            register.setPage(1)
            logUiAction(config.module, 'Change Tab', { tab: key })
          }}
          tabs={[
            { key: 'OPEN', label: 'Open', count: data?.open_count },
            { key: 'CLOSED', label: 'Closed', count: data?.closed_count },
          ]}
        />
        <RegisterFilters
          register={register}
          searchPlaceholder={`Search shuttle number, ${config.assetLabel.toLowerCase()} or location`}
          chipLabels={{ search: 'Search', shuttle_number: 'Shuttle', location: 'Location', asset: config.assetLabel, date_from: 'From', date_to: 'To' }}
          exportSlot={
            <div className="toolbar-group">
              <button type="button" className="btn btn-secondary btn-compact" onClick={register.refresh} disabled={loading}>
                <Icon name="refresh" size={14} />
                Refresh
              </button>
              <ExportGroup label="Export voyages" onExport={(format) => exportVoyages(kind, format, { ...filterParams(register.applied), tab })} />
            </div>
          }
          advanced={
            <>
              <label className="field">
                <span className="field-label">Shuttle number</span>
                <input className="input" maxLength={50} value={draft.shuttle_number} onChange={(event) => setDraft({ ...draft, shuttle_number: event.target.value })} />
              </label>
              <LookupFilter kind="locations" label="Location" value={draft.location} onChange={(location) => setDraft({ ...draft, location })} />
              <LookupFilter kind="assets" label={config.assetLabel} value={draft.asset} onChange={(asset) => setDraft({ ...draft, asset })} params={{ asset_type_code: config.assetType, location_id: draft.location?.id }} />
            </>
          }
        />
        {loading && !data ? (
          <Loading label="Loading voyages…" />
        ) : !data?.items?.length ? (
          <EmptyState title={`No ${tab.toLowerCase()} voyages`} description="Voyages appear once a ticket with a shuttle number is Approved." />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table" aria-busy={loading}>
                <thead>
                  <tr>
                    <th>Location</th>
                    <th>{config.assetLabel}</th>
                    <th>Shuttle number</th>
                    <th>Status</th>
                    <th className="num">Tickets</th>
                    {config.columns.map(([key, label]) => <th key={key} className="num">{label}</th>)}
                    <th>Dates</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((row) => (
                    <tr key={row.id}>
                      <td>{row.location_code}</td>
                      <td>
                        <div className="cell-primary">{row.asset_code}</div>
                        <div className="cell-sub">{row.asset_name}</div>
                      </td>
                      <td className="cell-mono">{row.shuttle_number}</td>
                      <td><TrackingTag value={row.voyage_status} /></td>
                      <td className="num tnum">{row.ticket_count}</td>
                      {config.columns.map(([key]) => <td key={key} className="num tnum">{fmt(row[key], key.endsWith('pct') ? 4 : 3)}</td>)}
                      <td className="nowrap">{formatDate(row.first_operation_date)} – {formatDate(row.last_operation_date)}</td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-secondary btn-compact"
                          onClick={() => {
                            logUiAction(config.module, 'Open Voyage', { voyage: row.group_key })
                            onOpen(row.id)
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
    </>
  )
}

/** One voyage: totals, Approved tickets, close / reopen and the voyage MTR export. */
export function VoyageDetail({ kind, voyageId, onBack }) {
  const config = VOYAGE_CONFIG[kind]
  const { hasPermission } = usePermissions()
  const [voyage, setVoyage] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [dialog, setDialog] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setVoyage(await getVoyage(kind, voyageId))
    } catch (loadError) {
      setError(loadError.message || 'Unable to load the voyage')
    } finally {
      setLoading(false)
    }
  }, [kind, voyageId])

  useEffect(() => {
    load()
  }, [load])

  const canChange = hasPermission('operation_voyages:update')
  const open = voyage?.voyage_status === 'OPEN'

  return (
    <>
      {error && <Alert tone="danger">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}
      {loading && !voyage ? (
        <Loading label="Loading voyage…" />
      ) : voyage ? (
        <>
          <section className="card">
            <div className="card-head">
              <div>
                <h2 className="card-title">
                  {voyage.asset_name} ({voyage.asset_code}) · Shuttle {voyage.shuttle_number}
                </h2>
                <p className="card-subtitle">
                  <TrackingTag value={voyage.voyage_status} /> <span className="muted">{voyage.location_name} ({voyage.location_code})</span>
                </p>
              </div>
              <div className="toolbar-group tracking-actions">
                <button type="button" className="btn btn-secondary" onClick={onBack}>Back to voyages</button>
                <button type="button" className="btn btn-secondary" onClick={() => window.print()}>Print</button>
                <button type="button" className="btn btn-secondary" onClick={load} disabled={loading}>
                  <Icon name="refresh" size={15} />
                  Refresh
                </button>
                {canChange && open && (
                  <button type="button" className="btn btn-primary" disabled={voyage.open_ticket_count > 0} onClick={() => setDialog('close')}>
                    Close voyage
                  </button>
                )}
                {canChange && !open && (
                  <button type="button" className="btn btn-secondary" onClick={() => setDialog('reopen')}>Reopen voyage</button>
                )}
              </div>
            </div>
            <div className="card-body">
              {open && voyage.open_ticket_count > 0 && (
                <Alert tone="warning">{voyage.open_ticket_count} Draft / Submitted / Rejected ticket(s) must be finished or cancelled before the voyage can be closed.</Alert>
              )}
              <FactGrid
                items={[
                  ...config.totals.map(([key, label]) => [label, fmt(voyage[key], key.endsWith('pct') ? 4 : 3)]),
                  ['Approved tickets', voyage.ticket_count],
                  ['Closed', voyage.closed_at ? `${voyage.closed_by} · ${formatDateTime(voyage.closed_at)}` : null],
                  ['Closure / reopen remarks', voyage.closure_remarks],
                ]}
              />
              <div className="tracking-export-row">
                <ExportGroup label="Voyage MTR" onExport={(format) => exportVoyage(kind, voyage.id, format)} />
              </div>
            </div>
          </section>
          <section className="card">
            <div className="card-head"><h2 className="card-title">Approved tickets</h2></div>
            {voyage.tickets.length === 0 ? (
              <EmptyState title="No Approved tickets in this voyage" />
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Ticket</th>
                      <th>Date / time</th>
                      <th>Operation</th>
                      <th className="num">Opening stock</th>
                      <th className="num">Opening water</th>
                      <th className="num">Closing stock</th>
                      <th className="num">Closing water</th>
                      <th className="num">Net stock</th>
                      <th className="num">Net water</th>
                      <th>{kind === 'fso' ? 'Vessel / qty' : 'Barge reference'}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {voyage.tickets.map((ticket) => (
                      <tr key={ticket.id}>
                        <td className="cell-mono">
                          {hasPermission('operation_transactions:read') ? <Link to={`/operation-transactions/${ticket.id}`}>{ticket.ticket_number}</Link> : ticket.ticket_number}
                        </td>
                        <td className="nowrap">{formatDate(ticket.operation_date)} {ticket.event_time || ''}</td>
                        <td>
                          <div className="cell-primary">{ticket.operation_label || ticket.operation_code}</div>
                          <div className="cell-sub">{ticket.operation_sign}</div>
                        </td>
                        {['opening_stock_bbl', 'opening_water_bbl', 'closing_stock_bbl', 'closing_water_bbl', 'net_stock_bbl', 'net_water_bbl'].map((key) => (
                          <td key={key} className="num tnum">{fmt(ticket[key])}</td>
                        ))}
                        <td>{kind === 'fso' ? [ticket.vessel_name, ticket.vessel_quantity_bbl ? `${fmt(ticket.vessel_quantity_bbl)} bbl` : ''].filter(Boolean).join(' · ') || '—' : ticket.barge_reference || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
      {dialog && (
        <RemarksDialog
          title={`${dialog === 'close' ? 'Close' : 'Reopen'} voyage · ${voyage.shuttle_number}`}
          message={dialog === 'close' ? 'A CLOSED voyage blocks new tickets against this shuttle number until it is reopened.' : 'Reopening allows tickets against this voyage again.'}
          confirmLabel={dialog === 'close' ? 'Close voyage' : 'Reopen voyage'}
          onCancel={() => setDialog(null)}
          onConfirm={async (remarks) => {
            const next = await changeVoyage(kind, voyage.id, dialog, remarks)
            setVoyage(next)
            setDialog(null)
            setNotice(`Voyage ${next.shuttle_number} is now ${next.voyage_status}.`)
          }}
        />
      )}
    </>
  )
}
