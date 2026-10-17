import { apiGet } from './apiClient'

export const getDashboardSummary = () => apiGet('/dashboard/summary')

export const getModuleDashboard = (moduleKey) =>
  apiGet(`/dashboard/modules/${encodeURIComponent(moduleKey)}`)
