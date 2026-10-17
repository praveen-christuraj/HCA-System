import { apiDownload, apiGet, apiUpload, buildQuery } from './apiClient'

export const listUsers = (params = {}) => apiGet(`/users${buildQuery(params)}`)

export const downloadUsersExport = (format, params = {}) =>
  apiDownload(`/users/export${buildQuery({ ...params, format })}`, `users.${format}`)

export const listRoles = (params = {}) => apiGet(`/roles${buildQuery(params)}`)

export const importUsersFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/users/import', formData)
}
