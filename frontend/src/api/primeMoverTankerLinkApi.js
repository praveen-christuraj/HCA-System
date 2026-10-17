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
 * Prime Mover-Tanker Link API (Master Data). Both asset types are fixed in the
 * asset catalogue, so the link form only chooses assets; it never creates types.
 */
export const listPrimeMoverTankerLinks = (params = {}) =>
  apiGet(`/prime-mover-tanker-links${buildQuery(params)}`)

export const getPrimeMoverTankerLinkOptions = () => apiGet('/prime-mover-tanker-links/options')

export const getCurrentLinkByPrimeMover = (assetId) =>
  apiGet(`/prime-mover-tanker-links/current-by-prime-mover/${assetId}`)

export const getCurrentLinkByTanker = (assetId) =>
  apiGet(`/prime-mover-tanker-links/current-by-tanker/${assetId}`)

export const createPrimeMoverTankerLink = (payload) => apiPost('/prime-mover-tanker-links', payload)
export const updatePrimeMoverTankerLink = (linkId, payload) =>
  apiPut(`/prime-mover-tanker-links/${linkId}`, payload)
export const closePrimeMoverTankerLink = (linkId, payload) =>
  apiPost(`/prime-mover-tanker-links/${linkId}/close`, payload)
export const deletePrimeMoverTankerLink = (linkId) =>
  apiDelete(`/prime-mover-tanker-links/${linkId}`)

export const downloadPrimeMoverTankerLinksExport = (format, params = {}) =>
  apiDownload(
    `/prime-mover-tanker-links/export${buildQuery({ ...params, format })}`,
    `prime-mover-tanker-links.${format}`,
  )

export const importPrimeMoverTankerLinksFile = (file, confirm) => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirm', confirm ? 'true' : 'false')
  return apiUpload('/prime-mover-tanker-links/import', formData)
}
