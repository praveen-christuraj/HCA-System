import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  createOperation,
  deactivateOperation,
  downloadOperationsExport,
  importOperationsFile,
  listOperations,
  updateOperation,
} from '../api/operationsApi'
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

const MODULE = 'Operation Master'

const EMPTY_FILTERS = {
  search: '',
  status: '',
  operation_type_code: '',
  operation_category: '',
  location_id: '',
  date_from: '',
  date_to: '',
}

const OPERATION_TEMPLATE = [
  'location_code',
  'operation_type',
  'operation_category',
  'operation_code',
  'operation_label',
  'sort_order',
  'description',
  'status',
]

const SIGN_TONE = { SET: 'info', IN: 'success', OUT: 'warning', NEUTRAL: 'neutral' }

function SignTag({ sign }) {
  return <StatusTag status={sign} tone={SIGN_TONE[sign] || 'neutral'} />
}

function OperationDialog({ operation, operationTypes, categories, locations, onClose, onSaved }) {
  const editing = Boolean(operation)
  const [form, setForm] = useState({
    location_id: operation ? String(operation.location_id) : '',
    operation_type_code: operation?.operation_type_code || operationTypes[0]?.code || '',
    operation_category: operation?.operation_category || categories[0]?.code || '',
    operation_code: operation?.operation_code || '',
    operation_label: operation?.operation_label || '',
    sort_order: operation ? String(operation.sort_order) : '0',
    description: operation?.description || '',
    status: operation?.status || 'Active',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const selectedType = operationTypes.find((item) => item.code === form.operation_type_code)
  const selectedCategory = categories.find((item) => item.code === form.operation_category)
  // Only Active locations are offered, plus the record's current location when editing.
  const locationOptions = locations.filter(
    (location) => location.status === 'Active' || location.id === operation?.location_id,
  )

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    const payload = {
      location_id: Number(form.location_id),
      operation_type_code: form.operation_type_code,
      operation_category: form.operation_category,
      operation_code: form.operation_code.trim(),
      operation_label: form.operation_label.trim(),
      sort_order: Number(form.sort_order) || 0,
      description: form.description.trim() || null,
      status: form.status,
    }
    try {
      const result = editing
        ? await updateOperation(operation.id, payload)
        : await createOperation(payload)
      onSaved(result, editing ? 'Operation updated successfully' : 'Operation created successfully')
    } catch (saveError) {
      setError(saveError.message || 'Unable to save the operation')
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
        aria-labelledby="operation-dialog-title"
        onSubmit={submit}
      >
        <div className="dialog-head">
          <h2 id="operation-dialog-title" className="dialog-title">
            {editing ? 'Edit operation' : 'Add operation'}
          </h2>
          <p className="dialog-subtitle">
            Operations belong to one location and one fixed operation type. The stock sign is set
            by the category.
          </p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="form-grid-2" style={{ marginTop: error ? 14 : 0 }}>
            <label className="field">
              <span className="field-label">Location</span>
              <select
                className="select"
                required
                autoFocus
                value={form.location_id}
                onChange={(event) => setForm({ ...form, location_id: event.target.value })}
              >
                <option value="">Select a location</option>
                {locationOptions.map((location) => (
                  <option key={location.id} value={location.id}>
                    {location.location_name} ({location.location_code})
                    {location.status === 'Inactive' ? ' — inactive' : ''}
                  </option>
                ))}
              </select>
              <span className="field-help">An Active operation needs an Active location.</span>
            </label>
            <label className="field">
              <span className="field-label">Operation type</span>
              <select
                className="select"
                value={form.operation_type_code}
                onChange={(event) => setForm({ ...form, operation_type_code: event.target.value })}
              >
                {operationTypes.map((type) => (
                  <option key={type.code} value={type.code}>
                    {type.name}
                  </option>
                ))}
              </select>
              {selectedType && (
                <span className="field-help">Recorded against: {selectedType.asset_type_name}</span>
              )}
            </label>
            <label className="field">
              <span className="field-label">Category</span>
              <select
                className="select"
                value={form.operation_category}
                onChange={(event) => setForm({ ...form, operation_category: event.target.value })}
              >
                {categories.map((category) => (
                  <option key={category.code} value={category.code}>
                    {category.label}
                  </option>
                ))}
              </select>
              {selectedCategory && (
                <span className="field-help">{selectedCategory.description}</span>
              )}
            </label>
            <div className="field">
              <span className="field-label">Stock sign</span>
              <div>
                {selectedCategory ? <SignTag sign={selectedCategory.sign} /> : <span className="muted">—</span>}
              </div>
              <span className="field-help">Set by the category; it cannot be chosen separately.</span>
            </div>
            <label className="field">
              <span className="field-label">Operation code</span>
              <input
                className="input"
                required
                maxLength={40}
                pattern="[A-Za-z0-9._\-]+"
                value={form.operation_code}
                onChange={(event) => setForm({ ...form, operation_code: event.target.value })}
              />
              <span className="field-help">Unique per location and type, ignoring case. Letters, numbers, periods, underscores, hyphens.</span>
            </label>
            <label className="field">
              <span className="field-label">Operation name</span>
              <input
                className="input"
                required
                minLength={2}
                maxLength={150}
                value={form.operation_label}
                onChange={(event) => setForm({ ...form, operation_label: event.target.value })}
              />
              <span className="field-help">Unique per location and type, ignoring case and extra spaces.</span>
            </label>
            <label className="field">
              <span className="field-label">Sort order</span>
              <input
                className="input"
                type="number"
                min={0}
                max={100000}
                value={form.sort_order}
                onChange={(event) => setForm({ ...form, sort_order: event.target.value })}
              />
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
              <span className="field-label">Description</span>
              <textarea
                className="textarea"
                maxLength={2000}
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
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
            {busy ? 'Saving…' : editing ? 'Save changes' : 'Create operation'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default function OperationMaster() {
  const { isAdmin, hasPermission } = usePermissions()
  const canCreate = isAdmin || hasPermission('operations:create')
  const canUpdate = isAdmin || hasPermission('operations:update')
  const canDelete = isAdmin || hasPermission('operations:delete')

  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [data, setData] = useState({
    items: [],
    total: 0,
    pages: 0,
    operation_types: [],
    operation_categories: [],
    locations: [],
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [exporting, setExporting] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [dialogOperation, setDialogOperation] = useState(undefined)
  const [deactivating, setDeactivating] = useState(null)
  const [deactivateBusy, setDeactivateBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await listOperations({ ...applied, page, page_size: pageSize }))
    } catch (loadError) {
      setError(loadError.message || 'Unable to load operations')
      setData((current) => ({ ...current, items: [], total: 0, pages: 0 }))
    } finally {
      setLoading(false)
    }
  }, [applied, page, pageSize])

  useEffect(() => {
    load()
  }, [load])

  const operationTypes = data.operation_types || []
  const categories = data.operation_categories || []
  const locations = data.locations || []

  const chips = useMemo(
    () => [
      ...(applied.search ? [{ key: 'search', label: `Search: ${applied.search}` }] : []),
      ...(applied.status ? [{ key: 'status', label: `Status: ${applied.status}` }] : []),
      ...(applied.operation_type_code
        ? [
            {
              key: 'operation_type_code',
              label: `Type: ${
                operationTypes.find((item) => item.code === applied.operation_type_code)?.name ||
                applied.operation_type_code
              }`,
            },
          ]
        : []),
      ...(applied.operation_category
        ? [
            {
              key: 'operation_category',
              label: `Category: ${
                categories.find((item) => item.code === applied.operation_category)?.label ||
                applied.operation_category
              }`,
            },
          ]
        : []),
      ...(applied.location_id
        ? [
            {
              key: 'location_id',
              label: `Location: ${
                locations.find((item) => String(item.id) === String(applied.location_id))
                  ?.location_name || applied.location_id
              }`,
            },
          ]
        : []),
      ...(applied.date_from ? [{ key: 'date_from', label: `Created from: ${applied.date_from}` }] : []),
      ...(applied.date_to ? [{ key: 'date_to', label: `Created to: ${applied.date_to}` }] : []),
    ],
    [applied, operationTypes, categories, locations],
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
      await downloadOperationsExport(format, applied)
      logUiAction(MODULE, 'Export', { format })
    } catch (exportError) {
      setError(exportError.message || 'Export failed')
    } finally {
      setExporting('')
    }
  }

  const confirmDeactivate = async () => {
    if (!deactivating) return
    setDeactivateBusy(true)
    setError('')
    try {
      await deactivateOperation(deactivating.id)
      setNotice(`${deactivating.operation_label} has been deactivated.`)
      setDeactivating(null)
      load()
    } catch (deactivateError) {
      setError(deactivateError.message || 'Unable to deactivate the operation')
      setDeactivating(null)
    } finally {
      setDeactivateBusy(false)
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="CONFIGURATIONS / OPERATION MASTER"
        title="Operation Master"
        description="Define the operations each location performs, under the fixed operation types and categories. Active operations populate the Operation Entry dropdowns."
        actions={
          <>
            {canCreate && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  setDialogOperation(null)
                  setNotice('')
                }}
              >
                <Icon name="database" size={15} /> Add operation
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
                  placeholder="Search code, name, description or location"
                  aria-label="Search operations"
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
          <div className="toolbar-group" role="group" aria-label="Export operations">
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
                <span className="field-label">Operation type</span>
                <select
                  className="select"
                  value={draft.operation_type_code}
                  onChange={(event) => setDraft({ ...draft, operation_type_code: event.target.value })}
                >
                  <option value="">All operation types</option>
                  {operationTypes.map((type) => (
                    <option key={type.code} value={type.code}>
                      {type.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field-label">Category</span>
                <select
                  className="select"
                  value={draft.operation_category}
                  onChange={(event) => setDraft({ ...draft, operation_category: event.target.value })}
                >
                  <option value="">All categories</option>
                  {categories.map((category) => (
                    <option key={category.code} value={category.code}>
                      {category.label} ({category.sign})
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field-label">Location</span>
                <select
                  className="select"
                  value={draft.location_id}
                  onChange={(event) => setDraft({ ...draft, location_id: event.target.value })}
                >
                  <option value="">All locations</option>
                  {locations.map((location) => (
                    <option key={location.id} value={location.id}>
                      {location.location_name} ({location.location_code})
                    </option>
                  ))}
                </select>
              </label>
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
            </div>
          )}
          <div className="date-group">
            <div className="date-group-title">
              <Icon name="calendar" size={14} /> Created date range
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
          <Loading label="Loading operations…" />
        ) : data.items.length === 0 ? (
          <EmptyState
            title="No operations match the current filters"
            description="Adjust your search or filters, or add an operation."
          />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Location</th>
                    <th>Operation type</th>
                    <th>Category</th>
                    <th>Sign</th>
                    <th>Operation</th>
                    <th>Sort</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((operation) => (
                    <tr key={operation.id}>
                      <td>
                        <div>{operation.location_name || '—'}</div>
                        <div className="cell-sub cell-mono">{operation.location_code}</div>
                      </td>
                      <td>
                        <div>{operation.operation_type_name}</div>
                        <div className="cell-sub">{operation.asset_type_name}</div>
                      </td>
                      <td>{operation.operation_category_label}</td>
                      <td>
                        <SignTag sign={operation.operation_sign} />
                      </td>
                      <td>
                        <div className="cell-primary">{operation.operation_label}</div>
                        <div className="cell-sub cell-mono">{operation.operation_code}</div>
                      </td>
                      <td>{operation.sort_order}</td>
                      <td>
                        <StatusTag status={operation.status} />
                      </td>
                      <td className="nowrap">{formatDateTime(operation.created_at)}</td>
                      <td>
                        <div className="table-actions">
                          {canUpdate && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-compact"
                              onClick={() => {
                                setDialogOperation(operation)
                                setNotice('')
                              }}
                            >
                              <Icon name="settings" size={14} /> Edit
                            </button>
                          )}
                          {canDelete && operation.status === 'Active' && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-compact"
                              onClick={() => setDeactivating(operation)}
                            >
                              <Icon name="close" size={14} /> Deactivate
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

      {dialogOperation !== undefined && (
        <OperationDialog
          operation={dialogOperation}
          operationTypes={operationTypes}
          categories={categories}
          locations={locations}
          onClose={() => setDialogOperation(undefined)}
          onSaved={(result, message) => {
            setDialogOperation(undefined)
            setNotice(message)
            load()
          }}
        />
      )}
      {deactivating && (
        <ConfirmDialog
          titleId="operation-deactivate-title"
          title={`Deactivate “${deactivating.operation_label}”?`}
          message="The operation is kept for history and stops appearing in Operation Entry dropdowns. Its code and name stay reserved, so a new operation cannot reuse them at this location and type."
          confirmLabel="Deactivate"
          busy={deactivateBusy}
          onCancel={() => setDeactivating(null)}
          onConfirm={confirmDeactivate}
        />
      )}
      {showImport && (
        <MasterImportDialog
          title="operations"
          templateHeaders={OPERATION_TEMPLATE}
          templateFilename="operation-import-template.csv"
          importFile={importOperationsFile}
          onClose={() => setShowImport(false)}
          onImported={(result) => {
            setShowImport(false)
            setNotice(result.message || 'Operations imported successfully')
            setPage(1)
            load()
          }}
        />
      )}
    </div>
  )
}
