import { apiDelete, apiGet, apiPost, apiPut, apiUpload, apiDownload, buildQuery } from './apiClient'

export const listLocations = (params = {}) => apiGet(`/locations${buildQuery(params)}`)
export const createLocation = (payload) => apiPost('/locations', payload)
export const updateLocation = (locationId, payload) => apiPut(`/locations/${locationId}`, payload)
export const deactivateLocation = (locationId) => apiDelete(`/locations/${locationId}`)

export const downloadLocationsExport = (format, params = {}) =>
  apiDownload(`/locations/export${buildQuery({ ...params, format })}`, `locations.${format}`)

export const importLocationsFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/locations/import', formData)
}
