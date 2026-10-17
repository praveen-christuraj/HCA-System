import {
  apiDelete,
  apiDownload,
  apiGet,
  apiPost,
  apiPut,
  apiUpload,
  buildQuery,
} from './apiClient'

/**
 * Asset Master and calibration API.
 *
 * Asset types are hard coded server-side, so there is no asset-type CRUD here —
 * only `getAssetReference`, which returns the fixed catalog plus the unit
 * conversion factors the calibration module uses.
 */
export const getAssetReference = () => apiGet('/assets/reference')

export const listAssets = (params = {}) => apiGet(`/assets${buildQuery(params)}`)
export const getAsset = (assetId) => apiGet(`/assets/${assetId}`)
export const createAsset = (payload) => apiPost('/assets', payload)
export const updateAsset = (assetId, payload) => apiPut(`/assets/${assetId}`, payload)
export const deactivateAsset = (assetId) => apiDelete(`/assets/${assetId}`)

export const downloadAssetsExport = (format, params = {}) =>
  apiDownload(`/assets/export${buildQuery({ ...params, format })}`, `assets.${format}`)

export const importAssetsFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/assets/import', formData)
}

// --- Calibration -----------------------------------------------------------
export const getCalibration = (assetId, includeRows = true) =>
  apiGet(`/assets/${assetId}/calibration${buildQuery({ include_rows: includeRows })}`)

export const uploadCalibrationFile = (assetId, file, options, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  formData.append('chart_name', options.chartName || '')
  formData.append('measurement_basis', options.measurementBasis || 'Dip')
  formData.append('dip_unit', options.dipUnit || 'cm')
  formData.append('volume_unit', options.volumeUnit || 'bbl')
  if (options.effectiveDate) formData.append('effective_date', options.effectiveDate)
  formData.append('remarks', options.remarks || '')
  return apiUpload(`/assets/${assetId}/calibration/upload`, formData)
}

export const deleteCalibration = (assetId) => apiDelete(`/assets/${assetId}/calibration`)

export const downloadCalibrationExport = (assetId, format, params = {}) =>
  apiDownload(
    `/assets/${assetId}/calibration/export${buildQuery({ ...params, format })}`,
    `calibration.${format}`,
  )

export const lookupVolume = (assetId, payload) =>
  apiPost(`/assets/${assetId}/calibration/lookup`, payload)

export const lookupVolumeBatch = (assetId, payload) =>
  apiPost(`/assets/${assetId}/calibration/lookup-batch`, payload)
