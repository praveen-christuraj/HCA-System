import { useEffect, useState } from 'react'
import { apiGet, apiPost, apiPut, apiDelete, apiDownload, buildQuery } from '../api/apiClient'
import { usePermissions } from '../hooks/usePermissions'
import {
  PageHead,
  KpiCard,
  StatusTag,
  Alert,
  Loading,
  EmptyState,
  Pagination,
  formatDate,
  formatDateTime,
} from '../components/common/Ui'
import { EntryDialog } from '../components/operationLayouts/EntryFeedback'
import { logUiAction } from '../utils/actionLogger'

// ============================================================================
// 1. Flowmeter Record Entry (/flowmeter-records)
// ============================================================================
export function FlowmeterRecordEntryPage() {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('flowmeter_records:create')
  const canUpdate = hasPermission('flowmeter_records:update')
  const canDelete = hasPermission('flowmeter_records:delete')

  const [filters, setFilters] = useState({ search: '', location_code: '', status: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [locations, setLocations] = useState([])
  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({
    location_code: '',
    flowmeter_asset_code: '',
    stream_name: 'Crude Export Stream',
    meter_label: 'Meter Run A',
    record_date: new Date().toISOString().slice(0, 10),
    opening_reading: 1000,
    closing_reading: 1500,
    meter_factor: 1.0012,
    ctl: 0.9985,
    cpl: 1.0004,
    bsw_pct: 0.25,
    api60: 36.5,
    temperature_deg: 28.0,
    pressure_psig: 45.0,
    remarks: '',
    status: 'Approved',
  })
  const [previewCalc, setPreviewCalc] = useState(null)
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    apiGet('/locations?page_size=200').then((r) => setLocations(r.items || [])).catch(() => {})
    apiGet('/assets?asset_type_code=FLOWMETER&page_size=200').then((r) => setAssets(r.items || [])).catch(() => {})
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/flowmeter-records${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Flowmeter Records', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize, refresh])

  const openEditor = (row = null) => {
    setEditing(row || { id: null })
    setPreviewCalc(null)
    setForm(
      row
        ? {
            location_code: row.location_code,
            flowmeter_asset_code: row.flowmeter_asset_code,
            stream_name: row.stream_name,
            meter_label: row.meter_label,
            record_date: row.record_date,
            opening_reading: row.opening_reading,
            closing_reading: row.closing_reading,
            meter_factor: row.meter_factor,
            ctl: row.ctl,
            cpl: row.cpl,
            bsw_pct: row.bsw_pct,
            api60: row.api60 ?? 36.5,
            temperature_deg: row.temperature_deg ?? 28.0,
            pressure_psig: row.pressure_psig ?? 45.0,
            remarks: row.remarks || '',
            status: row.status || 'Approved',
          }
        : {
            location_code: locations[0]?.location_code || '',
            flowmeter_asset_code: assets[0]?.asset_code || '',
            stream_name: 'Crude Export Stream',
            meter_label: 'Meter Run A',
            record_date: new Date().toISOString().slice(0, 10),
            opening_reading: 1000,
            closing_reading: 1500,
            meter_factor: 1.0012,
            ctl: 0.9985,
            cpl: 1.0004,
            bsw_pct: 0.25,
            api60: 36.5,
            temperature_deg: 28.0,
            pressure_psig: 45.0,
            remarks: '',
            status: 'Approved',
          },
    )
  }

  const handleCalculatePreview = async () => {
    try {
      const res = await apiPost('/flowmeter-records/calculate', {
        opening_reading: Number(form.opening_reading),
        closing_reading: Number(form.closing_reading),
        meter_factor: Number(form.meter_factor),
        ctl: Number(form.ctl),
        cpl: Number(form.cpl),
        bsw_pct: Number(form.bsw_pct),
        api60: Number(form.api60),
      })
      setPreviewCalc(res)
    } catch (e) {
      setError(e.message)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const payload = {
        ...form,
        opening_reading: Number(form.opening_reading),
        closing_reading: Number(form.closing_reading),
        meter_factor: Number(form.meter_factor),
        ctl: Number(form.ctl),
        cpl: Number(form.cpl),
        bsw_pct: Number(form.bsw_pct),
        api60: form.api60 !== '' ? Number(form.api60) : null,
        temperature_deg: form.temperature_deg !== '' ? Number(form.temperature_deg) : null,
        pressure_psig: form.pressure_psig !== '' ? Number(form.pressure_psig) : null,
      }
      if (editing?.id) {
        await apiPut(`/flowmeter-records/${editing.id}`, payload)
      } else {
        await apiPost('/flowmeter-records', payload)
      }
      setEditing(null)
      setRefresh((r) => r + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="BUSINESS OPERATIONS / CUSTODY FLOWMETERS"
        title="Flowmeter Record Entry"
        description="Standalone flowmeter run register with live Gross Volume, Meter Factor, CTL, CPL, GSV, BS&W, NSV, LT, and MT calculations."
        actions={
          <div className="toolbar-actions">
            {canCreate && (
              <button type="button" className="btn btn-primary" onClick={() => openEditor(null)}>
                New Flowmeter Record
              </button>
            )}
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/flowmeter-records/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
                    setError(e.message),
                  )
                }
              >
                Export {fmt.toUpperCase()}
              </button>
            ))}
          </div>
        }
      />

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Quick Search</label>
            <input
              className="input"
              placeholder="Record #, meter, stream…"
              value={filters.search}
              onChange={(e) => {
                setFilters((f) => ({ ...f, search: e.target.value }))
                setPage(1)
              }}
            />
          </div>
          <div className="filter-group">
            <label>Location</label>
            <select
              className="select"
              value={filters.location_code}
              onChange={(e) => {
                setFilters((f) => ({ ...f, location_code: e.target.value }))
                setPage(1)
              }}
            >
              <option value="">All Locations</option>
              {locations.map((l) => (
                <option key={l.id} value={l.location_code}>
                  {l.location_code} — {l.location_name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>From Date</label>
            <input type="date" className="input" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
          </div>
          <div className="filter-group">
            <label>To Date</label>
            <input type="date" className="input" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
          </div>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <EmptyState title="No flowmeter records found" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Record #</th>
                  <th>Date</th>
                  <th>Location</th>
                  <th>Asset</th>
                  <th>Stream / Meter</th>
                  <th>Gross Vol</th>
                  <th>MF</th>
                  <th>GSV (bbl)</th>
                  <th>NSV (bbl)</th>
                  <th>MT</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.record_number}</td>
                    <td>{formatDate(row.record_date)}</td>
                    <td className="mono">{row.location_code}</td>
                    <td className="mono">{row.flowmeter_asset_code}</td>
                    <td>
                      {row.stream_name} / {row.meter_label}
                    </td>
                    <td className="mono">{row.gross_volume}</td>
                    <td className="mono">{row.meter_factor}</td>
                    <td className="mono">{row.gsv_bbl}</td>
                    <td className="mono">
                      <strong>{row.nsv_bbl}</strong>
                    </td>
                    <td className="mono">{row.mt}</td>
                    <td>
                      <StatusTag status={row.status} />
                    </td>
                    <td>
                      <div className="toolbar-actions">
                        {canUpdate && (
                          <button type="button" className="btn btn-ghost" onClick={() => openEditor(row)}>
                            Edit
                          </button>
                        )}
                        {canDelete && (
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={async () => {
                              try {
                                await apiDelete(`/flowmeter-records/${row.id}`)
                                setRefresh((r) => r + 1)
                              } catch (e) {
                                setError(e.message)
                              }
                            }}
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <Pagination
          page={page}
          pageSize={pageSize}
          pages={data.pages || 1}
          total={data.total || 0}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n)
            setPage(1)
          }}
        />
      </section>

      {editing && (
        <EntryDialog
          title={editing.id ? 'Edit Flowmeter Record' : 'New Flowmeter Record'}
          footer={
            <>
              <button type="button" className="btn btn-secondary" onClick={handleCalculatePreview}>
                Calculate Preview
              </button>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={handleSave}>
                {saving ? 'Saving…' : 'Save Record'}
              </button>
            </>
          }
        >
          <div className="stack">
            <div className="entry-header-grid">
              <label>
                Location
                <select className="select" value={form.location_code} onChange={(e) => setForm((f) => ({ ...f, location_code: e.target.value }))}>
                  <option value="">Select Location</option>
                  {locations.map((l) => (
                    <option key={l.id} value={l.location_code}>
                      {l.location_code} — {l.location_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Flowmeter Asset
                <select className="select" value={form.flowmeter_asset_code} onChange={(e) => setForm((f) => ({ ...f, flowmeter_asset_code: e.target.value }))}>
                  <option value="">Select Flowmeter Asset</option>
                  {assets.map((a) => (
                    <option key={a.id} value={a.asset_code}>
                      {a.asset_code} — {a.asset_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Stream Name
                <input className="input" value={form.stream_name} onChange={(e) => setForm((f) => ({ ...f, stream_name: e.target.value }))} />
              </label>
              <label>
                Meter Label
                <input className="input" value={form.meter_label} onChange={(e) => setForm((f) => ({ ...f, meter_label: e.target.value }))} />
              </label>
              <label>
                Record Date
                <input type="date" className="input" value={form.record_date} onChange={(e) => setForm((f) => ({ ...f, record_date: e.target.value }))} />
              </label>
              <label>
                Opening Reading
                <input type="number" step="any" className="input mono" value={form.opening_reading} onChange={(e) => setForm((f) => ({ ...f, opening_reading: e.target.value }))} />
              </label>
              <label>
                Closing Reading
                <input type="number" step="any" className="input mono" value={form.closing_reading} onChange={(e) => setForm((f) => ({ ...f, closing_reading: e.target.value }))} />
              </label>
              <label>
                Meter Factor (MF)
                <input type="number" step="any" className="input mono" value={form.meter_factor} onChange={(e) => setForm((f) => ({ ...f, meter_factor: e.target.value }))} />
              </label>
              <label>
                CTL
                <input type="number" step="any" className="input mono" value={form.ctl} onChange={(e) => setForm((f) => ({ ...f, ctl: e.target.value }))} />
              </label>
              <label>
                CPL
                <input type="number" step="any" className="input mono" value={form.cpl} onChange={(e) => setForm((f) => ({ ...f, cpl: e.target.value }))} />
              </label>
              <label>
                BS&W (%)
                <input type="number" step="any" className="input mono" value={form.bsw_pct} onChange={(e) => setForm((f) => ({ ...f, bsw_pct: e.target.value }))} />
              </label>
              <label>
                API @ 60°F
                <input type="number" step="any" className="input mono" value={form.api60} onChange={(e) => setForm((f) => ({ ...f, api60: e.target.value }))} />
              </label>
            </div>
            {previewCalc && (
              <div className="kpi-grid">
                <KpiCard label="Gross Vol" value={previewCalc.gross_volume} />
                <KpiCard label="GSV (bbl)" value={previewCalc.gsv_bbl} />
                <KpiCard label="NSV (bbl)" value={previewCalc.nsv_bbl} />
                <KpiCard label="MT / LT" value={`${previewCalc.mt} / ${previewCalc.lt}`} />
              </div>
            )}
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 2. Movement Mapping (/movement-mappings)
// ============================================================================
export function MovementMappingPage() {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('movement_mappings:create')
  const canDelete = hasPermission('movement_mappings:delete')

  const [filters, setFilters] = useState({ search: '', mapping_type: '', location_code: '', status: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [candidates, setCandidates] = useState({ senders: [], receivers: [] })
  const [locations, setLocations] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({
    mapping_type: 'TANK_TO_BARGE',
    location_code: '',
    mapping_date: new Date().toISOString().slice(0, 10),
    sender_entry_ids: [],
    receiver_entry_ids: [],
    remarks: '',
    status: 'Reconciled',
  })
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    apiGet('/locations?page_size=200').then((r) => setLocations(r.items || [])).catch(() => {})
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/movement-mappings${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Movement Mapping', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize, refresh])

  const openCreator = async () => {
    setCreating(true)
    try {
      const res = await apiGet('/movement-mappings/candidates')
      setCandidates(res)
      setForm((f) => ({ ...f, location_code: locations[0]?.location_code || '' }))
    } catch (e) {
      setError(e.message)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const items = [
        ...form.sender_entry_ids.map((id) => ({ entry_id: Number(id), role: 'SENDER' })),
        ...form.receiver_entry_ids.map((id) => ({ entry_id: Number(id), role: 'RECEIVER' })),
      ]
      await apiPost('/movement-mappings', {
        mapping_type: form.mapping_type,
        location_code: form.location_code,
        mapping_date: form.mapping_date,
        remarks: form.remarks || null,
        status: form.status,
        items,
      })
      setCreating(false)
      setRefresh((r) => r + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="BUSINESS OPERATIONS / CUSTODY RECONCILIATION"
        title="Movement Mapping"
        description="Many-to-many reconciliation between sender dispatch tickets and receiver out-turn tickets (Tank-to-Barge, Tank-to-Tanker, Barge-to-Shuttle, Shuttle-to-FSO)."
        actions={
          <div className="toolbar-actions">
            {canCreate && (
              <button type="button" className="btn btn-primary" onClick={openCreator}>
                New Movement Mapping
              </button>
            )}
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/movement-mappings/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
                    setError(e.message),
                  )
                }
              >
                Export {fmt.toUpperCase()}
              </button>
            ))}
          </div>
        }
      />

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Quick Search</label>
            <input
              className="input"
              placeholder="Mapping #, location, remarks…"
              value={filters.search}
              onChange={(e) => {
                setFilters((f) => ({ ...f, search: e.target.value }))
                setPage(1)
              }}
            />
          </div>
          <div className="filter-group">
            <label>Mapping Type</label>
            <select
              className="select"
              value={filters.mapping_type}
              onChange={(e) => {
                setFilters((f) => ({ ...f, mapping_type: e.target.value }))
                setPage(1)
              }}
            >
              <option value="">All Types</option>
              <option value="TANK_TO_BARGE">TANK_TO_BARGE</option>
              <option value="TANK_TO_TANKER">TANK_TO_TANKER</option>
              <option value="BARGE_TO_SHUTTLE">BARGE_TO_SHUTTLE</option>
              <option value="SHUTTLE_TO_FSO">SHUTTLE_TO_FSO</option>
            </select>
          </div>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <EmptyState title="No movement mappings created yet" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Mapping #</th>
                  <th>Type</th>
                  <th>Location</th>
                  <th>Date</th>
                  <th>Sender NSV (bbl)</th>
                  <th>Receiver NSV (bbl)</th>
                  <th>Variance NSV</th>
                  <th>Variance (%)</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.mapping_number}</td>
                    <td className="mono">{row.mapping_type}</td>
                    <td className="mono">{row.location_code}</td>
                    <td>{formatDate(row.mapping_date)}</td>
                    <td className="mono">{row.sender_total_nsv}</td>
                    <td className="mono">{row.receiver_total_nsv}</td>
                    <td className="mono">{row.variance_nsv}</td>
                    <td className="mono">{row.variance_nsv_pct}%</td>
                    <td>
                      <StatusTag status={row.status} />
                    </td>
                    <td>
                      {canDelete && (
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={async () => {
                            try {
                              await apiDelete(`/movement-mappings/${row.id}`)
                              setRefresh((r) => r + 1)
                            } catch (e) {
                              setError(e.message)
                            }
                          }}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <Pagination
          page={page}
          pageSize={pageSize}
          pages={data.pages || 1}
          total={data.total || 0}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n)
            setPage(1)
          }}
        />
      </section>

      {creating && (
        <EntryDialog
          title="Create Movement Mapping"
          footer={
            <>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setCreating(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={handleSave}>
                {saving ? 'Saving…' : 'Create Mapping'}
              </button>
            </>
          }
        >
          <div className="stack">
            <div className="entry-header-grid">
              <label>
                Mapping Type
                <select className="select" value={form.mapping_type} onChange={(e) => setForm((f) => ({ ...f, mapping_type: e.target.value }))}>
                  <option value="TANK_TO_BARGE">TANK_TO_BARGE</option>
                  <option value="TANK_TO_TANKER">TANK_TO_TANKER</option>
                  <option value="BARGE_TO_SHUTTLE">BARGE_TO_SHUTTLE</option>
                  <option value="SHUTTLE_TO_FSO">SHUTTLE_TO_FSO</option>
                </select>
              </label>
              <label>
                Location
                <select className="select" value={form.location_code} onChange={(e) => setForm((f) => ({ ...f, location_code: e.target.value }))}>
                  <option value="">Select Location</option>
                  {locations.map((l) => (
                    <option key={l.id} value={l.location_code}>
                      {l.location_code} — {l.location_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Mapping Date
                <input type="date" className="input" value={form.mapping_date} onChange={(e) => setForm((f) => ({ ...f, mapping_date: e.target.value }))} />
              </label>
              <label>
                Remarks
                <input className="input" value={form.remarks} onChange={(e) => setForm((f) => ({ ...f, remarks: e.target.value }))} />
              </label>
            </div>
            <div>
              <strong>Select Sender Tickets ({candidates.senders?.length || 0} available)</strong>
              <div style={{ maxHeight: '150px', overflowY: 'auto', border: '1px solid var(--border)', padding: '8px', borderRadius: '6px' }}>
                {(candidates.senders || []).map((s) => (
                  <label key={s.entry_id} className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={form.sender_entry_ids.includes(s.entry_id)}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          sender_entry_ids: e.target.checked
                            ? [...f.sender_entry_ids, s.entry_id]
                            : f.sender_entry_ids.filter((id) => id !== s.entry_id),
                        }))
                      }
                    />
                    <span className="mono">
                      {s.ticket_number} ({s.asset_code}) — NSV: {s.nsv_bbl} bbl
                    </span>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <strong>Select Receiver Tickets ({candidates.receivers?.length || 0} available)</strong>
              <div style={{ maxHeight: '150px', overflowY: 'auto', border: '1px solid var(--border)', padding: '8px', borderRadius: '6px' }}>
                {(candidates.receivers || []).map((r) => (
                  <label key={r.entry_id} className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={form.receiver_entry_ids.includes(r.entry_id)}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          receiver_entry_ids: e.target.checked
                            ? [...f.receiver_entry_ids, r.entry_id]
                            : f.receiver_entry_ids.filter((id) => id !== r.entry_id),
                        }))
                      }
                    />
                    <span className="mono">
                      {r.ticket_number} ({r.asset_code}) — NSV: {r.nsv_bbl} bbl
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 3. Operation Task Manager (/operation-tasks)
// ============================================================================
export function OperationTaskManagerPage() {
  const { hasPermission } = usePermissions()
  const canUpdate = hasPermission('operation_tasks:update') || hasPermission('operation_approvals:create') || hasPermission('operation_tasks:create')
  const canSupervisorView = hasPermission('operation_tasks:read')

  const [filters, setFilters] = useState({ search: '', status: '', task_type: '', location_code: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1, kpis: {}, status_counts: {} })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedTask, setSelectedTask] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [remarks, setRemarks] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [detailEvents, setDetailEvents] = useState([])

  const statusCounts = data.status_counts || {}
  const kpis = data.kpis || {}
  // Fallback: derive KPIs from status_counts if kpis missing (OTMS parity)
  const totalTasks = kpis.total ?? statusCounts.All ?? data.total ?? 0
  const pendingCount = kpis.pending ?? statusCounts.Pending ?? 0
  const inProgressCount = kpis.in_progress ?? kpis.in_review ?? statusCounts['In Progress'] ?? 0
  const completedCount = kpis.completed ?? ((statusCounts.Approved || 0) + (statusCounts.Rejected || 0) + (statusCounts.Cancelled || 0) + (statusCounts.Closed || 0))

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    // Normalize status alias: In Review -> In Progress for backend
    const queryFilters = { ...filters }
    if (queryFilters.status === 'In Review' || queryFilters.status === 'In Progress') {
      queryFilters.status = 'In Progress'
    }
    apiGet(`/operation-tasks${buildQuery({ ...queryFilters, page, page_size: pageSize })}`)
      .then((res) => {
        if (!active) return
        // Normalize response shape: backend may return rows/total_rows or items/total
        const normalized = {
          items: res.items || res.rows || [],
          total: res.total ?? res.total_rows ?? 0,
          pages: res.pages ?? Math.ceil((res.total ?? res.total_rows ?? 0) / (res.page_size || pageSize)) || 1,
          page: res.page || page,
          page_size: res.page_size || pageSize,
          status_counts: res.status_counts || {},
          kpis: res.kpis || {},
        }
        setData(normalized)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Operation Task Manager', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize, refresh])

  const fetchTaskDetail = async (taskRow) => {
    setDetailLoading(true)
    setError('')
    try {
      const detail = await apiGet(`/operation-tasks/${taskRow.id}`)
      setSelectedTask(detail)
      // Detail may include events array; otherwise fetch separately
      if (detail.events && Array.isArray(detail.events)) {
        setDetailEvents(detail.events)
      } else {
        try {
          const ev = await apiGet(`/operation-tasks/${taskRow.id}/events`)
          setDetailEvents(ev || [])
        } catch {
          setDetailEvents(detail.events || [])
        }
      }
      setRemarks('')
    } catch (e) {
      setError(e.message)
      // Fallback to row data
      setSelectedTask(taskRow)
      setDetailEvents(taskRow.events || [])
    } finally {
      setDetailLoading(false)
    }
  }

  const runAction = async (taskId, action) => {
    setError('')
    // Map OTMS alias actions to HCA endpoints
    const endpointMap = {
      take: 'take',
      'take-ownership': 'take-ownership',
      release: 'release',
      approve: 'approve',
      reject: 'reject',
    }
    const endpointAction = endpointMap[action] || action
    try {
      await apiPost(`/operation-tasks/${taskId}/${endpointAction}`, { remarks: remarks || `Action: ${action}` })
      setSelectedTask(null)
      setDetailEvents([])
      setRemarks('')
      setRefresh((r) => r + 1)
    } catch (e) {
      // Fallback: try alternative endpoint name (OTMS vs HCA)
      if (action === 'take' || action === 'take-ownership') {
        const alt = action === 'take' ? 'take-ownership' : 'take'
        try {
          await apiPost(`/operation-tasks/${taskId}/${alt}`, { remarks: remarks || `Action: ${action}` })
          setSelectedTask(null)
          setDetailEvents([])
          setRemarks('')
          setRefresh((r) => r + 1)
          return
        } catch (e2) {
          setError(e2.message)
          return
        }
      }
      setError(e.message)
    }
  }

  const closeDetail = () => {
    setSelectedTask(null)
    setDetailEvents([])
    setRemarks('')
  }

  const isOpenStatus = (s) => ['Pending', 'In Progress', 'In Review'].includes(s)
  const displayTakenBy = (row) => {
    if (row.taken_by_user_id) return `User #${row.taken_by_user_id}`
    if (row.taken_by_name) return row.taken_by_name
    return 'Unassigned'
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="BUSINESS OPERATIONS / WORKFLOW INBOX"
        title="Operation Task Manager"
        description="Unified workflow task queue for submitted tickets, review assignments, approval decisions, and correction escalations."
        actions={
          <div className="toolbar-actions">
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/operation-tasks/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
                    setError(e.message),
                  )
                }
              >
                Export {fmt.toUpperCase()}
              </button>
            ))}
          </div>
        }
      />

      <div className="kpi-grid">
        <KpiCard label="Total Tasks" value={totalTasks} context="In queue" />
        <KpiCard label="Pending" value={pendingCount} context="Awaiting pickup" />
        <KpiCard label="In Progress" value={inProgressCount} context="Taken by reviewer" />
        <KpiCard label="Completed" value={completedCount} context="Approved / rejected / cancelled" />
      </div>

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Quick Search</label>
            <input
              className="input"
              placeholder="Task #, ticket #, asset…"
              value={filters.search}
              onChange={(e) => {
                setFilters((f) => ({ ...f, search: e.target.value }))
                setPage(1)
              }}
            />
          </div>
          <div className="filter-group">
            <label>Status</label>
            <select
              className="select"
              value={filters.status}
              onChange={(e) => {
                setFilters((f) => ({ ...f, status: e.target.value }))
                setPage(1)
              }}
            >
              <option value="">All Statuses</option>
              <option value="Pending">Pending</option>
              <option value="In Progress">In Progress</option>
              <option value="Approved">Approved</option>
              <option value="Rejected">Rejected</option>
              <option value="Cancelled">Cancelled</option>
            </select>
          </div>
          <div className="filter-group">
            <label>Task Type</label>
            <select
              className="select"
              value={filters.task_type}
              onChange={(e) => {
                setFilters((f) => ({ ...f, task_type: e.target.value }))
                setPage(1)
              }}
            >
              <option value="">All Types</option>
              <option value="OPERATION_APPROVAL">Operation Approval</option>
              <option value="APPROVED_TRANSACTION_REVOKE_REQUEST">Correction Revoke</option>
              <option value="PASSWORD_RESET_REQUEST">Password Reset</option>
            </select>
          </div>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <EmptyState title="No workflow tasks found" description={filters.status || filters.search ? 'Adjust filters or clear search to see tasks.' : 'Tasks appear here when tickets are submitted for approval or correction requests are raised.'} />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Task #</th>
                  <th>Type</th>
                  <th>Ticket #</th>
                  <th>Location</th>
                  <th>Asset</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Taken By</th>
                  <th>Created At</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.task_number}</td>
                    <td className="mono" style={{ fontSize: '12px' }}>{row.task_type?.replace(/_/g, ' ')}</td>
                    <td className="mono">{row.ticket_number || '—'}</td>
                    <td className="mono">{row.location_code || '—'}</td>
                    <td className="mono">{row.primary_asset_code || '—'}</td>
                    <td>{row.priority}</td>
                    <td>
                      <StatusTag status={row.status} />
                    </td>
                    <td>{displayTakenBy(row)}</td>
                    <td>{formatDateTime(row.created_at)}</td>
                    <td>
                      <button type="button" className="btn btn-secondary" onClick={() => fetchTaskDetail(row)}>
                        Manage
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <Pagination
          page={page}
          pageSize={pageSize}
          pages={data.pages || 1}
          total={data.total || 0}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n)
            setPage(1)
          }}
        />
      </section>

      {selectedTask && (
        <EntryDialog
          title={`Task ${selectedTask.task_number} — Ticket ${selectedTask.ticket_number || '—'}`}
          footer={
            <>
              <button type="button" className="btn btn-secondary" onClick={closeDetail}>
                Close
              </button>
              {canUpdate && isOpenStatus(selectedTask.status) && (
                <>
                  {selectedTask.status === 'Pending' && (
                    <button type="button" className="btn btn-secondary" disabled={detailLoading} onClick={() => runAction(selectedTask.id, 'take')}>
                      Take Task
                    </button>
                  )}
                  {selectedTask.status === 'In Progress' && (
                    <button type="button" className="btn btn-secondary" disabled={detailLoading} onClick={() => runAction(selectedTask.id, 'release')}>
                      Release
                    </button>
                  )}
                  <button type="button" className="btn btn-secondary" disabled={detailLoading} onClick={() => runAction(selectedTask.id, 'reject')}>
                    Reject
                  </button>
                  <button type="button" className="btn btn-primary" disabled={detailLoading} onClick={() => runAction(selectedTask.id, 'approve')}>
                    Approve Ticket
                  </button>
                </>
              )}
            </>
          }
        >
          <div className="stack">
            {detailLoading ? (
              <Loading label="Loading task details…" />
            ) : (
              <>
                <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'center' }}>
                  <span><strong>Status:</strong> <StatusTag status={selectedTask.status} /></span>
                  <span><strong>Operation:</strong> {selectedTask.operation_code || '—'}</span>
                  <span><strong>Type:</strong> {selectedTask.task_type}</span>
                  <span><strong>Priority:</strong> {selectedTask.priority}</span>
                </div>
                {selectedTask.correction_request && (
                  <div className="alert alert-info" role="status">
                    <strong>Correction:</strong> {selectedTask.correction_request.request_number} — {selectedTask.correction_request.request_type} ({selectedTask.correction_request.suggested_action})
                    <div className="muted small">{selectedTask.correction_request.reason}</div>
                  </div>
                )}
                <label>
                  Decision Remarks
                  <input className="input" value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Enter review/approval/rejection remarks…" />
                </label>
                {selectedTask.entry && (
                  <div className="card" style={{ padding: '12px', background: 'var(--bg-subtle)' }}>
                    <strong>Linked Ticket:</strong> {selectedTask.entry.ticket_number} ({selectedTask.entry.operation_type_code}) — {selectedTask.entry.status}
                    <div className="muted small">Asset: {selectedTask.entry.asset_code_snapshot || selectedTask.entry.primary_asset_code || '—'} | Location: {selectedTask.entry.location_code || selectedTask.location_code}</div>
                  </div>
                )}
                <div>
                  <strong>Task Event Timeline:</strong>
                  {(detailEvents.length === 0 && !(selectedTask.events || []).length) ? (
                    <div className="muted small" style={{ marginTop: '8px' }}>No task history yet. Actions will be recorded here.</div>
                  ) : (
                    <div className="table-wrap" style={{ marginTop: '8px' }}>
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Event</th>
                            <th>Transition</th>
                            <th>Actor</th>
                            <th>Notes</th>
                            <th>Timestamp</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(detailEvents.length ? detailEvents : (selectedTask.events || [])).map((ev) => (
                            <tr key={ev.id}>
                              <td className="mono">{ev.event_type}</td>
                              <td>
                                {ev.old_status || '—'} → {ev.new_status || '—'}
                              </td>
                              <td>{ev.actor_display || '—'}</td>
                              <td>{ev.notes || '—'}</td>
                              <td>{formatDateTime(ev.created_at)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 4. Approved Transaction Correction Requests (/correction-requests)
// ============================================================================
export function CorrectionRequestsPage() {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('correction_requests:create')
  const canUpdate = hasPermission('correction_requests:update')

  const [filters, setFilters] = useState({ search: '', status: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [approvedEntries, setApprovedEntries] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({
    entry_id: '',
    request_type: 'Quantity / Gauge Correction',
    suggested_action: 'Revoke to Rejected for Re-entry',
    reason: '',
  })
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/correction-requests${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Correction Requests', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize, refresh])

  const openCreator = async () => {
    setCreating(true)
    try {
      const res = await apiGet('/operation-tracking/transactions?status=Approved&page_size=100')
      const items = res.items || []
      setApprovedEntries(items)
      setForm((f) => ({ ...f, entry_id: items[0]?.id || '' }))
    } catch (e) {
      setError(e.message)
    }
  }

  const handleCreate = async () => {
    setSaving(true)
    setError('')
    try {
      await apiPost('/correction-requests', {
        ...form,
        entry_id: Number(form.entry_id),
      })
      setCreating(false)
      setRefresh((r) => r + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="OPERATION TRACKING / GOVERNANCE"
        title="Approved Transaction Correction Requests"
        description="Controlled workflow to request revocation of an Approved custody ticket back to Rejected/Draft for correction, removing its ledger posting until re-approved."
        actions={
          canCreate && (
            <button type="button" className="btn btn-primary" onClick={openCreator}>
              Raise Correction Request
            </button>
          )
        }
      />

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Quick Search</label>
            <input
              className="input"
              placeholder="Request #, ticket #, reason…"
              value={filters.search}
              onChange={(e) => {
                setFilters((f) => ({ ...f, search: e.target.value }))
                setPage(1)
              }}
            />
          </div>
          <div className="filter-group">
            <label>Status</label>
            <select
              className="select"
              value={filters.status}
              onChange={(e) => {
                setFilters((f) => ({ ...f, status: e.target.value }))
                setPage(1)
              }}
            >
              <option value="">All Statuses</option>
              <option value="Pending Admin Review">Pending Admin Review</option>
              <option value="Approval Revoked">Approval Revoked</option>
              <option value="Rejected">Rejected</option>
            </select>
          </div>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <EmptyState title="No correction requests found" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Request #</th>
                  <th>Ticket #</th>
                  <th>Request Type</th>
                  <th>Reason</th>
                  <th>Requested By</th>
                  <th>Status</th>
                  <th>Admin Action</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.request_number}</td>
                    <td className="mono">{row.ticket_number}</td>
                    <td>{row.request_type}</td>
                    <td>{row.reason}</td>
                    <td>{row.requested_by_display}</td>
                    <td>
                      <StatusTag status={row.status} />
                    </td>
                    <td>{row.admin_action || '—'}</td>
                    <td>
                      {canUpdate && row.status === 'Pending Admin Review' && (
                        <div className="toolbar-actions">
                          <button
                            type="button"
                            className="btn btn-primary"
                            onClick={async () => {
                              try {
                                await apiPost(`/correction-requests/${row.id}/revoke`, {
                                  target_status: 'Rejected',
                                  admin_remarks: 'Approval revoked for operator correction',
                                })
                                setRefresh((r) => r + 1)
                              } catch (e) {
                                setError(e.message)
                              }
                            }}
                          >
                            Revoke Approval
                          </button>
                          <button
                            type="button"
                            className="btn btn-secondary"
                            onClick={async () => {
                              try {
                                await apiPost(`/correction-requests/${row.id}/reject`, {
                                  admin_remarks: 'Correction request declined',
                                })
                                setRefresh((r) => r + 1)
                              } catch (e) {
                                setError(e.message)
                              }
                            }}
                          >
                            Decline
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <Pagination
          page={page}
          pageSize={pageSize}
          pages={data.pages || 1}
          total={data.total || 0}
          onPageChange={setPage}
          onPageSizeChange={(n) => {
            setPageSize(n)
            setPage(1)
          }}
        />
      </section>

      {creating && (
        <EntryDialog
          title="Raise Approved Transaction Correction Request"
          footer={
            <>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setCreating(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={handleCreate}>
                {saving ? 'Submitting…' : 'Submit Request'}
              </button>
            </>
          }
        >
          <div className="stack">
            <label>
              Approved Ticket
              <select className="select" value={form.entry_id} onChange={(e) => setForm((f) => ({ ...f, entry_id: e.target.value }))}>
                <option value="">Select Approved Ticket</option>
                {approvedEntries.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.ticket_number} — {t.asset_code_snapshot} ({t.operation_date})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Request Type
              <select className="select" value={form.request_type} onChange={(e) => setForm((f) => ({ ...f, request_type: e.target.value }))}>
                <option value="Quantity / Gauge Correction">Quantity / Gauge Correction</option>
                <option value="Lab Quality / BS&W Correction">Lab Quality / BS&W Correction</option>
                <option value="Wrong Asset / Date Selected">Wrong Asset / Date Selected</option>
              </select>
            </label>
            <label>
              Reason for Correction (minimum 5 characters)
              <input className="input" value={form.reason} onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} />
            </label>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}
