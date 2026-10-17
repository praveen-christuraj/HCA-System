import { apiDelete, apiDownload, apiGet, apiPost, apiPut, apiUpload, buildQuery } from './apiClient'

/**
 * Permission Preset Master API.
 *
 * A preset is a named, reusable set of standard permissions (the catalog is
 * capped at 20 presets). Presets are applied to roles in one audited action —
 * `replace` sets a role's grants to exactly the preset, `add` merges them in.
 */
export const listPermissionPresets = (params = {}) =>
  apiGet(`/permission-presets${buildQuery(params)}`)

export const getPresetOptions = () => apiGet('/permission-presets/options')

export const getPermissionPreset = (presetId) => apiGet(`/permission-presets/${presetId}`)

export const createPermissionPreset = (payload) => apiPost('/permission-presets', payload)

export const updatePermissionPreset = (presetId, payload) =>
  apiPut(`/permission-presets/${presetId}`, payload)

/** Soft delete: the preset is kept and can be reactivated. */
export const deactivatePermissionPreset = (presetId) => apiDelete(`/permission-presets/${presetId}`)

/** Hard delete: only allowed while the preset has never been applied. */
export const deletePermissionPresetPermanently = (presetId) =>
  apiDelete(`/permission-presets/${presetId}${buildQuery({ permanent: true })}`)

export const applyPermissionPreset = (presetId, roleIds, mode = 'replace') =>
  apiPost(`/permission-presets/${presetId}/apply`, { role_ids: roleIds, mode })

export const downloadPermissionPresetsExport = (format, params = {}) =>
  apiDownload(
    `/permission-presets/export${buildQuery({ ...params, format })}`,
    `permission-presets.${format}`,
  )

export const importPermissionPresetsFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/permission-presets/import', formData)
}

export const PRESET_IMPORT_TEMPLATE = ['preset_name', 'permission_names', 'description', 'status']
