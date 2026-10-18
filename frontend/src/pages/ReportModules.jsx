import { useEffect, useState } from 'react'
import { apiGet, apiPut, apiDownload, buildQuery } from '../api/apiClient'
import { usePermissions } from '../hooks/usePermissions'
import {
  PageHead,
  KpiCard,
  Alert,
  Loading,
  EmptyState,
} from '../components/common/Ui'
import { EntryDialog } from '../components/operationLayouts/EntryFeedback'
import { logUiAction } from '../utils/actionLogger'

// ============================================================================
// 1. Tank Operation Summary (/tank-operation-summary)
// ============================================================================
export function TankOperationSummaryPage() {
  const [locations, setLocations] = useState([])
  const [tanks, setTanks] = useState([])
  const [filters, setFilters] = useState({
    location_code: '',
    view: 'all_tanks',
    tank_asset_code: '',
    metric: 'NSV',
    date_from: '',
    date_to: '',
  })
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    apiGet('/locations?page_size=200')
      .then((res) => {
        const items = res.items || []
        setLocations(items)
        if (items.length > 0) {
          setFilters((f) => ({ ...f, location_code: f.location_code || items[0].location_code }))
        }
      })
      .catch(() => {})
    apiGet('/assets?asset_type_code=STORAGE_TANK&page_size=200')
      .then((res) => setTanks(res.items || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!filters.location_code) return
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/reports/tank-operation-summary${buildQuery(filters)}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Tank Operation Summary', 'Apply Filter', filters)
    return () => {
      active = false
    }
  }, [filters])

  return (
    <div className="page">
      <PageHead
        eyebrow="REPORT MODULES / TANK LEDGER SUMMARY"
        title="Tank Operation Summary"
        description="Daily opening stock, closing stock, stock difference, and dynamic operation movement columns across all tanks or a single storage tank."
        actions={
          filters.location_code && (
            <div className="toolbar-actions">
              {['csv', 'xlsx', 'pdf'].map((fmt) => (
                <button
                  key={fmt}
                  type="button"
                  className="btn btn-secondary"
                  onClick={() =>
                    apiDownload(`/reports/tank-operation-summary/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
                      setError(e.message),
                    )
                  }
                >
                  Export {fmt.toUpperCase()}
                </button>
              ))}
            </div>
          )
        }
      />

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Location</label>
            <select
              className="select"
              value={filters.location_code}
              onChange={(e) => setFilters((f) => ({ ...f, location_code: e.target.value }))}
            >
              <option value="">Select Location</option>
              {locations.map((l) => (
                <option key={l.id} value={l.location_code}>
                  {l.location_code} — {l.location_name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>View Mode</label>
            <select className="select" value={filters.view} onChange={(e) => setFilters((f) => ({ ...f, view: e.target.value }))}>
              <option value="all_tanks">All Tanks (Location Consolidated)</option>
              <option value="single_tank">Single Storage Tank</option>
            </select>
          </div>
          {filters.view === 'single_tank' && (
            <div className="filter-group">
              <label>Tank Asset</label>
              <select
                className="select"
                value={filters.tank_asset_code}
                onChange={(e) => setFilters((f) => ({ ...f, tank_asset_code: e.target.value }))}
              >
                <option value="">Select Tank</option>
                {tanks.map((t) => (
                  <option key={t.id} value={t.asset_code}>
                    {t.asset_code} — {t.asset_name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="filter-group">
            <label>Volume Basis</label>
            <select className="select" value={filters.metric} onChange={(e) => setFilters((f) => ({ ...f, metric: e.target.value }))}>
              <option value="NSV">NSV (BBL)</option>
              <option value="GSV">GSV (BBL)</option>
              <option value="GOV">GOV (BBL)</option>
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
        ) : !data || !data.rows || data.rows.length === 0 ? (
          <EmptyState title="No approved tank stock ledger entries for the selected location and date window" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Opening Stock</th>
                  <th>Closing Stock</th>
                  <th>Stock Diff</th>
                  {(data.operation_columns || []).map((col) => (
                    <th key={col.key}>{col.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.date}>
                    <td className="mono">{r.date}</td>
                    <td className="mono">{r.opening_stock}</td>
                    <td className="mono">{r.closing_stock}</td>
                    <td className="mono">{r.stock_diff}</td>
                    {(data.operation_columns || []).map((col) => (
                      <td key={col.key} className="mono">
                        {r[col.key] ?? 0}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th>Total</th>
                  <th className="mono">{data.totals?.opening_stock ?? 0}</th>
                  <th className="mono">{data.totals?.closing_stock ?? 0}</th>
                  <th className="mono">{data.totals?.stock_diff ?? 0}</th>
                  {(data.operation_columns || []).map((col) => (
                    <th key={col.key} className="mono">
                      {data.totals?.[col.key] ?? 0}
                    </th>
                  ))}
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

// ============================================================================
// 2. Out-Turn Summary (/out-turn-summary)
// ============================================================================
export function OutTurnSummaryPage() {
  const { hasPermission } = usePermissions()
  const canConfigure = hasPermission('reports:update')
  const [locations, setLocations] = useState([])
  const [filters, setFilters] = useState({ location_code: '', metric: 'NSV', date_from: '', date_to: '' })
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [configOpen, setConfigOpen] = useState(false)
  const [columnsConfig, setColumnsConfig] = useState([])
  const [savingCfg, setSavingCfg] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    apiGet('/locations?page_size=200')
      .then((res) => {
        const items = res.items || []
        setLocations(items)
        if (items.length > 0) {
          setFilters((f) => ({ ...f, location_code: f.location_code || items[0].location_code }))
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!filters.location_code) return
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/reports/out-turn-summary${buildQuery(filters)}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Out-Turn Summary', 'Apply Filter', filters)
    return () => {
      active = false
    }
  }, [filters, refresh])

  const openConfigModal = async () => {
    if (!filters.location_code) return
    try {
      const res = await apiGet(`/reports/out-turn-summary/config${buildQuery({ location_code: filters.location_code })}`)
      setColumnsConfig(res.columns || [])
      setConfigOpen(true)
    } catch (e) {
      setError(e.message)
    }
  }

  const saveConfigModal = async () => {
    setSavingCfg(true)
    try {
      await apiPut('/reports/out-turn-summary/config', {
        location_code: filters.location_code,
        columns: columnsConfig,
      })
      setConfigOpen(false)
      setRefresh((r) => r + 1)
    } catch (e) {
      setError(e.message)
    } finally {
      setSavingCfg(false)
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="REPORT MODULES / PRODUCTION RECONCILIATION"
        title="Out-Turn Summary Report"
        description="Daily production out-turn calculation (Stock Difference + Signed Operation Movements) with configurable per-location columns and signs."
        actions={
          filters.location_code && (
            <div className="toolbar-actions">
              {canConfigure && (
                <button type="button" className="btn btn-secondary" onClick={openConfigModal}>
                  Configure Columns
                </button>
              )}
              {['csv', 'xlsx', 'pdf'].map((fmt) => (
                <button
                  key={fmt}
                  type="button"
                  className="btn btn-secondary"
                  onClick={() =>
                    apiDownload(`/reports/out-turn-summary/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
                      setError(e.message),
                    )
                  }
                >
                  Export {fmt.toUpperCase()}
                </button>
              ))}
            </div>
          )
        }
      />

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Location</label>
            <select
              className="select"
              value={filters.location_code}
              onChange={(e) => setFilters((f) => ({ ...f, location_code: e.target.value }))}
            >
              <option value="">Select Location</option>
              {locations.map((l) => (
                <option key={l.id} value={l.location_code}>
                  {l.location_code} — {l.location_name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Metric</label>
            <select className="select" value={filters.metric} onChange={(e) => setFilters((f) => ({ ...f, metric: e.target.value }))}>
              <option value="NSV">NSV (BBL)</option>
              <option value="GSV">GSV (BBL)</option>
              <option value="GOV">GOV (BBL)</option>
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
        ) : !data || !data.rows || data.rows.length === 0 ? (
          <EmptyState title="No out-turn summary records for the selected criteria" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Opening Stock</th>
                  <th>Closing Stock</th>
                  <th>Stock Diff</th>
                  {(data.columns || []).map((c) => (
                    <th key={c.column_key}>
                      {c.column_label} ({c.sign})
                    </th>
                  ))}
                  <th>Net Production (Out-Turn)</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.date}>
                    <td className="mono">{r.date}</td>
                    <td className="mono">{r.opening_stock}</td>
                    <td className="mono">{r.closing_stock}</td>
                    <td className="mono">{r.stock_diff}</td>
                    {(data.columns || []).map((c) => (
                      <td key={c.column_key} className="mono">
                        {r[c.column_key] ?? 0}
                      </td>
                    ))}
                    <td className="mono">
                      <strong>{r.net_production}</strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {configOpen && (
        <EntryDialog
          title={`Configure Out-Turn Columns — ${filters.location_code}`}
          footer={
            <>
              <button type="button" className="btn btn-secondary" onClick={() => setConfigOpen(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={savingCfg} onClick={saveConfigModal}>
                {savingCfg ? 'Saving…' : 'Save Column Configuration'}
              </button>
            </>
          }
        >
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Operation Code</th>
                  <th>Column Label</th>
                  <th>Sign</th>
                  <th>Visible</th>
                </tr>
              </thead>
              <tbody>
                {columnsConfig.map((col, idx) => (
                  <tr key={col.column_key}>
                    <td className="mono">{col.operation_code}</td>
                    <td>
                      <input
                        className="input"
                        value={col.column_label}
                        onChange={(e) => {
                          const next = [...columnsConfig]
                          next[idx] = { ...next[idx], column_label: e.target.value }
                          setColumnsConfig(next)
                        }}
                      />
                    </td>
                    <td>
                      <select
                        className="select"
                        value={col.sign}
                        onChange={(e) => {
                          const next = [...columnsConfig]
                          next[idx] = { ...next[idx], sign: e.target.value }
                          setColumnsConfig(next)
                        }}
                      >
                        <option value="+">+</option>
                        <option value="-">-</option>
                      </select>
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        checked={Boolean(col.visible)}
                        onChange={(e) => {
                          const next = [...columnsConfig]
                          next[idx] = { ...next[idx], visible: e.target.checked }
                          setColumnsConfig(next)
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 3. Material Balance Report (/material-balance-report)
// ============================================================================
export function MaterialBalanceReportPage() {
  const [locations, setLocations] = useState([])
  const [templates, setTemplates] = useState([])
  const [filters, setFilters] = useState({ location_code: '', template_id: '', date_from: '', date_to: '' })
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    apiGet('/locations?page_size=200')
      .then((res) => {
        const items = res.items || []
        setLocations(items)
        if (items.length > 0) {
          setFilters((f) => ({ ...f, location_code: f.location_code || items[0].location_code }))
        }
      })
      .catch(() => {})
    apiGet('/material-balance-templates?page_size=100')
      .then((res) => setTemplates(res.items || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!filters.location_code) return
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/reports/material-balance${buildQuery(filters)}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Material Balance Report', 'Apply Filter', filters)
    return () => {
      active = false
    }
  }, [filters])

  return (
    <div className="page">
      <PageHead
        eyebrow="REPORT MODULES / ACCOUNTING LEDGER"
        title="Material Balance Report"
        description="Template-driven daily hydrocarbon material balance with automatic opening stock carry-forward, movement columns, book vs physical closing stock, and gain/loss."
        actions={
          filters.location_code && (
            <div className="toolbar-actions">
              {['csv', 'xlsx', 'pdf'].map((fmt) => (
                <button
                  key={fmt}
                  type="button"
                  className="btn btn-secondary"
                  onClick={() =>
                    apiDownload(`/reports/material-balance/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
                      setError(e.message),
                    )
                  }
                >
                  Export {fmt.toUpperCase()}
                </button>
              ))}
            </div>
          )
        }
      />

      {data && (
        <div className="kpi-grid">
          <KpiCard label="Template" value={data.template_name || 'Standard'} context={data.basis || 'NSV'} />
          <KpiCard label="Reporting Days" value={data.total_rows || 0} context={data.location_code} />
        </div>
      )}

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Location</label>
            <select
              className="select"
              value={filters.location_code}
              onChange={(e) => setFilters((f) => ({ ...f, location_code: e.target.value }))}
            >
              <option value="">Select Location</option>
              {locations.map((l) => (
                <option key={l.id} value={l.location_code}>
                  {l.location_code} — {l.location_name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Template</label>
            <select
              className="select"
              value={filters.template_id}
              onChange={(e) => setFilters((f) => ({ ...f, template_id: e.target.value }))}
            >
              <option value="">Default Template</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.template_code} — {t.template_name}
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
        ) : !data || !data.rows || data.rows.length === 0 ? (
          <EmptyState title="No material balance rows for the selected location and date window" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Date</th>
                  {(data.columns || []).map((c) => (
                    <th key={c.column_code}>{c.column_label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.date}>
                    <td className="mono">{r.date}</td>
                    {(data.columns || []).map((c) => (
                      <td key={c.column_code} className="mono">
                        {r[c.column_code] ?? 0}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
