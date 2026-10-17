import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  createAsset,
  deactivateAsset,
  downloadAssetsExport,
  importAssetsFile,
  listAssets,
  updateAsset,
} from '../api/assetsApi'
import { listLocations } from '../api/locationsApi'
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

const EMPTY_FILTERS = {
  search: '',
  status: '',
  asset_type_code: '',
  asset_scope: '',
  location_id: '',
  calibration_required: '',
  has_calibration: '',
  date_from: '',
  date_to: '',
}

const ASSET_TEMPLATE = [
  'asset_code',
  'asset_name',
  'asset_type',
  'asset_scope',
  'location_code',
  'tank_names',
  'calibration_required',
  'dip_unit',
  'volume_unit',
  'serial_number',
  'manufacturer',
  'model',
  'commission_date',
  'description',
  'status',
]

const EMPTY_TANK = { tank_name: '', tank_code: '', description: '' }

function TankEditor({ tanks, onChange, disabled }) {
  const update = (index, field, value) => {
    const next = tanks.map((tank, position) =>
      position === index ? { ...tank, [field]: value } : tank,
    )
    onChange(next)
  }
  const remove = (index) => onChange(tanks.filter((_, position) => position !== index))

  return (
    <div className="field" style={{ gridColumn: '1 / -1' }}>
      <span className="field-label">
        Tanks / compartments
        <span className="muted small" style={{ marginLeft: 8 }}>
          Names must match the calibration chart exactly
        </span>
      </span>
      {tanks.length === 0 && (
        <p className="field-help">
          No tanks declared. Declare at least one tank before marking this asset as requiring
          calibration.
        </p>
      )}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: '34%' }}>Tank name</th>
              <th style={{ width: '22%' }}>Tank code</th>
              <th>Description</th>
              <th aria-label="Actions" style={{ width: 70 }} />
            </tr>
          </thead>
          <tbody>
            {tanks.map((tank, index) => (
              // eslint-disable-next-line react/no-array-index-key
              <tr key={index}>
                <td>
                  <input
                    className="input"
                    required
                    maxLength={120}
                    value={tank.tank_name}
                    disabled={disabled}
                    placeholder="1P, 2S, T-101…"
                    onChange={(event) => update(index, 'tank_name', event.target.value)}
                  />
                </td>
                <td>
                  <input
                    className="input"
                    maxLength={50}
                    value={tank.tank_code}
                    disabled={disabled}
                    onChange={(event) => update(index, 'tank_code', event.target.value)}
                  />
                </td>
                <td>
                  <input
                    className="input"
                    maxLength={2000}
                    value={tank.description}
                    disabled={disabled}
                    onChange={(event) => update(index, 'description', event.target.value)}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost btn-compact"
                    onClick={() => remove(index)}
                    disabled={disabled}
                    aria-label={`Remove tank ${index + 1}`}
                  >
                    <Icon name="close" size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button
        type="button"
        className="btn btn-secondary btn-compact"
        style={{ marginTop: 8 }}
        onClick={() => onChange([...tanks, { ...EMPTY_TANK }])}
        disabled={disabled}
      >
        <Icon name="database" size={14} /> Add tank
      </button>
    </div>
  )
}

function AssetDialog({ asset, assetTypes, locations, onClose, onSaved }) {
  const [form, setForm] = useState({
    asset_name: asset?.asset_name || '',
    asset_code: asset?.asset_code || '',
    asset_type_code: asset?.asset_type_code || assetTypes[0]?.code || '',
    asset_scope: asset?.asset_scope || 'Local',
    location_id: asset?.location_id ? String(asset.location_id) : '',
    calibration_required: asset ? asset.calibration_required : true,
    dip_unit: asset?.dip_unit || 'cm',
    volume_unit: asset?.volume_unit || 'bbl',
    serial_number: asset?.serial_number || '',
    manufacturer: asset?.manufacturer || '',
    model: asset?.model || '',
    commission_date: asset?.commission_date || '',
    description: asset?.description || '',
    status: asset?.status || 'Active',
  })
  const [tanks, setTanks] = useState(
    asset?.tanks?.length
      ? asset.tanks.map((tank) => ({
          tank_name: tank.tank_name,
          tank_code: tank.tank_code || '',
          description: tank.description || '',
        }))
      : [{ ...EMPTY_TANK }],
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const selectedType = assetTypes.find((type) => type.code === form.asset_type_code)
  const supportsTanks = Boolean(selectedType?.supports_tanks)
  const supportsCalibration = Boolean(selectedType?.calibration_supported)
  const isLocal = form.asset_scope === 'Local'
  const locationOptions = locations.filter(
    (location) => location.status === 'Active' || location.id === asset?.location_id,
  )

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    const payload = {
      ...form,
      asset_code: form.asset_code.trim().toUpperCase(),
      location_id: isLocal && form.location_id ? Number(form.location_id) : null,
      calibration_required: supportsCalibration ? form.calibration_required : false,
      commission_date: form.commission_date || null,
      description: form.description.trim() || null,
      serial_number: form.serial_number.trim() || null,
      manufacturer: form.manufacturer.trim() || null,
      model: form.model.trim() || null,
      tanks: supportsTanks
        ? tanks
            .filter((tank) => tank.tank_name.trim())
            .map((tank) => ({
              tank_name: tank.tank_name.trim(),
              tank_code: tank.tank_code.trim() || null,
              description: tank.description.trim() || null,
            }))
        : [],
    }
    try {
      const result = asset ? await updateAsset(asset.id, payload) : await createAsset(payload)
      onSaved(result, asset ? 'Asset updated successfully' : 'Asset created successfully')
    } catch (saveError) {
      setError(saveError.message || 'Unable to save the asset')
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
        aria-labelledby="asset-dialog-title"
        onSubmit={submit}
      >
        <div className="dialog-head">
          <h2 id="asset-dialog-title" className="dialog-title">
            {asset ? 'Edit asset' : 'Add asset'}
          </h2>
          <p className="dialog-subtitle">
            Asset types are fixed by the system. Declare the tanks of this asset here — the
            calibration chart is keyed by these exact names.
          </p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="form-grid-2" style={{ marginTop: error ? 14 : 0 }}>
            <label className="field">
              <span className="field-label">Asset name</span>
              <input
                className="input"
                required
                minLength={2}
                maxLength={150}
                autoFocus
                value={form.asset_name}
                onChange={(event) => setForm({ ...form, asset_name: event.target.value })}
              />
            </label>
            <label className="field">
              <span className="field-label">Asset code</span>
              <input
                className="input"
                required
                minLength={1}
                maxLength={80}
                pattern="[A-Za-z0-9._/-]+"
                value={form.asset_code}
                onChange={(event) =>
                  setForm({ ...form, asset_code: event.target.value.toUpperCase() })
                }
              />
              <span className="field-help">Unique. Letters, numbers, periods, underscores, hyphens.</span>
            </label>
            <label className="field">
              <span className="field-label">Asset type</span>
              <select
                className="select"
                value={form.asset_type_code}
                onChange={(event) => setForm({ ...form, asset_type_code: event.target.value })}
              >
                {assetTypes.map((type) => (
                  <option key={type.code} value={type.code}>
                    {type.name}
                  </option>
                ))}
              </select>
              {selectedType && <span className="field-help">{selectedType.description}</span>}
            </label>
            <label className="field">
              <span className="field-label">Asset scope</span>
              <select
                className="select"
                value={form.asset_scope}
                onChange={(event) => setForm({ ...form, asset_scope: event.target.value })}
              >
                <option value="Local">Local — belongs to one location</option>
                <option value="Global">Global — available everywhere</option>
              </select>
              <span className="field-help">
                {isLocal
                  ? 'A location is required for a Local asset.'
                  : 'Global assets are not tied to a location.'}
              </span>
            </label>
            {isLocal && (
              <label className="field">
                <span className="field-label">Location</span>
                <select
                  className="select"
                  required
                  value={form.location_id}
                  onChange={(event) => setForm({ ...form, location_id: event.target.value })}
                >
                  <option value="">Select a location</option>
                  {locationOptions.map((location) => (
                    <option key={location.id} value={location.id}>
                      {location.location_name} ({location.location_code})
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="field">
              <span className="field-label">Calibration required</span>
              <select
                className="select"
                value={form.calibration_required ? 'true' : 'false'}
                disabled={!supportsCalibration}
                onChange={(event) =>
                  setForm({ ...form, calibration_required: event.target.value === 'true' })
                }
              >
                <option value="true">Yes — this asset is gauged</option>
                <option value="false">No — no calibration needed</option>
              </select>
              <span className="field-help">
                {supportsCalibration
                  ? 'A calibrated asset needs at least one declared tank.'
                  : `${selectedType?.name || 'This asset type'} is not calibrated.`}
              </span>
            </label>
            <label className="field">
              <span className="field-label">Display dip unit</span>
              <select
                className="select"
                value={form.dip_unit}
                onChange={(event) => setForm({ ...form, dip_unit: event.target.value })}
              >
                <option value="cm">Centimetres (cm)</option>
                <option value="mm">Millimetres (mm)</option>
                <option value="m">Metres (m)</option>
              </select>
              <span className="field-help">Calculations always run in cm.</span>
            </label>
            <label className="field">
              <span className="field-label">Display volume unit</span>
              <select
                className="select"
                value={form.volume_unit}
                onChange={(event) => setForm({ ...form, volume_unit: event.target.value })}
              >
                <option value="bbl">Barrels (bbl)</option>
                <option value="l">Litres (L)</option>
                <option value="kl">Kilolitres (kL)</option>
              </select>
              <span className="field-help">Calculations always run in bbl.</span>
            </label>
            <label className="field">
              <span className="field-label">Serial number</span>
              <input
                className="input"
                maxLength={100}
                value={form.serial_number}
                onChange={(event) => setForm({ ...form, serial_number: event.target.value })}
              />
            </label>
            <label className="field">
              <span className="field-label">Manufacturer</span>
              <input
                className="input"
                maxLength={150}
                value={form.manufacturer}
                onChange={(event) => setForm({ ...form, manufacturer: event.target.value })}
              />
            </label>
            <label className="field">
              <span className="field-label">Model</span>
              <input
                className="input"
                maxLength={150}
                value={form.model}
                onChange={(event) => setForm({ ...form, model: event.target.value })}
              />
            </label>
            <label className="field">
              <span className="field-label">Commission date</span>
              <input
                className="input"
                type="date"
                value={form.commission_date || ''}
                onChange={(event) => setForm({ ...form, commission_date: event.target.value })}
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
            <label className="field">
              <span className="field-label">Description</span>
              <textarea
                className="textarea"
                maxLength={2000}
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
              />
            </label>
            {supportsTanks && (
              <TankEditor tanks={tanks} onChange={setTanks} disabled={busy} />
            )}
          </div>
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Icon name="checkCircle" size={15} />
            {busy ? 'Saving…' : asset ? 'Save changes' : 'Create asset'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default function Assets() {
  const { isAdmin, hasPermission } = usePermissions()
  const canCreate = isAdmin || hasPermission('assets:create')
  const canUpdate = isAdmin || hasPermission('assets:update')
  const canDelete = isAdmin || hasPermission('assets:delete')

  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [data, setData] = useState({ items: [], total: 0, pages: 0, asset_types: [] })
  const [locations, setLocations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editingAsset, setEditingAsset] = useState(null)
  const [showDialog, setShowDialog] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [exporting, setExporting] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await listAssets({ ...applied, page, page_size: pageSize }))
    } catch (loadError) {
      setError(loadError.message || 'Unable to load assets')
      setData({ items: [], total: 0, pages: 0, asset_types: [] })
    } finally {
      setLoading(false)
    }
  }, [applied, page, pageSize])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    let active = true
    listLocations({ page: 1, page_size: 200, status: 'Active' })
      .then((response) => {
        if (active) setLocations(response.items || [])
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])

  const assetTypes = data.asset_types || []

  const chips = useMemo(
    () => [
      ...(applied.search ? [{ key: 'search', label: `Search: ${applied.search}` }] : []),
      ...(applied.status ? [{ key: 'status', label: `Status: ${applied.status}` }] : []),
      ...(applied.asset_type_code
        ? [
            {
              key: 'asset_type_code',
              label: `Type: ${
                assetTypes.find((type) => type.code === applied.asset_type_code)?.name ||
                applied.asset_type_code
              }`,
            },
          ]
        : []),
      ...(applied.asset_scope ? [{ key: 'asset_scope', label: `Scope: ${applied.asset_scope}` }] : []),
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
      ...(applied.calibration_required
        ? [
            {
              key: 'calibration_required',
              label: `Calibration: ${applied.calibration_required === 'true' ? 'required' : 'not required'}`,
            },
          ]
        : []),
      ...(applied.has_calibration
        ? [
            {
              key: 'has_calibration',
              label: `Chart: ${applied.has_calibration === 'true' ? 'uploaded' : 'missing'}`,
            },
          ]
        : []),
      ...(applied.date_from ? [{ key: 'date_from', label: `Created from: ${applied.date_from}` }] : []),
      ...(applied.date_to ? [{ key: 'date_to', label: `Created to: ${applied.date_to}` }] : []),
    ],
    [applied, assetTypes, locations],
  )

  const applyFilters = () => {
    setApplied({ ...draft })
    setPage(1)
    logUiAction('Asset Master', 'Apply Filter')
  }
  const resetFilters = () => {
    setDraft(EMPTY_FILTERS)
    setApplied(EMPTY_FILTERS)
    setPage(1)
    logUiAction('Asset Master', 'Reset Filter')
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
      await downloadAssetsExport(format, applied)
    } catch (exportError) {
      setError(exportError.message || 'Export failed')
    } finally {
      setExporting('')
    }
  }

  const handleDeactivate = async (asset) => {
    if (!window.confirm(`Deactivate “${asset.asset_name}”?`)) return
    setError('')
    try {
      await deactivateAsset(asset.id)
      setNotice(`${asset.asset_name} has been deactivated.`)
      load()
    } catch (deactivateError) {
      setError(deactivateError.message || 'Unable to deactivate the asset')
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="MASTER DATA / ASSET MASTER"
        title="Asset Master"
        description="Register assets against the seven fixed hydrocarbon asset types, declare their tanks, and set the scope that controls location access."
        actions={
          <>
            {canCreate && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  setEditingAsset(null)
                  setShowDialog(true)
                  setNotice('')
                }}
              >
                <Icon name="database" size={15} /> Add asset
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
                  placeholder="Search name, code, serial or manufacturer"
                  aria-label="Search assets"
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
          <div className="toolbar-group" role="group" aria-label="Export assets">
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
                <span className="field-label">Asset type</span>
                <select
                  className="select"
                  value={draft.asset_type_code}
                  onChange={(event) => setDraft({ ...draft, asset_type_code: event.target.value })}
                >
                  <option value="">All asset types</option>
                  {assetTypes.map((type) => (
                    <option key={type.code} value={type.code}>
                      {type.name}
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
              <label className="field">
                <span className="field-label">Scope</span>
                <select
                  className="select"
                  value={draft.asset_scope}
                  onChange={(event) => setDraft({ ...draft, asset_scope: event.target.value })}
                >
                  <option value="">All scopes</option>
                  <option value="Local">Local</option>
                  <option value="Global">Global</option>
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
                      {location.location_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field-label">Calibration</span>
                <select
                  className="select"
                  value={draft.calibration_required}
                  onChange={(event) =>
                    setDraft({ ...draft, calibration_required: event.target.value })
                  }
                >
                  <option value="">Required or not</option>
                  <option value="true">Calibration required</option>
                  <option value="false">No calibration</option>
                </select>
              </label>
              <label className="field">
                <span className="field-label">Chart uploaded</span>
                <select
                  className="select"
                  value={draft.has_calibration}
                  onChange={(event) => setDraft({ ...draft, has_calibration: event.target.value })}
                >
                  <option value="">Either</option>
                  <option value="true">Has a chart</option>
                  <option value="false">No chart yet</option>
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
          <Loading label="Loading assets…" />
        ) : data.items.length === 0 ? (
          <EmptyState
            title="No assets match the current filters"
            description="Adjust your search or filters, or add an asset."
          />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Asset</th>
                    <th>Type</th>
                    <th>Scope</th>
                    <th>Tanks</th>
                    <th>Calibration</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((asset) => (
                    <tr key={asset.id}>
                      <td>
                        <div className="cell-primary">{asset.asset_name}</div>
                        <div className="cell-sub cell-mono">{asset.asset_code}</div>
                      </td>
                      <td>{asset.asset_type_name}</td>
                      <td>
                        {asset.asset_scope === 'Global' ? (
                          <span className="tag tag-info">Global</span>
                        ) : (
                          <>
                            <div>{asset.location_name || '—'}</div>
                            <div className="cell-sub cell-mono">{asset.location_code}</div>
                          </>
                        )}
                      </td>
                      <td>
                        {asset.tank_count > 0 ? (
                          <div className="location-chip-list">
                            {asset.tanks.slice(0, 4).map((tank) => (
                              <span className="location-chip" key={tank.id}>
                                {tank.tank_name}
                              </span>
                            ))}
                            {asset.tank_count > 4 && (
                              <span className="tag">+{asset.tank_count - 4} more</span>
                            )}
                          </div>
                        ) : (
                          <span className="muted">No tanks</span>
                        )}
                      </td>
                      <td>
                        {!asset.calibration_required ? (
                          <span className="muted">Not required</span>
                        ) : asset.has_calibration ? (
                          <StatusTag status="Chart uploaded" tone="success" />
                        ) : (
                          <StatusTag status="Chart missing" tone="warning" />
                        )}
                      </td>
                      <td>
                        <StatusTag status={asset.status} />
                      </td>
                      <td className="nowrap">{formatDateTime(asset.created_at)}</td>
                      <td>
                        <div className="table-actions">
                          {asset.calibration_required && (
                            <Link
                              to={`/asset-calibration?asset=${asset.id}`}
                              className="btn btn-ghost btn-compact"
                            >
                              <Icon name="barChart" size={14} /> Calibration
                            </Link>
                          )}
                          {canUpdate && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-compact"
                              onClick={() => {
                                setEditingAsset(asset)
                                setShowDialog(true)
                                setNotice('')
                              }}
                            >
                              <Icon name="settings" size={14} /> Edit
                            </button>
                          )}
                          {canDelete && asset.status === 'Active' && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-compact"
                              onClick={() => handleDeactivate(asset)}
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
                logUiAction('Asset Master', 'Change Page', { page: next })
              }}
              onPageSizeChange={(next) => {
                setPageSize(next)
                setPage(1)
                logUiAction('Asset Master', 'Change Page Size', { page_size: next })
              }}
              disabled={loading}
            />
          </>
        )}
      </section>

      {showDialog && (
        <AssetDialog
          asset={editingAsset}
          assetTypes={assetTypes}
          locations={locations}
          onClose={() => {
            setShowDialog(false)
            setEditingAsset(null)
          }}
          onSaved={(asset, message) => {
            setShowDialog(false)
            setEditingAsset(null)
            setNotice(message)
            load()
          }}
        />
      )}
      {showImport && (
        <MasterImportDialog
          title="assets"
          templateHeaders={ASSET_TEMPLATE}
          templateFilename="asset-import-template.csv"
          importFile={importAssetsFile}
          onClose={() => setShowImport(false)}
          onImported={(result) => {
            setShowImport(false)
            setNotice(result.message || 'Assets imported successfully')
            setPage(1)
            load()
          }}
        />
      )}
    </div>
  )
}
