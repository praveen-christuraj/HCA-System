import { useEffect, useState } from 'react'
import { apiGet, apiPost, apiPut, apiDelete, apiDownload, buildQuery } from '../api/apiClient'
import { usePermissions } from '../hooks/usePermissions'
import {
  PageHead,
  StatusTag,
  Alert,
  Loading,
  EmptyState,
  Pagination,
  formatDate,
} from '../components/common/Ui'
import { EntryDialog } from '../components/operationLayouts/EntryFeedback'
import { logUiAction } from '../utils/actionLogger'

const OP_TYPES = [
  { code: 'TANK_OPERATIONS', name: 'Tank Operations' },
  { code: 'BARGE_OPERATIONS', name: 'Barge Operations' },
  { code: 'SHUTTLE_OPERATIONS', name: 'Shuttle Operations' },
  { code: 'FSO_OPERATIONS', name: 'FSO Operations' },
  { code: 'TANKER_OPERATIONS', name: 'Tanker Operations' },
  { code: 'FLOWMETER_OPERATIONS', name: 'Flowmeter Operations' },
]

// ============================================================================
// 1. Location Operation Availability (/location-operation-availability)
// ============================================================================
export function LocationOperationAvailabilityPage() {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('location_operation_availability:create')
  const canUpdate = hasPermission('location_operation_availability:update')
  const canDelete = hasPermission('location_operation_availability:delete')

  const [filters, setFilters] = useState({ search: '', status: '', location_code: '', operation_type_code: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [locations, setLocations] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({ location_code: '', operation_type_code: 'TANK_OPERATIONS', status: 'Active', remarks: '' })
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    apiGet('/locations?page_size=200').then((r) => setLocations(r.items || [])).catch(() => {})
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/location-operation-availability${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Location Operation Availability', 'Apply Filter', { ...filters, page, page_size: pageSize })
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
            location_code: row.location_code,
            operation_type_code: row.operation_type_code,
            status: row.status,
            remarks: row.remarks || '',
          }
        : {
            location_code: locations[0]?.location_code || '',
            operation_type_code: 'TANK_OPERATIONS',
            status: 'Active',
            remarks: '',
          },
    )
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      if (editing?.id) {
        await apiPut(`/location-operation-availability/${editing.id}`, form)
      } else {
        await apiPost('/location-operation-availability', form)
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
        eyebrow="CONFIGURATIONS / LOCATION CAPABILITIES"
        title="Location Operation Availability"
        description="Configure which of the six fixed operation types are enabled at each operational location."
        actions={
          <div className="toolbar-actions">
            {canCreate && (
              <button type="button" className="btn btn-primary" onClick={() => openEditor(null)}>
                Add Availability Rule
              </button>
            )}
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/location-operation-availability/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
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
            <input className="input" value={filters.search} onChange={(e) => setFilter('search', e.target.value)} placeholder="Location, operation type…" />
          </div>
          <div className="filter-group">
            <label>Location</label>
            <select className="select" value={filters.location_code} onChange={(e) => setFilter('location_code', e.target.value)}>
              <option value="">All Locations</option>
              {locations.map((l) => (
                <option key={l.id} value={l.location_code}>
                  {l.location_code} — {l.location_name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Operation Type</label>
            <select className="select" value={filters.operation_type_code} onChange={(e) => setFilter('operation_type_code', e.target.value)}>
              <option value="">All Operation Types</option>
              {OP_TYPES.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name}
                </option>
              ))}
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
        ) : data.items.length === 0 ? (
          <EmptyState title="No availability rules configured" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Location Code</th>
                  <th>Location Name</th>
                  <th>Operation Type</th>
                  <th>Asset Type</th>
                  <th>Remarks</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.location_code}</td>
                    <td>{row.location_name}</td>
                    <td>{row.operation_type_name}</td>
                    <td className="mono">{row.asset_type_code}</td>
                    <td>{row.remarks || '—'}</td>
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
                                await apiDelete(`/location-operation-availability/${row.id}`)
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
          title={editing.id ? 'Edit Location Operation Availability' : 'Add Location Operation Availability'}
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
              Operation Type
              <select className="select" value={form.operation_type_code} onChange={(e) => setForm((f) => ({ ...f, operation_type_code: e.target.value }))}>
                {OP_TYPES.map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Status
              <select className="select" value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
                <option value="Active">Active</option>
                <option value="Inactive">Inactive</option>
              </select>
            </label>
            <label>
              Remarks
              <input className="input" value={form.remarks} onChange={(e) => setForm((f) => ({ ...f, remarks: e.target.value }))} />
            </label>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 2. Location Operation Summary (/location-operation-summary)
// ============================================================================
export function LocationOperationSummaryPage() {
  const [filters, setFilters] = useState({ search: '', location_code: '', operation_type_code: '', status: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/location-operation-availability/summary${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Location Operation Summary', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize])

  return (
    <div className="page">
      <PageHead
        eyebrow="CONFIGURATIONS / LOCATION MATRIX"
        title="Location Operation Summary"
        description="Matrix view of each location's enabled operation types and active Operation Master codes."
      />
      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Quick Search</label>
            <input
              className="input"
              placeholder="Location code or name…"
              value={filters.search}
              onChange={(e) => {
                setFilters((f) => ({ ...f, search: e.target.value }))
                setPage(1)
              }}
            />
          </div>
          <div className="filter-group">
            <label>Operation Type</label>
            <select
              className="select"
              value={filters.operation_type_code}
              onChange={(e) => {
                setFilters((f) => ({ ...f, operation_type_code: e.target.value }))
                setPage(1)
              }}
            >
              <option value="">All Operation Types</option>
              {OP_TYPES.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name}
                </option>
              ))}
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
                  <th>Location Code</th>
                  <th>Location Name</th>
                  <th>Status</th>
                  <th>Operation Types Enabled</th>
                  <th>Active Operations</th>
                  <th>Breakdown by Operation Type</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.location_id}>
                    <td className="mono">{row.location_code}</td>
                    <td>{row.location_name}</td>
                    <td>
                      <StatusTag status={row.location_status} />
                    </td>
                    <td>{row.enabled_operation_types_count}</td>
                    <td>{row.active_operations_count}</td>
                    <td>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {(row.operation_types || []).map((t) => (
                          <span key={t.operation_type_code} className="tag">
                            {t.operation_type_name}: {t.active_operations} ({t.availability_status})
                          </span>
                        ))}
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
    </div>
  )
}

// ============================================================================
// 3. Location Accounting Day Setting (/location-accounting-day-settings)
// ============================================================================
export function LocationAccountingDaySettingPage() {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('location_accounting_day_settings:create')
  const canUpdate = hasPermission('location_accounting_day_settings:update')
  const canDelete = hasPermission('location_accounting_day_settings:delete')

  const [filters, setFilters] = useState({ search: '', status: '', location_code: '', date_from: '', date_to: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [locations, setLocations] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({
    location_code: '',
    day_start_time: '06:00',
    day_end_time: '06:00',
    effective_from: new Date().toISOString().slice(0, 10),
    effective_to: '',
    timezone_name: 'Africa/Lagos',
    description: '',
    status: 'Active',
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
    apiGet(`/location-accounting-day-settings${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Location Accounting Day Setting', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize, refresh])

  const openEditor = (row = null) => {
    setEditing(row || { id: null })
    setForm(
      row
        ? {
            location_code: row.location_code,
            day_start_time: row.day_start_time || '06:00',
            day_end_time: row.day_end_time || '06:00',
            effective_from: row.effective_from || new Date().toISOString().slice(0, 10),
            effective_to: row.effective_to || '',
            timezone_name: row.timezone_name || 'Africa/Lagos',
            description: row.description || '',
            status: row.status || 'Active',
          }
        : {
            location_code: locations[0]?.location_code || '',
            day_start_time: '06:00',
            day_end_time: '06:00',
            effective_from: new Date().toISOString().slice(0, 10),
            effective_to: '',
            timezone_name: 'Africa/Lagos',
            description: 'Standard 06:00 to 06:00 hydrocarbon accounting day window',
            status: 'Active',
          },
    )
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const payload = { ...form, effective_to: form.effective_to || null }
      if (editing?.id) {
        await apiPut(`/location-accounting-day-settings/${editing.id}`, payload)
      } else {
        await apiPost('/location-accounting-day-settings', payload)
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
        eyebrow="CONFIGURATIONS / ACCOUNTING WINDOWS"
        title="Location Accounting Day Setting"
        description="Configure location-specific accounting day start/end cut-off times, effective date windows, and timezones without overlaps."
        actions={
          <div className="toolbar-actions">
            {canCreate && (
              <button type="button" className="btn btn-primary" onClick={() => openEditor(null)}>
                Add Accounting Window
              </button>
            )}
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/location-accounting-day-settings/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
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
              placeholder="Location code, timezone, description…"
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
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <EmptyState title="No accounting day settings configured" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Location</th>
                  <th>Day Start</th>
                  <th>Day End</th>
                  <th>Effective From</th>
                  <th>Effective To</th>
                  <th>Timezone</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.location_code}</td>
                    <td className="mono">{row.day_start_time}</td>
                    <td className="mono">{row.day_end_time}</td>
                    <td>{formatDate(row.effective_from)}</td>
                    <td>{row.effective_to ? formatDate(row.effective_to) : 'Open-ended'}</td>
                    <td className="mono">{row.timezone_name}</td>
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
                                await apiDelete(`/location-accounting-day-settings/${row.id}`)
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
          title={editing.id ? 'Edit Accounting Day Window' : 'Add Accounting Day Window'}
          footer={
            <>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={handleSave}>
                {saving ? 'Saving…' : 'Save Window'}
              </button>
            </>
          }
        >
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
              Day Start Time (HH:MM)
              <input className="input mono" value={form.day_start_time} onChange={(e) => setForm((f) => ({ ...f, day_start_time: e.target.value }))} />
            </label>
            <label>
              Day End Time (HH:MM)
              <input className="input mono" value={form.day_end_time} onChange={(e) => setForm((f) => ({ ...f, day_end_time: e.target.value }))} />
            </label>
            <label>
              Effective From
              <input type="date" className="input" value={form.effective_from} onChange={(e) => setForm((f) => ({ ...f, effective_from: e.target.value }))} />
            </label>
            <label>
              Effective To (Optional)
              <input type="date" className="input" value={form.effective_to} onChange={(e) => setForm((f) => ({ ...f, effective_to: e.target.value }))} />
            </label>
            <label>
              Timezone
              <input className="input mono" value={form.timezone_name} onChange={(e) => setForm((f) => ({ ...f, timezone_name: e.target.value }))} />
            </label>
            <label>
              Status
              <select className="select" value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
                <option value="Active">Active</option>
                <option value="Inactive">Inactive</option>
              </select>
            </label>
            <label>
              Description
              <input className="input" value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
            </label>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 4. Company Report Profile Master (/company-report-profiles)
// ============================================================================
export function CompanyReportProfileMasterPage() {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('company_report_profiles:create')
  const canUpdate = hasPermission('company_report_profiles:update')
  const canDelete = hasPermission('company_report_profiles:delete')

  const [filters, setFilters] = useState({ search: '', status: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({
    profile_code: '',
    company_name: '',
    company_short_name: '',
    report_header_line_1: '',
    report_header_line_2: '',
    address_line: '',
    email: '',
    phone: '',
    footer_text: '',
    primary_color: '#0F2D59',
    accent_color: '#1D4ED8',
    is_default: false,
    status: 'Active',
  })
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/company-report-profiles${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Company Report Profile Master', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize, refresh])

  const openEditor = (row = null) => {
    setEditing(row || { id: null })
    setForm(
      row
        ? {
            profile_code: row.profile_code,
            company_name: row.company_name,
            company_short_name: row.company_short_name || '',
            report_header_line_1: row.report_header_line_1 || '',
            report_header_line_2: row.report_header_line_2 || '',
            address_line: row.address_line || '',
            email: row.email || '',
            phone: row.phone || '',
            footer_text: row.footer_text || '',
            primary_color: row.primary_color || '#0F2D59',
            accent_color: row.accent_color || '#1D4ED8',
            is_default: Boolean(row.is_default),
            status: row.status || 'Active',
          }
        : {
            profile_code: '',
            company_name: '',
            company_short_name: '',
            report_header_line_1: '',
            report_header_line_2: '',
            address_line: '',
            email: '',
            phone: '',
            footer_text: '',
            primary_color: '#0F2D59',
            accent_color: '#1D4ED8',
            is_default: false,
            status: 'Active',
          },
    )
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      if (editing?.id) {
        await apiPut(`/company-report-profiles/${editing.id}`, form)
      } else {
        await apiPost('/company-report-profiles', form)
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
        eyebrow="CONFIGURATIONS / REPORT BRANDING"
        title="Company Report Profile Master"
        description="Manage corporate header branding, address lines, signature block labels, and footer text applied to PDF and print reports."
        actions={
          <div className="toolbar-actions">
            {canCreate && (
              <button type="button" className="btn btn-primary" onClick={() => openEditor(null)}>
                New Report Profile
              </button>
            )}
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/company-report-profiles/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
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
              placeholder="Profile code, company name…"
              value={filters.search}
              onChange={(e) => {
                setFilters((f) => ({ ...f, search: e.target.value }))
                setPage(1)
              }}
            />
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
                  <th>Profile Code</th>
                  <th>Company Name</th>
                  <th>Header Line</th>
                  <th>Email</th>
                  <th>Default</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.profile_code}</td>
                    <td>
                      <strong>{row.company_name}</strong>
                    </td>
                    <td>{row.report_header_line_1 || '—'}</td>
                    <td>{row.email || '—'}</td>
                    <td>{row.is_default ? <span className="tag tag-success">Default</span> : '—'}</td>
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
                        {canDelete && !row.is_default && (
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={async () => {
                              try {
                                await apiDelete(`/company-report-profiles/${row.id}`)
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
          title={editing.id ? 'Edit Company Report Profile' : 'Create Company Report Profile'}
          footer={
            <>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={handleSave}>
                {saving ? 'Saving…' : 'Save Profile'}
              </button>
            </>
          }
        >
          <div className="entry-header-grid">
            <label>
              Profile Code
              <input className="input mono" value={form.profile_code} onChange={(e) => setForm((f) => ({ ...f, profile_code: e.target.value }))} />
            </label>
            <label>
              Company Name
              <input className="input" value={form.company_name} onChange={(e) => setForm((f) => ({ ...f, company_name: e.target.value }))} />
            </label>
            <label>
              Short Name
              <input className="input" value={form.company_short_name} onChange={(e) => setForm((f) => ({ ...f, company_short_name: e.target.value }))} />
            </label>
            <label>
              Report Header Line 1
              <input className="input" value={form.report_header_line_1} onChange={(e) => setForm((f) => ({ ...f, report_header_line_1: e.target.value }))} />
            </label>
            <label>
              Address Line
              <input className="input" value={form.address_line} onChange={(e) => setForm((f) => ({ ...f, address_line: e.target.value }))} />
            </label>
            <label>
              Email
              <input className="input" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            </label>
            <label>
              Footer Text
              <input className="input" value={form.footer_text} onChange={(e) => setForm((f) => ({ ...f, footer_text: e.target.value }))} />
            </label>
            <label>
              Status
              <select className="select" value={form.status} onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}>
                <option value="Active">Active</option>
                <option value="Inactive">Inactive</option>
              </select>
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={form.is_default} onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))} />
              <span>Set as Default Report Profile</span>
            </label>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 5. Material Balance Template Master (/material-balance-template-master)
// ============================================================================
export function MaterialBalanceTemplateMasterPage() {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('material_balance_templates:create')
  const canUpdate = hasPermission('material_balance_templates:update')
  const canDelete = hasPermission('material_balance_templates:delete')

  const [filters, setFilters] = useState({ search: '', status: '', location_code: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({
    template_code: '',
    template_name: '',
    location_code: 'ALL',
    basis: 'NSV',
    reporting_unit: 'BBL',
    is_default: false,
    status: 'Active',
    description: '',
    columns: [],
  })
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/material-balance-templates${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Material Balance Template Master', 'Apply Filter', { ...filters, page, page_size: pageSize })
    return () => {
      active = false
    }
  }, [filters, page, pageSize, refresh])

  const openEditor = (row = null) => {
    setEditing(row || { id: null })
    setForm(
      row
        ? {
            template_code: row.template_code,
            template_name: row.template_name,
            location_code: row.location_code || 'ALL',
            basis: row.basis || 'NSV',
            reporting_unit: row.reporting_unit || 'BBL',
            is_default: Boolean(row.is_default),
            status: row.status || 'Active',
            description: row.description || '',
            columns: (row.columns || []).map((c) => ({
              column_code: c.column_code,
              column_label: c.column_label,
              column_group: c.column_group || 'MOVEMENTS',
              column_type: c.column_type || 'OPERATION_SUM',
              unit: c.unit || 'BBL',
              display_order: c.display_order || 1,
              source_metric: c.source_metric || 'NSV',
              sign_multiplier: c.sign_multiplier ?? 1,
              visible: c.visible !== false,
              include_operation_codes: c.include_operation_codes || [],
              exclude_operation_codes: c.exclude_operation_codes || [],
            })),
          }
        : {
            template_code: '',
            template_name: '',
            location_code: 'ALL',
            basis: 'NSV',
            reporting_unit: 'BBL',
            is_default: false,
            status: 'Active',
            description: '',
            columns: [
              { column_code: 'OPENING_STOCK', column_label: 'Opening Stock', column_group: 'STOCK', column_type: 'OPENING_STOCK', unit: 'BBL', display_order: 1, source_metric: 'NSV', sign_multiplier: 1, visible: true, include_operation_codes: [], exclude_operation_codes: [] },
              { column_code: 'RECEIPTS', column_label: 'Receipts (+)', column_group: 'MOVEMENTS', column_type: 'CATEGORY_TOTAL', unit: 'BBL', display_order: 2, source_metric: 'NSV', sign_multiplier: 1, visible: true, include_operation_codes: [], exclude_operation_codes: [] },
              { column_code: 'DISPATCHES', column_label: 'Dispatches (-)', column_group: 'MOVEMENTS', column_type: 'CATEGORY_TOTAL', unit: 'BBL', display_order: 3, source_metric: 'NSV', sign_multiplier: -1, visible: true, include_operation_codes: [], exclude_operation_codes: [] },
              { column_code: 'CLOSING_STOCK', column_label: 'Physical Closing Stock', column_group: 'STOCK', column_type: 'CLOSING_STOCK', unit: 'BBL', display_order: 4, source_metric: 'NSV', sign_multiplier: 1, visible: true, include_operation_codes: [], exclude_operation_codes: [] },
              { column_code: 'GAIN_LOSS', column_label: 'Gain / Loss', column_group: 'SUMMARY', column_type: 'GAIN_LOSS', unit: 'BBL', display_order: 5, source_metric: 'NSV', sign_multiplier: 1, visible: true, include_operation_codes: [], exclude_operation_codes: [] },
            ],
          },
    )
  }

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      if (editing?.id) {
        await apiPut(`/material-balance-templates/${editing.id}`, form)
      } else {
        await apiPost('/material-balance-templates', form)
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
        eyebrow="CONFIGURATIONS / MATERIAL BALANCE TEMPLATES"
        title="Material Balance Template Master"
        description="Configure multi-column Material Balance Report templates with typed column rules, operation code inclusions/exclusions, and formula columns."
        actions={
          <div className="toolbar-actions">
            {canCreate && (
              <button type="button" className="btn btn-primary" onClick={() => openEditor(null)}>
                New Template
              </button>
            )}
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/material-balance-templates/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
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
              placeholder="Template code, name, location…"
              value={filters.search}
              onChange={(e) => {
                setFilters((f) => ({ ...f, search: e.target.value }))
                setPage(1)
              }}
            />
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
                  <th>Template Code</th>
                  <th>Template Name</th>
                  <th>Location</th>
                  <th>Basis / Unit</th>
                  <th>Columns</th>
                  <th>Default</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.template_code}</td>
                    <td>
                      <strong>{row.template_name}</strong>
                    </td>
                    <td className="mono">{row.location_code}</td>
                    <td>
                      {row.basis} ({row.reporting_unit})
                    </td>
                    <td>{(row.columns || []).length} columns</td>
                    <td>{row.is_default ? <span className="tag tag-success">Default</span> : '—'}</td>
                    <td>
                      <StatusTag status={row.status} />
                    </td>
                    <td>
                      <div className="toolbar-actions">
                        {canUpdate && (
                          <button type="button" className="btn btn-ghost" onClick={() => openEditor(row)}>
                            Edit Columns
                          </button>
                        )}
                        {canDelete && !row.is_default && (
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={async () => {
                              try {
                                await apiDelete(`/material-balance-templates/${row.id}`)
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
          title={editing.id ? `Edit Template — ${form.template_code}` : 'New Material Balance Template'}
          footer={
            <>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={handleSave}>
                {saving ? 'Saving…' : 'Save Template'}
              </button>
            </>
          }
        >
          <div className="stack">
            <div className="entry-header-grid">
              <label>
                Template Code
                <input className="input mono" value={form.template_code} onChange={(e) => setForm((f) => ({ ...f, template_code: e.target.value }))} />
              </label>
              <label>
                Template Name
                <input className="input" value={form.template_name} onChange={(e) => setForm((f) => ({ ...f, template_name: e.target.value }))} />
              </label>
              <label>
                Location Code (or ALL)
                <input className="input mono" value={form.location_code} onChange={(e) => setForm((f) => ({ ...f, location_code: e.target.value }))} />
              </label>
              <label>
                Basis
                <select className="select" value={form.basis} onChange={(e) => setForm((f) => ({ ...f, basis: e.target.value }))}>
                  <option value="NSV">NSV</option>
                  <option value="GSV">GSV</option>
                  <option value="GOV">GOV</option>
                </select>
              </label>
            </div>
            <div>
              <strong>Configured Columns ({form.columns.length})</strong>
              <div className="table-wrap" style={{ marginTop: '8px' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Order</th>
                      <th>Code</th>
                      <th>Label</th>
                      <th>Type</th>
                      <th>Sign</th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.columns.map((col, idx) => (
                      <tr key={idx}>
                        <td>{col.display_order}</td>
                        <td className="mono">{col.column_code}</td>
                        <td>
                          <input
                            className="input"
                            value={col.column_label}
                            onChange={(e) => {
                              const next = [...form.columns]
                              next[idx] = { ...next[idx], column_label: e.target.value }
                              setForm((f) => ({ ...f, columns: next }))
                            }}
                          />
                        </td>
                        <td className="mono">{col.column_type}</td>
                        <td className="mono">{col.sign_multiplier > 0 ? '+' : '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}
