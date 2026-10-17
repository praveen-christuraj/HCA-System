import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  applyPermissionPreset,
  createPermissionPreset,
  deactivatePermissionPreset,
  deletePermissionPresetPermanently,
  downloadPermissionPresetsExport,
  getPermissionPreset,
  importPermissionPresetsFile,
  listPermissionPresets,
  PRESET_IMPORT_TEMPLATE,
  updatePermissionPreset,
} from '../api/permissionPresetsApi'
import { getPermissionCatalog, getRolePermissions, listRoles } from '../api/rolesApi'
import Icon from '../components/common/Icon'
import ConfirmDialog from '../components/common/ConfirmDialog'
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
  module_name: '',
  permission_id: '',
  date_from: '',
  date_to: '',
}

const isReservedRole = (role) =>
  Boolean(role?.is_reserved) || String(role?.role_name || '').trim().toLowerCase() === 'admin'

/** Shared permission picker: the catalog grouped category → module → permission. */
function PermissionPicker({ catalog, selectedIds, onToggle, onToggleModule, disabled, totalSelected, totalAvailable, onClear }) {
  return (
    <div className="preset-picker">
      <div className="preset-picker-toolbar">
        <span className="muted small">
          {totalSelected} of {totalAvailable} standard permissions selected
        </span>
        <div className="toolbar-group">
          <button type="button" className="btn btn-ghost btn-compact" onClick={onClear} disabled={disabled || totalSelected === 0}>
            <Icon name="close" size={13} /> Clear
          </button>
        </div>
      </div>
      <div className="permission-modules">
        {catalog.map((category) => (
          <div className="permission-category" key={category.category}>
            <div className="permission-category-title">{category.category}</div>
            {category.modules.map((module) => {
              const permissions = module.permissions || []
              const ids = permissions.map((permission) => permission.id)
              const allSelected = ids.length > 0 && ids.every((id) => selectedIds.includes(id))
              const someSelected = ids.some((id) => selectedIds.includes(id))
              return (
                <section key={`${category.category}-${module.module_name}`} className="permission-module">
                  <div className="permission-module-head">
                    <div>
                      <h3>{module.module_name}</h3>
                      <span className="muted small">{permissions.length} standard permissions</span>
                    </div>
                    <label className="checkbox-inline">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        ref={(element) => { if (element) element.indeterminate = someSelected && !allSelected }}
                        disabled={disabled}
                        onChange={() => onToggleModule(ids)}
                      />
                      <span>Select all</span>
                    </label>
                  </div>
                  <div className="permission-list">
                    {permissions.map((permission) => (
                      <label
                        key={permission.id}
                        className={`permission-option ${selectedIds.includes(permission.id) ? 'is-checked' : ''}`}
                      >
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(permission.id)}
                          disabled={disabled}
                          onChange={() => onToggle(permission.id)}
                        />
                        <span className="permission-copy">
                          <strong>{permission.permission_name}</strong>
                          <small>{permission.description}</small>
                        </span>
                        <span className="permission-action-tag">{permission.action}</span>
                      </label>
                    ))}
                  </div>
                </section>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

function PresetDialog({ preset, catalog, roles, onClose, onSaved }) {
  const [form, setForm] = useState({
    preset_name: preset?.preset_name || '',
    description: preset?.description || '',
    status: preset?.status || 'Active',
  })
  const [selectedIds, setSelectedIds] = useState([])
  const [loadingDetail, setLoadingDetail] = useState(Boolean(preset))
  const [droppedCount, setDroppedCount] = useState(0)
  const [sourceRoleId, setSourceRoleId] = useState('')
  const [dialogNotice, setDialogNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [fieldError, setFieldError] = useState('')

  const allPermissions = useMemo(
    () => catalog.flatMap((category) => category.modules.flatMap((module) => module.permissions || [])),
    [catalog],
  )
  const roleOptions = useMemo(
    () => roles.filter((role) => role.status === 'Active' && !isReservedRole(role)),
    [roles],
  )

  useEffect(() => {
    if (!preset) return undefined
    let active = true
    setLoadingDetail(true)
    getPermissionPreset(preset.id)
      .then((detail) => {
        if (!active) return
        // Only still-active permissions can be saved back, so the picker opens
        // with those and the dropped ones are reported instead of failing later.
        setSelectedIds(detail.active_permission_ids || [])
        setDroppedCount(detail.inactive_permission_count || 0)
        setForm({
          preset_name: detail.preset_name || '',
          description: detail.description || '',
          status: detail.status || 'Active',
        })
      })
      .catch((loadError) => {
        if (active) setError(loadError.message || 'Unable to load this preset')
      })
      .finally(() => { if (active) setLoadingDetail(false) })
    return () => { active = false }
  }, [preset])

  const togglePermission = (id) =>
    setSelectedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]))

  const toggleModule = (ids) => {
    const allSelected = ids.every((id) => selectedIds.includes(id))
    setSelectedIds((current) =>
      allSelected ? current.filter((id) => !ids.includes(id)) : [...new Set([...current, ...ids])],
    )
  }

  const loadFromRole = async (roleId) => {
    setSourceRoleId(roleId)
    setDialogNotice('')
    setError('')
    if (!roleId) return
    try {
      const detail = await getRolePermissions(roleId)
      const ids = detail.permission_ids || []
      setSelectedIds(ids)
      const role = roles.find((item) => String(item.id) === String(roleId))
      setDialogNotice(`Loaded ${ids.length} permission(s) from ${role?.role_name || 'the selected role'}.`)
    } catch (loadError) {
      setError(loadError.message || 'Unable to load the permissions of that role')
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    if (selectedIds.length === 0) {
      setFieldError('Select at least one permission — an empty preset could strip a role\'s access.')
      return
    }
    setFieldError('')
    setBusy(true)
    setError('')
    const payload = {
      preset_name: form.preset_name.trim(),
      description: form.description.trim() || null,
      status: form.status,
      permission_ids: selectedIds,
    }
    try {
      const result = preset
        ? await updatePermissionPreset(preset.id, payload)
        : await createPermissionPreset(payload)
      onSaved(result, preset ? 'Preset updated successfully' : 'Preset created successfully')
    } catch (saveError) {
      setError(saveError.message || 'Unable to save the preset')
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
        aria-labelledby="preset-dialog-title"
        onSubmit={submit}
      >
        <div className="dialog-head">
          <h2 id="preset-dialog-title" className="dialog-title">
            {preset ? 'Edit permission preset' : 'Create permission preset'}
          </h2>
          <p className="dialog-subtitle">
            Name a reusable set of standard permissions, then apply it to any number of roles instead of
            ticking permissions one by one.
          </p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          {dialogNotice && <Alert tone="success" icon="checkCircle">{dialogNotice}</Alert>}
          {droppedCount > 0 && (
            <Alert tone="warning" icon="alertTriangle">
              {droppedCount} permission(s) in this preset are no longer active in the catalog. They are excluded
              below and will be dropped when you save.
            </Alert>
          )}
          {loadingDetail ? <Loading label="Loading preset…" /> : (
            <>
              <div className="form-grid-2" style={{ marginTop: error || dialogNotice || droppedCount ? 14 : 0 }}>
                <label className="field">
                  <span className="field-label">Preset name</span>
                  <input
                    className="input"
                    required
                    minLength={2}
                    maxLength={120}
                    autoFocus
                    value={form.preset_name}
                    onChange={(event) => setForm({ ...form, preset_name: event.target.value })}
                    placeholder="Terminal Operations Read"
                  />
                  <span className="field-help">Shown in the preset list and in the audit trail.</span>
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
                  <span className="field-help">Only active presets can be applied to roles.</span>
                </label>
                <label className="field" style={{ gridColumn: '1 / -1' }}>
                  <span className="field-label">Description</span>
                  <textarea
                    className="textarea"
                    maxLength={500}
                    value={form.description}
                    onChange={(event) => setForm({ ...form, description: event.target.value })}
                    placeholder="What this preset is for, and which roles usually receive it"
                  />
                </label>
                <label className="field">
                  <span className="field-label">Load permissions from a role</span>
                  <select
                    className="select"
                    value={sourceRoleId}
                    onChange={(event) => loadFromRole(event.target.value)}
                  >
                    <option value="">Start from an empty selection</option>
                    {roleOptions.map((role) => (
                      <option key={role.id} value={role.id}>
                        {role.role_name} ({role.permission_count || 0} permissions)
                      </option>
                    ))}
                  </select>
                  <span className="field-help">Copies that role's current grants into the picker below.</span>
                </label>
              </div>

              <div className="form-section">
                <div className="assignment-select-all">
                  <div>
                    <h3 className="dialog-section-title">Permissions in this preset</h3>
                    <p className="muted small">
                      {selectedIds.length} selected · {allPermissions.length - selectedIds.length} remaining
                    </p>
                  </div>
                </div>
                {fieldError && <p className="field-error" role="alert">{fieldError}</p>}
                <PermissionPicker
                  catalog={catalog}
                  selectedIds={selectedIds}
                  onToggle={togglePermission}
                  onToggleModule={toggleModule}
                  onClear={() => setSelectedIds([])}
                  disabled={busy}
                  totalSelected={selectedIds.length}
                  totalAvailable={allPermissions.length}
                />
              </div>
            </>
          )}
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || loadingDetail}>
            <Icon name="checkCircle" size={15} /> {busy ? 'Saving…' : preset ? 'Save changes' : 'Create preset'}
          </button>
        </div>
      </form>
    </div>
  )
}

function ApplyPresetDialog({ preset, roles, onClose, onApplied }) {
  const [mode, setMode] = useState('replace')
  const [selectedRoleIds, setSelectedRoleIds] = useState([])
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [fieldError, setFieldError] = useState('')

  const eligible = useMemo(
    () => roles.filter((role) => role.status === 'Active' && !isReservedRole(role)),
    [roles],
  )
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return eligible
    return eligible.filter(
      (role) =>
        String(role.role_name || '').toLowerCase().includes(term) ||
        String(role.description || '').toLowerCase().includes(term),
    )
  }, [eligible, search])

  const toggleRole = (roleId) =>
    setSelectedRoleIds((current) =>
      current.includes(roleId) ? current.filter((id) => id !== roleId) : [...current, roleId],
    )

  const selectAllFiltered = () => {
    const ids = filtered.map((role) => role.id)
    const allSelected = ids.length > 0 && ids.every((id) => selectedRoleIds.includes(id))
    setSelectedRoleIds((current) =>
      allSelected ? current.filter((id) => !ids.includes(id)) : [...new Set([...current, ...ids])],
    )
  }

  const submit = async (event) => {
    event.preventDefault()
    if (selectedRoleIds.length === 0) {
      setFieldError('Select at least one role to receive this preset.')
      return
    }
    setFieldError('')
    setBusy(true)
    setError('')
    try {
      const result = await applyPermissionPreset(preset.id, selectedRoleIds, mode)
      onApplied(result)
    } catch (applyError) {
      setError(applyError.message || 'Unable to apply the preset')
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
        aria-labelledby="apply-preset-title"
        onSubmit={submit}
      >
        <div className="dialog-head">
          <h2 id="apply-preset-title" className="dialog-title">Apply “{preset.preset_name}” to roles</h2>
          <p className="dialog-subtitle">
            {preset.permission_count} permission(s) across {preset.module_count} module(s). Every role you
            select is updated in one audited action.
          </p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          {mode === 'replace' && (
            <Alert tone="warning" icon="alertTriangle">
              Replace sets each selected role's grants to exactly this preset — permissions the role holds
              that are not in the preset are removed.
            </Alert>
          )}
          <div className="form-section" style={{ marginTop: 14 }}>
            <span className="field-label">Apply mode</span>
            <div className="preset-mode-grid">
              <label className="preset-mode-option">
                <input type="radio" name="apply-mode" value="replace" checked={mode === 'replace'} onChange={() => setMode('replace')} />
                <span className="preset-mode-copy">
                  <strong>Replace</strong>
                  <small>Role ends up with exactly the preset's permissions.</small>
                </span>
              </label>
              <label className="preset-mode-option">
                <input type="radio" name="apply-mode" value="add" checked={mode === 'add'} onChange={() => setMode('add')} />
                <span className="preset-mode-copy">
                  <strong>Add</strong>
                  <small>Preset permissions are merged in; nothing is removed.</small>
                </span>
              </label>
            </div>
          </div>

          <div className="form-section">
            <div className="assignment-select-all">
              <div>
                <h3 className="dialog-section-title">Roles</h3>
                <p className="muted small">
                  {selectedRoleIds.length} selected · {eligible.length} eligible (active, not the reserved Admin role)
                </p>
              </div>
              <div className="toolbar-group">
                <div className="search-field">
                  <Icon name="search" size={14} className="search-icon" />
                  <input
                    className="input"
                    type="search"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search roles"
                    aria-label="Search roles to apply this preset to"
                  />
                </div>
                <button type="button" className="btn btn-secondary btn-compact" onClick={selectAllFiltered} disabled={filtered.length === 0}>
                  {filtered.length > 0 && filtered.every((role) => selectedRoleIds.includes(role.id)) ? 'Clear listed' : 'Select listed'}
                </button>
              </div>
            </div>
            {fieldError && <p className="field-error" role="alert">{fieldError}</p>}
            {eligible.length === 0 ? (
              <EmptyState title="No role can receive this preset" description="Create an active role in Role Master first. The reserved Admin role always holds the full catalog." />
            ) : (
              <div className="preset-role-scroll">
                <div className="role-options">
                  {filtered.map((role) => (
                    <label className="role-option" key={role.id}>
                      <input
                        type="checkbox"
                        checked={selectedRoleIds.includes(role.id)}
                        onChange={() => toggleRole(role.id)}
                        disabled={busy}
                      />
                      <span>
                        <strong>{role.role_name}</strong>
                        <small>{role.permission_count || 0} permissions · {role.user_count || 0} users</small>
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || selectedRoleIds.length === 0}>
            <Icon name="shieldCheck" size={15} />
            {busy ? 'Applying…' : `Apply to ${selectedRoleIds.length || 0} role(s)`}
          </button>
        </div>
      </form>
    </div>
  )
}

export default function PermissionPresets() {
  const { isAdmin, hasPermission } = usePermissions()
  const canCreate = isAdmin || hasPermission('permission_presets:create')
  const canUpdate = isAdmin || hasPermission('permission_presets:update')
  const canDelete = isAdmin || hasPermission('permission_presets:delete')
  const canApply = isAdmin || hasPermission('assignments:write')
  const canOpenAssignments = isAdmin || (hasPermission('roles:read') && hasPermission('permissions:read'))
  // Building a preset needs the permission catalog; applying one needs the role
  // list. Both are separate standard capabilities, so each is loaded only when
  // the user holds it and a gap is reported instead of failing silently.
  const canReadCatalog = isAdmin || hasPermission('permissions:read')
  const canReadRoles = isAdmin || hasPermission('roles:read')

  const [draft, setDraft] = useState(EMPTY_FILTERS)
  const [applied, setApplied] = useState(EMPTY_FILTERS)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [data, setData] = useState({ items: [], total: 0, pages: 0, preset_limit: 20, presets_used: 0, presets_remaining: 20 })
  const [catalog, setCatalog] = useState([])
  const [roles, setRoles] = useState([])
  const [referenceWarning, setReferenceWarning] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [exporting, setExporting] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [dialogPreset, setDialogPreset] = useState(undefined)
  const [applyPreset, setApplyPreset] = useState(null)
  const [deletePreset, setDeletePreset] = useState(null)
  const [deleteBusy, setDeleteBusy] = useState(false)

  const permissionOptions = useMemo(
    () =>
      catalog.flatMap((category) =>
        category.modules.flatMap((module) =>
          (module.permissions || []).map((permission) => ({
            id: permission.id,
            label: `${permission.permission_name} — ${module.module_name}`,
          })),
        ),
      ),
    [catalog],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await listPermissionPresets({ ...applied, page, page_size: pageSize }))
    } catch (loadError) {
      setError(loadError.message || 'Unable to load permission presets')
      setData({ items: [], total: 0, pages: 0, preset_limit: 20, presets_used: 0, presets_remaining: 20 })
    } finally {
      setLoading(false)
    }
  }, [applied, page, pageSize])

  const loadReferences = useCallback(async () => {
    const gaps = []
    if (canReadCatalog) {
      try {
        const catalogResponse = await getPermissionCatalog()
        setCatalog(catalogResponse.categories || [])
      } catch (catalogError) {
        setCatalog([])
        gaps.push('permission catalog')
      }
    } else {
      setCatalog([])
      gaps.push('permission catalog (needs permissions:read)')
    }
    if (canReadRoles) {
      try {
        const roleResponse = await listRoles({ page: 1, page_size: 200 })
        setRoles(roleResponse.items || [])
      } catch (roleError) {
        setRoles([])
        gaps.push('role list')
      }
    } else {
      setRoles([])
      gaps.push('role list (needs roles:read)')
    }
    setReferenceWarning(
      gaps.length
        ? `Not available for your account: ${gaps.join(', ')}. Presets can still be listed, applied and exported where the missing data is not required.`
        : '',
    )
  }, [canReadCatalog, canReadRoles])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadReferences() }, [loadReferences])

  const activeChips = useMemo(() => [
    ...(applied.search ? [{ key: 'search', label: `Search: ${applied.search}` }] : []),
    ...(applied.status ? [{ key: 'status', label: `Status: ${applied.status}` }] : []),
    ...(applied.module_name ? [{ key: 'module_name', label: `Module: ${applied.module_name}` }] : []),
    ...(applied.permission_id
      ? [{
        key: 'permission_id',
        label: `Contains: ${permissionOptions.find((option) => String(option.id) === String(applied.permission_id))?.label || applied.permission_id}`,
      }]
      : []),
    ...(applied.date_from ? [{ key: 'date_from', label: `Created from: ${applied.date_from}` }] : []),
    ...(applied.date_to ? [{ key: 'date_to', label: `Created to: ${applied.date_to}` }] : []),
  ], [applied, permissionOptions])

  const applyFilters = () => { setApplied({ ...draft }); setPage(1); logUiAction('Permission Presets', 'Apply Filter') }
  const resetFilters = () => { setDraft(EMPTY_FILTERS); setApplied(EMPTY_FILTERS); setPage(1); logUiAction('Permission Presets', 'Reset Filter') }
  const removeChip = (key) => { const next = { ...applied, [key]: '' }; setApplied(next); setDraft(next); setPage(1) }

  const exportRows = async (format) => {
    setExporting(format)
    setError('')
    try {
      await downloadPermissionPresetsExport(format, applied)
    } catch (exportError) {
      setError(exportError.message || 'Export failed')
    } finally {
      setExporting('')
    }
  }

  const handleDeactivate = async (preset) => {
    setError('')
    setDeleteBusy(true)
    try {
      await deactivatePermissionPreset(preset.id)
      setNotice(`“${preset.preset_name}” was deactivated. It still occupies a preset slot and can be reactivated.`)
      logUiAction('Permission Presets', 'Deactivate Preset', { preset_id: preset.id })
      load()
    } catch (deactivateError) {
      setError(deactivateError.message || 'Unable to deactivate the preset')
    } finally {
      setDeleteBusy(false)
    }
  }

  const confirmPermanentDelete = async () => {
    if (!deletePreset) return
    setError('')
    setDeleteBusy(true)
    try {
      await deletePermissionPresetPermanently(deletePreset.id)
      setNotice(`“${deletePreset.preset_name}” was deleted and its preset slot freed.`)
      logUiAction('Permission Presets', 'Delete Preset', { preset_id: deletePreset.id })
      setDeletePreset(null)
      load()
    } catch (permanentError) {
      setError(permanentError.message || 'Unable to delete the preset')
      setDeletePreset(null)
    } finally {
      setDeleteBusy(false)
    }
  }

  const limit = data.preset_limit || 20
  const used = data.presets_used || 0
  const remaining = data.presets_remaining ?? Math.max(limit - used, 0)
  const limitReached = remaining <= 0
  // A preset cannot be composed without the permission catalog.
  const canBuildPreset = canCreate && catalog.length > 0

  return (
    <div className="page">
      <PageHead
        eyebrow="USER MANAGEMENT / PERMISSION PRESETS"
        title="Permission Presets"
        description="Save a named set of standard permissions once, then apply it to one role or many — in replace or add mode — instead of ticking every permission for every role."
        actions={
          <>
            {canOpenAssignments && (
              <Link to="/role-permissions" className="btn btn-secondary">
                <Icon name="shieldCheck" size={15} /> Role permissions
              </Link>
            )}
            {canCreate && (
              <button type="button" className="btn btn-secondary" onClick={() => { setNotice(''); setShowImport(true) }}>
                <Icon name="upload" size={15} /> Import
              </button>
            )}
            <div className="toolbar-group" role="group" aria-label="Export permission presets">
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
            {canCreate && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => { setNotice(''); setDialogPreset(null) }}
                disabled={limitReached || !canBuildPreset}
                title={
                  limitReached
                    ? `Preset limit of ${limit} reached`
                    : !canBuildPreset
                      ? 'The permission catalog is not available to your account'
                      : 'Create a permission preset'
                }
              >
                <Icon name="layers" size={15} /> New preset
              </button>
            )}
            <button type="button" className="btn btn-secondary" onClick={() => { load(); loadReferences() }} disabled={loading}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </>
        }
      />

      {error && <Alert tone="danger">{error}</Alert>}
      {notice && <Alert tone="success" icon="checkCircle">{notice}</Alert>}
      {referenceWarning && <Alert tone="warning" icon="alertTriangle">{referenceWarning}</Alert>}
      {limitReached && (
        <Alert tone="warning" icon="alertTriangle">
          Preset limit reached — {used} of {limit} presets are saved. Rename or reuse an existing preset, or
          permanently delete a preset that has never been applied to free a slot.
        </Alert>
      )}

      <section className="card">
        <div className="toolbar">
          <div className="toolbar-group">
            <form className="toolbar-group" onSubmit={(event) => { event.preventDefault(); applyFilters() }}>
              <div className="search-field">
                <Icon name="search" size={15} className="search-icon" />
                <input
                  className="input"
                  type="search"
                  value={draft.search}
                  onChange={(event) => setDraft({ ...draft, search: event.target.value })}
                  placeholder="Search preset name or description"
                  aria-label="Search permission presets"
                />
              </div>
              <button type="submit" className="btn btn-primary">Search</button>
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
          <span className="tag tag-info" aria-live="polite">{used} / {limit} presets</span>
        </div>

        <div className="filters-panel">
          {showAdvanced && (
            <div className="filters-grid">
              <label className="field">
                <span className="field-label">Status</span>
                <select className="select" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
                  <option value="">All statuses</option>
                  {(data.statuses || ['Active', 'Inactive']).map((status) => <option key={status} value={status}>{status}</option>)}
                </select>
              </label>
              <label className="field">
                <span className="field-label">Covers module</span>
                <select className="select" value={draft.module_name} onChange={(event) => setDraft({ ...draft, module_name: event.target.value })}>
                  <option value="">All modules</option>
                  {(data.modules || []).map((module) => <option key={module} value={module}>{module}</option>)}
                </select>
              </label>
              <label className="field">
                <span className="field-label">Contains permission</span>
                <select className="select" value={draft.permission_id} onChange={(event) => setDraft({ ...draft, permission_id: event.target.value })}>
                  <option value="">Any permission</option>
                  {permissionOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
            </div>
          )}
          <div className="date-group">
            <div className="date-group-title"><Icon name="calendar" size={14} /> Created date range</div>
            <div className="date-grid">
              <label className="field">
                <span className="field-label">From date</span>
                <input className="input" type="date" value={draft.date_from} onChange={(event) => setDraft({ ...draft, date_from: event.target.value })} />
              </label>
              <label className="field">
                <span className="field-label">To date</span>
                <input className="input" type="date" value={draft.date_to} onChange={(event) => setDraft({ ...draft, date_to: event.target.value })} />
              </label>
            </div>
          </div>
          <div className="filter-actions">
            <button type="button" className="btn btn-primary btn-compact" onClick={applyFilters}>Apply filters</button>
            <button type="button" className="btn btn-secondary btn-compact" onClick={resetFilters}>Reset</button>
            <span className="muted small">Date filters apply independently from general filters.</span>
          </div>
          {activeChips.length > 0 && (
            <div className="chip-row" aria-label="Active filters">
              {activeChips.map((chip) => (
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

        {loading ? <Loading label="Loading permission presets…" /> : data.items.length === 0 ? (
          <EmptyState
            title="No permission presets yet"
            description={limitReached
              ? 'Every preset slot is in use. Free a slot to save another preset.'
              : 'Create a preset to bundle the permissions a family of roles shares, then apply it in one action.'}
            action={canBuildPreset && !limitReached ? (
              <button type="button" className="btn btn-primary" onClick={() => setDialogPreset(null)}>
                <Icon name="layers" size={15} /> New preset
              </button>
            ) : undefined}
          />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Preset</th>
                    <th>Permissions</th>
                    <th>Applied</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((preset) => (
                    <tr key={preset.id}>
                      <td>
                        <div className="cell-primary">{preset.preset_name}</div>
                        <div className="cell-sub">{preset.description || 'No description'}</div>
                      </td>
                      <td>
                        <div>{preset.permission_count}</div>
                        <div className="preset-module-chips">
                          {preset.modules.slice(0, 3).map((module) => (
                            <span key={module} className="preset-module-chip">{module}</span>
                          ))}
                          {preset.modules.length > 3 && (
                            <span className="preset-module-chip">+{preset.modules.length - 3} more</span>
                          )}
                        </div>
                        {preset.inactive_permission_count > 0 && (
                          <div className="cell-sub">{preset.inactive_permission_count} deactivated permission(s) excluded</div>
                        )}
                      </td>
                      <td>
                        <div>{preset.times_applied}×</div>
                        <div className="cell-sub">{preset.last_applied_at ? formatDateTime(preset.last_applied_at) : 'Never applied'}</div>
                      </td>
                      <td><StatusTag status={preset.status} /></td>
                      <td className="nowrap">
                        <div>{formatDateTime(preset.created_at)}</div>
                        <div className="cell-sub">{preset.created_by_name || 'System'}</div>
                      </td>
                      <td>
                        <div className="table-actions">
                          {canApply && preset.status === 'Active' && preset.permission_count > 0 && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-compact"
                              onClick={() => { setNotice(''); setApplyPreset(preset) }}
                            >
                              <Icon name="shieldCheck" size={14} /> Apply
                            </button>
                          )}
                          {canUpdate && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-compact"
                              onClick={() => { setNotice(''); setDialogPreset(preset) }}
                            >
                              <Icon name="settings" size={14} /> Edit
                            </button>
                          )}
                          {canDelete && preset.status === 'Active' && (
                            <button type="button" className="btn btn-ghost btn-compact" onClick={() => handleDeactivate(preset)}>
                              <Icon name="close" size={14} /> Deactivate
                            </button>
                          )}
                          {canDelete && preset.times_applied === 0 && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-compact"
                              onClick={() => { setNotice(''); setError(''); setDeletePreset(preset) }}
                            >
                              <Icon name="archive" size={14} /> Delete
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
              onPageChange={(next) => { setPage(next); logUiAction('Permission Presets', 'Change Page', { page: next }) }}
              onPageSizeChange={(next) => { setPageSize(next); setPage(1); logUiAction('Permission Presets', 'Change Page Size', { page_size: next }) }}
              disabled={loading}
            />
          </>
        )}
      </section>

      {dialogPreset !== undefined && (
        <PresetDialog
          preset={dialogPreset}
          catalog={catalog}
          roles={roles}
          onClose={() => setDialogPreset(undefined)}
          onSaved={(result, message) => {
            setDialogPreset(undefined)
            setNotice(message)
            setPage(1)
            load()
          }}
        />
      )}

      {applyPreset && (
        <ApplyPresetDialog
          preset={applyPreset}
          roles={roles}
          onClose={() => setApplyPreset(null)}
          onApplied={(result) => {
            setApplyPreset(null)
            const totals = `+${result.total_added} / −${result.total_removed} permission grant(s)`
            setNotice(`Preset “${result.preset.preset_name}” applied to ${result.roles_updated} role(s) in ${result.mode} mode (${totals}).`)
            logUiAction('Permission Presets', 'Apply Preset', {
              preset_id: result.preset.id,
              roles: result.roles_updated,
              mode: result.mode,
            })
            load()
            loadReferences()
          }}
        />
      )}

      {deletePreset && (
        <ConfirmDialog
          titleId="preset-confirm-title"
          title={`Delete “${deletePreset.preset_name}”?`}
          message="This permanently removes the preset and its permission rows, and frees a slot in the 20-preset catalog. It is only offered for presets that have never been applied; anything already applied to roles is deactivated instead so the history stays traceable."
          confirmLabel="Delete permanently"
          busy={deleteBusy}
          onCancel={() => setDeletePreset(null)}
          onConfirm={confirmPermanentDelete}
        />
      )}

      {showImport && (
        <MasterImportDialog
          title="Permission presets"
          templateHeaders={PRESET_IMPORT_TEMPLATE}
          templateFilename="permission-preset-import-template.csv"
          importFile={importPermissionPresetsFile}
          onClose={() => setShowImport(false)}
          onImported={(result) => {
            setShowImport(false)
            setNotice(result.message || 'Presets imported successfully')
            setPage(1)
            load()
          }}
        />
      )}
    </div>
  )
}
