import { useEffect, useState } from 'react'
import { apiGet, buildQuery } from '../../api/apiClient'
import { downloadEntryTemplate, importEntryFile } from '../../api/operationEntryApi'
import { Alert, Pagination } from '../common/Ui'
import { EntryDialog } from './EntryFeedback'
import { logUiAction } from '../../utils/actionLogger'

export default function EntryImport({ definitions, onCancel, onImported }) {
  const [code, setCode] = useState(definitions[0]?.payload_field_code || '')
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [headers, setHeaders] = useState([])
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  useEffect(() => {
    let active = true
    apiGet(`/operation-entry-import/template${buildQuery({ payload_code: code, format: 'metadata' })}`).then(r => { if (active) setHeaders(r.headers) }).catch(e => { if (active) setError(e.message) })
    setPreview(null); setPage(1)
    return () => { active = false }
  }, [code])
  const run = async confirm => {
    if (!file) { setError('Choose a CSV or XLSX file first.'); return }
    setBusy(true); setError('')
    try {
      const r = await importEntryFile(file, confirm, code)
      if (confirm) onImported(r)
      else { setPreview(r); setPage(1) }
    } catch (e) { setError(e.message); if (e.payload?.rows) setPreview(e.payload) }
    finally { setBusy(false) }
  }
  return <EntryDialog title="Import operation tickets" footer={<>
    <button className="btn btn-secondary" disabled={busy} onClick={onCancel}>Cancel</button>
    <button className="btn btn-secondary" disabled={busy || !file} onClick={() => run(false)}>Validate file</button>
    <button className="btn btn-primary" disabled={busy || !preview?.valid_rows || preview.invalid_rows > 0} onClick={() => run(true)}>{busy ? 'Working…' : `Import ${preview?.ticket_count || 0} Draft tickets`}</button>
  </>}>
    <p>Fixed columns only — no JSON cells or template customizations. All rows are validated before any ticket is written. Imports create Drafts; submission remains a separate reviewed action.</p>
    <label className="field"><span className="field-label">Module payload</span><select className="select" value={code} onChange={e => setCode(e.target.value)}>
      {definitions.flatMap(d => [d, ...(d.alternatives || [])]).map(d => <option key={d.payload_field_code} value={d.payload_field_code}>{d.entry_layout_type}</option>)}
    </select></label>
    <p>Use one row per ticket for tank, tanker, shuttle and FSO; one row per tank for barge; one row per configured meter for flowmeter. Repeat the same <code>ticket_key</code> to group a ticket’s rows.</p>
    <div className="entry-form-actions">{['csv','xlsx'].map(format => <button key={format} className="btn btn-secondary" onClick={async () => { try { await downloadEntryTemplate(code, format); logUiAction('Operation Entry','Download Import Template',{ code, format }) } catch (e) { setError(e.message) } }}>Download {format.toUpperCase()} template</button>)}</div>
    <details><summary>Fixed column names ({headers.length})</summary><p className="mono small">{headers.join(', ')}</p></details>
    <label className="field"><span className="field-label">CSV or XLSX file (maximum 5 MB / 5,000 rows)</span><input className="input" type="file" accept=".csv,.xlsx" onChange={e => { setFile(e.target.files?.[0]); setPreview(null) }} /></label>
    {error && <Alert tone="danger">{error}</Alert>}
    {preview && <><Alert tone={preview.invalid_rows ? 'warning' : 'success'}>{preview.valid_rows} valid rows · {preview.invalid_rows} invalid rows · {preview.ticket_count} tickets</Alert>
      <div className="table-wrap"><table className="data-table"><thead><tr><th>Row</th><th>Ticket key</th><th>Asset ID</th><th>Validation</th></tr></thead><tbody>{preview.rows.slice((page-1)*pageSize, page*pageSize).map(r => <tr key={r.row_number}><td>{r.row_number}</td><td>{r.ticket_key}</td><td>{r.asset_id}</td><td>{r.valid ? 'Valid' : r.errors.join('; ')}</td></tr>)}</tbody></table></div>
      <Pagination page={page} pageSize={pageSize} pages={Math.ceil(preview.rows.length/pageSize)} total={preview.rows.length}
        onPageChange={setPage} onPageSizeChange={n => { setPageSize(n); setPage(1) }} />
    </>}
  </EntryDialog>
}
