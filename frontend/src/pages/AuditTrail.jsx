import { useCallback, useEffect, useMemo, useState } from 'react'
import { downloadAuditExport, listAuditLogs } from '../api/auditApi'
import Icon from '../components/common/Icon'
import {
  Alert,
  EmptyState,
  formatDateTime,
  Loading,
  PageHead,
  Pagination,
  StatusTag,
} from '../components/common/Ui'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'

const EMPTY_FILTERS = {
  search: '',
  module_name: '',
  category: '',
  outcome: '',
  actor_username: '',
  date_from: '',
  date_to: '',
}

const truncate = (value, length = 90) => {
  if (!value) return '—'
  return value.length > length ? `${value.slice(0, length - 1)}…` : value
}

export default function AuditTrail() {
  const { isAdmin, hasPermission } = usePermissions()
  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [data, setData] = useState({ items: [], total: 0, pages: 0 })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState('')

  const canExport = isAdmin || hasPermission('audit:read')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const response = await listAuditLogs({ ...applied, page, page_size: pageSize })
      setData(response)
    } catch (loadError) {
      setError(loadError.message || 'Unable to load the audit trail')
      setData({ items: [], total: 0, pages: 0 })
    } finally {
      setLoading(false)
    }
  }, [applied, page, pageSize])

  useEffect(() => {
    load()
  }, [load])

  const activeChips = useMemo(() => {
    const chips = []
    if (applied.search) chips.push({ key: 'search', label: `Search: ${applied.search}` })
    if (applied.module_name) chips.push({ key: 'module_name', label: `Module: ${applied.module_name}` })
    if (applied.category) chips.push({ key: 'category', label: `Category: ${applied.category}` })
    if (applied.outcome) chips.push({ key: 'outcome', label: `Outcome: ${applied.outcome}` })
    if (applied.actor_username)
      chips.push({ key: 'actor_username', label: `Actor: ${applied.actor_username}` })
    if (applied.date_from) chips.push({ key: 'date_from', label: `From: ${applied.date_from}` })
    if (applied.date_to) chips.push({ key: 'date_to', label: `To: ${applied.date_to}` })
    return chips
  }, [applied])

  const applyFilters = () => {
    setApplied({ ...draft })
    setPage(1)
    logUiAction('Audit Trail', 'Apply Filter', {
      module: draft.module_name || 'all',
      outcome: draft.outcome || 'all',
      has_date_range: Boolean(draft.date_from || draft.date_to),
    })
  }

  const resetFilters = () => {
    setDraft(EMPTY_FILTERS)
    setApplied(EMPTY_FILTERS)
    setPage(1)
    logUiAction('Audit Trail', 'Reset Filter')
  }

  const handleExport = async (format) => {
    setExporting(format)
    setError('')
    try {
      await downloadAuditExport(format, applied)
    } catch (exportError) {
      setError(exportError.message || 'Export failed')
    } finally {
      setExporting('')
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="AUDITING / AUDIT TRAIL"
        title="Audit trail"
        description="Append-only record of sign-ins, data changes, exports, security events and client-side actions. Import is intentionally unavailable for immutable audit data."
        actions={
          <button type="button" className="btn btn-secondary" onClick={load} disabled={loading}>
            <Icon name="refresh" size={15} />
            Refresh
          </button>
        }
      />

      {error && <Alert tone="danger">{error}</Alert>}

      <section className="card">
        <div className="toolbar">
          <div className="toolbar-group">
            <form
              className="toolbar-group"
              onSubmit={(event) => {
                event.preventDefault()
                applyFilters()
              }}
            >
              <div className="search-field">
                <Icon name="search" size={15} className="search-icon" />
                <input
                  className="input"
                  type="search"
                  value={draft.search}
                  onChange={(event) => setDraft({ ...draft, search: event.target.value })}
                  placeholder="Search actor, module, action, entity or details"
                  aria-label="Quick search audit trail"
                />
              </div>
              <button type="submit" className="btn btn-primary">
                Search
              </button>
            </form>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setShowAdvanced((value) => !value)}
              aria-expanded={showAdvanced}
            >
              <Icon name="filter" size={15} />
              Advanced filters
            </button>
          </div>

          <div className="toolbar-spacer" />

          {canExport && (
            <div className="toolbar-group" role="group" aria-label="Export audit trail">
              <span className="muted small">Export</span>
              {['csv', 'xlsx', 'pdf'].map((format) => (
                <button
                  key={format}
                  type="button"
                  className="btn btn-secondary btn-compact"
                  onClick={() => handleExport(format)}
                  disabled={Boolean(exporting)}
                >
                  <Icon name="download" size={14} />
                  {exporting === format ? 'Exporting…' : format.toUpperCase()}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="filters-panel">
          {showAdvanced && (
            <div className="filters-grid">
              <label className="field">
                <span className="field-label">Module</span>
                <select
                  className="select"
                  value={draft.module_name}
                  onChange={(event) => setDraft({ ...draft, module_name: event.target.value })}
                >
                  <option value="">All modules</option>
                  {(data.modules || []).map((module) => (
                    <option key={module} value={module}>
                      {module}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span className="field-label">Category</span>
                <select
                  className="select"
                  value={draft.category}
                  onChange={(event) => setDraft({ ...draft, category: event.target.value })}
                >
                  <option value="">All categories</option>
                  {(data.categories || []).map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span className="field-label">Outcome</span>
                <select
                  className="select"
                  value={draft.outcome}
                  onChange={(event) => setDraft({ ...draft, outcome: event.target.value })}
                >
                  <option value="">All outcomes</option>
                  <option value="Success">Success</option>
                  <option value="Failure">Failure</option>
                </select>
              </label>

              <label className="field">
                <span className="field-label">Actor</span>
                <input
                  className="input"
                  type="text"
                  value={draft.actor_username}
                  onChange={(event) => setDraft({ ...draft, actor_username: event.target.value })}
                  placeholder="Username contains"
                />
              </label>
            </div>
          )}

          <div className="date-group">
            <div className="date-group-title">
              <Icon name="calendar" size={14} />
              Event date range
            </div>
            <div className="date-grid">
              <label className="field">
                <span className="field-label">From date</span>
                <input
                  className="input"
                  type="date"
                  value={draft.date_from}
                  onChange={(event) => setDraft({ ...draft, date_from: event.target.value })}
                />
              </label>
              <label className="field">
                <span className="field-label">To date</span>
                <input
                  className="input"
                  type="date"
                  value={draft.date_to}
                  onChange={(event) => setDraft({ ...draft, date_to: event.target.value })}
                />
              </label>
            </div>
          </div>

          <div className="filter-actions">
            <button type="button" className="btn btn-primary btn-compact" onClick={applyFilters}>
              Apply filters
            </button>
            <button type="button" className="btn btn-secondary btn-compact" onClick={resetFilters}>
              Reset
            </button>
            <span className="muted small">
              Date filters are applied separately from the general filters.
            </span>
          </div>

          {activeChips.length > 0 && (
            <div className="chip-row" aria-label="Active filters">
              {activeChips.map((chip) => (
                <span key={chip.key} className="filter-chip">
                  {chip.label}
                  <button
                    type="button"
                    onClick={() => {
                      const next = { ...applied, [chip.key]: '' }
                      setApplied(next)
                      setDraft((current) => ({ ...current, [chip.key]: '' }))
                      setPage(1)
                    }}
                    aria-label={`Remove filter ${chip.label}`}
                  >
                    <Icon name="close" size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {loading ? (
          <Loading label="Loading audit trail…" />
        ) : data.items.length === 0 ? (
          <EmptyState
            title="No audit records match the current filters"
            description="Adjust the search, module, actor or date range."
          />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Module</th>
                    <th>Category</th>
                    <th>Outcome</th>
                    <th>Entity</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((entry) => (
                    <tr key={entry.id}>
                      <td className="nowrap tnum">{formatDateTime(entry.created_at)}</td>
                      <td>
                        <div className="cell-primary">{entry.actor_username || 'system'}</div>
                        <div className="cell-sub">{entry.ip_address || 'no IP'}</div>
                      </td>
                      <td>
                        <div className="cell-primary">{entry.action}</div>
                        <div className="cell-sub">
                          {entry.http_method ? `${entry.http_method} ${entry.status_code || ''}` : ''}
                        </div>
                      </td>
                      <td>{entry.module_name}</td>
                      <td>{entry.category}</td>
                      <td>
                        <StatusTag status={entry.outcome} />
                      </td>
                      <td>
                        <div>{entry.entity_label || entry.entity_type || '—'}</div>
                        {entry.entity_id ? (
                          <div className="cell-sub">
                            {entry.entity_type || 'ID'} #{entry.entity_id}
                          </div>
                        ) : null}
                      </td>
                      <td title={entry.details_summary || entry.remarks || ''}>
                        <div>{truncate(entry.details_summary || entry.remarks)}</div>
                        {entry.request_path && (
                          <div className="cell-mono">{entry.request_path}</div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <Pagination
              page={data.page || page}
              pageSize={data.page_size || pageSize}
              pages={data.pages || 0}
              total={data.total || 0}
              onPageChange={(nextPage) => {
                setPage(nextPage)
                logUiAction('Audit Trail', 'Change Page', { page: nextPage })
              }}
              onPageSizeChange={(nextSize) => {
                setPageSize(nextSize)
                setPage(1)
                logUiAction('Audit Trail', 'Change Page Size', { page_size: nextSize })
              }}
              disabled={loading}
            />
          </>
        )}
      </section>
    </div>
  )
}
