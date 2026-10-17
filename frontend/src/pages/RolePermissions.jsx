import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  createPermissionPreset,
  getPermissionPreset,
  getPresetOptions,
} from '../api/permissionPresetsApi'
import { downloadRolePermissionsExport, getPermissionCatalog, getRolePermissions, importRolePermissionsFile, listRoles, replaceRolePermissions } from '../api/rolesApi'
import Icon from '../components/common/Icon'
import MasterImportDialog from '../components/common/MasterImportDialog'
import { Alert, Loading, PageHead, StatusTag } from '../components/common/Ui'
import { usePermissions } from '../hooks/usePermissions'
import { logUiAction } from '../utils/actionLogger'

/** Name the current selection so it becomes a reusable preset. */
function SavePresetDialog({ permissionIds, remaining, onClose, onSaved }) {
  const [form, setForm] = useState({ preset_name: '', description: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await createPermissionPreset({
        preset_name: form.preset_name.trim(),
        description: form.description.trim() || null,
        status: 'Active',
        permission_ids: permissionIds,
      })
      onSaved(result)
    } catch (saveError) {
      setError(saveError.message || 'Unable to save the preset')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop">
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="save-preset-title" onSubmit={submit}>
        <div className="dialog-head">
          <h2 id="save-preset-title" className="dialog-title">Save selection as a preset</h2>
          <p className="dialog-subtitle">
            The {permissionIds.length} permission(s) currently selected are stored as a named preset that can be
            applied to any role. {remaining} of the preset slots are still free.
          </p>
        </div>
        <div className="dialog-body">
          {error && <Alert tone="danger">{error}</Alert>}
          <div className="form-grid" style={{ marginTop: error ? 14 : 0 }}>
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
            </label>
            <label className="field">
              <span className="field-label">Description</span>
              <textarea
                className="textarea"
                maxLength={500}
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
                placeholder="Which roles this preset is meant for"
              />
            </label>
          </div>
        </div>
        <div className="dialog-foot">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Icon name="layers" size={15} /> {busy ? 'Saving…' : 'Save preset'}
          </button>
        </div>
      </form>
    </div>
  )
}

export default function RolePermissions() {
  const { isAdmin, hasPermission } = usePermissions()
  const canAssign = isAdmin || hasPermission('assignments:write')
  const canReadPresets = isAdmin || hasPermission('permission_presets:read')
  const canCreatePresets = isAdmin || hasPermission('permission_presets:create')
  const [roles, setRoles] = useState([])
  const [catalog, setCatalog] = useState([])
  const [selectedRoleId, setSelectedRoleId] = useState('')
  const [savedIds, setSavedIds] = useState([])
  const [selectedIds, setSelectedIds] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [presetOptions, setPresetOptions] = useState([])
  const [presetsRemaining, setPresetsRemaining] = useState(0)
  const [presetError, setPresetError] = useState('')
  const [selectedPresetId, setSelectedPresetId] = useState('')
  const [presetDetail, setPresetDetail] = useState(null)
  const [presetLoading, setPresetLoading] = useState(false)
  const [showSavePreset, setShowSavePreset] = useState(false)

  const selectedRole = useMemo(() => roles.find((role) => String(role.id) === String(selectedRoleId)), [roles, selectedRoleId])
  const isReserved = Boolean(selectedRole?.is_reserved || selectedRole?.role_name?.trim().toLowerCase() === 'admin')
  const editable = Boolean(selectedRole) && !isReserved && selectedRole?.status === 'Active' && canAssign
  const dirty = useMemo(() => {
    const current = [...selectedIds].sort((a, b) => a - b)
    const saved = [...savedIds].sort((a, b) => a - b)
    return current.length !== saved.length || current.some((id, index) => id !== saved[index])
  }, [selectedIds, savedIds])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [roleResponse, catalogResponse] = await Promise.all([
        listRoles({ page: 1, page_size: 200 }),
        getPermissionCatalog(),
      ])
      const roleItems = roleResponse.items || []
      setRoles(roleItems)
      setCatalog(catalogResponse.categories || [])
      setSelectedRoleId((current) => current && roleItems.some((role) => String(role.id) === String(current))
        ? current
        : String(roleItems[0]?.id || ''))
    } catch (loadError) {
      setError(loadError.message || 'Unable to load role permissions')
    } finally { setLoading(false) }
  }, [])

  const loadPresets = useCallback(async () => {
    if (!canReadPresets) return
    setPresetError('')
    try {
      const response = await getPresetOptions()
      setPresetOptions(response.items || [])
      setPresetsRemaining(response.presets_remaining ?? 0)
    } catch (presetLoadError) {
      // The preset bar is a convenience layer; failing to load it must not
      // block permission assignment itself.
      setPresetOptions([])
      setPresetError(presetLoadError.message || 'Unable to load permission presets')
    }
  }, [canReadPresets])

  const loadSelected = useCallback(async (roleId) => {
    if (!roleId) { setSavedIds([]); setSelectedIds([]); return }
    setError('')
    try {
      const response = await getRolePermissions(roleId)
      const ids = response.permission_ids || []
      setSavedIds(ids)
      setSelectedIds(ids)
    } catch (loadError) {
      setError(loadError.message || 'Unable to load this role’s permission set')
      setSavedIds([])
      setSelectedIds([])
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadPresets() }, [loadPresets])
  useEffect(() => { if (selectedRoleId) loadSelected(selectedRoleId) }, [selectedRoleId, loadSelected])

  useEffect(() => {
    if (!selectedPresetId) { setPresetDetail(null); return undefined }
    let active = true
    setPresetLoading(true)
    getPermissionPreset(selectedPresetId)
      .then((detail) => { if (active) setPresetDetail(detail) })
      .catch((detailError) => {
        if (active) setPresetError(detailError.message || 'Unable to load the selected preset')
      })
      .finally(() => { if (active) setPresetLoading(false) })
    return () => { active = false }
  }, [selectedPresetId])

  const presetIds = presetDetail?.active_permission_ids || []
  const presetDelta = useMemo(() => {
    if (!presetIds.length) return null
    const current = new Set(selectedIds)
    const incoming = new Set(presetIds)
    return {
      adds: presetIds.filter((id) => !current.has(id)).length,
      removes: selectedIds.filter((id) => !incoming.has(id)).length,
    }
  }, [presetIds, selectedIds])

  const togglePermission = (id) => setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  const toggleModule = (permissionIds) => {
    const allSelected = permissionIds.every((id) => selectedIds.includes(id))
    setSelectedIds((current) => allSelected
      ? current.filter((id) => !permissionIds.includes(id))
      : [...new Set([...current, ...permissionIds])])
  }

  /**
   * Stage a preset onto the selection. The write still goes through the audited
   * role-permission endpoint when the administrator saves, so the result can be
   * reviewed (and discarded) before anything changes.
   */
  const applyPresetToSelection = (mode) => {
    if (!presetDetail || !editable) return
    if (!presetIds.length) {
      setPresetError('This preset contains no active permission, so it cannot be applied.')
      return
    }
    setPresetError('')
    setError('')
    setSelectedIds((current) => mode === 'replace' ? [...presetIds] : [...new Set([...current, ...presetIds])])
    setNotice(`Preset “${presetDetail.preset_name}” ${mode === 'replace' ? 'replaced' : 'was added to'} the selection for ${selectedRole.role_name}. Review it below, then save.`)
    logUiAction('Role Permission Assignment', 'Stage Permission Preset', {
      preset_id: presetDetail.id,
      preset_name: presetDetail.preset_name,
      role_id: selectedRole.id,
      mode,
    })
  }

  const save = async () => {
    if (!selectedRole || !canAssign || isReserved || selectedRole.status !== 'Active') return
    setSaving(true)
    setError('')
    try {
      const response = await replaceRolePermissions(selectedRole.id, selectedIds)
      const ids = response.permission_ids || selectedIds
      setSavedIds(ids)
      setSelectedIds(ids)
      setNotice(`Permissions saved for ${selectedRole.role_name}.`)
      logUiAction('Role Permission Assignment', 'Save Role Permissions', { role_id: selectedRole.id, total: ids.length })
    } catch (saveError) {
      setError(saveError.message || 'Unable to save permissions')
    } finally { setSaving(false) }
  }

  const exportCurrent = async (format) => {
    if (!selectedRole) return
    setExporting(format)
    setError('')
    try { await downloadRolePermissionsExport(selectedRole.id, format) }
    catch (exportError) { setError(exportError.message || 'Export failed') }
    finally { setExporting('') }
  }

  return (
    <div className="page">
      <PageHead
        eyebrow="USER MANAGEMENT / ROLE PERMISSION ASSIGNMENT"
        title="Role Permission Assignment"
        description="Assign only standard resource:action capabilities, one by one or by applying a named permission preset. CSV/XLSX import uses one role per row and semicolon-separated permission keys; the reserved Admin role remains system-managed."
        actions={<>{canReadPresets && <Link to="/permission-presets" className="btn btn-secondary"><Icon name="layers" size={15} /> Permission presets</Link>}{canAssign && <button type="button" className="btn btn-secondary" onClick={() => setShowImport(true)}><Icon name="upload" size={15} /> Import</button>}<div className="toolbar-group" role="group" aria-label="Export role permissions">{['csv', 'xlsx', 'pdf'].map((format) => <button key={format} type="button" className="btn btn-secondary btn-compact" onClick={() => exportCurrent(format)} disabled={!selectedRole || Boolean(exporting)}><Icon name="download" size={14} />{exporting === format ? 'Exporting…' : format.toUpperCase()}</button>)}</div><button type="button" className="btn btn-secondary" onClick={() => { load(); loadPresets(); if (selectedRoleId) loadSelected(selectedRoleId) }} disabled={loading}><Icon name="refresh" size={15} /> Refresh</button></>}
      />
      {error && <Alert tone="danger">{error}</Alert>}
      {notice && <Alert tone="success">{notice}</Alert>}
      {loading ? <Loading label="Loading permission catalog…" /> : (
        <div className="assignment-layout">
          <section className="card assignment-role-panel">
            <div className="card-head"><div><h2 className="card-title">Roles</h2><p className="card-subtitle">Select a role to inspect its permissions.</p></div><span className="tag">{roles.length}</span></div>
            <div className="assignment-role-list" role="listbox" aria-label="Roles">
              {roles.map((role) => <button type="button" key={role.id} role="option" aria-selected={String(role.id) === String(selectedRoleId)} className={`assignment-role-option ${String(role.id) === String(selectedRoleId) ? 'is-selected' : ''}`} onClick={() => { setNotice(''); setSelectedRoleId(String(role.id)) }}><span><strong>{role.role_name}</strong><small>{role.permission_count || 0} permissions · {role.user_count || 0} users</small></span><StatusTag status={role.status} /></button>)}
            </div>
          </section>

          <section className="card assignment-content-panel">
            <div className="card-head assignment-header">
              <div><h2 className="card-title">{selectedRole?.role_name || 'Select a role'}</h2><p className="card-subtitle">{isReserved ? 'Reserved role — complete catalog is maintained by system bootstrap.' : 'Select standard capabilities, or apply a preset. Changes take effect immediately after saving.'}</p></div>
              <div className="assignment-header-actions">{selectedRole && <StatusTag status={selectedRole.status} />}<span className="tag">{selectedIds.length} selected</span></div>
            </div>
            {isReserved && <div className="card-body"><Alert tone="info" icon="shieldCheck">Admin retains every active standard permission. Its grants cannot be edited here.</Alert></div>}
            {selectedRole?.status === 'Inactive' && <div className="card-body"><Alert tone="warning" icon="alertTriangle">Inactive roles cannot be changed. Reactivate the role in Role Master first.</Alert></div>}

            {canReadPresets && editable && (
              <div className="preset-bar">
                <span className="preset-bar-label"><Icon name="layers" size={15} /> Apply a preset</span>
                <select
                  className="select"
                  value={selectedPresetId}
                  onChange={(event) => { setPresetError(''); setSelectedPresetId(event.target.value) }}
                  aria-label="Permission preset"
                  disabled={presetLoading}
                >
                  <option value="">{presetOptions.length ? 'Choose a preset…' : 'No active presets yet'}</option>
                  {presetOptions.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.preset_name} — {preset.permission_count} permission{preset.permission_count === 1 ? '' : 's'}
                    </option>
                  ))}
                </select>
                {presetDetail && (
                  <span className="preset-bar-meta">
                    {presetDetail.module_count} module(s){presetDelta ? ` · replace adds ${presetDelta.adds} and removes ${presetDelta.removes} · add grants ${presetDelta.adds}` : ''}
                  </span>
                )}
                <div className="toolbar-group" role="group" aria-label="Apply preset to the selection">
                  <button type="button" className="btn btn-secondary btn-compact" onClick={() => applyPresetToSelection('replace')} disabled={!presetDetail || presetLoading}>
                    <Icon name="copy" size={14} /> Replace selection
                  </button>
                  <button type="button" className="btn btn-secondary btn-compact" onClick={() => applyPresetToSelection('add')} disabled={!presetDetail || presetLoading}>
                    <Icon name="shieldCheck" size={14} /> Add to selection
                  </button>
                </div>
                <div className="preset-bar-spacer" />
                {canCreatePresets && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-compact"
                    onClick={() => { setNotice(''); setShowSavePreset(true) }}
                    disabled={selectedIds.length === 0 || presetsRemaining <= 0}
                    title={presetsRemaining <= 0 ? 'Preset limit reached — free a slot in Permission Presets' : 'Store the current selection as a new preset'}
                  >
                    <Icon name="layers" size={14} /> Save selection as preset
                  </button>
                )}
              </div>
            )}
            {presetError && <div className="card-body"><Alert tone="warning" icon="alertTriangle">{presetError}</Alert></div>}

            <div className="permission-modules">
              {catalog.map((category) => <div className="permission-category" key={category.category}>
                <div className="permission-category-title">{category.category}</div>
                {category.modules.map((module) => {
                  const permissions = module.permissions || []
                  const ids = permissions.map((permission) => permission.id)
                  const allSelected = ids.length > 0 && ids.every((id) => selectedIds.includes(id))
                  const someSelected = ids.some((id) => selectedIds.includes(id))
                  return <section key={`${category.category}-${module.module_name}`} className="permission-module">
                    <div className="permission-module-head">
                      <div><h3>{module.module_name}</h3><span className="muted small">{permissions.length} standard permissions</span></div>
                      {!isReserved && <label className="checkbox-inline"><input type="checkbox" checked={allSelected} ref={(element) => { if (element) element.indeterminate = someSelected && !allSelected }} disabled={!canAssign || selectedRole?.status !== 'Active'} onChange={() => toggleModule(ids)} /><span>Select all</span></label>}
                    </div>
                    <div className="permission-list">{permissions.map((permission) => <label key={permission.id} className={`permission-option ${selectedIds.includes(permission.id) ? 'is-checked' : ''}`}><input type="checkbox" checked={selectedIds.includes(permission.id)} disabled={isReserved || !canAssign || selectedRole?.status !== 'Active'} onChange={() => togglePermission(permission.id)} /><span className="permission-copy"><strong>{permission.permission_name}</strong><small>{permission.description}</small></span><span className="permission-action-tag">{permission.action}</span></label>)}</div>
                  </section>
                })}
              </div>)}
            </div>
            <div className="assignment-footer"><span className="muted small">{dirty ? 'Unsaved changes' : 'All changes saved'}</span><div className="toolbar-group"><button type="button" className="btn btn-secondary" onClick={() => setSelectedIds(savedIds)} disabled={!dirty || saving}>Discard changes</button><button type="button" className="btn btn-primary" onClick={save} disabled={!dirty || !canAssign || isReserved || selectedRole?.status !== 'Active' || saving}><Icon name="checkCircle" size={15} />{saving ? 'Saving…' : 'Save permissions'}</button></div></div>
          </section>
        </div>
      )}
      {showImport && <MasterImportDialog title="Role permissions" templateHeaders={["role_name", "permission_names"]} templateFilename="role-permission-import-template.csv" importFile={importRolePermissionsFile} onClose={() => setShowImport(false)} onImported={(result) => { setShowImport(false); setNotice(result.message || 'Role permissions imported successfully'); load(); if (selectedRoleId) loadSelected(selectedRoleId) }} />}
      {showSavePreset && (
        <SavePresetDialog
          permissionIds={selectedIds}
          remaining={presetsRemaining}
          onClose={() => setShowSavePreset(false)}
          onSaved={(result) => {
            setShowSavePreset(false)
            setNotice(`Preset “${result.preset_name}” saved with ${result.permission_count} permission(s).`)
            setSelectedPresetId(String(result.id))
            loadPresets()
          }}
        />
      )}
    </div>
  )
}
