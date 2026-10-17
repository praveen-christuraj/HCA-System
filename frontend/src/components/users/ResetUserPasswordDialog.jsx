import { useState } from 'react'
import { resetUserPassword } from '../../api/usersApi'
import Icon from '../common/Icon'
import { Alert } from '../common/Ui'

export default function ResetUserPasswordDialog({ user, onClose, onSaved }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [forceChange, setForceChange] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    if (password !== confirm) {
      setError('The passwords do not match.')
      return
    }
    setError('')
    setBusy(true)
    try {
      await resetUserPassword(user.id, { new_password: password, force_password_change: forceChange })
      onSaved(`Password reset for ${user.username}.`)
    } catch (resetError) {
      setError(resetError.message || 'Unable to reset the password')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="reset-password-title" onSubmit={submit}>
        <div className="dialog-head">
          <h2 id="reset-password-title" className="dialog-title">Reset password</h2>
          <p className="dialog-subtitle">Set a temporary password for @{user.username}.</p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="form-grid" style={{ marginTop: error ? 14 : 0 }}>
            <label className="field">
              <span className="field-label">New temporary password</span>
              <input className="input" type="password" required minLength={8} maxLength={200} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus />
              <span className="field-help">At least 8 characters with upper/lowercase, a number and a special character.</span>
            </label>
            <label className="field">
              <span className="field-label">Confirm password</span>
              <input className="input" type="password" required minLength={8} maxLength={200} autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} />
            </label>
            <label className="checkbox-field">
              <input type="checkbox" checked={forceChange} onChange={(event) => setForceChange(event.target.checked)} />
              <span>Require password change at next sign-in</span>
            </label>
          </div>
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Icon name="key" size={15} /> {busy ? 'Resetting…' : 'Reset password'}
          </button>
        </div>
      </form>
    </div>
  )
}
