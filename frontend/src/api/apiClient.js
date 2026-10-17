import {
  clearAccessToken,
  getStoredAccessToken,
  getStoredRefreshToken,
  saveAccessToken,
  saveRefreshToken,
} from './authToken'

// Relative URL: Vite (dev) and nginx (Docker) proxy /api to the FastAPI
// backend, so the browser never needs to know the backend host.
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

const REQUEST_TIMEOUT_MS = 60000

const buildHeaders = (customHeaders = {}, includeAuth = true) => {
  const headers = { ...customHeaders }
  const token = includeAuth ? getStoredAccessToken() : null
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

const readResponseData = async (response) => {
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return response.json()
  }
  return null
}

const formatApiError = (data) => {
  if (!data) return 'API request failed'
  if (typeof data.detail === 'string') return data.detail
  if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg).join('; ')
  if (typeof data.detail === 'object') return 'The request was rejected. Check the entered values.'
  return 'API request failed'
}

const fetchWithTimeout = async (url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) => {
  if (typeof AbortController === 'undefined') {
    return fetch(url, options)
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('The server took too long to respond. Please try again.')
    }
    throw error
  } finally {
    clearTimeout(timer)
  }
}

// Single-flight token refresh. Defined here (not in authApi) to avoid a
// circular dependency at module-evaluation time.
let refreshPromise = null

export const refreshSession = async () => {
  const refreshToken = getStoredRefreshToken()
  if (!refreshToken) return false

  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const response = await fetchWithTimeout(`${API_BASE_URL}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
        if (!response.ok) {
          clearAccessToken()
          return false
        }
        const data = await response.json()
        if (data.access_token) saveAccessToken(data.access_token)
        if (data.refresh_token) saveRefreshToken(data.refresh_token)
        return true
      } catch {
        clearAccessToken()
        return false
      } finally {
        refreshPromise = null
      }
    })()
  }
  return refreshPromise
}

export const apiRequest = async (
  endpoint,
  { method = 'GET', body, headers = {}, skipAuth = false, skipRefresh = false } = {},
) => {
  const options = {
    method,
    headers: buildHeaders(headers, !skipAuth),
  }
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }

  const response = await fetchWithTimeout(`${API_BASE_URL}${endpoint}`, options)
  const data = await readResponseData(response)

  if (!response.ok) {
    if (response.status === 401 && !skipAuth && !skipRefresh) {
      const refreshed = await refreshSession()
      if (refreshed) {
        return apiRequest(endpoint, { method, body, headers, skipAuth, skipRefresh: true })
      }
    }
    throw new Error(formatApiError(data))
  }

  return data
}

export const apiGet = (endpoint, options = {}) =>
  apiRequest(endpoint, { ...options, method: 'GET' })

export const apiPost = (endpoint, body, options = {}) =>
  apiRequest(endpoint, { ...options, method: 'POST', body })

export const apiPut = (endpoint, body, options = {}) =>
  apiRequest(endpoint, { ...options, method: 'PUT', body })

export const apiDelete = (endpoint, options = {}) =>
  apiRequest(endpoint, { ...options, method: 'DELETE' })

const triggerBlobDownload = (blob, filename) => {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

export const apiDownload = async (endpoint, fallbackFilename = 'download') => {
  const requestOnce = async () =>
    fetchWithTimeout(`${API_BASE_URL}${endpoint}`, {
      headers: buildHeaders(),
    }, 120000)

  let response = await requestOnce()
  if (response.status === 401) {
    const refreshed = await refreshSession()
    if (refreshed) {
      response = await requestOnce()
    }
  }

  if (!response.ok) {
    let message = 'Download failed'
    try {
      const data = await response.json()
      message = formatApiError(data)
    } catch {
      // Non-JSON error.
    }
    throw new Error(message)
  }

  const disposition = response.headers.get('content-disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/i)
  const filename = match?.[1] || fallbackFilename
  const blob = await response.blob()
  triggerBlobDownload(blob, filename)
  return filename
}

export const apiUpload = async (endpoint, formData, { skipRefresh = false } = {}) => {
  const requestOnce = async () =>
    fetchWithTimeout(
      `${API_BASE_URL}${endpoint}`,
      {
        method: 'POST',
        headers: buildHeaders(),
        body: formData,
      },
      120000,
    )

  let response = await requestOnce()
  if (response.status === 401 && !skipRefresh) {
    const refreshed = await refreshSession()
    if (refreshed) {
      response = await requestOnce()
    }
  }

  const data = await readResponseData(response)
  if (!response.ok) {
    const error = new Error(formatApiError(data))
    error.status = response.status
    error.payload = data
    throw error
  }
  return data
}

export const buildQuery = (params = {}) => {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    search.set(key, value)
  })
  const query = search.toString()
  return query ? `?${query}` : ''
}
