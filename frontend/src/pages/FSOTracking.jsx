import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { exportFsoReport, fsoReport } from '../api/operationTrackingApi'
import Icon from '../components/common/Icon'
import { Alert, EmptyState, Loading, PageHead, formatDate } from '../components/common/Ui'
import { ExportGroup, LookupFilter, TabStrip, fmt } from '../components/operationTracking/TrackingKit'
import { VoyageDetail, VoyageList } from '../components/operationTracking/VoyageTracking'
import { logUiAction } from '../utils/actionLogger'
import '../styles/operation-entry.css'
import '../styles/operation-tracking.css'

const MODULE = 'FSO Tracking'
const VIEWS = [
  { key: 'voyages', label: 'Voyages' },
  { key: 'otr', label: 'OTR' },
  { key: 'material-balance', label: 'Material Balance' },
  { key: 'outturn', label: 'Outturn' },
]

const REPORTS = {
  otr: {
    title: 'FSO OTR (transaction-wise)',
    columns: [
      ['ticket_number', 'Ticket', 'text'],
      ['accounting_date', 'Acc date', 'date'],
      ['event_time', 'Time', 'text'],
      ['operation_label', 'Operation', 'text'],
      ['operation_sign', 'Sign', 'text'],
      ['shuttle_number', 'Shuttle', 'text'],
      ['vessel_name', 'Vessel', 'text'],
      ['vessel_quantity_bbl', 'Vessel qty', 'num'],
      ['movement_qty_bbl', 'Move qty', 'num'],
      ['variance_bbl', 'Variance', 'num'],
      ['source_shuttle_discharge_bbl', 'Shuttle discharge', 'num'],
      ['compare_variance_bbl', 'Compare variance', 'num'],
    ],
    totals: [
      ['total_receipt_bbl', 'Receipt'],
      ['total_export_bbl', 'Export'],
      ['total_movement_bbl', 'Movement'],
      ['total_variance_bbl', 'Vessel variance'],
      ['total_compare_variance_bbl', 'Compare variance'],
    ],
  },
  'material-balance': {
    title: 'FSO Material Balance (daily)',
    columns: [
      ['accounting_date', 'Acc date', 'date'],
      ['opening_stock_bbl', 'Opening', 'num'],
      ['receipt_bbl', 'Receipt', 'num'],
      ['export_bbl', 'Export', 'num'],
      ['book_closing_bbl', 'Book close', 'num'],
      ['physical_closing_bbl', 'Physical close', 'num'],
      ['physical_closing_water_bbl', 'Close water', 'num'],
      ['loss_gain_bbl', 'Loss / gain', 'num'],
    ],
    totals: [],
  },
  outturn: {
    title: 'FSO Outturn (shuttle discharge vs FSO receipt)',
    columns: [
      ['accounting_date', 'Acc date', 'date'],
      ['shuttle_number', 'Shuttle', 'text'],
      ['shuttle_discharge_bbl', 'Shuttle discharge', 'num'],
      ['fso_receipt_bbl', 'FSO receipt', 'num'],
      ['variance_bbl', 'Variance', 'num'],
      ['variance_pct', 'Variance %', 'pct'],
    ],
    totals: [
      ['total_shuttle_discharge_bbl', 'Shuttle discharge'],
      ['total_fso_receipt_bbl', 'FSO receipt'],
      ['total_variance_bbl', 'Variance'],
      ['total_variance_pct', 'Variance %'],
    ],
  },
}

/** OTMS FSO Tracking: voyages plus the OTR, Material Balance and Outturn reports. */
export default function FSOTracking() {
  const [params, setParams] = useSearchParams()
  const voyage = params.get('voyage')
  const view = params.get('view') || 'voyages'
  return (
    <div className="page operation-tracking">
      <PageHead
        eyebrow="OPERATION TRACKING / FSO TRACKING"
        title="FSO Tracking"
        description="FSO voyages per shuttle number (receipt, export, shuttle discharge vs FSO receipt) and the OTR, Material Balance and Outturn reports from Approved FSO tickets."
      />
      <TabStrip
        label="FSO view"
        value={view}
        onChange={(key) => {
          setParams(key === 'voyages' ? {} : { view: key })
          logUiAction(MODULE, 'Change View', { view: key })
        }}
        tabs={VIEWS}
      />
      {view === 'voyages' ? (
        voyage ? (
          <VoyageDetail kind="fso" voyageId={voyage} onBack={() => setParams({})} />
        ) : (
          <VoyageList kind="fso" onOpen={(id) => setParams({ voyage: String(id) })} />
        )
      ) : (
        <FsoReport key={view} kind={view} />
      )}
    </div>
  )
}

const cell = (value, type) => (type === 'date' ? formatDate(value) : type === 'num' ? fmt(value) : type === 'pct' ? `${fmt(value, 4)}%` : value || '—')

function FsoReport({ kind }) {
  const config = REPORTS[kind]
  const [form, setForm] = useState({ location: null, asset: null, date_from: '', date_to: '', shuttle_number: '' })
  const [applied, setApplied] = useState(null)
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const ready = form.location && form.asset && form.date_from && form.date_to
  const toParams = (value) => ({
    location_id: value.location.id,
    asset_id: value.asset.id,
    date_from: value.date_from,
    date_to: value.date_to,
    shuttle_number: value.shuttle_number,
  })

  const run = async () => {
    setLoading(true)
    setError('')
    try {
      const params = toParams(form)
      setReport(await fsoReport(kind, params))
      setApplied(params)
      logUiAction(MODULE, `Run ${config.title}`, params)
    } catch (runError) {
      setError(runError.message || 'Unable to run the report')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h2 className="card-title">{config.title}</h2>
          <p className="card-subtitle">Location, FSO and date range are required. Accounting date = operation date (Location Accounting Day Setting is Planned).</p>
        </div>
      </div>
      <div className="filters-panel">
        <div className="filters-grid">
          <LookupFilter kind="locations" label="Location" value={form.location} onChange={(location) => setForm({ ...form, location, asset: null })} />
          <LookupFilter kind="assets" label="FSO" value={form.asset} onChange={(asset) => setForm({ ...form, asset })} params={{ asset_type_code: 'FSO', location_id: form.location?.id }} />
          <label className="field">
            <span className="field-label">Shuttle number (optional)</span>
            <input className="input" maxLength={50} value={form.shuttle_number} onChange={(event) => setForm({ ...form, shuttle_number: event.target.value })} />
          </label>
        </div>
        <div className="date-group">
          <div className="date-group-title">
            <Icon name="calendar" size={14} />
            Accounting date range
          </div>
          <div className="date-grid">
            <label className="field">
              <span className="field-label">From date</span>
              <input className="input" type="date" value={form.date_from} onChange={(event) => setForm({ ...form, date_from: event.target.value })} />
            </label>
            <label className="field">
              <span className="field-label">To date</span>
              <input className="input" type="date" value={form.date_to} onChange={(event) => setForm({ ...form, date_to: event.target.value })} />
            </label>
          </div>
        </div>
        <div className="filter-actions">
          <button type="button" className="btn btn-primary btn-compact" onClick={run} disabled={!ready || loading}>
            {loading ? 'Running…' : 'Run report'}
          </button>
          <div className="toolbar-spacer" />
          {applied && <ExportGroup label="Export report" onExport={(format) => exportFsoReport(kind, format, applied)} />}
        </div>
      </div>
      {error && <Alert tone="danger">{error}</Alert>}
      {loading && !report ? (
        <Loading label="Running report…" />
      ) : !report ? (
        <EmptyState title="Select a location, FSO and date range" description="Then choose Run report." />
      ) : report.rows.length === 0 ? (
        <EmptyState title="No Approved FSO tickets in this range" />
      ) : (
        <>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  {config.columns.map(([key, label, type]) => <th key={key} className={type === 'num' || type === 'pct' ? 'num' : ''}>{label}</th>)}
                </tr>
              </thead>
              <tbody>
                {report.rows.map((row, index) => (
                  <tr key={row.transaction_id || `${row.accounting_date}-${row.shuttle_number || ''}-${index}`}>
                    {config.columns.map(([key, , type]) => (
                      <td key={key} className={type === 'num' || type === 'pct' ? `num tnum${key.includes('variance') || key === 'loss_gain_bbl' ? (row[key] ? ' tracking-delta' : '') : ''}` : key === 'ticket_number' ? 'cell-mono' : ''}>
                        {cell(row[key], type)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {config.totals.length > 0 && (
            <div className="kpi-grid tracking-report-totals">
              {config.totals.map(([key, label]) => (
                <div key={key} className="kpi-card">
                  <div className="kpi-label">{label}</div>
                  <div className="kpi-value">{key.endsWith('pct') ? `${fmt(report.totals[key], 4)}%` : fmt(report.totals[key])}</div>
                  {!key.endsWith('pct') && <div className="kpi-context">bbl</div>}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
