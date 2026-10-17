import { apiGet, apiPost, apiPut, apiDownload, apiUpload, buildQuery } from './apiClient'

export const entryOptions = () => apiGet('/operation-entries/options')
export const entryLookup = (kind, params = {}) => apiGet(`/operation-entries/lookups/${kind}${buildQuery(params)}`)
export const getEntry = id => apiGet(`/operation-entries/${id}`)
export const listEntries = params => apiGet(`/operation-entries${buildQuery(params)}`)
export const createEntry = body => apiPost('/operation-entries', body)
export const updateEntry = (id, body) => apiPut(`/operation-entries/${id}`, body)
export const transitionEntry = (id, action, body) => apiPost(`/operation-entries/${id}/${action}`, body)
export const calculateEntry = body => apiPost('/operation-entries/calculate', body)
export const getAssetContext = (id, linkedTicketId = null) => apiGet(`/operation-entries/asset-context/${id}${buildQuery({ linked_ticket_id: linkedTicketId })}`)
export const linkedSender = id => apiGet(`/operation-entries/linked-sender/${id}`)
export const exportEntries = (format, params) => apiDownload(`/operation-entries/export${buildQuery({ ...params, format })}`)
export const importEntryFile = (file, confirm, payloadCode) => {
  const data = new FormData()
  data.append('file', file); data.append('confirm', confirm); data.append('payload_code', payloadCode)
  return apiUpload('/operation-entry-import', data)
}
export const downloadEntryTemplate = (payloadCode, format = 'csv') => apiDownload(`/operation-entry-import/template${buildQuery({ payload_code: payloadCode, format })}`)

// Narrow adapters preserve the source layouts' camelCase reference contracts.
// They use entry-authorized lookups; operators never need master-admin grants.
export const lookupTable11Factor = async api60 => {
  const r = await apiGet(`/operation-entries/table11${buildQuery({ api60 })}`)
  return { api60: r.api60, lowerApi60: r.lower_api60, upperApi60: r.upper_api60, ltFactor: r.lt_factor, lookupMethod: r.lookup_method }
}
export const getVesselOperations = async params => {
  const r = await entryLookup('operations', { location_code: params.location_code, asset_type_code: params.applicable_asset_type_code, page_size: 200 })
  return r.items
}
export const getTankOperations = async params => {
  const r = await entryLookup('operations', { location_code: params.locationCode, operation_type_code: 'TANK_OPERATIONS', page_size: 200 })
  return r.items.map(o => ({ id: o.id, operationCode: o.operation_code, operationLabel: o.operation_label, operationCategory: o.operation_category, operationSign: o.operation_sign }))
}
const assetId = async code => {
  const r = await entryLookup('assets', { asset_code: code })
  if (!r.items.length) throw new Error('Asset is unavailable or outside your location scope.')
  return r.items[0].id
}
export const getPrimeMoverTankerLinks = async params => {
  const id = await assetId(params.tanker_asset_code)
  const r = await getAssetContext(id)
  return r.link ? [r.link] : []
}
export const getCurrentPrimeMoverTankerLink = async () => {
  throw new Error('Select the Tanker Trailer as the primary asset; its prime mover is resolved from the active link.')
}
export const getBargeSealMaster = async code => {
  const id = await assetId(code)
  const r = await apiGet(`/operation-references/seals${buildQuery({ asset_id: id, status: 'Active', page_size: 200 })}`)
  if (r.has_more) throw new Error('Seal reference exceeds 200 positions. Narrow the configured tank set before entry.')
  return r.items.map(s => ({ ...s, tankId: s.tank_name, sealPosition: s.seal_position, sealNumber: s.seal_number }))
}
export const getFlowmeterConfigs = async ({ assetCode, locationCode }) => {
  const [id, loc] = await Promise.all([assetId(assetCode), entryLookup('locations', { search: locationCode })])
  const location = loc.items.find(l => l.location_code === locationCode)
  if (!location) throw new Error('Origin Location is unavailable.')
  const r = await apiGet(`/operation-references/meters${buildQuery({ asset_id: id, location_id: location.id, status: 'Active', page_size: 200 })}`)
  if (r.has_more) throw new Error('An entry supports at most 200 configured meters.')
  return r.items.map(m => ({ id: m.id, meterLabel: m.meter_label, meterFactor: m.meter_factor, meterUnit: m.meter_unit, meterAssetCode: m.meter_asset_code, meterAssetName: m.meter_asset_name, streamName: m.stream_name, status: m.status }))
}
export const getShuttleTracking = ({ shuttle_number }) => apiGet(`/operation-entries/closed-shuttle${buildQuery({ shuttle_number })}`)
