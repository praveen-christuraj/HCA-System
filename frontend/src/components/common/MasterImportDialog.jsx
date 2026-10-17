import { useMemo, useRef, useState } from 'react'
import Icon from './Icon'
import { Alert } from './Ui'

const downloadTemplate = (headers, filename) => {
  const content = `\ufeff${headers.join(',')}\n`
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

const labelFor = (key) => String(key || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())

export default function MasterImportDialog({
  title,
  templateHeaders,
  templateFilename,
  importFile,
  onClose,
  onImported,
}) {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef(null)
  const previewRows = useMemo(() => (preview?.rows || []).slice(0, 80), [preview])
  const columns = useMemo(() => {
    if (previewRows.length) {
      return Object.keys(previewRows[0]).filter((key) => !['row_number', 'valid', 'errors'].includes(key))
    }
    return []
  }, [previewRows])
  const canCommit = Boolean(file && preview && preview.valid_rows > 0 && preview.invalid_rows === 0 && !busy)

  const runPreview = async () => {
    if (!file) {
      setError('Choose an XLSX or CSV file first.')
      return
    }
    setBusy(true)
    setError('')
    setPreview(null)
    try {
      setPreview(await importFile(file, false))
    } catch (previewError) {
      setError(previewError.message || 'The file could not be previewed')
      if (previewError.payload?.rows) setPreview(previewError.payload)
    } finally {
      setBusy(false)
    }
  }

  const commitImport = async () => {
    if (!canCommit) return
    setBusy(true)
    setError('')
    try {
      onImported(await importFile(file, true))
    } catch (importError) {
      setError(importError.message || 'The import failed')
      if (importError.payload?.rows) setPreview(importError.payload)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <div className="dialog dialog-lg" role="dialog" aria-modal="true" aria-labelledby="master-import-title">
        <div className="dialog-head">
          <h2 id="master-import-title" className="dialog-title">Import {title.toLowerCase()}</h2>
          <p className="dialog-subtitle">Upload a CSV or XLSX, validate every row, then confirm. No data is changed during preview.</p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="filters-grid" style={{ alignItems: 'end', marginTop: error ? 12 : 0 }}>
            <label className="field">
              <span className="field-label">Spreadsheet file</span>
              <input
                ref={inputRef}
                className="input"
                type="file"
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={(event) => {
                  setFile(event.target.files?.[0] || null)
                  setPreview(null)
                  setError('')
                }}
              />
            </label>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => downloadTemplate(templateHeaders, templateFilename)}
            >
              <Icon name="download" size={15} /> Download template
            </button>
          </div>

          {preview && (
            <div style={{ marginTop: 16 }}>
              <Alert tone={preview.invalid_rows ? 'warning' : 'success'} icon={preview.invalid_rows ? 'alertTriangle' : 'checkCircle'}>
                {preview.message || `${preview.valid_rows || 0} row(s) ready to import`}
                {preview.total_rows > 0 && <span> · {preview.valid_rows} valid · {preview.invalid_rows} invalid</span>}
              </Alert>
              {preview.missing_columns?.length > 0 && (
                <p className="field-error" style={{ marginTop: 8 }}>Missing columns: {preview.missing_columns.join(', ')}</p>
              )}
              {preview.rows?.length > 0 && (
                <div className="table-wrap" style={{ marginTop: 12, maxHeight: 340 }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Row</th>
                        {columns.map((key) => <th key={key}>{labelFor(key)}</th>)}
                        <th>Validation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewRows.map((row) => (
                        <tr key={row.row_number}>
                          <td>{row.row_number}</td>
                          {columns.map((key) => <td key={key}>{String(row[key] ?? '—')}</td>)}
                          <td>{row.valid
                            ? <span className="tag tag-success">Valid</span>
                            : <span className="field-error">{(row.errors || []).join('; ')}</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {preview.rows?.length > previewRows.length && (
                <p className="field-help" style={{ marginTop: 6 }}>
                  Showing {previewRows.length} of {preview.rows.length} rows; the entire file was validated.
                </p>
              )}
            </div>
          )}
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="button" className="btn btn-secondary" onClick={runPreview} disabled={busy || !file}>
            <Icon name="eye" size={15} /> {busy && !canCommit ? 'Checking…' : 'Preview file'}
          </button>
          <button type="button" className="btn btn-primary" onClick={commitImport} disabled={!canCommit}>
            <Icon name="upload" size={15} />
            {busy && canCommit ? 'Importing…' : `Import ${preview?.valid_rows || 0}`}
          </button>
        </div>
      </div>
    </div>
  )
}
