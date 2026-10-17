import { useEffect, useId, useRef, useState } from 'react'
import { entryLookup } from '../../api/operationEntryApi'

export const optionLabel = row => row ? `${row.location_name || row.asset_name || row.operation_label} (${row.location_code || row.asset_code || row.operation_code})` : ''

/** Bounded, server-searchable dropdown. Never downloads an entire master. */
export default function EntryLookup({ kind, label, selected, onPick, params = {}, disabled = false, required = false }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ items: [], pages: 0, total: 0 })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const ref = useRef(null)
  const query = JSON.stringify(params)
  useEffect(() => {
    if (!open || disabled) return
    let active = true
    const timer = setTimeout(async () => {
      setBusy(true); setError('')
      try { const r = await entryLookup(kind, { ...JSON.parse(query), search, page, page_size: 20 }); if (active) setData(r) }
      catch (e) { if (active) setError(e.message) }
      finally { if (active) setBusy(false) }
    }, 160)
    return () => { active = false; clearTimeout(timer) }
  }, [open, disabled, kind, query, search, page])
  useEffect(() => {
    const outside = e => { if (!ref.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [])
  return <div ref={ref} className="entry-lookup">
    <label htmlFor={id}>{label}{required ? ' *' : ''}</label>
    <button id={id} className="entry-lookup-trigger" type="button" disabled={disabled} aria-haspopup="listbox" aria-expanded={open}
      onClick={() => { setOpen(v => !v); setSearch(''); setPage(1) }} onKeyDown={e => { if (e.key === 'Escape') setOpen(false) }}>
      {optionLabel(selected) || `Select ${label}`}<span aria-hidden="true">▾</span>
    </button>
    {open && !disabled && <div className="entry-lookup-menu">
      <input aria-label={`Search ${label}`} autoFocus value={search} placeholder="Search code or name…" onChange={e => { setSearch(e.target.value); setPage(1) }} onKeyDown={e => {
        if (e.key === 'Escape') { e.preventDefault(); setOpen(false); document.getElementById(id)?.focus() }
        if (e.key === 'ArrowDown') { e.preventDefault(); ref.current?.querySelector('[role="option"]')?.focus() }
      }} />
      {error && <div role="alert" className="error-box">{error}</div>}
      <div role="listbox" aria-label={label} aria-busy={busy} onKeyDown={e => {
        const els = [...ref.current.querySelectorAll('[role="option"]')]; const i = els.indexOf(document.activeElement)
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); els[(i + (e.key === 'ArrowDown' ? 1 : els.length - 1)) % els.length]?.focus() }
        if (e.key === 'Escape') { setOpen(false); document.getElementById(id)?.focus() }
      }}>
        {!required && <button type="button" role="option" aria-selected={!selected} onClick={() => { onPick(null); setOpen(false) }}>None</button>}
        {data.items.map(row => <button type="button" role="option" key={row.id} aria-selected={row.id === selected?.id} onClick={() => { onPick(row); setOpen(false); document.getElementById(id)?.focus() }}>{optionLabel(row)}</button>)}
      </div>
      {!data.items.length && <small>{busy ? 'Loading…' : 'No matching records. Check master setup and location access.'}</small>}
      <div className="entry-lookup-pager"><button type="button" disabled={page <= 1 || busy} onClick={() => setPage(p => p - 1)}>Previous</button>
        <small>{data.total} records · {page} / {Math.max(data.pages, 1)}</small>
        <button type="button" disabled={page >= data.pages || busy} onClick={() => setPage(p => p + 1)}>Next</button></div>
    </div>}
  </div>
}
