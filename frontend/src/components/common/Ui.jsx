import Icon from './Icon'

export const PAGE_SIZE_OPTIONS = [20, 50, 100, 200]

export const formatDateTime = (value) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export const formatDate = (value) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
  })
}

export const PageHead = ({ eyebrow, title, description, actions }) => (
  <div className="page-head">
    <div className="page-head-copy">
      {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
      <h1 className="page-title">{title}</h1>
      {description && <p className="page-subtitle">{description}</p>}
    </div>
    {actions && <div className="page-actions">{actions}</div>}
  </div>
)

export const KpiCard = ({ label, value, context }) => (
  <div className="kpi-card">
    <div className="kpi-label">{label}</div>
    <div className="kpi-value">{value}</div>
    {context && <div className="kpi-context">{context}</div>}
  </div>
)

const TONE_BY_STATUS = {
  active: 'success',
  available: 'success',
  success: 'success',
  foundation: 'info',
  planned: 'neutral',
  inactive: 'neutral',
  pending: 'warning',
  locked: 'danger',
  failure: 'danger',
  failed: 'danger',
  warning: 'warning',
}

export const StatusTag = ({ status, tone }) => {
  const resolved = tone || TONE_BY_STATUS[String(status || '').toLowerCase()] || 'neutral'
  return <span className={`tag ${resolved === 'neutral' ? '' : `tag-${resolved}`}`.trim()}>{status}</span>
}

export const Alert = ({ tone = 'info', children, icon = 'info' }) => (
  <div className={`alert alert-${tone}`} role={tone === 'danger' || tone === 'warning' ? 'alert' : 'status'}>
    <Icon name={icon} size={16} className="alert-icon" />
    <div>{children}</div>
  </div>
)

export const Loading = ({ label = 'Loading data…' }) => (
  <div className="loading" role="status" aria-live="polite">
    <span className="spinner" aria-hidden="true" />
    {label}
  </div>
)

export const EmptyState = ({ title = 'No records found', description, action }) => (
  <div className="empty-state">
    <Icon name="grid" size={22} />
    <strong>{title}</strong>
    {description && <span>{description}</span>}
    {action}
  </div>
)

const pageNumbers = (page, pages) => {
  if (pages <= 7) return Array.from({ length: pages }, (_, index) => index + 1)
  const start = Math.max(2, Math.min(page - 1, pages - 4))
  const numbers = [1]
  if (start > 2) numbers.push('…')
  for (let value = start; value <= Math.min(start + 3, pages - 1); value += 1) {
    numbers.push(value)
  }
  if (start + 3 < pages - 1) numbers.push('…')
  numbers.push(pages)
  return numbers
}

export const Pagination = ({
  page,
  pageSize,
  pages,
  total,
  onPageChange,
  onPageSizeChange,
  disabled = false,
}) => (
  <div className="table-footer">
    <div className="muted small" aria-live="polite">
      {total === 0
        ? 'No records'
        : `Showing ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}`}
    </div>
    <div className="page-size">
      <label htmlFor="page-size-select">Rows per page</label>
      <select
        id="page-size-select"
        className="select"
        value={pageSize}
        onChange={(event) => onPageSizeChange(Number(event.target.value))}
        disabled={disabled}
      >
        {PAGE_SIZE_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </div>
    <div className="pagination" role="navigation" aria-label="Pagination">
      <button
        type="button"
        className="page-btn"
        onClick={() => onPageChange(page - 1)}
        disabled={disabled || page <= 1}
        aria-label="Previous page"
      >
        ‹
      </button>
      {pageNumbers(page, pages).map((number, index) =>
        number === '…' ? (
          <span key={`ellipsis-${index}`} className="page-btn" aria-hidden="true">
            …
          </span>
        ) : (
          <button
            key={number}
            type="button"
            className={`page-btn ${number === page ? 'is-active' : ''}`.trim()}
            onClick={() => onPageChange(number)}
            disabled={disabled}
            aria-current={number === page ? 'page' : undefined}
          >
            {number}
          </button>
        ),
      )}
      <button
        type="button"
        className="page-btn"
        onClick={() => onPageChange(page + 1)}
        disabled={disabled || page >= pages}
        aria-label="Next page"
      >
        ›
      </button>
    </div>
  </div>
)
