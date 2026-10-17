import { apiDownload, apiGet, buildQuery } from './apiClient'

export const listAuditLogs = (params = {}) =>
  apiGet(`/audit-logs${buildQuery(params)}`)

export const downloadAuditExport = (format, params = {}) =>
  apiDownload(
    `/audit-logs/export${buildQuery({ ...params, format })}`,
    `audit-log.${format}`,
  )
