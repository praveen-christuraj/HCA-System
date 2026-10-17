import { apiGet, apiPut, apiDownload, apiUpload, buildQuery } from './apiClient'

export const listRoleLocations = (params = {}) => apiGet(`/role-locations${buildQuery(params)}`)
export const getRoleLocations = (roleId) => apiGet(`/role-locations/${roleId}`)
export const saveRoleLocations = (roleId, locationIds) =>
  apiPut(`/role-locations/${roleId}`, { location_ids: locationIds })
export const importRoleLocationsFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/role-locations/import', formData)
}
export const downloadRoleLocationsExport = (format, params = {}) =>
  apiDownload(`/role-locations/export${buildQuery({ ...params, format })}`, `role-locations.${format}`)

export const listUserRoles = (params = {}) => apiGet(`/user-roles${buildQuery(params)}`)
export const saveUserRoles = (userId, roleIds) =>
  apiPut(`/user-roles/${userId}`, { role_ids: roleIds })
export const importUserRolesFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/user-roles/import', formData)
}
export const downloadUserRolesExport = (format, params = {}) =>
  apiDownload(`/user-roles/export${buildQuery({ ...params, format })}`, `user-roles.${format}`)
