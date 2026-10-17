import { useRef, useState } from 'react'
import { importUsersFile } from '../../api/usersApi'
import Icon from '../common/Icon'
import { Alert } from '../common/Ui'

const TEMPLATE_HEADERS = [
  'username',
  'full_name',
  'email',
  'password',
  'phone',
  'department',
  'designation',
  'status',
  'role_names',
  'force_password_change',
]

const downloadTemplate = () => {
  const content = '\ufeff' + TEMPLATE_HEADERS.join(',') + '\n'
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'user-import-template.csv'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

const displayRows = (preview) => (preview?.rows || []).slice(0, 100)

/**
 * Import dialog (owner rules 7 and 10).
 * Upload XLSX/CSV → preview validation → commit. No writes occur before the
 * explicit import action. Closes only via Cancel or a successful import.
 */
export default function ImportUsersDialog({ onClose, onImported }) {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  const canCommit =
    Boolean(file) &&
    Boolean(preview) &&
    preview.valid_rows > 0 &&
    preview.invalid_rows === 0 &&
    !busy

  const handlePreview = async () => {
    if (!file) {
      setError('Choose an XLSX or CSV file first.')
      return
    }
    setBusy(true)
    setError('')
    setPreview(null)
    try {
      setPreview(await importUsersFile(file, false))
    } catch (previewError) {
      setError(previewError.message || 'The file could not be previewed')
      if (previewError.payload?.rows) setPreview(previewError.payload)
    } finally {
      setBusy(false)
    }
  }

  const handleImport = async () => {
    if (!canCommit) return
    setBusy(true)
    setError('')
    try {
      const result = await importUsersFile(file, true)
      onImported(result)
    } catch (importError) {
      setError(importError.message || 'The import failed')
      if (importError.payload?.rows) setPreview(importError.payload)
    } finally {
      setBusy(false)
    }
  }

  const rows = displayRows(preview)

  return (
    <div className="dialog-backdrop">
      <div
        className="dialog dialog-lg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-users-title"
        aria-describedby="import-users-subtitle"
      >
        <div className="dialog-head">
          <h2 id="import-users-title" className="dialog-title">
            Import users
          </h2>
          <p id="import-users-subtitle" className="dialog-subtitle">
            Upload an XLSX or CSV file, preview every row, then commit. Nothing is written until
            you choose Import.
          </p>
        </div>

        <div className="dialog-body">
          <div className="filters-grid" style={{ alignItems: 'end' }}>
            <label className="field">
              <span className="field-label">Spreadsheet file</span>
              <input
                ref={inputRef}
                id="import-users-file"
                className="input"
                type="file"
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(event) => {
                  const selected = event.target.files?.[0] || null
                  setFile(selected)
                  setPreview(null)
                  setError('')
                }}
              />
            </label>
            <div className="field">
              <span className="field-label">Template</span>
              <button type="button" className="btn btn-secondary" onClick={downloadTemplate}>
                <Icon name="download" size={15} />
                Download CSV template
              </button>
            </div>
          </div>

          <p className="field-help" style={{ marginTop: 8 }}>
            Maximum 5 MB and 5,000 rows. Required columns: username, full_name, email and
            password. Optional: phone, department, designation, status, role_names
            (comma-separated), force_password_change.
          </p>

          {error && (
            <div style={{ marginTop: 12 }}>
              <Alert tone="danger">{error}</Alert>
            </div>
          )}

          {preview && (
            <div style={{ marginTop: 14 }}>
              <Alert
                tone={
                  preview.missing_columns?.length
                    ? 'danger'
                    : preview.invalid_rows > 0
                      ? 'warning'
                      : 'success'
                }
                icon={preview.invalid_rows > 0 ? 'alertTriangle' : 'checkCircle'}
              >
                <strong>{preview.message}</strong>
                <div className="small" style={{ marginTop: 3 }}>
                  File: {preview.filename} · Rows: {preview.total_rows} · Valid:{' '}
                  {preview.valid_rows} · Invalid: {preview.invalid_rows}
                </div>
                {preview.missing_columns?.length > 0 && (
                  <div className="small" style={{ marginTop: 3 }}>
                    Missing required columns: {preview.missing_columns.join(', ')}
                  </div>
                )}
              </Alert>

              {rows.length > 0 && (
                <div className="table-wrap" style={{ marginTop: 12, maxHeight: 360, overflowY: 'auto' }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Row</th>
                        <th>Username</th>
                        <th>Full name</th>
                        <th>Email</th>
                        <th>Status</th>
                        <th>Roles</th>
                        <th>Validation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.row_number}>
                          <td className="tnum">{row.row_number}</td>
                          <td>{row.username || '—'}</td>
                          <td>{row.full_name || '—'}</td>
                          <td>{row.email || '—'}</td>
                          <td>{row.status || '—'}</td>
                          <td>{row.role_names || 'No role'}</td>
                          <td>
                            {row.valid ? (
                              <span className="tag tag-success">Valid</span>
                            ) : (
                              <span className="field-error">{row.errors.join('; ')}</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {preview.rows?.length > rows.length && (
                <p className="field-help" style={{ marginTop: 6 }}>
                  Showing the first {rows.length} of {preview.rows.length} rows. All rows are
                  validated and imported when you confirm.
                </p>
              )}
            </div>
          )}
        </div>

        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handlePreview}
            disabled={busy || !file}
          >
            <Icon name="eye" size={15} />
            {busy && !canCommit ? 'Checking…' : 'Preview file'}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleImport}
            disabled={!canCommit}
          >
            <Icon name="upload" size={15} />
            {busy && canCommit
              ? 'Importing…'
              : `Import ${preview?.valid_rows || 0} user${preview?.valid_rows === 1 ? '' : 's'}`}
          </button>
        </div>
      </div>
    </div>
  )
}
