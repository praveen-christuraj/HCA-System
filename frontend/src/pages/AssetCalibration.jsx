import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  deleteCalibration,
  downloadCalibrationExport,
  getAssetReference,
  getCalibration,
  listAssets,
  lookupVolumeBatch,
  uploadCalibrationFile,
} from '../api/assetsApi'
import Icon from '../components/common/Icon'
import {
  Alert,
  EmptyState,
  formatDate,
  formatDateTime,
  Loading,
  PageHead,
  StatusTag,
} from '../components/common/Ui'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'

const CHART_TEMPLATE = ['tank_name', 'dip_ullage', 'volume']

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

function UploadDialog({ asset, reference, onClose, onUploaded }) {
  const [file, setFile] = useState(null)
  const [options, setOptions] = useState({
    chartName: '',
    measurementBasis: 'Dip',
    dipUnit: asset.dip_unit || 'cm',
    volumeUnit: asset.volume_unit || 'bbl',
    effectiveDate: '',
    remarks: '',
  })
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const previewRows = useMemo(() => (preview?.rows || []).slice(0, 80), [preview])
  const canCommit = Boolean(file && preview && preview.valid_rows > 0 && preview.invalid_rows === 0 && !busy)

  const runPreview = async () => {
    if (!file) {
      setError('Choose an XLSX or CSV calibration chart first.')
      return
    }
    setBusy(true)
    setError('')
    setPreview(null)
    try {
      setPreview(await uploadCalibrationFile(asset.id, file, options, false))
    } catch (previewError) {
      setError(previewError.message || 'The chart could not be read')
      if (previewError.payload?.rows) setPreview(previewError.payload)
    } finally {
      setBusy(false)
    }
  }

  const commit = async () => {
    if (!canCommit) return
    setBusy(true)
    setError('')
    try {
      onUploaded(await uploadCalibrationFile(asset.id, file, options, true))
    } catch (commitError) {
      setError(commitError.message || 'The upload failed')
      if (commitError.payload?.rows) setPreview(commitError.payload)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <div
        className="dialog dialog-lg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="calibration-upload-title"
      >
        <div className="dialog-head">
          <h2 id="calibration-upload-title" className="dialog-title">
            Upload calibration chart — {asset.asset_name}
          </h2>
          <p className="dialog-subtitle">
            Three columns: tank name, dip/ullage, volume. Depths are stored in cm and volumes in
            bbl whatever unit the chart uses. Preview validates every row before anything is saved.
          </p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="filters-grid" style={{ marginTop: error ? 12 : 0 }}>
            <label className="field">
              <span className="field-label">Chart file</span>
              <input
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
            <label className="field">
              <span className="field-label">Chart name</span>
              <input
                className="input"
                maxLength={150}
                value={options.chartName}
                placeholder={`${asset.asset_code} calibration chart`}
                onChange={(event) => setOptions({ ...options, chartName: event.target.value })}
              />
            </label>
            <label className="field">
              <span className="field-label">Measurement basis</span>
              <select
                className="select"
                value={options.measurementBasis}
                onChange={(event) =>
                  setOptions({ ...options, measurementBasis: event.target.value })
                }
              >
                <option value="Dip">Dip — measured up from the datum</option>
                <option value="Ullage">Ullage — measured down from the reference point</option>
              </select>
              <span className="field-help">
                The chart declares its own basis; lookups must use the same basis.
              </span>
            </label>
            <label className="field">
              <span className="field-label">Dip/Ullage unit in the file</span>
              <select
                className="select"
                value={options.dipUnit}
                onChange={(event) => setOptions({ ...options, dipUnit: event.target.value })}
              >
                {(reference?.units?.dip_units || []).map((unit) => (
                  <option key={unit.code} value={unit.code}>
                    {unit.label} — {unit.example}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Volume unit in the file</span>
              <select
                className="select"
                value={options.volumeUnit}
                onChange={(event) => setOptions({ ...options, volumeUnit: event.target.value })}
              >
                {(reference?.units?.volume_units || []).map((unit) => (
                  <option key={unit.code} value={unit.code}>
                    {unit.label} — {unit.example}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Effective date</span>
              <input
                className="input"
                type="date"
                value={options.effectiveDate}
                onChange={(event) => setOptions({ ...options, effectiveDate: event.target.value })}
              />
            </label>
            <label className="field" style={{ gridColumn: '1 / -1' }}>
              <span className="field-label">Remarks</span>
              <input
                className="input"
                maxLength={2000}
                value={options.remarks}
                onChange={(event) => setOptions({ ...options, remarks: event.target.value })}
              />
            </label>
          </div>

          <div style={{ marginTop: 12 }}>
            <button
              type="button"
              className="btn btn-ghost btn-compact"
              onClick={() => downloadTemplate(CHART_TEMPLATE, 'calibration-chart-template.csv')}
            >
              <Icon name="download" size={15} /> Download chart template
            </button>
            <span className="muted small" style={{ marginLeft: 10 }}>
              Declared tanks: {asset.tanks.map((tank) => tank.tank_name).join(', ') || 'none'}
            </span>
          </div>

          {preview && (
            <div style={{ marginTop: 16 }}>
              <Alert
                tone={preview.invalid_rows ? 'warning' : 'success'}
                icon={preview.invalid_rows ? 'alertTriangle' : 'checkCircle'}
              >
                {preview.message}
                {preview.total_rows > 0 && (
                  <span>
                    {' '}
                    · {preview.valid_rows} valid · {preview.invalid_rows} invalid · layout{' '}
                    {preview.layout}
                  </span>
                )}
              </Alert>
              {preview.missing_columns?.length > 0 && (
                <p className="field-error" style={{ marginTop: 8 }}>
                  Missing columns: {preview.missing_columns.join(', ')}
                </p>
              )}
              {preview.tanks_without_rows?.length > 0 && (
                <p className="field-help" style={{ marginTop: 8 }}>
                  Tanks with no calibration rows: {preview.tanks_without_rows.join(', ')}
                </p>
              )}
              {preview.warnings?.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  {preview.warnings.map((warning) => (
                    <p className="field-help" key={warning}>
                      <Icon name="alertTriangle" size={13} /> {warning}
                    </p>
                  ))}
                </div>
              )}
              {preview.rows?.length > 0 && (
                <div className="table-wrap" style={{ marginTop: 12, maxHeight: 320 }}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Row</th>
                        <th>Tank</th>
                        <th>
                          Dip/Ullage ({preview.declared_units?.dip_unit})
                        </th>
                        <th>
                          Volume ({preview.declared_units?.volume_unit})
                        </th>
                        <th>Depth (cm)</th>
                        <th>Volume (bbl)</th>
                        <th>Validation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewRows.map((row, index) => (
                        // eslint-disable-next-line react/no-array-index-key
                        <tr key={`${row.row_number}-${row.tank_name}-${index}`}>
                          <td>{row.row_number}</td>
                          <td>{row.tank_name || '—'}</td>
                          <td className="tnum">{String(row.dip_value ?? '—')}</td>
                          <td className="tnum">{String(row.volume_value ?? '—')}</td>
                          <td className="tnum">{row.dip_cm ?? '—'}</td>
                          <td className="tnum">{row.volume_bbl ?? '—'}</td>
                          <td>
                            {row.valid ? (
                              <span className="tag tag-success">Valid</span>
                            ) : (
                              <span className="field-error">{(row.errors || []).join('; ')}</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {preview.total_rows > previewRows.length && (
                <p className="field-help" style={{ marginTop: 6 }}>
                  Showing the first {previewRows.length.toLocaleString()} of{' '}
                  {preview.total_rows.toLocaleString()} rows — every row in the file was validated,
                  and the whole chart is saved.
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
            onClick={runPreview}
            disabled={busy || !file}
          >
            <Icon name="eye" size={15} /> {busy && !canCommit ? 'Checking…' : 'Preview chart'}
          </button>
          <button type="button" className="btn btn-primary" onClick={commit} disabled={!canCommit}>
            <Icon name="upload" size={15} />
            {busy && canCommit ? 'Saving…' : `Save ${preview?.valid_rows || 0} points`}
          </button>
        </div>
      </div>
    </div>
  )
}

function LookupPanel({ asset, chart }) {
  const [tankName, setTankName] = useState(chart?.tank_point_counts?.[0]?.tank_name || '')
  const [dipUnit, setDipUnit] = useState(asset.dip_unit || 'cm')
  const [volumeUnit, setVolumeUnit] = useState(asset.volume_unit || 'bbl')
  const [allowClamping, setAllowClamping] = useState(false)
  const [input, setInput] = useState('')
  const [results, setResults] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const tanks = chart?.tank_point_counts || []

  useEffect(() => {
    if (!tankName && tanks.length) setTankName(tanks[0].tank_name)
  }, [tankName, tanks])

  const resolve = async () => {
    const values = input
      .split(/[\s,;]+/)
      .map((value) => value.trim())
      .filter(Boolean)
      .map(Number)
    if (!tankName) {
      setError('Choose a tank first.')
      return
    }
    if (!values.length || values.some((value) => Number.isNaN(value) || value < 0)) {
      setError('Enter one or more non-negative readings, separated by spaces or commas.')
      return
    }
    setBusy(true)
    setError('')
    setResults(null)
    try {
      setResults(
        await lookupVolumeBatch(asset.id, {
          tank_name: tankName,
          dip_values: values,
          dip_unit: dipUnit,
          volume_unit: volumeUnit,
          allow_clamping: allowClamping,
        }),
      )
      logUiAction('Asset Calibration', 'Interpolate Volume', {
        asset: asset.asset_code,
        tank: tankName,
        readings: values.length,
      })
    } catch (lookupError) {
      setError(lookupError.message || 'Unable to resolve the readings')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h2 className="card-title">Dip to volume</h2>
          <p className="card-subtitle">
            Enter one or more {chart?.measurement_basis?.toLowerCase() || 'dip'} readings. The tank
            is resolved exactly, then the depth curve is interpolated. Anything outside the
            certified range is reported rather than guessed.
          </p>
        </div>
      </div>
      <div className="card-body">
        {error && <Alert tone="danger">{error}</Alert>}
        <div className="filters-grid" style={{ marginTop: error ? 12 : 0 }}>
          <label className="field">
            <span className="field-label">Tank</span>
            <select className="select" value={tankName} onChange={(event) => setTankName(event.target.value)}>
              <option value="">Select a tank</option>
              {tanks.map((tank) => (
                <option key={tank.tank_name} value={tank.tank_name}>
                  {tank.tank_name} ({tank.points} points)
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Reading unit</span>
            <select className="select" value={dipUnit} onChange={(event) => setDipUnit(event.target.value)}>
              <option value="cm">Centimetres (cm)</option>
              <option value="mm">Millimetres (mm)</option>
              <option value="m">Metres (m)</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">Result unit</span>
            <select
              className="select"
              value={volumeUnit}
              onChange={(event) => setVolumeUnit(event.target.value)}
            >
              <option value="bbl">Barrels (bbl)</option>
              <option value="l">Litres (L)</option>
              <option value="kl">Kilolitres (kL)</option>
            </select>
          </label>
          <label className="field" style={{ gridColumn: '1 / -1' }}>
            <span className="field-label">
              {chart?.measurement_basis || 'Dip'} readings ({dipUnit})
            </span>
            <input
              className="input"
              value={input}
              placeholder="e.g. 125, 180, 240"
              onChange={(event) => setInput(event.target.value)}
            />
            <span className="field-help">Separate several readings with spaces, commas or semicolons.</span>
          </label>
          <label className="role-option" style={{ gridColumn: '1 / -1' }}>
            <input
              type="checkbox"
              checked={allowClamping}
              onChange={(event) => setAllowClamping(event.target.checked)}
            />
            <span>
              <strong>Hold the end volume for a reading just outside the chart</strong>
              <small>
                Off by default. A reading more than 5 cm outside the certified range is refused
                either way.
              </small>
            </span>
          </label>
        </div>
        <div className="filter-actions">
          <button type="button" className="btn btn-primary btn-compact" onClick={resolve} disabled={busy}>
            <Icon name="barChart" size={15} /> {busy ? 'Resolving…' : 'Resolve volumes'}
          </button>
        </div>

        {results && (
          <div style={{ marginTop: 14 }}>
            <Alert tone={results.failed ? 'warning' : 'success'} icon={results.failed ? 'alertTriangle' : 'checkCircle'}>
              {results.resolved} of {results.requested} reading(s) resolved against “{results.chart_name}”.
              {results.failed > 0 && <span> {results.failed} could not be resolved.</span>}
            </Alert>
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>
                      {results.measurement_basis} ({dipUnit})
                    </th>
                    <th>Depth (cm)</th>
                    <th>Volume (bbl)</th>
                    <th>
                      Volume ({volumeUnit})
                    </th>
                    <th>Method</th>
                    <th>Bracketing points</th>
                  </tr>
                </thead>
                <tbody>
                  {results.results.map((row, index) => (
                    // eslint-disable-next-line react/no-array-index-key
                    <tr key={`${row.dip_value}-${index}`}>
                      <td className="tnum">{row.dip_value}</td>
                      <td className="tnum">{row.dip_cm ?? '—'}</td>
                      <td className="tnum">{row.error ? '—' : row.volume_bbl}</td>
                      <td className="tnum">{row.error ? '—' : row.volume_display}</td>
                      <td>
                        {row.error ? (
                          <span className="field-error">{row.error}</span>
                        ) : (
                          <StatusTag
                            status={row.method}
                            tone={row.in_range ? 'success' : 'warning'}
                          />
                        )}
                      </td>
                      <td className="muted small">
                        {row.error
                          ? '—'
                          : `${row.lower_point ? `${row.lower_point.dip_cm} cm → ${row.lower_point.volume_bbl} bbl` : 'below chart'} · ${
                              row.upper_point
                                ? `${row.upper_point.dip_cm} cm → ${row.upper_point.volume_bbl} bbl`
                                : 'above chart'
                            }`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {results.results.some((row) => row.warnings?.length) && (
              <div style={{ marginTop: 10 }}>
                {results.results.flatMap((row) => row.warnings || []).map((warning) => (
                  <p className="field-help" key={warning}>
                    <Icon name="alertTriangle" size={13} /> {warning}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

export default function AssetCalibration() {
  const { isAdmin, hasPermission } = usePermissions()
  const canUpdate = isAdmin || hasPermission('assets:update')
  const canDelete = isAdmin || hasPermission('assets:delete')
  const [searchParams] = useSearchParams()

  const [assets, setAssets] = useState([])
  const [assetId, setAssetId] = useState(searchParams.get('asset') || '')
  const [reference, setReference] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [showUpload, setShowUpload] = useState(false)
  const [exporting, setExporting] = useState('')

  useEffect(() => {
    let active = true
    Promise.all([
      listAssets({ page: 1, page_size: 200, calibration_required: true, status: 'Active' }),
      getAssetReference(),
    ])
      .then(([assetPage, referencePayload]) => {
        if (!active) return
        setAssets(assetPage.items || [])
        setReference(referencePayload)
        if (!assetId && assetPage.items?.length) setAssetId(String(assetPage.items[0].id))
      })
      .catch((loadError) => {
        if (active) setError(loadError.message || 'Unable to load assets')
      })
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const load = useCallback(async () => {
    if (!assetId) {
      setData(null)
      return
    }
    setLoading(true)
    setError('')
    try {
      // Rows are not rendered on this page — only the point counts, the tank
      // breakdown and the lookups are. A chart can hold tens of thousands of
      // points, so asking for them would download the whole table for nothing.
      setData(await getCalibration(assetId, false))
    } catch (loadError) {
      setError(loadError.message || 'Unable to load the calibration chart')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [assetId])

  useEffect(() => {
    load()
  }, [load])

  const asset = data
    ? {
        id: data.asset_id,
        asset_code: data.asset_code,
        asset_name: data.asset_name,
        dip_unit: data.asset_dip_unit,
        volume_unit: data.asset_volume_unit,
        tanks: data.tanks,
      }
    : null
  const chart = data?.chart || null

  const exportChart = async (format) => {
    setExporting(format)
    setError('')
    try {
      await downloadCalibrationExport(assetId, format)
    } catch (exportError) {
      setError(exportError.message || 'Export failed')
    } finally {
      setExporting('')
    }
  }

  const removeChart = async () => {
    if (!window.confirm('Delete this calibration chart? The asset will have no chart until you upload another.')) return
    setError('')
    try {
      await deleteCalibration(assetId)
      setNotice('Calibration chart deleted.')
      load()
    } catch (deleteError) {
      setError(deleteError.message || 'Unable to delete the chart')
    }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="MASTER DATA / ASSET CALIBRATION"
        title="Asset Calibration"
        description="Upload a three-column calibration chart — tank name, dip/ullage, volume — in any accepted unit, then resolve readings to volumes in canonical cm and bbl."
        actions={
          <>
            <Link to="/assets" className="btn btn-secondary">
              <Icon name="database" size={15} /> Asset Master
            </Link>
            <button type="button" className="btn btn-secondary" onClick={load} disabled={loading || !assetId}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </>
        }
      />
      {error && <Alert tone="danger">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}

      <section className="card">
        <div className="card-body">
          <div className="filters-grid">
            <label className="field">
              <span className="field-label">Asset</span>
              <select
                className="select"
                value={assetId}
                onChange={(event) => {
                  setAssetId(event.target.value)
                  setNotice('')
                }}
              >
                <option value="">Select an asset</option>
                {assets.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.asset_name} ({item.asset_code}) — {item.asset_type_name}
                  </option>
                ))}
              </select>
              <span className="field-help">Only assets that require calibration are listed.</span>
            </label>
            {chart && (
              <>
                <label className="field">
                  <span className="field-label">Basis</span>
                  <input className="input" value={chart.measurement_basis} readOnly />
                </label>
                <label className="field">
                  <span className="field-label">Source units</span>
                  <input
                    className="input"
                    value={`${chart.source_dip_unit} → cm, ${chart.source_volume_unit} → bbl`}
                    readOnly
                  />
                </label>
                <label className="field">
                  <span className="field-label">Chart</span>
                  <input className="input" value={chart.chart_name} readOnly />
                </label>
              </>
            )}
          </div>
          <div className="filter-actions">
            {asset && canUpdate && (
              <button
                type="button"
                className="btn btn-primary btn-compact"
                onClick={() => {
                  setShowUpload(true)
                  setNotice('')
                }}
              >
                <Icon name="upload" size={15} /> {chart ? 'Replace chart' : 'Upload chart'}
              </button>
            )}
            {chart && (
              <>
                <div className="toolbar-group" role="group" aria-label="Export chart">
                  <span className="muted small">Export</span>
                  {['csv', 'xlsx', 'pdf'].map((format) => (
                    <button
                      key={format}
                      type="button"
                      className="btn btn-secondary btn-compact"
                      onClick={() => exportChart(format)}
                      disabled={Boolean(exporting)}
                    >
                      <Icon name="download" size={14} />
                      {exporting === format ? 'Exporting…' : format.toUpperCase()}
                    </button>
                  ))}
                </div>
                {canDelete && (
                  <button type="button" className="btn btn-ghost btn-compact" onClick={removeChart}>
                    <Icon name="close" size={14} /> Delete chart
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      </section>

      {!assetId ? (
        <EmptyState
          title="Select an asset"
          description="Choose an asset above to view or upload its calibration chart."
        />
      ) : loading ? (
        <Loading label="Loading calibration chart…" />
      ) : (
        asset && (
          <>
            <section className="card">
              <div className="card-head">
                <div>
                  <h2 className="card-title">Chart coverage</h2>
                  <p className="card-subtitle">
                    {chart
                      ? `${chart.row_count} calibration points across ${chart.tank_point_counts.length} tank(s). Uploaded ${formatDateTime(chart.updated_at)} from ${chart.source_file_name || 'manual entry'}.`
                      : 'No chart uploaded yet for this asset.'}
                  </p>
                </div>
              </div>
              <div className="card-body">
                {!chart && data?.tanks?.length > 0 && (
                  <Alert tone="info">
                    Declared tanks awaiting a chart: {data.tanks.map((tank) => tank.tank_name).join(', ')}
                  </Alert>
                )}
                {chart?.effective_date && (
                  <p className="muted small">
                    Effective {formatDate(chart.effective_date)}
                    {chart.remarks ? ` · ${chart.remarks}` : ''}
                  </p>
                )}
                {data?.tank_curves?.length > 0 && (
                  <div className="table-wrap" style={{ marginTop: 12 }}>
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Tank</th>
                          <th>Points</th>
                          <th>Depth range (cm)</th>
                          <th>Volume range (bbl)</th>
                          <th>Chart check</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.tank_curves.map((curve) => (
                          <tr key={curve.tank_name}>
                            <td className="cell-primary">{curve.tank_name}</td>
                            <td className="tnum">{curve.points}</td>
                            <td className="tnum">
                              {curve.min_dip_cm} – {curve.max_dip_cm}
                            </td>
                            <td className="tnum">
                              {curve.min_volume_bbl} – {curve.max_volume_bbl}
                            </td>
                            <td>
                              {curve.warnings?.length ? (
                                <span className="field-error">{curve.warnings.join('; ')}</span>
                              ) : (
                                <span className="tag tag-success">Monotonic</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {data?.tanks_without_rows?.length > 0 && (
                  <p className="field-help" style={{ marginTop: 8 }}>
                    Tanks with no calibration rows: {data.tanks_without_rows.join(', ')}
                  </p>
                )}
              </div>
            </section>

            {chart ? (
              <LookupPanel asset={asset} chart={chart} />
            ) : (
              <EmptyState
                title="No calibration chart"
                description="Upload a three-column chart to start resolving readings for this asset."
              />
            )}
          </>
        )
      )}

      {showUpload && asset && (
        <UploadDialog
          asset={asset}
          reference={reference}
          onClose={() => setShowUpload(false)}
          onUploaded={(result) => {
            setShowUpload(false)
            setNotice(result.message || 'Calibration chart saved')
            load()
          }}
        />
      )}
    </div>
  )
}
