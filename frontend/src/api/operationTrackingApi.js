import { apiDownload, apiGet, apiPost, apiPut, buildQuery } from './apiClient'

/**
 * Operation Tracking API (OTMS tracking modules). Every list is paginated by
 * the server; every export is audited by the server.
 */
const base = '/operation-tracking'

// Operation Transaction Register
export const listTransactions = (params) => apiGet(`${base}/transactions${buildQuery(params)}`)
export const exportTransactions = (format, params) =>
  apiDownload(`${base}/transactions/export${buildQuery({ ...params, format })}`)

// Barge Tracking
export const listBargeVoyages = (params) => apiGet(`${base}/barge/voyages${buildQuery(params)}`)
export const exportBargeVoyages = (format, params) =>
  apiDownload(`${base}/barge/voyages/export${buildQuery({ ...params, format })}`)
export const getBargeConvoy = (convoyNumber) =>
  apiGet(`${base}/barge/convoy${buildQuery({ convoy_number: convoyNumber })}`)
export const exportBargeConvoy = (convoyNumber, format) =>
  apiDownload(`${base}/barge/convoy/export${buildQuery({ convoy_number: convoyNumber, format })}`)
export const acknowledgeBargeReceipt = (body) => apiPost(`${base}/barge/receipts`, body)
export const revokeBargeReceipt = (body) => apiPost(`${base}/barge/receipts/revoke`, body)
export const fixBargeTimeline = (body) => apiPut(`${base}/barge/timeline`, body)
export const closeBargeConvoy = (body) => apiPost(`${base}/barge/close`, body)
export const reopenBargeConvoy = (body) => apiPost(`${base}/barge/reopen`, body)

// Tanker Tracking
export const listTankerTracking = (params) => apiGet(`${base}/tanker${buildQuery(params)}`)
export const exportTankerTracking = (format, params) =>
  apiDownload(`${base}/tanker/export${buildQuery({ ...params, format })}`)
export const acknowledgeTanker = (body) => apiPost(`${base}/tanker/acknowledgements`, body)
export const revokeTanker = (id, body) => apiPost(`${base}/tanker/acknowledgements/${id}/revoke`, body)
export const closeTanker = (id, body) => apiPost(`${base}/tanker/acknowledgements/${id}/close`, body)

// Tanker Transaction Report
export const tankerReport = (params) => apiGet(`${base}/tanker/report${buildQuery(params)}`)
export const exportTankerReport = (format, params) =>
  apiDownload(`${base}/tanker/report/export${buildQuery({ ...params, format })}`)

// Shuttle / FSO voyages (kind = 'shuttle' | 'fso')
export const listVoyages = (kind, params) => apiGet(`${base}/${kind}/voyages${buildQuery(params)}`)
export const exportVoyages = (kind, format, params) =>
  apiDownload(`${base}/${kind}/voyages/export${buildQuery({ ...params, format })}`)
export const getVoyage = (kind, id) => apiGet(`${base}/${kind}/voyages/${id}`)
export const exportVoyage = (kind, id, format) =>
  apiDownload(`${base}/${kind}/voyages/${id}/export${buildQuery({ format })}`)
export const changeVoyage = (kind, id, action, remarks) =>
  apiPost(`${base}/${kind}/voyages/${id}/${action}`, { remarks })

// FSO reports (kind = 'otr' | 'material-balance' | 'outturn')
export const fsoReport = (kind, params) => apiGet(`${base}/fso/reports/${kind}${buildQuery(params)}`)
export const exportFsoReport = (kind, format, params) =>
  apiDownload(`${base}/fso/reports/${kind}/export${buildQuery({ ...params, format })}`)
