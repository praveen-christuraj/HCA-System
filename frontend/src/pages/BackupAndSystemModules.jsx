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
  formatDateTime,
} from '../components/common/Ui'
import { EntryDialog } from '../components/operationLayouts/EntryFeedback'
import { logUiAction } from '../utils/actionLogger'

// ============================================================================
// 1. Backup & Recovery (/backup-recovery)
// ============================================================================
export function BackupRecoveryPage() {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('backup_recovery:create')
  const canUpdate = hasPermission('backup_recovery:update')

  const [tab, setTab] = useState('jobs')
  const [settings, setSettings] = useState(null)
  const [jobs, setJobs] = useState({ items: [], total: 0, pages: 1 })
  const [restoreRequests, setRestoreRequests] = useState({ items: [], total: 0, pages: 1 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [manualDesc, setManualDesc] = useState('')
  const [restoreModalJob, setRestoreModalJob] = useState(null)
  const [restoreReason, setRestoreReason] = useState('')
  const [restoreImpact, setRestoreImpact] = useState('')
  const [execModalReq, setExecModalReq] = useState(null)
  const [execConfirmText, setExecConfirmText] = useState('')
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    Promise.all([
      apiGet('/backup/settings'),
      apiGet('/backup/jobs?page_size=20'),
      apiGet('/backup/restore-requests?page_size=20'),
    ])
      .then(([s, j, r]) => {
        if (!active) return
        setSettings(s)
        setJobs(j)
        setRestoreRequests(r)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Backup & Recovery', 'View Module', { tab })
    return () => {
      active = false
    }
  }, [refresh, tab])

  const handleManualBackup = async () => {
    setError('')
    setMessage('')
    try {
      const job = await apiPost('/backup/jobs/manual', { description: manualDesc || 'On-demand manual snapshot' })
      setMessage(`Created backup snapshot ${job.backup_number} (${job.table_count} tables, ${job.row_count} rows).`)
      setManualDesc('')
      setRefresh((r) => r + 1)
    } catch (e) {
      setError(e.message)
    }
  }

  const handleSaveSettings = async (e) => {
    e.preventDefault()
    setError('')
    setMessage('')
    try {
      const updated = await apiPut('/backup/settings', {
        enabled: Boolean(settings.enabled),
        schedule_mode: settings.schedule_mode,
        interval_value: Number(settings.interval_value),
        run_time: settings.run_time,
        retention_days: Number(settings.retention_days),
        keep_minimum: Number(settings.keep_minimum),
        compression_enabled: Boolean(settings.compression_enabled),
      })
      setSettings(updated)
      setMessage('Backup schedule and retention settings updated.')
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="BACK-UP MODULES / DISASTER RECOVERY"
        title="Backup & Recovery"
        description="Automated backup scheduling, manual database snapshots with SHA-256 checksum verification, and 4-eyes restore request approval, dry-run validation, and execution."
        actions={
          <div className="toolbar-actions">
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() => apiDownload(`/backup/jobs/export?format=${fmt}`).catch((e) => setError(e.message))}
              >
                Export {fmt.toUpperCase()}
              </button>
            ))}
          </div>
        }
      />

      <div className="kpi-grid">
        <KpiCard label="Backup Jobs" value={jobs.total || 0} context="Recorded snapshots" />
        <KpiCard label="Schedule Status" value={settings?.enabled ? 'Enabled' : 'Manual Only'} context={settings?.schedule_mode || 'Daily'} />
        <KpiCard label="Retention Policy" value={`${settings?.retention_days ?? 30} days`} context={`Keep min ${settings?.keep_minimum ?? 5}`} />
        <KpiCard label="Restore Requests" value={restoreRequests.total || 0} context="4-eyes governed" />
      </div>

      <div className="entry-form-actions" style={{ marginBottom: '12px' }}>
        <button type="button" className={`btn ${tab === 'jobs' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('jobs')}>
          Backup Jobs ({jobs.total || 0})
        </button>
        <button type="button" className={`btn ${tab === 'restores' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('restores')}>
          Restore Requests ({restoreRequests.total || 0})
        </button>
        <button type="button" className={`btn ${tab === 'settings' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('settings')}>
          Schedule & Retention Settings
        </button>
      </div>

      {error && <Alert tone="danger">{error}</Alert>}
      {message && <Alert tone="success">{message}</Alert>}

      {loading ? (
        <Loading />
      ) : tab === 'jobs' ? (
        <section className="card">
          {canCreate && (
            <div className="filter-bar">
              <div className="filter-group" style={{ flex: 1 }}>
                <label>Manual Backup Snapshot Description</label>
                <input
                  className="input"
                  placeholder="e.g. Pre-closing custody snapshot…"
                  value={manualDesc}
                  onChange={(e) => setManualDesc(e.target.value)}
                />
              </div>
              <button type="button" className="btn btn-primary" onClick={handleManualBackup}>
                Run Manual Backup Now
              </button>
            </div>
          )}

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Backup #</th>
                  <th>Type</th>
                  <th>Tables / Rows</th>
                  <th>SHA-256 Checksum</th>
                  <th>Verified</th>
                  <th>Status</th>
                  <th>Completed At</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(jobs.items || []).map((job) => (
                  <tr key={job.id}>
                    <td className="mono">{job.backup_number}</td>
                    <td>{job.backup_type}</td>
                    <td className="mono">
                      {job.table_count} / {job.row_count}
                    </td>
                    <td className="mono small">{(job.checksum_sha256 || '').slice(0, 16)}…</td>
                    <td>
                      <StatusTag
                        status={job.verified_checksum_matched ? 'Verified' : 'Unverified'}
                        tone={job.verified_checksum_matched ? 'success' : 'neutral'}
                      />
                    </td>
                    <td>
                      <StatusTag status={job.status} />
                    </td>
                    <td>{formatDateTime(job.completed_at)}</td>
                    <td>
                      <div className="toolbar-actions">
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={async () => {
                            try {
                              await apiPost(`/backup/jobs/${job.id}/verify`, {})
                              setMessage(`Verified SHA-256 checksum for ${job.backup_number}.`)
                              setRefresh((r) => r + 1)
                            } catch (e) {
                              setError(e.message)
                            }
                          }}
                        >
                          Verify
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => apiDownload(`/backup/jobs/${job.id}/download`).catch((e) => setError(e.message))}
                        >
                          Download
                        </button>
                        {canCreate && (
                          <button type="button" className="btn btn-secondary" onClick={() => setRestoreModalJob(job)}>
                            Request Restore
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {(!jobs.items || jobs.items.length === 0) && (
                  <tr>
                    <td colSpan={8}>No database backups created yet. Click "Run Manual Backup Now" to create a snapshot.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      ) : tab === 'restores' ? (
        <section className="card">
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Request #</th>
                  <th>Backup #</th>
                  <th>Reason</th>
                  <th>Requested By</th>
                  <th>Status</th>
                  <th>Safety Backup</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(restoreRequests.items || []).map((req) => (
                  <tr key={req.id}>
                    <td className="mono">{req.request_number}</td>
                    <td className="mono">{req.backup_number}</td>
                    <td>{req.reason}</td>
                    <td>{req.requested_by_display}</td>
                    <td>
                      <StatusTag status={req.status} />
                    </td>
                    <td className="mono">{req.pre_restore_backup_number || '—'}</td>
                    <td>
                      {canUpdate && (
                        <div className="toolbar-actions">
                          {req.status === 'Pending Approval' && (
                            <>
                              <button
                                type="button"
                                className="btn btn-primary"
                                onClick={async () => {
                                  await apiPost(`/backup/restore-requests/${req.id}/approve`, { remarks: 'Approved' })
                                  setRefresh((r) => r + 1)
                                }}
                              >
                                Approve
                              </button>
                              <button
                                type="button"
                                className="btn btn-secondary"
                                onClick={async () => {
                                  await apiPost(`/backup/restore-requests/${req.id}/reject`, { remarks: 'Rejected' })
                                  setRefresh((r) => r + 1)
                                }}
                              >
                                Reject
                              </button>
                            </>
                          )}
                          {req.status === 'Approved' && (
                            <button
                              type="button"
                              className="btn btn-primary"
                              onClick={async () => {
                                await apiPost(`/backup/restore-requests/${req.id}/validate`, {})
                                setRefresh((r) => r + 1)
                              }}
                            >
                              Dry-Run Validate
                            </button>
                          )}
                          {req.status === 'Validated' && (
                            <button
                              type="button"
                              className="btn btn-primary"
                              onClick={() => {
                                setExecModalReq(req)
                                setExecConfirmText(`EXECUTE RESTORE ${req.request_number}`)
                              }}
                            >
                              Execute Restore
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {(!restoreRequests.items || restoreRequests.items.length === 0) && (
                  <tr>
                    <td colSpan={7}>No restore requests submitted.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        settings && (
          <section className="card" style={{ maxWidth: '640px' }}>
            <form className="stack" onSubmit={handleSaveSettings}>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={Boolean(settings.enabled)}
                  onChange={(e) => setSettings((s) => ({ ...s, enabled: e.target.checked }))}
                />
                <span>Enable Automated Scheduled Backups</span>
              </label>
              <label>
                Schedule Mode
                <select
                  className="select"
                  value={settings.schedule_mode}
                  onChange={(e) => setSettings((s) => ({ ...s, schedule_mode: e.target.value }))}
                >
                  <option value="Daily">Daily</option>
                  <option value="Weekly">Weekly</option>
                  <option value="Hours">Hours</option>
                </select>
              </label>
              <label>
                Run Time (UTC)
                <input
                  className="input mono"
                  value={settings.run_time}
                  onChange={(e) => setSettings((s) => ({ ...s, run_time: e.target.value }))}
                />
              </label>
              <label>
                Retention Days
                <input
                  type="number"
                  className="input mono"
                  value={settings.retention_days}
                  onChange={(e) => setSettings((s) => ({ ...s, retention_days: e.target.value }))}
                />
              </label>
              <label>
                Keep Minimum Snapshots
                <input
                  type="number"
                  className="input mono"
                  value={settings.keep_minimum}
                  onChange={(e) => setSettings((s) => ({ ...s, keep_minimum: e.target.value }))}
                />
              </label>
              {canUpdate && (
                <div>
                  <button type="submit" className="btn btn-primary">
                    Save Schedule Settings
                  </button>
                </div>
              )}
            </form>
          </section>
        )
      )}

      {restoreModalJob && (
        <EntryDialog
          title={`Request Restore — ${restoreModalJob.backup_number}`}
          footer={
            <>
              <button type="button" className="btn btn-secondary" onClick={() => setRestoreModalJob(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={async () => {
                  try {
                    await apiPost('/backup/restore-requests', {
                      backup_job_id: restoreModalJob.id,
                      reason: restoreReason,
                      business_impact: restoreImpact,
                    })
                    setRestoreModalJob(null)
                    setRestoreReason('')
                    setRestoreImpact('')
                    setTab('restores')
                    setRefresh((r) => r + 1)
                  } catch (e) {
                    setError(e.message)
                  }
                }}
              >
                Submit Restore Request
              </button>
            </>
          }
        >
          <div className="stack">
            <label>
              Reason for Restore (minimum 5 characters)
              <input className="input" value={restoreReason} onChange={(e) => setRestoreReason(e.target.value)} />
            </label>
            <label>
              Business Impact Assessment
              <input className="input" value={restoreImpact} onChange={(e) => setRestoreImpact(e.target.value)} />
            </label>
          </div>
        </EntryDialog>
      )}

      {execModalReq && (
        <EntryDialog
          title={`Execute Validated Restore — ${execModalReq.request_number}`}
          footer={
            <>
              <button type="button" className="btn btn-secondary" onClick={() => setExecModalReq(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={async () => {
                  try {
                    await apiPost(`/backup/restore-requests/${execModalReq.id}/execute`, {
                      confirmation_text: execConfirmText,
                      remarks: 'Executed after dry-run validation',
                    })
                    setExecModalReq(null)
                    setRefresh((r) => r + 1)
                  } catch (e) {
                    setError(e.message)
                  }
                }}
              >
                Confirm & Execute Restore
              </button>
            </>
          }
        >
          <div className="stack">
            <Alert tone="warning">
              A pre-restore safety backup snapshot will be created automatically before executing {execModalReq.request_number}.
            </Alert>
            <label>
              Confirmation String (must match EXECUTE RESTORE {execModalReq.request_number})
              <input className="input mono" value={execConfirmText} onChange={(e) => setExecConfirmText(e.target.value)} />
            </label>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 2. System Notification Master (/system-notifications)
// ============================================================================
export function SystemNotificationMasterPage() {
  const { hasPermission } = usePermissions()
  const canCreate = hasPermission('system_notifications:create')
  const canDelete = hasPermission('system_notifications:delete')

  const [filters, setFilters] = useState({ search: '', priority: '', status: '' })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [data, setData] = useState({ items: [], total: 0, pages: 1 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({
    title: '',
    message: '',
    notification_type: 'Info',
    priority: 'Normal',
    target_scope: 'All Users',
    delivery_mode: 'Banner + Inbox',
    requires_acknowledgement: true,
    status: 'Published',
  })
  const [saving, setSaving] = useState(false)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/system-notifications${buildQuery({ ...filters, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('System Notification Master', 'Apply Filter', { ...filters, page })
    return () => {
      active = false
    }
  }, [filters, page, pageSize, refresh])

  const handleCreate = async () => {
    setSaving(true)
    setError('')
    try {
      await apiPost('/system-notifications', form)
      setCreating(false)
      setForm({
        title: '',
        message: '',
        notification_type: 'Info',
        priority: 'Normal',
        target_scope: 'All Users',
        delivery_mode: 'Banner + Inbox',
        requires_acknowledgement: true,
        status: 'Published',
      })
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
        eyebrow="SYSTEM ADMINISTRATION / COMMUNICATIONS"
        title="System Notification Master"
        description="Publish targeted announcements, maintenance alerts, and mandatory acknowledgement notices across users, roles, and operational locations."
        actions={
          <div className="toolbar-actions">
            {canCreate && (
              <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                New Notification
              </button>
            )}
            {['csv', 'xlsx', 'pdf'].map((fmt) => (
              <button
                key={fmt}
                type="button"
                className="btn btn-secondary"
                onClick={() =>
                  apiDownload(`/system-notifications/export${buildQuery({ ...filters, format: fmt })}`).catch((e) =>
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
              placeholder="Notification #, title, message…"
              value={filters.search}
              onChange={(e) => {
                setFilters((f) => ({ ...f, search: e.target.value }))
                setPage(1)
              }}
            />
          </div>
          <div className="filter-group">
            <label>Priority</label>
            <select
              className="select"
              value={filters.priority}
              onChange={(e) => {
                setFilters((f) => ({ ...f, priority: e.target.value }))
                setPage(1)
              }}
            >
              <option value="">All Priorities</option>
              <option value="Low">Low</option>
              <option value="Normal">Normal</option>
              <option value="High">High</option>
              <option value="Critical">Critical</option>
            </select>
          </div>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <EmptyState title="No system notifications published yet" />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Notification #</th>
                  <th>Title</th>
                  <th>Priority</th>
                  <th>Target Scope</th>
                  <th>Recipients</th>
                  <th>Acknowledged</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td className="mono">{row.notification_number}</td>
                    <td>
                      <strong>{row.title}</strong>
                      <div className="muted small">{row.message}</div>
                    </td>
                    <td>{row.priority}</td>
                    <td>{row.target_scope}</td>
                    <td className="mono">{row.total_recipients}</td>
                    <td className="mono">{row.acknowledged_count}</td>
                    <td>
                      <StatusTag status={row.status} />
                    </td>
                    <td>
                      <div className="toolbar-actions">
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={async () => {
                            await apiPost(`/system-notifications/${row.id}/acknowledge`, {})
                            setRefresh((r) => r + 1)
                          }}
                        >
                          Acknowledge
                        </button>
                        {canDelete && (
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={async () => {
                              await apiDelete(`/system-notifications/${row.id}`)
                              setRefresh((r) => r + 1)
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

      {creating && (
        <EntryDialog
          title="Publish System Notification"
          footer={
            <>
              <button type="button" className="btn btn-secondary" disabled={saving} onClick={() => setCreating(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" disabled={saving} onClick={handleCreate}>
                {saving ? 'Publishing…' : 'Publish Notification'}
              </button>
            </>
          }
        >
          <div className="stack">
            <label>
              Title
              <input className="input" value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
            </label>
            <label>
              Message
              <input className="input" value={form.message} onChange={(e) => setForm((f) => ({ ...f, message: e.target.value }))} />
            </label>
            <div className="entry-header-grid">
              <label>
                Priority
                <select className="select" value={form.priority} onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}>
                  <option value="Low">Low</option>
                  <option value="Normal">Normal</option>
                  <option value="High">High</option>
                  <option value="Critical">Critical</option>
                </select>
              </label>
              <label>
                Target Scope
                <select className="select" value={form.target_scope} onChange={(e) => setForm((f) => ({ ...f, target_scope: e.target.value }))}>
                  <option value="All Users">All Users</option>
                  <option value="Roles">Roles</option>
                  <option value="Locations">Locations</option>
                  <option value="Specific Users">Specific Users</option>
                </select>
              </label>
            </div>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={Boolean(form.requires_acknowledgement)}
                onChange={(e) => setForm((f) => ({ ...f, requires_acknowledgement: e.target.checked }))}
              />
              <span>Require user acknowledgement receipt</span>
            </label>
          </div>
        </EntryDialog>
      )}
    </div>
  )
}

// ============================================================================
// 3. Read-Only Database Browser (/database-browser)
// ============================================================================
export function DatabaseBrowserPage() {
  const [tables, setTables] = useState([])
  const [selectedTable, setSelectedTable] = useState('')
  const [tableSearch, setTableSearch] = useState('')
  const [rowSearch, setRowSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [tableData, setTableData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    apiGet(`/database-browser/tables${buildQuery({ search: tableSearch })}`)
      .then((res) => {
        const items = res.items || []
        setTables(items)
        if (!selectedTable && items.length > 0) {
          setSelectedTable(items[0].table_name)
        }
      })
      .catch((e) => setError(e.message))
  }, [tableSearch])

  useEffect(() => {
    if (!selectedTable) return
    let active = true
    setLoading(true)
    setError('')
    apiGet(`/database-browser/tables/${selectedTable}${buildQuery({ search: rowSearch, page, page_size: pageSize })}`)
      .then((res) => {
        if (active) setTableData(res)
      })
      .catch((e) => {
        if (active) setError(e.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    logUiAction('Database Browser', 'Inspect Table', { table: selectedTable, page })
    return () => {
      active = false
    }
  }, [selectedTable, rowSearch, page, pageSize])

  return (
    <div className="page">
      <PageHead
        eyebrow="SYSTEM ADMINISTRATION / SCHEMA DIAGNOSTICS"
        title="Read-Only Database Browser"
        description="Inspect relational database tables, typed columns, primary/foreign keys, and paginated rows with automatic masking of credential hashes and secrets."
        actions={
          selectedTable && (
            <div className="toolbar-actions">
              {['csv', 'xlsx', 'pdf'].map((fmt) => (
                <button
                  key={fmt}
                  type="button"
                  className="btn btn-secondary"
                  onClick={() =>
                    apiDownload(`/database-browser/tables/${selectedTable}/export?format=${fmt}`).catch((e) =>
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

      <div className="kpi-grid">
        <KpiCard label="Total Relational Tables" value={tables.length} context="Zero JSON/JSONB columns" />
        <KpiCard label="Selected Table" value={selectedTable || '—'} context={`${tableData?.total ?? 0} rows`} />
        <KpiCard label="Columns" value={tableData?.columns?.length ?? 0} context="Strictly typed" />
      </div>

      <section className="card">
        <div className="filter-bar">
          <div className="filter-group">
            <label>Select Table</label>
            <select
              className="select mono"
              value={selectedTable}
              onChange={(e) => {
                setSelectedTable(e.target.value)
                setPage(1)
              }}
            >
              {tables.map((t) => (
                <option key={t.table_name} value={t.table_name}>
                  {t.table_name} ({t.row_count} rows, {t.column_count} cols)
                </option>
              ))}
            </select>
          </div>
          <div className="filter-group">
            <label>Filter Rows</label>
            <input
              className="input"
              placeholder="Search text across table columns…"
              value={rowSearch}
              onChange={(e) => {
                setRowSearch(e.target.value)
                setPage(1)
              }}
            />
          </div>
        </div>

        {error && <Alert tone="danger">{error}</Alert>}
        {loading || !tableData ? (
          <Loading />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  {(tableData.columns || []).map((c) => (
                    <th key={c.name} className="mono">
                      {c.name}
                      <div className="muted small">{c.type}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(tableData.items || []).map((row, idx) => (
                  <tr key={idx}>
                    {(tableData.columns || []).map((c) => (
                      <td key={c.name} className="mono small">
                        {row[c.name] === null || row[c.name] === undefined ? 'NULL' : String(row[c.name])}
                      </td>
                    ))}
                  </tr>
                ))}
                {(!tableData.items || tableData.items.length === 0) && (
                  <tr>
                    <td colSpan={(tableData.columns || []).length || 1}>Table is empty.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        <Pagination
          page={page}
          pageSize={pageSize}
          pages={tableData?.total_pages || 1}
          total={tableData?.total || 0}
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
