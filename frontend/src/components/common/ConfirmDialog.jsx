import Icon from './Icon'

/**
 * Confirmation pop-up for destructive or irreversible actions. It closes only
 * through Cancel or a successful confirmation (the caller clears its state
 * after the action succeeds). It replaces window.confirm, which is not themed.
 */
export default function ConfirmDialog({
  title,
  message,
  confirmLabel,
  busy = false,
  onCancel,
  onConfirm,
  titleId = 'confirm-dialog-title',
  tone = 'danger',
}) {
  return (
    <div className="dialog-backdrop">
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="dialog-head">
          <h2 id={titleId} className="dialog-title">{title}</h2>
          <p className="dialog-subtitle">{message}</p>
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
          <button
            type="button"
            className={`btn ${tone === 'primary' ? 'btn-primary' : 'btn-danger'}`}
            onClick={onConfirm}
            disabled={busy}
          >
            <Icon name={tone === 'primary' ? 'checkCircle' : 'close'} size={15} /> {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
