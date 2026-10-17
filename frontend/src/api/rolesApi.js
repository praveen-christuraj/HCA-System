import { apiDelete, apiGet, apiPost, apiPut, apiUpload, apiDownload, buildQuery } from './apiClient'

export const listRoles = (params = {}) => apiGet(`/roles${buildQuery(params)}`)
export const getRole = (roleId) => apiGet(`/roles/${roleId}`)
export const createRole = (payload) => apiPost('/roles', payload)
export const updateRole = (roleId, payload) => apiPut(`/roles/${roleId}`, payload)
export const deactivateRole = (roleId) => apiDelete(`/roles/${roleId}`)

export const downloadRolesExport = (format, params = {}) =>
  apiDownload(`/roles/export${buildQuery({ ...params, format })}`, `roles.${format}`)

export const importRolesFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/roles/import', formData)
}

export const getRolePermissions = (roleId) => apiGet(`/roles/${roleId}/permissions`)
export const replaceRolePermissions = (roleId, permissionIds) =>
  apiPut(`/roles/${roleId}/permissions`, { permission_ids: permissionIds })
export const downloadRolePermissionsExport = (roleId, format) =>
  apiDownload(`/roles/${roleId}/permissions/export${buildQuery({ format })}`, `role-permissions.${format}`)
export const importRolePermissionsFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/roles/permissions/import', formData)
}
export const getPermissionCatalog = () => apiGet('/permissions/catalog')
