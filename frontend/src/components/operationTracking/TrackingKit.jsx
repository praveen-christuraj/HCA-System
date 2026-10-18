import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../common/Icon'
import { Alert } from '../common/Ui'
import { EntryDialog } from '../operationLayouts/EntryFeedback'
import EntryLookup, { optionLabel } from '../operationLayouts/EntryLookup'
import { logUiAction } from '../../utils/actionLogger'

/**
 * Shared building blocks for the Operation Tracking pages. They reuse the
 * platform register pattern (quick search + advanced filters + a separate
 * date-range group + active chips + server pagination + CSV/XLSX/PDF export).
 */

export const OPERATION_TYPES = [
  { code: 'TANK_OPERATIONS', name: 'Tank Operations' },
  { code: 'BARGE_OPERATIONS', name: 'Barge Operations' },
  { code: 'SHUTTLE_OPERATIONS', name: 'Shuttle Operations' },
  { code: 'FSO_OPERATIONS', name: 'FSO Operations' },
  { code: 'TANKER_OPERATIONS', name: 'Tanker Operations' },
  { code: 'FLOWMETER_OPERATIONS', name: 'Flowmeter Operations' },
]

export const fmt = (value, digits = 3) => {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (Number.isNaN(number)) return String(value)
  return number.toLocaleString(undefined, { maximumFractionDigits: digits })
}

export const humanCode = (value) =>
  String(value || '—')
    .replaceAll('_', ' ')
    .toLowerCase()
    .replace(/(^|\s)\S/g, (letter) => letter.toUpperCase())

const TRACKING_TONES = {
  OPEN: 'info',
  CLOSED: 'neutral',
  PENDING_RECEIPT: 'warning',
  ACKNOWLEDGED: 'info',
  SEAL_MISMATCH: 'danger',
  QUANTITY_VARIANCE: 'warning',
  MATCHED: 'success',
  RECEIVED: 'success',
  NO_SENDER: 'danger',
  MATCH: 'success',
  MISMATCH: 'danger',
  MISSING_SENDER: 'warning',
  MISSING_RECEIVER: 'warning',
  MISSING_BOTH: 'neutral',
  SENDER_MISSING: 'warning',
  RECEIVER_MISSING: 'warning',
  NOT_ENTERED: 'neutral',
}

export function TrackingTag({ value, label }) {
  const tone = TRACKING_TONES[value] || 'neutral'
  return <span className={`tag ${tone === 'neutral' ? '' : `tag-${tone}`}`.trim()}>{label || humanCode(value)}</span>
}

/** Converts filter state ({ location: {id,..}, asset: {...}, ... }) into API params. */
export const filterParams = (filters) =>
  Object.fromEntries(
    Object.entries(filters).map(([key, value]) =>
      value && typeof value === 'object' ? [`${key}_id`, value.id] : [key, value],
    ),
  )

/**
 * Register state: draft vs applied filters, page, page size and a loader.
 * `fetcher(params, page, pageSize)` must be memoised by the caller.
 */
export function useRegister(initial, fetcher, module) {
  const initialRef = useRef(initial)
  const [draft, setDraft] = useState(initial)
  const [applied, setApplied] = useState(initial)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSizeState] = useState(20)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    fetcher(filterParams(applied), page, pageSize)
      .then((result) => {
        if (active) setData(result)
      })
      .catch((loadError) => {
        if (active) setError(loadError.message || 'Unable to load records')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [fetcher, applied, page, pageSize, tick])

  const apply = useCallback(() => {
    setApplied(draft)
    setPage(1)
    logUiAction(module, 'Apply Filter', filterParams(draft))
  }, [draft, module])
  const reset = useCallback(() => {
    setDraft(initialRef.current)
    setApplied(initialRef.current)
    setPage(1)
    logUiAction(module, 'Reset Filters')
  }, [module])
  const removeFilter = useCallback((key) => {
    const blank = initialRef.current[key] ?? ''
    setDraft((current) => ({ ...current, [key]: blank }))
    setApplied((current) => ({ ...current, [key]: blank }))
    setPage(1)
  }, [])
  const setPageSize = useCallback((size) => {
    setPageSizeState(size)
    setPage(1)
  }, [])
  const refresh = useCallback(() => setTick((value) => value + 1), [])

  return { draft, setDraft, applied, apply, reset, removeFilter, page, setPage, pageSize, setPageSize, data, loading, error, refresh }
}

export function TabStrip({ label, tabs, value, onChange }) {
  return (
    <div className="tracking-tabs" role="tablist" aria-label={label}>
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={value === tab.key}
          className={`tracking-tab${value === tab.key ? ' is-active' : ''}`}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
          {tab.count !== undefined && tab.count !== null && <span className="tracking-tab-count">{tab.count}</span>}
        </button>
      ))}
    </div>
  )
}

export function ExportGroup({ label = 'Export', onExport, formats = ['csv', 'xlsx', 'pdf'] }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const run = async (format) => {
    setBusy(format)
    setError('')
    try {
      await onExport(format)
    } catch (exportError) {
      setError(exportError.message || 'Export failed')
    } finally {
      setBusy('')
    }
  }
  return (
    <div className="toolbar-group" role="group" aria-label={label}>
      <span className="muted small">{label}</span>
      {formats.map((format) => (
        <button key={format} type="button" className="btn btn-secondary btn-compact" onClick={() => run(format)} disabled={Boolean(busy)}>
          <Icon name="download" size={14} />
          {busy === format ? 'Exporting…' : format.toUpperCase()}
        </button>
      ))}
      {error && <span className="field-error" role="alert">{error}</span>}
    </div>
  )
}

/**
 * Quick search + advanced filters + separate date range group + chips.
 * `chipLabels` maps filter keys to readable labels for the active chips.
 */
export function RegisterFilters({
  register,
  searchPlaceholder,
  searchLabel,
  advanced,
  dateTitle = 'Operation date range',
  chipLabels = {},
  exportSlot,
  hideDates = false,
}) {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const { draft, setDraft, applied, apply, reset, removeFilter } = register
  const chips = Object.entries(applied)
    .filter(([key, value]) => chipLabels[key] && value)
    .map(([key, value]) => ({ key, label: `${chipLabels[key]}: ${typeof value === 'object' ? optionLabel(value) : value}` }))
  return (
    <>
      <div className="toolbar">
        <div className="toolbar-group">
          <form
            className="toolbar-group"
            onSubmit={(event) => {
              event.preventDefault()
              apply()
            }}
          >
            <div className="search-field">
              <Icon name="search" size={15} className="search-icon" />
              <input
                className="input"
                type="search"
                value={draft.search || ''}
                onChange={(event) => setDraft({ ...draft, search: event.target.value })}
                placeholder={searchPlaceholder}
                aria-label={searchLabel || searchPlaceholder}
                maxLength={150}
              />
            </div>
            <button type="submit" className="btn btn-primary">Search</button>
          </form>
          {advanced && (
            <button type="button" className="btn btn-secondary" onClick={() => setShowAdvanced((value) => !value)} aria-expanded={showAdvanced}>
              <Icon name="filter" size={15} />
              Advanced filters
            </button>
          )}
        </div>
        <div className="toolbar-spacer" />
        {exportSlot}
      </div>
      <div className="filters-panel">
        {showAdvanced && advanced && <div className="filters-grid">{advanced}</div>}
        {!hideDates && (
          <div className="date-group">
            <div className="date-group-title">
              <Icon name="calendar" size={14} />
              {dateTitle}
            </div>
            <div className="date-grid">
              <label className="field">
                <span className="field-label">From date</span>
                <input className="input" type="date" value={draft.date_from || ''} onChange={(event) => setDraft({ ...draft, date_from: event.target.value })} />
              </label>
              <label className="field">
                <span className="field-label">To date</span>
                <input className="input" type="date" value={draft.date_to || ''} onChange={(event) => setDraft({ ...draft, date_to: event.target.value })} />
              </label>
            </div>
          </div>
        )}
        <div className="filter-actions">
          <button type="button" className="btn btn-primary btn-compact" onClick={apply}>Apply filters</button>
          <button type="button" className="btn btn-secondary btn-compact" onClick={reset}>Reset</button>
          {!hideDates && <span className="muted small">Date filters are applied separately from the general filters.</span>}
        </div>
        {chips.length > 0 && (
          <div className="chip-row" aria-label="Active filters">
            {chips.map((chip) => (
              <span key={chip.key} className="filter-chip">
                {chip.label}
                <button type="button" onClick={() => removeFilter(chip.key)} aria-label={`Remove filter ${chip.label}`}>
                  <Icon name="close" size={12} />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </>
  )
}

/** Server-searchable location / asset filter (reuses the bounded entry lookup). */
export function LookupFilter({ kind, label, value, onChange, params }) {
  return (
    <div className="field tracking-lookup-field">
      <EntryLookup kind={kind} label={label} selected={value} onPick={(row) => onChange(row || null)} params={params} />
      {value && (
        <button type="button" className="btn btn-ghost btn-compact" onClick={() => onChange(null)}>
          Clear {label.toLowerCase()}
        </button>
      )}
    </div>
  )
}

/**
 * Confirmation dialog with remarks. Closes only via Cancel or a successful
 * confirm. `onConfirm(remarks)` may throw; the message is shown inline.
 */
export function RemarksDialog({ title, message, confirmLabel = 'Confirm', tone = 'primary', minLength = 3, optional = false, children, onCancel, onConfirm }) {
  const [remarks, setRemarks] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const trimmed = remarks.trim()
  const valid = optional ? !trimmed || trimmed.length >= minLength : trimmed.length >= minLength
  const run = async () => {
    setBusy(true)
    setError('')
    try {
      await onConfirm(trimmed || null)
    } catch (actionError) {
      setError(actionError.message || 'The action failed')
      setBusy(false)
    }
  }
  return (
    <EntryDialog
      title={title}
      footer={
        <>
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className={`btn ${tone === 'danger' ? 'btn-danger' : 'btn-primary'}`} onClick={run} disabled={busy || !valid}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </>
      }
    >
      {message && <p>{message}</p>}
      {children}
      <label className="field">
        <span className="field-label">Remarks {optional ? '(optional)' : `(required, at least ${minLength} characters)`}</span>
        <textarea className="textarea" rows={3} maxLength={2000} value={remarks} onChange={(event) => setRemarks(event.target.value)} />
      </label>
      {error && <Alert tone="danger">{error}</Alert>}
    </EntryDialog>
  )
}

/** Small label/value grid used by tracking detail headers. */
export function FactGrid({ items }) {
  return (
    <dl className="tracking-facts">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value === null || value === undefined || value === '' ? '—' : value}</dd>
        </div>
      ))}
    </dl>
  )
}
