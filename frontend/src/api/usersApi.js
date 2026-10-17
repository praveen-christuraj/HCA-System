import { apiDownload, apiGet, apiUpload, buildQuery } from './apiClient'

export const listUsers = (params = {}) => apiGet(`/users${buildQuery(params)}`)
export const getUser = (userId) => apiGet(`/users/${userId}`)
export const createUser = (payload) => apiPost('/users', payload)
export const updateUser = (userId, payload) => apiPut(`/users/${userId}`, payload)
export const deactivateUser = (userId) => apiDelete(`/users/${userId}`)
export const resetUserPassword = (userId, payload) => apiPost(`/users/${userId}/reset-password`, payload)

export const downloadUsersExport = (format, params = {}) =>
  apiDownload(`/users/export${buildQuery({ ...params, format })}`, `users.${format}`)

export const listRoles = (params = {}) => apiGet(`/roles${buildQuery(params)}`)

export const importUsersFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/users/import', formData)
}
