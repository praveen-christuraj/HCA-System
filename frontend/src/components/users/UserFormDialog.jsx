import { useMemo, useState } from 'react'
import { createUser, updateUser } from '../../api/usersApi'
import Icon from '../common/Icon'
import { Alert } from '../common/Ui'

const blankForm = {
  full_name: '',
  username: '',
  email: '',
  phone: '',
  department: '',
  designation: '',
  password: '',
  status: 'Active',
  force_password_change: true,
}

export default function UserFormDialog({ user, roles = [], canAssignRoles = false, onClose, onSaved }) {
  const [form, setForm] = useState(() => ({ ...blankForm, ...(user || {}) }))
  const [roleIds, setRoleIds] = useState(() => (user?.roles || []).map((role) => role.id))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const isEdit = Boolean(user)
  const activeRoles = useMemo(() => roles.filter((role) => role.status === 'Active'), [roles])

  const update = (key, value) => setForm((current) => ({ ...current, [key]: value }))
  const toggleRole = (id) => setRoleIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    if (!isEdit && form.password.length < 8) {
      setError('Temporary password must be at least 8 characters and include upper/lowercase, a number and a special character.')
      return
    }
    setBusy(true)
    const payload = {
      full_name: form.full_name.trim(),
      email: form.email.trim(),
      phone: form.phone.trim() || null,
      department: form.department.trim() || null,
      designation: form.designation.trim() || null,
      status: form.status,
      force_password_change: Boolean(form.force_password_change),
    }
    if (!isEdit) {
      payload.username = form.username.trim()
      payload.password = form.password
    }
    if (canAssignRoles) payload.role_ids = roleIds
    try {
      const result = isEdit ? await updateUser(user.id, payload) : await createUser(payload)
      onSaved(result, isEdit ? 'User updated successfully' : 'User created successfully')
    } catch (submitError) {
      setError(submitError.message || 'Unable to save user')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <form className="dialog dialog-lg" role="dialog" aria-modal="true" aria-labelledby="user-form-title" onSubmit={submit}>
        <div className="dialog-head">
          <h2 id="user-form-title" className="dialog-title">{isEdit ? 'Edit user' : 'Add new user'}</h2>
          <p className="dialog-subtitle">
            {isEdit ? 'Update account information and access status.' : 'Create an account. A temporary password is never stored in audit details.'}
          </p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="form-grid-2" style={{ marginTop: error ? 14 : 0 }}>
            <label className="field">
              <span className="field-label">Full name</span>
              <input className="input" required minLength={2} maxLength={150} value={form.full_name || ''} onChange={(event) => update('full_name', event.target.value)} autoFocus />
            </label>
            <label className="field">
              <span className="field-label">Username</span>
              <input className="input" required minLength={3} maxLength={80} pattern="[A-Za-z0-9._-]+" value={form.username || ''} onChange={(event) => update('username', event.target.value)} disabled={isEdit} />
              {isEdit && <span className="field-help">Usernames cannot be changed.</span>}
            </label>
            <label className="field">
              <span className="field-label">Email</span>
              <input className="input" type="email" required maxLength={150} value={form.email || ''} onChange={(event) => update('email', event.target.value)} />
            </label>
            {!isEdit && (
              <label className="field">
                <span className="field-label">Temporary password</span>
                <input className="input" type="password" required minLength={8} maxLength={200} autoComplete="new-password" value={form.password} onChange={(event) => update('password', event.target.value)} />
                <span className="field-help">At least 8 characters with upper/lowercase, a number and a special character.</span>
              </label>
            )}
            <label className="field">
              <span className="field-label">Phone</span>
              <input className="input" maxLength={50} value={form.phone || ''} onChange={(event) => update('phone', event.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">Department</span>
              <input className="input" maxLength={100} value={form.department || ''} onChange={(event) => update('department', event.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">Designation</span>
              <input className="input" maxLength={100} value={form.designation || ''} onChange={(event) => update('designation', event.target.value)} />
            </label>
            <label className="field">
              <span className="field-label">Account status</span>
              <select className="select" value={form.status || 'Active'} onChange={(event) => update('status', event.target.value)}>
                <option value="Active">Active</option>
                <option value="Inactive">Inactive</option>
              </select>
            </label>
            <label className="checkbox-field">
              <input type="checkbox" checked={Boolean(form.force_password_change)} onChange={(event) => update('force_password_change', event.target.checked)} />
              <span>Require password change at next sign-in</span>
            </label>
          </div>

          {canAssignRoles && (
            <div className="form-section">
              <div className="section-head">
                <div>
                  <h3 className="section-title">Role assignments</h3>
                  <p className="section-note">Only active roles are available. Admin access is managed separately.</p>
                </div>
                <span className="tag">{roleIds.length} selected</span>
              </div>
              <div className="role-options">
                {activeRoles.filter((role) => role.role_name?.toLowerCase() !== 'admin').map((role) => (
                  <label className="role-option" key={role.id}>
                    <input type="checkbox" checked={roleIds.includes(role.id)} onChange={() => toggleRole(role.id)} />
                    <span><strong>{role.role_name}</strong><small>{role.description || 'No description'}</small></span>
                  </label>
                ))}
                {activeRoles.filter((role) => role.role_name?.toLowerCase() !== 'admin').length === 0 && <p className="muted small">No active roles are available.</p>}
              </div>
            </div>
          )}
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Icon name="checkCircle" size={15} /> {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Create user'}
          </button>
        </div>
      </form>
    </div>
  )
}
