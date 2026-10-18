import { useEffect, useState } from 'react'
import { apiGet, apiPost, apiPut, apiDelete, apiDownload, apiUpload, buildQuery } from '../api/apiClient'
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
import MasterImportDialog from '../components/common/MasterImportDialog'
import { EntryDialog } from '../components/operationLayouts/EntryFeedback'
import { logUiAction } from '../utils/actionLogger'

const EMPTY_FORM = {
  asset_code: '',
  assignment_location_code: '',
  assigned_to_type: 'Location',
  assigned_to: '',
  assignment_date: new Date().toISOString().slice(0, 10),
  return_date: '',
  remarks: '',
  status: 'Active',
}

export function AssetAssignmentPage() {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('asset_assignments:create')
  const canUpdate = hasPermission('asset_assignments:update')
  const canDelete = hasPermission('asset_assignments:delete')

  const [filters, setFilters] = useState({
    search: '',
    status: '',
    asset_scope: '',
    assigned_to_type: '',
    location_code: '',
    date_from: '',
    date_to: '',
  })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [assets, setAssets] = useState([])
  const [locations, setLocations] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [importing, setImporting] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    apiGet('/assets?page_size=200').then((r) => setAssets(r.items || [])).catch(() => {})
    apiGet('/locations?page_size=200').then((r) => setLocations(r.items || [])).catch(() => {})
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/asset-assignments${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((err) => {
        if (active) setError(err.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Asset Assignment', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize, refresh])

  const setFilter = (k, v) => {
    setFilters((prev) => ({ ...prev, [k]: v }))
    setPage(1)
  }

  const openEditor = (row = null) => {
    setEditing(row || { id: null })
    setForm(
      row
        ? {
            asset_code: row.asset_code,
            assignment_location_code: row.assignment_location_code,
            assigned_to_type: row.assigned_to_type,
            assigned_to: row.assigned_to,
            assignment_date: row.assignment_date || new Date().toISOString().slice(0, 10),
            return_date: row.return_date || '',
            remarks: row.remarks || '',
            status: row.status || 'Active',
          }
        : {
            ...EMPTY_FORM,
            asset_code: assets[0]?.asset_code || '',
            assignment_location_code: locations[0]?.location_code || '',
          },
    )
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const payload = {
        ...form,
        return_date: form.return_date || null,
        remarks: form.remarks || null,
      }
      if (editing?.id) {
        await apiPut(`/asset-assignments/${editing.id}`, payload)
      } else {
        await apiPost('/asset-assignments', payload)
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
        eyebrow="MASTER DATA / ASSET DEPLOYMENT"
        title="Asset Assignment Master"
        description="Assign storage tanks, barges, vessels, FSOs, tankers, prime movers, and flowmeters to operational locations, users, or external custodians."
        actions={
          <div className="toolbar-actions">
            {canCreate && (
              <>
                <button type="button" className="btn btn-primary" onClick={() => openEditor(null)}>
                  Add Assignment
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => setImporting(true)}>
                  Import CSV / XLSX
                </button>
              </>
            )}
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/asset-assignments/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
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
              placeholder="Asset code, custodian, location…"
              value={filters.search}
              onChange={(e) => setFilter('search', e.target.value)}
            />
          </div>
          <div className="filter-group">
            <label>Location</label>
            <select className="select" value={filters.location_code} onChange={(e) => setFilter('location_code', e.target.value)}>
              <option value="">All Locations</option>
              {locations.map((loc) => (
                <option key={loc.id} value={loc.location_code}>
                  {loc.location_code} — {loc.location_name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Assigned To Type</label>
            <select className="select" value={filters.assigned_to_type} onChange={(e) => setFilter('assigned_to_type', e.target.value)}>
              <option value="">All Types</option>
              <option value="Location">Location</option>
              <option value="User">User</option>
              <option value="External">External</option>
            </select>
          </div>
          <div className="filter-group">
            <label>Status</label>
            <select className="select" value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
              <option value="">All</option>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
              <option value="Returned">Returned</option>
            </select>
          </div>
          <div className="filter-group">
            <label>From</label>
            <input type="date" className="input" value={filters.date_from} onChange={(e) => setFilter('date_from', e.target.value)} />
          </div>
          <div className="filter-group">
            <label>To</label>
            <input type="date" className="input" value={filters.date_to} onChange={(e) => setFilter('date_to', e.target.value)} />
          </div>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <EmptyState title="No asset assignments found" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Asset Code</th>
                  <th>Asset Name</th>
                  <th>Scope</th>
                  <th>Location</th>
                  <th>Type</th>
                  <th>Assigned To</th>
                  <th>Assignment Date</th>
                  <th>Return Date</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.asset_code}</td>
                    <td>{row.asset_name}</td>
                    <td>{row.asset_scope}</td>
                    <td className="mono">{row.assignment_location_code}</td>
                    <td>{row.assigned_to_type}</td>
                    <td>{row.assigned_to}</td>
                    <td>{formatDate(row.assignment_date)}</td>
                    <td>{formatDate(row.return_date)}</td>
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
                                await apiDelete(`/asset-assignments/${row.id}`)
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
          title={editing.id ? 'Edit Asset Assignment' : 'New Asset Assignment'}
          footer={
            <>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={handleSave}>
                {saving ? 'Saving…' : 'Save Assignment'}
              </button>
            </>
          }
        >
          <div className="entry-header-grid">
            <label>
              Asset
              <select
                className="select"
                value={form.asset_code}
                onChange={(e) => setForm((f) => ({ ...f, asset_code: e.target.value }))}
              >
                <option value="">Select Asset</option>
                {assets.map((a) => (
                  <option key={a.id} value={a.asset_code}>
                    {a.asset_code} — {a.asset_name} ({a.asset_scope})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Assignment Location
              <select
                className="select"
                value={form.assignment_location_code}
                onChange={(e) => setForm((f) => ({ ...f, assignment_location_code: e.target.value }))}
              >
                <option value="">Select Location</option>
                {locations.map((l) => (
                  <option key={l.id} value={l.location_code}>
                    {l.location_code} — {l.location_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Assigned To Type
              <select
                className="select"
                value={form.assigned_to_type}
                onChange={(e) => setForm((f) => ({ ...f, assigned_to_type: e.target.value }))}
              >
                <option value="Location">Location</option>
                <option value="User">User</option>
                <option value="External">External</option>
              </select>
            </label>
            <label>
              Assigned To (Custodian / Site / User)
              <input
                className="input"
                value={form.assigned_to}
                onChange={(e) => setForm((f) => ({ ...f, assigned_to: e.target.value }))}
              />
            </label>
            <label>
              Assignment Date
              <input
                type="date"
                className="input"
                value={form.assignment_date}
                onChange={(e) => setForm((f) => ({ ...f, assignment_date: e.target.value }))}
              />
            </label>
            <label>
              Return Date
              <input
                type="date"
                className="input"
                value={form.return_date}
                onChange={(e) => setForm((f) => ({ ...f, return_date: e.target.value }))}
              />
            </label>
            <label>
              Status
              <select className="select" value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
                <option value="Active">Active</option>
                <option value="Inactive">Inactive</option>
                <option value="Returned">Returned</option>
              </select>
            </label>
            <label>
              Remarks
              <input
                className="input"
                value={form.remarks}
                onChange={(e) => setForm((f) => ({ ...f, remarks: e.target.value }))}
              />
            </label>
          </div>
        </EntryDialog>
      )}

      {importing && (
        <MasterImportDialog
          title="Asset Assignments"
          templateHeaders={[
            'asset_code',
            'assignment_location_code',
            'assigned_to_type',
            'assigned_to',
            'assignment_date',
            'return_date',
            'status',
            'remarks',
          ]}
          templateFilename="asset-assignments-template.csv"
          onClose={() => setImporting(false)}
          onImported={() => {
            setImporting(false)
            setRefresh((r) => r + 1)
          }}
          importFile={(file) => {
            const fd = new FormData()
            fd.append('file', file)
            return apiUpload('/asset-assignments/import', fd)
          }}
        />
      )}
    </div>
  )
}

export function AssetAssignmentSummaryPage() {
  const [filters, setFilters] = useState({
    search: '',
    status: '',
    asset_scope: '',
    asset_type_code: '',
    location_code: '',
  })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1, kpis: {} })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/asset-assignments/summary${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((err) => {
        if (active) setError(err.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Asset Assignment Summary', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize])

  const setFilter = (k, v) => {
    setFilters((prev) => ({ ...prev, [k]: v }))
    setPage(1)
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="MASTER DATA / DEPLOYMENT MATRIX"
        title="Asset Assignment Summary"
        description="Consolidated deployment overview across all assets, showing active custodians, home vs deployed locations, and unassigned inventory."
        actions={
          <div className="toolbar-actions">
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/asset-assignments/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
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
        <KpiCard label="Total Assets" value={data.kpis?.total_assets ?? 0} context="In Asset Master" />
        <KpiCard label="Currently Assigned" value={data.kpis?.assigned_assets ?? 0} context="Active deployment" />
        <KpiCard label="Unassigned Assets" value={data.kpis?.unassigned_assets ?? 0} context="Available for assignment" />
        <KpiCard label="Active Assignments" value={data.kpis?.active_assignments ?? 0} context="Total active records" />
      </div>

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Quick Search</label>
            <input
              className="input"
              placeholder="Search asset code, name, location…"
              value={filters.search}
              onChange={(e) => setFilter('search', e.target.value)}
            />
          </div>
          <div className="filter-group">
            <label>Scope</label>
            <select className="select" value={filters.asset_scope} onChange={(e) => setFilter('asset_scope', e.target.value)}>
              <option value="">All Scopes</option>
              <option value="Local">Local</option>
              <option value="Global">Global</option>
            </select>
          </div>
          <div className="filter-group">
            <label>Status</label>
            <select className="select" value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
              <option value="">All</option>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
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
                  <th>Asset Code</th>
                  <th>Asset Name</th>
                  <th>Asset Type</th>
                  <th>Scope</th>
                  <th>Home Location</th>
                  <th>Deployment Status</th>
                  <th>Current Location</th>
                  <th>Assigned To</th>
                  <th>Assignment History</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.asset_id}>
                    <td className="mono">{row.asset_code}</td>
                    <td>{row.asset_name}</td>
                    <td>{row.asset_type_code}</td>
                    <td>{row.asset_scope}</td>
                    <td className="mono">{row.home_location_code}</td>
                    <td>
                      <StatusTag status={row.assignment_status} tone={row.assignment_status === 'Assigned' ? 'success' : 'neutral'} />
                    </td>
                    <td className="mono">{row.current_assignment?.assignment_location_code || '—'}</td>
                    <td>{row.current_assignment?.assigned_to || '—'}</td>
                    <td>{row.total_assignments} records</td>
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
    </div>
  )
}
