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
 * Configurations API. Operation types, categories and stock signs are fixed in
 * the backend catalogue and are read-only here. Operations are location-scoped
 * records of those fixed types and feed the Operation Entry dropdowns later.
 */
export const listOperationTypes = () => apiGet('/operation-types')

export const listOperations = (params = {}) => apiGet(`/operations${buildQuery(params)}`)
export const getOperation = (operationId) => apiGet(`/operations/${operationId}`)
export const createOperation = (payload) => apiPost('/operations', payload)
export const updateOperation = (operationId, payload) => apiPut(`/operations/${operationId}`, payload)
export const deactivateOperation = (operationId) => apiDelete(`/operations/${operationId}`)

export const downloadOperationsExport = (format, params = {}) =>
  apiDownload(`/operations/export${buildQuery({ ...params, format })}`, `operations.${format}`)

export const importOperationsFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/operations/import', formData)
}
