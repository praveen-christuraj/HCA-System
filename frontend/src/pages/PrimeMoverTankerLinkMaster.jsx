import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  closePrimeMoverTankerLink,
  createPrimeMoverTankerLink,
  deletePrimeMoverTankerLink,
  downloadPrimeMoverTankerLinksExport,
  getCurrentLinkByPrimeMover,
  getCurrentLinkByTanker,
  getPrimeMoverTankerLinkOptions,
  importPrimeMoverTankerLinksFile,
  listPrimeMoverTankerLinks,
  updatePrimeMoverTankerLink,
} from '../api/primeMoverTankerLinkApi'
import ConfirmDialog from '../components/common/ConfirmDialog'
import Icon from '../components/common/Icon'
import MasterImportDialog from '../components/common/MasterImportDialog'
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

const MODULE = 'Prime Mover-Tanker Link'

const EMPTY_FILTERS = {
  search: '',
  status: '',
  prime_mover_asset_id: '',
  tanker_asset_id: '',
  date_from: '',
  date_to: '',
}

const LINK_TEMPLATE = [
  'prime_mover_code',
  'tanker_code',
  'linked_from',
  'linked_to',
  'status',
  'remarks',
]

const todayIso = () => {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

// Dates are calendar dates (no time), so they are shown exactly as stored.
const showDate = (value) => (value ? String(value) : '—')

const assetLabel = (asset) => {
  if (!asset) return '—'
  const chassis = asset.chassis_number ? ` · Chassis ${asset.chassis_number}` : ''
  return `${asset.asset_code} — ${asset.asset_name}${chassis}`
}

function LinkDialog({ link, options, onClose, onSaved }) {
  const editing = Boolean(link)
  const [form, setForm] = useState({
    prime_mover_asset_id: link ? String(link.prime_mover_asset_id) : '',
    tanker_asset_id: link ? String(link.tanker_asset_id) : '',
    linked_from: link?.linked_from || todayIso(),
    linked_to: link?.linked_to || '',
    status: link?.status || 'Active',
    remarks: link?.remarks || '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [conflicts, setConflicts] = useState({ prime: null, tanker: null })

  // Edits can point at an asset that is no longer Active; keep it selectable so the
  // record stays editable without silently changing the asset.
  const primeOptions = useMemo(() => {
    const rows = [...options.prime_movers]
    if (link && !rows.some((item) => item.id === link.prime_mover_asset_id)) {
      rows.push({
        id: link.prime_mover_asset_id,
        asset_code: link.prime_mover_asset_code,
        asset_name: link.prime_mover_asset_name,
        chassis_number: link.prime_mover_chassis_number,
      })
    }
    return rows
  }, [options.prime_movers, link])

  const tankerOptions = useMemo(() => {
    const rows = [...options.tankers]
    if (link && !rows.some((item) => item.id === link.tanker_asset_id)) {
      rows.push({
        id: link.tanker_asset_id,
        asset_code: link.tanker_asset_code,
        asset_name: link.tanker_asset_name,
        chassis_number: link.tanker_chassis_number,
      })
    }
    return rows
  }, [options.tankers, link])

  // Live hint: a prime mover or tanker that already has another Active link cannot
  // take a second one. The server enforces this; the hint explains it before save.
  useEffect(() => {
    let active = true
    const check = async (assetId, lookup, key) => {
      if (!assetId) {
        setConflicts((current) => ({ ...current, [key]: null }))
        return
      }
      try {
        const response = await lookup(assetId)
        if (!active) return
        const other =
          response.has_active_link && response.link && response.link.id !== link?.id
            ? response.link
            : null
        setConflicts((current) => ({ ...current, [key]: other }))
      } catch {
        if (active) setConflicts((current) => ({ ...current, [key]: null }))
      }
    }
    check(form.prime_mover_asset_id, getCurrentLinkByPrimeMover, 'prime')
    check(form.tanker_asset_id, getCurrentLinkByTanker, 'tanker')
    return () => {
      active = false
    }
  }, [form.prime_mover_asset_id, form.tanker_asset_id, link?.id])

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    const payload = {
      prime_mover_asset_id: Number(form.prime_mover_asset_id),
      tanker_asset_id: Number(form.tanker_asset_id),
      linked_from: form.linked_from,
      linked_to: form.linked_to || null,
      status: form.status,
      remarks: form.remarks.trim() || null,
    }
    try {
      const result = editing
        ? await updatePrimeMoverTankerLink(link.id, payload)
        : await createPrimeMoverTankerLink(payload)
      onSaved(
        result,
        editing ? 'Prime mover-tanker link updated successfully' : 'Prime mover-tanker link created successfully',
      )
    } catch (saveError) {
      setError(saveError.message || 'Unable to save the link')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <form
        className="dialog dialog-lg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="link-dialog-title"
        onSubmit={submit}
      >
        <div className="dialog-head">
          <h2 id="link-dialog-title" className="dialog-title">
            {editing ? 'Edit prime mover-tanker link' : 'Add prime mover-tanker link'}
          </h2>
          <p className="dialog-subtitle">
            A prime mover pulls one tanker trailer at a time. Only one Active link can exist for a
            prime mover and for a tanker.
          </p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          {conflicts.prime && (
            <Alert tone="warning" icon="alertTriangle">
              {`This prime mover is already linked to ${conflicts.prime.tanker_asset_code} from ${showDate(conflicts.prime.linked_from)}. Close that link first, or save this one as Inactive.`}
            </Alert>
          )}
          {conflicts.tanker && (
            <Alert tone="warning" icon="alertTriangle">
              {`This tanker is already linked to ${conflicts.tanker.prime_mover_asset_code} from ${showDate(conflicts.tanker.linked_from)}. Close that link first, or save this one as Inactive.`}
            </Alert>
          )}
          <div className="form-grid-2" style={{ marginTop: error || conflicts.prime || conflicts.tanker ? 14 : 0 }}>
            <label className="field">
              <span className="field-label">Prime mover</span>
              <select
                className="select"
                required
                autoFocus
                value={form.prime_mover_asset_id}
                onChange={(event) => setForm({ ...form, prime_mover_asset_id: event.target.value })}
              >
                <option value="">Select a prime mover</option>
                {primeOptions.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {assetLabel(asset)}
                  </option>
                ))}
              </select>
              <span className="field-help">Prime Mover assets only. Active assets are offered.</span>
            </label>
            <label className="field">
              <span className="field-label">Tanker trailer</span>
              <select
                className="select"
                required
                value={form.tanker_asset_id}
                onChange={(event) => setForm({ ...form, tanker_asset_id: event.target.value })}
              >
                <option value="">Select a tanker trailer</option>
                {tankerOptions.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {assetLabel(asset)}
                  </option>
                ))}
              </select>
              <span className="field-help">Tanker Trailer assets only. Active assets are offered.</span>
            </label>
            <label className="field">
              <span className="field-label">Linked from</span>
              <input
                className="input"
                type="date"
                required
                value={form.linked_from}
                onChange={(event) => setForm({ ...form, linked_from: event.target.value })}
              />
            </label>
            <label className="field">
              <span className="field-label">Linked to</span>
              <input
                className="input"
                type="date"
                value={form.linked_to}
                onChange={(event) => setForm({ ...form, linked_to: event.target.value })}
              />
              <span className="field-help">Leave empty while the link is still in use.</span>
            </label>
            <label className="field">
              <span className="field-label">Status</span>
              <select
                className="select"
                value={form.status}
                onChange={(event) => setForm({ ...form, status: event.target.value })}
              >
                <option value="Active">Active</option>
                <option value="Inactive">Inactive</option>
              </select>
            </label>
            <label className="field" style={{ gridColumn: '1 / -1' }}>
              <span className="field-label">Remarks</span>
              <textarea
                className="textarea"
                maxLength={2000}
                value={form.remarks}
                onChange={(event) => setForm({ ...form, remarks: event.target.value })}
              />
            </label>
          </div>
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Icon name="checkCircle" size={15} />
            {busy ? 'Saving…' : editing ? 'Save changes' : 'Create link'}
          </button>
        </div>
      </form>
    </div>
  )
}

function CloseLinkDialog({ link, onClose, onClosed }) {
  const [linkedTo, setLinkedTo] = useState(todayIso())
  const [remarks, setRemarks] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await closePrimeMoverTankerLink(link.id, {
        linked_to: linkedTo || null,
        remarks: remarks.trim() || null,
      })
      onClosed(result)
    } catch (closeError) {
      setError(closeError.message || 'Unable to close the link')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <form
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="close-link-title"
        onSubmit={submit}
      >
        <div className="dialog-head">
          <h2 id="close-link-title" className="dialog-title">Close link</h2>
          <p className="dialog-subtitle">
            {`${link.prime_mover_asset_code} ↔ ${link.tanker_asset_code}, linked from ${showDate(link.linked_from)}. Closing keeps the record and marks it Inactive.`}
          </p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="form-grid-2" style={{ marginTop: error ? 14 : 0 }}>
            <label className="field">
              <span className="field-label">Linked to</span>
              <input
                className="input"
                type="date"
                required
                min={link.linked_from}
                value={linkedTo}
                onChange={(event) => setLinkedTo(event.target.value)}
              />
              <span className="field-help">Defaults to today. Cannot be before the linked-from date.</span>
            </label>
            <label className="field" style={{ gridColumn: '1 / -1' }}>
              <span className="field-label">Close remarks</span>
              <textarea
                className="textarea"
                maxLength={2000}
                value={remarks}
                onChange={(event) => setRemarks(event.target.value)}
              />
              <span className="field-help">Appended to the link remarks as “Close Remarks”.</span>
            </label>
          </div>
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Icon name="checkCircle" size={15} />
            {busy ? 'Closing…' : 'Close link'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default function PrimeMoverTankerLinkMaster() {
  const { isAdmin, hasPermission } = usePermissions()
  const canCreate = isAdmin || hasPermission('prime_mover_tanker_links:create')
  const canUpdate = isAdmin || hasPermission('prime_mover_tanker_links:update')
  const canDelete = isAdmin || hasPermission('prime_mover_tanker_links:delete')

  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [data, setData] = useState({ items: [], total: 0, pages: 0 })
  const [options, setOptions] = useState({ prime_movers: [], tankers: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [exporting, setExporting] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [dialogLink, setDialogLink] = useState(undefined)
  const [closingLink, setClosingLink] = useState(null)
  const [deletingLink, setDeletingLink] = useState(null)
  const [deleteBusy, setDeleteBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await listPrimeMoverTankerLinks({ ...applied, page, page_size: pageSize }))
    } catch (loadError) {
      setError(loadError.message || 'Unable to load prime mover-tanker links')
      setData({ items: [], total: 0, pages: 0 })
    } finally {
      setLoading(false)
    }
  }, [applied, page, pageSize])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    let active = true
    getPrimeMoverTankerLinkOptions()
      .then((response) => {
        if (active) setOptions(response)
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])

  const chips = useMemo(
    () => [
      ...(applied.search ? [{ key: 'search', label: `Search: ${applied.search}` }] : []),
      ...(applied.status ? [{ key: 'status', label: `Status: ${applied.status}` }] : []),
      ...(applied.prime_mover_asset_id
        ? [
            {
              key: 'prime_mover_asset_id',
              label: `Prime mover: ${
                options.prime_movers.find((item) => String(item.id) === String(applied.prime_mover_asset_id))
                  ?.asset_code || applied.prime_mover_asset_id
              }`,
            },
          ]
        : []),
      ...(applied.tanker_asset_id
        ? [
            {
              key: 'tanker_asset_id',
              label: `Tanker: ${
                options.tankers.find((item) => String(item.id) === String(applied.tanker_asset_id))
                  ?.asset_code || applied.tanker_asset_id
              }`,
            },
          ]
        : []),
      ...(applied.date_from ? [{ key: 'date_from', label: `Linked from: ${applied.date_from}` }] : []),
      ...(applied.date_to ? [{ key: 'date_to', label: `Linked to: ${applied.date_to}` }] : []),
    ],
    [applied, options],
  )

  const applyFilters = () => {
    setApplied({ ...draft })
    setPage(1)
    logUiAction(MODULE, 'Apply Filter')
  }
  const resetFilters = () => {
    setDraft(EMPTY_FILTERS)
    setApplied(EMPTY_FILTERS)
    setPage(1)
    logUiAction(MODULE, 'Reset Filter')
  }
  const removeChip = (key) => {
    const next = { ...applied, [key]: '' }
    setApplied(next)
    setDraft(next)
    setPage(1)
  }

  const exportRows = async (format) => {
    setExporting(format)
    setError('')
    try {
      await downloadPrimeMoverTankerLinksExport(format, applied)
      logUiAction(MODULE, 'Export', { format })
    } catch (exportError) {
      setError(exportError.message || 'Export failed')
    } finally {
      setExporting('')
    }
  }

  const refreshOptions = () =>
    getPrimeMoverTankerLinkOptions()
      .then(setOptions)
      .catch(() => undefined)

  const confirmDelete = async () => {
    if (!deletingLink) return
    setDeleteBusy(true)
    setError('')
    try {
      await deletePrimeMoverTankerLink(deletingLink.id)
      setNotice(`The link between ${deletingLink.prime_mover_asset_code} and ${deletingLink.tanker_asset_code} has been deleted.`)
      setDeletingLink(null)
      load()
    } catch (deleteError) {
      setError(deleteError.message || 'Unable to delete the link')
      setDeletingLink(null)
    } finally {
      setDeleteBusy(false)
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="MASTER DATA / PRIME MOVER-TANKER LINK"
        title="Prime Mover-Tanker Link"
        description="Record which tanker trailer each prime mover pulls, and from which date. One Active link is allowed per prime mover and per tanker, and the Operation Entry tanker truck flow reads these links."
        actions={
          <>
            {canCreate && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  setDialogLink(null)
                  setNotice('')
                }}
              >
                <Icon name="database" size={15} /> Add link
              </button>
            )}
            <button type="button" className="btn btn-secondary" onClick={load} disabled={loading}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </>
        }
      />
      {error && <Alert tone="danger">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}

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
                  placeholder="Search prime mover, tanker, chassis or remarks"
                  aria-label="Search links"
                />
              </div>
              <button type="submit" className="btn btn-primary">
                Search
              </button>
            </form>
            <button
              type="button"
              className={`btn btn-secondary ${showAdvanced ? 'is-active' : ''}`}
              onClick={() => setShowAdvanced((value) => !value)}
              aria-expanded={showAdvanced}
            >
              <Icon name="filter" size={15} /> Advanced filters
            </button>
          </div>
          <div className="toolbar-spacer" />
          {canCreate && (
            <button type="button" className="btn btn-secondary" onClick={() => setShowImport(true)}>
              <Icon name="upload" size={15} /> Import
            </button>
          )}
          <div className="toolbar-group" role="group" aria-label="Export links">
            <span className="muted small">Export</span>
            {['csv', 'xlsx', 'pdf'].map((format) => (
              <button
                key={format}
                type="button"
                className="btn btn-secondary btn-compact"
                onClick={() => exportRows(format)}
                disabled={Boolean(exporting)}
              >
                <Icon name="download" size={14} />
                {exporting === format ? 'Exporting…' : format.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div className="filters-panel">
          {showAdvanced && (
            <div className="filters-grid">
              <label className="field">
                <span className="field-label">Status</span>
                <select
                  className="select"
                  value={draft.status}
                  onChange={(event) => setDraft({ ...draft, status: event.target.value })}
                >
                  <option value="">All statuses</option>
                  <option value="Active">Active</option>
                  <option value="Inactive">Inactive</option>
                </select>
              </label>
              <label className="field">
                <span className="field-label">Prime mover</span>
                <select
                  className="select"
                  value={draft.prime_mover_asset_id}
                  onChange={(event) => setDraft({ ...draft, prime_mover_asset_id: event.target.value })}
                >
                  <option value="">All prime movers</option>
                  {options.prime_movers.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {asset.asset_code} — {asset.asset_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field-label">Tanker trailer</span>
                <select
                  className="select"
                  value={draft.tanker_asset_id}
                  onChange={(event) => setDraft({ ...draft, tanker_asset_id: event.target.value })}
                >
                  <option value="">All tankers</option>
                  {options.tankers.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {asset.asset_code} — {asset.asset_name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          <div className="date-group">
            <div className="date-group-title">
              <Icon name="calendar" size={14} /> Linked-from date range
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
            <span className="muted small">Date filters apply independently from general filters.</span>
          </div>
          {chips.length > 0 && (
            <div className="chip-row" aria-label="Active filters">
              {chips.map((chip) => (
                <span key={chip.key} className="filter-chip">
                  {chip.label}
                  <button type="button" onClick={() => removeChip(chip.key)} aria-label={`Remove ${chip.label}`}>
                    <Icon name="close" size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {loading ? (
          <Loading label="Loading links…" />
        ) : data.items.length === 0 ? (
          <EmptyState
            title="No links match the current filters"
            description="Adjust your search or filters, or add a link."
          />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Prime mover</th>
                    <th>Tanker trailer</th>
                    <th>Linked from</th>
                    <th>Linked to</th>
                    <th>Status</th>
                    <th>Remarks</th>
                    <th>Updated</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((link) => (
                    <tr key={link.id}>
                      <td>
                        <div className="cell-primary">{link.prime_mover_asset_name || '—'}</div>
                        <div className="cell-sub cell-mono">{link.prime_mover_asset_code}</div>
                        {link.prime_mover_chassis_number && (
                          <div className="cell-sub">Chassis {link.prime_mover_chassis_number}</div>
                        )}
                      </td>
                      <td>
                        <div className="cell-primary">{link.tanker_asset_name || '—'}</div>
                        <div className="cell-sub cell-mono">{link.tanker_asset_code}</div>
                        {link.tanker_chassis_number && (
                          <div className="cell-sub">Chassis {link.tanker_chassis_number}</div>
                        )}
                      </td>
                      <td className="nowrap">{showDate(link.linked_from)}</td>
                      <td className="nowrap">{showDate(link.linked_to)}</td>
                      <td>
                        <StatusTag status={link.status} />
                      </td>
                      <td style={{ whiteSpace: 'normal' }}>{link.remarks || <span className="muted">—</span>}</td>
                      <td className="nowrap">
                        <div>{formatDateTime(link.updated_at)}</div>
                        {link.updated_by_name && <div className="cell-sub">{link.updated_by_name}</div>}
                      </td>
                      <td>
                        <div className="table-actions">
                          {canUpdate && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-compact"
                              onClick={() => {
                                setDialogLink(link)
                                setNotice('')
                              }}
                            >
                              <Icon name="settings" size={14} /> Edit
                            </button>
                          )}
                          {canUpdate && link.status === 'Active' && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-compact"
                              onClick={() => setClosingLink(link)}
                            >
                              <Icon name="checkCircle" size={14} /> Close
                            </button>
                          )}
                          {canDelete && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-compact"
                              onClick={() => setDeletingLink(link)}
                            >
                              <Icon name="close" size={14} /> Delete
                            </button>
                          )}
                        </div>
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
              onPageChange={(next) => {
                setPage(next)
                logUiAction(MODULE, 'Change Page', { page: next })
              }}
              onPageSizeChange={(next) => {
                setPageSize(next)
                setPage(1)
                logUiAction(MODULE, 'Change Page Size', { page_size: next })
              }}
              disabled={loading}
            />
          </>
        )}
      </section>

      {dialogLink !== undefined && (
        <LinkDialog
          link={dialogLink}
          options={options}
          onClose={() => setDialogLink(undefined)}
          onSaved={(result, message) => {
            setDialogLink(undefined)
            setNotice(message)
            refreshOptions()
            load()
          }}
        />
      )}
      {closingLink && (
        <CloseLinkDialog
          link={closingLink}
          onClose={() => setClosingLink(null)}
          onClosed={() => {
            setNotice(`The link between ${closingLink.prime_mover_asset_code} and ${closingLink.tanker_asset_code} has been closed.`)
            setClosingLink(null)
            load()
          }}
        />
      )}
      {deletingLink && (
        <ConfirmDialog
          titleId="link-delete-title"
          title="Delete this link?"
          message={`This permanently removes the link between ${deletingLink.prime_mover_asset_code} and ${deletingLink.tanker_asset_code} from ${showDate(deletingLink.linked_from)}. Use Close instead to keep the history.`}
          confirmLabel="Delete permanently"
          busy={deleteBusy}
          onCancel={() => setDeletingLink(null)}
          onConfirm={confirmDelete}
        />
      )}
      {showImport && (
        <MasterImportDialog
          title="prime mover-tanker links"
          templateHeaders={LINK_TEMPLATE}
          templateFilename="prime-mover-tanker-link-import-template.csv"
          importFile={importPrimeMoverTankerLinksFile}
          onClose={() => setShowImport(false)}
          onImported={(result) => {
            setShowImport(false)
            setNotice(result.message || 'Prime mover-tanker links imported successfully')
            setPage(1)
            refreshOptions()
            load()
          }}
        />
      )}
    </div>
  )
}
