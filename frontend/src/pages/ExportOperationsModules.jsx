import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
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
} from '../components/common/Ui'
import { EntryDialog } from '../components/operationLayouts/EntryFeedback'
import { logUiAction } from '../utils/actionLogger'

const EXPORT_NAV = [
  { label: 'Dashboard', path: '/export-operations/dashboard' },
  { label: 'Transactions', path: '/export-operations/transactions' },
  { label: 'Reports', path: '/export-operations/reports' },
  { label: 'Permits', path: '/export-operations/permits' },
  { label: 'Locations', path: '/export-operations/locations' },
  { label: 'Entities', path: '/export-operations/entities' },
  { label: 'Blocks', path: '/export-operations/blocks' },
  { label: 'Consignees', path: '/export-operations/consignees' },
  { label: 'Settings', path: '/export-operations/settings' },
]

function ExportSubNav({ current }) {
  return (
    <div className="entry-form-actions" style={{ marginBottom: '12px' }}>
      {EXPORT_NAV.map((item) => (
        <Link
          key={item.path}
          to={item.path}
          className={`btn ${current === item.path ? 'btn-primary' : 'btn-secondary'}`}
        >
          {item.label}
        </Link>
      ))}
    </div>
  )
}

// ============================================================================
// 1. Export Operations Dashboard (/export-operations/dashboard)
// ============================================================================
export function ExportDashboardPage() {
  const [quarter, setQuarter] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    apiGet(`/export-operations/dashboard${buildQuery({ quarter })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Export Operations Dashboard', 'View Dashboard', { quarter })
    return () => {
      active = false
    }
  }, [quarter])

  return (
    <div className="page">
      <PageHead
        eyebrow="EXPORT OPERATIONS / EXECUTIVE OVERVIEW"
        title="Export Operations Dashboard"
        description="Live KPIs for quarterly export permit allocations, Bill of Lading lifting volumes, remaining permit balances, and block utilization."
      />
      <ExportSubNav current="/export-operations/dashboard" />

      {error && <Alert tone="danger">{error}</Alert>}
      {loading || !data ? (
        <Loading />
      ) : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Total Exported Volume" value={(data.total_export_volume ?? 0).toLocaleString()} context="BBL lifted" />
            <KpiCard label="Total Permit Volume" value={(data.total_permit_volume ?? 0).toLocaleString()} context="Active permits" />
            <KpiCard label="Remaining Permit Balance" value={(data.total_remaining_permit_volume ?? 0).toLocaleString()} context="Available BBL" />
            <KpiCard
              label="Permits Near Limit"
              value={data.permit_insufficient_count ?? 0}
              context={`Above ${data.insufficient_threshold_pct ?? 90}% utilization`}
            />
          </div>

          <section className="card" style={{ marginTop: '16px' }}>
            <header className="card-header">
              <div>
                <h2 className="card-title">Block & Permit Utilization Summary</h2>
                <p className="card-subtitle">Comparison of allocated quarterly permit volumes vs lifted Bill of Lading transactions.</p>
              </div>
              <input
                className="input mono"
                style={{ maxWidth: '180px' }}
                placeholder="Filter Quarter (e.g. Q4_2026)"
                value={quarter}
                onChange={(e) => setQuarter(e.target.value)}
              />
            </header>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Block</th>
                    <th>Permit #</th>
                    <th>Quarter</th>
                    <th>Permit Volume</th>
                    <th>Exported Volume</th>
                    <th>Remaining Volume</th>
                    <th>Utilization (%)</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.blocks_summary || []).map((b, i) => (
                    <tr key={i}>
                      <td className="mono">{b.block_code}</td>
                      <td className="mono">{b.permit_number || '—'}</td>
                      <td className="mono">{b.quarter || '—'}</td>
                      <td className="mono">{(b.permit_volume ?? 0).toLocaleString()}</td>
                      <td className="mono">{(b.exported_volume ?? 0).toLocaleString()}</td>
                      <td className="mono">{(b.remaining_volume ?? 0).toLocaleString()}</td>
                      <td className="mono">{b.utilization_pct ?? 0}%</td>
                      <td>
                        <StatusTag status={b.is_insufficient ? 'Near Limit' : 'Healthy'} tone={b.is_insufficient ? 'warning' : 'success'} />
                      </td>
                    </tr>
                  ))}
                  {(!data.blocks_summary || data.blocks_summary.length === 0) && (
                    <tr>
                      <td colSpan={8}>No export permit or block activity recorded yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}

// ============================================================================
// 2. Generic Master Builder for Export Locations, Entities, Blocks, Consignees
// ============================================================================
function ExportMasterGrid({
  currentPath,
  title,
  description,
  endpoint,
  columns,
  initialForm,
  renderFormFields,
}) {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('export_operations:create')
  const canUpdate = hasPermission('export_operations:update')
  const canDelete = hasPermission('export_operations:delete')

  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(initialForm)
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`${endpoint}${buildQuery({ search, status, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction(title, 'Apply Filter', { search, status, page })
    return () => {
      active = false
    }
  }, [endpoint, search, status, page, pageSize, refresh, title])

  const openEditor = (row = null) => {
    setEditing(row || { id: null })
    setForm(row ? { ...initialForm, ...row } : { ...initialForm })
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      if (editing?.id) {
        await apiPut(`${endpoint}/${editing.id}`, form)
      } else {
        await apiPost(endpoint, form)
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
        eyebrow="EXPORT OPERATIONS / MASTER DATA"
        title={title}
        description={description}
        actions={
          <div className="toolbar-actions">
            {canCreate && (
              <button type="button" className="btn btn-primary" onClick={() => openEditor(null)}>
                Add Record
              </button>
            )}
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`${endpoint}/export${buildQuery({ search, status, format: fmt })}`).catch((e) =>
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
      <ExportSubNav current={currentPath} />

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Quick Search</label>
            <input
              className="input"
              placeholder="Search code, name…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
            />
          </div>
          <div className="filter-group">
            <label>Status</label>
            <select
              className="select"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value)
                setPage(1)
              }}
            >
              <option value="">All</option>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </div>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <EmptyState title={`No ${title.toLowerCase()} records found`} />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c.key}>{c.label}</th>
                  ))}
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    {columns.map((c) => (
                      <td key={c.key}>
                        {c.key === 'status' ? (
                          <StatusTag status={row.status} />
                        ) : Array.isArray(row[c.key]) ? (
                          row[c.key].join(', ') || '—'
                        ) : (
                          row[c.key] ?? '—'
                        )}
                      </td>
                    ))}
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
                                await apiDelete(`${endpoint}/${row.id}`)
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
          title={editing.id ? `Edit ${title}` : `New ${title}`}
          footer={
            <>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={handleSave}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </>
          }
        >
          <div className="entry-header-grid">{renderFormFields(form, setForm)}</div>
        </EntryDialog>
      )}
    </div>
  )
}

export function ExportLocationsPage() {
  return (
    <ExportMasterGrid
      currentPath="/export-operations/locations"
      title="Export Locations Master"
      description="Manage export terminals and FPSO/FSO lifting locations."
      endpoint="/export-operations/locations"
      columns={[
        { key: 'location_code', label: 'Location Code' },
        { key: 'location_name', label: 'Location Name' },
        { key: 'entity_codes', label: 'Linked Entities' },
        { key: 'description', label: 'Description' },
        { key: 'status', label: 'Status' },
      ]}
      initialForm={{ location_code: '', location_name: '', description: '', entity_codes: [], status: 'Active' }}
      renderFormFields={(form, setForm) => (
        <>
          <label>
            Location Code
            <input className="input mono" value={form.location_code} onChange={(e) => setForm((f) => ({ ...f, location_code: e.target.value }))} />
          </label>
          <label>
            Location Name
            <input className="input" value={form.location_name} onChange={(e) => setForm((f) => ({ ...f, location_name: e.target.value }))} />
          </label>
          <label>
            Description
            <input className="input" value={form.description || ''} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
          </label>
          <label>
            Status
            <select className="select" value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </label>
        </>
      )}
    />
  )
}

export function ExportEntitiesPage() {
  return (
    <ExportMasterGrid
      currentPath="/export-operations/entities"
      title="Export Entities Master"
      description="Manage operating entities and joint-venture partners for export liftings."
      endpoint="/export-operations/entities"
      columns={[
        { key: 'entity_code', label: 'Entity Code' },
        { key: 'entity_name', label: 'Entity Name' },
        { key: 'block_codes', label: 'Linked Blocks' },
        { key: 'description', label: 'Description' },
        { key: 'status', label: 'Status' },
      ]}
      initialForm={{ entity_code: '', entity_name: '', description: '', block_codes: [], status: 'Active' }}
      renderFormFields={(form, setForm) => (
        <>
          <label>
            Entity Code
            <input className="input mono" value={form.entity_code} onChange={(e) => setForm((f) => ({ ...f, entity_code: e.target.value }))} />
          </label>
          <label>
            Entity Name
            <input className="input" value={form.entity_name} onChange={(e) => setForm((f) => ({ ...f, entity_name: e.target.value }))} />
          </label>
          <label>
            Description
            <input className="input" value={form.description || ''} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
          </label>
          <label>
            Status
            <select className="select" value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </label>
        </>
      )}
    />
  )
}

export function ExportBlocksPage() {
  return (
    <ExportMasterGrid
      currentPath="/export-operations/blocks"
      title="Export Blocks Master"
      description="Manage OML/OPL production blocks mapped to export permits and transactions."
      endpoint="/export-operations/blocks"
      columns={[
        { key: 'block_code', label: 'Block Code' },
        { key: 'block_name', label: 'Block Name' },
        { key: 'description', label: 'Description' },
        { key: 'status', label: 'Status' },
      ]}
      initialForm={{ block_code: '', block_name: '', description: '', status: 'Active' }}
      renderFormFields={(form, setForm) => (
        <>
          <label>
            Block Code
            <input className="input mono" value={form.block_code} onChange={(e) => setForm((f) => ({ ...f, block_code: e.target.value }))} />
          </label>
          <label>
            Block Name
            <input className="input" value={form.block_name} onChange={(e) => setForm((f) => ({ ...f, block_name: e.target.value }))} />
          </label>
          <label>
            Description
            <input className="input" value={form.description || ''} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
          </label>
          <label>
            Status
            <select className="select" value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </label>
        </>
      )}
    />
  )
}

export function ExportConsigneesPage() {
  return (
    <ExportMasterGrid
      currentPath="/export-operations/consignees"
      title="Export Consignees Master"
      description="Manage international buyers, off-takers, and destination countries."
      endpoint="/export-operations/consignees"
      columns={[
        { key: 'consignee_code', label: 'Consignee Code' },
        { key: 'consignee_name', label: 'Consignee Name' },
        { key: 'country', label: 'Country' },
        { key: 'contact_info', label: 'Contact Info' },
        { key: 'status', label: 'Status' },
      ]}
      initialForm={{ consignee_code: '', consignee_name: '', country: '', contact_info: '', status: 'Active' }}
      renderFormFields={(form, setForm) => (
        <>
          <label>
            Consignee Code
            <input className="input mono" value={form.consignee_code} onChange={(e) => setForm((f) => ({ ...f, consignee_code: e.target.value }))} />
          </label>
          <label>
            Consignee Name
            <input className="input" value={form.consignee_name} onChange={(e) => setForm((f) => ({ ...f, consignee_name: e.target.value }))} />
          </label>
          <label>
            Country
            <input className="input" value={form.country || ''} onChange={(e) => setForm((f) => ({ ...f, country: e.target.value }))} />
          </label>
          <label>
            Contact Info
            <input className="input" value={form.contact_info || ''} onChange={(e) => setForm((f) => ({ ...f, contact_info: e.target.value }))} />
          </label>
          <label>
            Status
            <select className="select" value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </label>
        </>
      )}
    />
  )
}

// ============================================================================
// 3. Export Permits (/export-operations/permits)
// ============================================================================
export function ExportPermitsPage() {
  return (
    <ExportMasterGrid
      currentPath="/export-operations/permits"
      title="Export Permits Register"
      description="Quarterly regulatory export permits with multi-block assignment, volume ceilings, and automatic quarter-end expiry."
      endpoint="/export-operations/permits"
      columns={[
        { key: 'permit_number', label: 'Permit #' },
        { key: 'location_code', label: 'Location' },
        { key: 'entity_code', label: 'Entity' },
        { key: 'block_codes', label: 'Blocks' },
        { key: 'quarter', label: 'Quarter' },
        { key: 'permit_volume', label: 'Permit Volume' },
        { key: 'exported_volume', label: 'Exported' },
        { key: 'remaining_volume', label: 'Remaining' },
        { key: 'status', label: 'Status' },
      ]}
      initialForm={{
        permit_number: '',
        location_code: '',
        entity_code: '',
        block_codes: ['OML-100'],
        quarter: 'Q4_2026',
        permit_volume: 500000,
        status: 'Active',
      }}
      renderFormFields={(form, setForm) => (
        <>
          <label>
            Permit Number
            <input className="input mono" value={form.permit_number} onChange={(e) => setForm((f) => ({ ...f, permit_number: e.target.value }))} />
          </label>
          <label>
            Location Code
            <input className="input mono" value={form.location_code} onChange={(e) => setForm((f) => ({ ...f, location_code: e.target.value }))} />
          </label>
          <label>
            Entity Code
            <input className="input mono" value={form.entity_code} onChange={(e) => setForm((f) => ({ ...f, entity_code: e.target.value }))} />
          </label>
          <label>
            Block Codes (comma-separated)
            <input
              className="input mono"
              value={Array.isArray(form.block_codes) ? form.block_codes.join(',') : form.block_codes || ''}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  block_codes: e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean),
                }))
              }
            />
          </label>
          <label>
            Quarter (e.g. Q4_2026)
            <input className="input mono" value={form.quarter} onChange={(e) => setForm((f) => ({ ...f, quarter: e.target.value }))} />
          </label>
          <label>
            Permit Volume (BBL)
            <input
              type="number"
              step="any"
              className="input mono"
              value={form.permit_volume}
              onChange={(e) => setForm((f) => ({ ...f, permit_volume: Number(e.target.value) }))}
            />
          </label>
        </>
      )}
    />
  )
}

// ============================================================================
// 4. Export Transactions (/export-operations/transactions)
// ============================================================================
export function ExportTransactionsPage() {
  return (
    <ExportMasterGrid
      currentPath="/export-operations/transactions"
      title="Export Transactions (Bill of Lading)"
      description="Record crude/condensate export liftings by Bill of Lading date, vessel, consignee, destination country, permit, and block volume."
      endpoint="/export-operations/transactions"
      columns={[
        { key: 'bl_date', label: 'BL Date' },
        { key: 'location_code', label: 'Location' },
        { key: 'entity_code', label: 'Entity' },
        { key: 'block_code', label: 'Block' },
        { key: 'permit_number', label: 'Permit #' },
        { key: 'quarter', label: 'Quarter' },
        { key: 'vessel_name', label: 'Vessel' },
        { key: 'consignee', label: 'Consignee' },
        { key: 'country', label: 'Country' },
        { key: 'volume', label: 'Volume (BBL)' },
      ]}
      initialForm={{
        bl_date: new Date().toISOString().slice(0, 10),
        location_code: '',
        entity_code: '',
        block_code: '',
        permit_number: '',
        quarter: 'Q4_2026',
        vessel_name: '',
        consignee: '',
        country: '',
        volume: 50000,
        override_permit_limit: false,
        status: 'Active',
      }}
      renderFormFields={(form, setForm) => (
        <>
          <label>
            Bill of Lading Date
            <input type="date" className="input" value={form.bl_date} onChange={(e) => setForm((f) => ({ ...f, bl_date: e.target.value }))} />
          </label>
          <label>
            Location Code
            <input className="input mono" value={form.location_code} onChange={(e) => setForm((f) => ({ ...f, location_code: e.target.value }))} />
          </label>
          <label>
            Entity Code
            <input className="input mono" value={form.entity_code} onChange={(e) => setForm((f) => ({ ...f, entity_code: e.target.value }))} />
          </label>
          <label>
            Block Code
            <input className="input mono" value={form.block_code || ''} onChange={(e) => setForm((f) => ({ ...f, block_code: e.target.value }))} />
          </label>
          <label>
            Permit Number
            <input className="input mono" value={form.permit_number || ''} onChange={(e) => setForm((f) => ({ ...f, permit_number: e.target.value }))} />
          </label>
          <label>
            Vessel Name
            <input className="input" value={form.vessel_name || ''} onChange={(e) => setForm((f) => ({ ...f, vessel_name: e.target.value }))} />
          </label>
          <label>
            Consignee
            <input className="input" value={form.consignee || ''} onChange={(e) => setForm((f) => ({ ...f, consignee: e.target.value }))} />
          </label>
          <label>
            Destination Country
            <input className="input" value={form.country || ''} onChange={(e) => setForm((f) => ({ ...f, country: e.target.value }))} />
          </label>
          <label>
            Volume (BBL)
            <input
              type="number"
              step="any"
              className="input mono"
              value={form.volume ?? 0}
              onChange={(e) => setForm((f) => ({ ...f, volume: Number(e.target.value) }))}
            />
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={Boolean(form.override_permit_limit)}
              onChange={(e) => setForm((f) => ({ ...f, override_permit_limit: e.target.checked }))}
            />
            <span>Override permit balance limit</span>
          </label>
        </>
      )}
    />
  )
}

// ============================================================================
// 5. Export Reports (/export-operations/reports)
// ============================================================================
export function ExportReportsPage() {
  const [filters, setFilters] = useState({ location_code: '', entity_code: '', block_code: '', quarter: '', country: '', date_from: '', date_to: '' })
  const [data, setData] = useState({ rows: [], total_rows: 0, total_volume: 0 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    apiGet(`/export-operations/report${buildQuery(filters)}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Export Reports', 'Apply Filter', filters)
    return () => {
      active = false
    }
  }, [filters])

  return (
    <div className="page">
      <PageHead
        eyebrow="EXPORT OPERATIONS / ANALYTICAL REPORTING"
        title="Export Operations Report"
        description="Multi-dimensional lifting report by location, entity, block, quarter, consignee, and destination country."
        actions={
          <div className="toolbar-actions">
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/export-operations/transactions/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
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
      <ExportSubNav current="/export-operations/reports" />

      <div className="kpi-grid">
        <KpiCard label="Matching Liftings" value={data.total_rows || 0} context="Bill of Lading records" />
        <KpiCard label="Total Volume (BBL)" value={(data.total_volume || 0).toLocaleString()} context="Cumulative lifted" />
      </div>

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Location Code</label>
            <input className="input mono" value={filters.location_code} onChange={(e) => setFilters((f) => ({ ...f, location_code: e.target.value }))} />
          </div>
          <div className="filter-group">
            <label>Entity Code</label>
            <input className="input mono" value={filters.entity_code} onChange={(e) => setFilters((f) => ({ ...f, entity_code: e.target.value }))} />
          </div>
          <div className="filter-group">
            <label>Block Code</label>
            <input className="input mono" value={filters.block_code} onChange={(e) => setFilters((f) => ({ ...f, block_code: e.target.value }))} />
          </div>
          <div className="filter-group">
            <label>Quarter</label>
            <input className="input mono" value={filters.quarter} onChange={(e) => setFilters((f) => ({ ...f, quarter: e.target.value }))} />
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
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>BL Date</th>
                  <th>Location</th>
                  <th>Entity</th>
                  <th>Block</th>
                  <th>Permit #</th>
                  <th>Quarter</th>
                  <th>Vessel</th>
                  <th>Consignee</th>
                  <th>Country</th>
                  <th>Volume (BBL)</th>
                </tr>
              </thead>
              <tbody>
                {(data.rows || []).map((r) => (
                  <tr key={r.id}>
                    <td>{formatDate(r.bl_date)}</td>
                    <td className="mono">{r.location_code}</td>
                    <td className="mono">{r.entity_code}</td>
                    <td className="mono">{r.block_code}</td>
                    <td className="mono">{r.permit_number || '—'}</td>
                    <td className="mono">{r.quarter}</td>
                    <td>{r.vessel_name || '—'}</td>
                    <td>{r.consignee || '—'}</td>
                    <td>{r.country || '—'}</td>
                    <td className="mono">{(r.volume ?? 0).toLocaleString()}</td>
                  </tr>
                ))}
                {(!data.rows || data.rows.length === 0) && (
                  <tr>
                    <td colSpan={10}>No export transactions match the selected filters.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

// ============================================================================
// 6. Export Settings (/export-operations/settings)
// ============================================================================
export function ExportSettingsPage() {
  const { hasPermission } = usePermissions()
  const canUpdate = hasPermission('export_operations:update')
  const [form, setForm] = useState({
    permit_insufficiency_threshold_pct: 90,
    default_volume_unit: 'BBL',
    auto_expire_permits: true,
  })
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    apiGet('/export-operations/settings')
      .then((res) => setForm(res))
      .catch((e) => setErr(e.message))
  }, [])

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    setMsg('')
    setErr('')
    try {
      const res = await apiPut('/export-operations/settings', {
        ...form,
        permit_insufficiency_threshold_pct: Number(form.permit_insufficiency_threshold_pct),
      })
      setForm(res)
      setMsg('Export operations settings updated.')
    } catch (error) {
      setErr(error.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="EXPORT OPERATIONS / CONFIGURATION"
        title="Export Operations Settings"
        description="Configure permit utilization warning thresholds, default volume units, and automatic quarterly permit expiration."
      />
      <ExportSubNav current="/export-operations/settings" />

      <section className="card" style={{ maxWidth: '640px' }}>
        <form className="stack" onSubmit={handleSave}>
          <label>
            Permit Utilization Alert Threshold (%)
            <input
              type="number"
              min="1"
              max="100"
              step="any"
              className="input mono"
              value={form.permit_insufficiency_threshold_pct}
              onChange={(e) => setForm((f) => ({ ...f, permit_insufficiency_threshold_pct: e.target.value }))}
            />
          </label>
          <label>
            Default Volume Unit
            <select
              className="select"
              value={form.default_volume_unit}
              onChange={(e) => setForm((f) => ({ ...f, default_volume_unit: e.target.value }))}
            >
              <option value="BBL">BBL</option>
              <option value="MT">MT</option>
            </select>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={Boolean(form.auto_expire_permits)}
              onChange={(e) => setForm((f) => ({ ...f, auto_expire_permits: e.target.checked }))}
            />
            <span>Automatically mark permits as Expired once their quarter ends</span>
          </label>
          {err && <Alert tone="danger">{err}</Alert>}
          {msg && <Alert tone="success">{msg}</Alert>}
          {canUpdate && (
            <div>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? 'Saving…' : 'Save Settings'}
              </button>
            </div>
          )}
        </form>
      </section>
    </div>
  )
}
