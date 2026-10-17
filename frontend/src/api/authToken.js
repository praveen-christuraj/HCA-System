const ACCESS_TOKEN_KEY = 'hca.accessToken'
const REFRESH_TOKEN_KEY = 'hca.refreshToken'

export const getStoredAccessToken = () => {
  try {
    return window.localStorage.getItem(ACCESS_TOKEN_KEY)
  } catch {
    return null
  }
}

export const getStoredRefreshToken = () => {
  try {
    return window.localStorage.getItem(REFRESH_TOKEN_KEY)
  } catch {
    return null
  }
}

export const saveAccessToken = (token) => {
  try {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, token)
  } catch {
    // Storage unavailable — the session will not survive a reload.
  }
}

export const saveRefreshToken = (token) => {
  try {
    window.localStorage.setItem(REFRESH_TOKEN_KEY, token)
  } catch {
    // ignore
  }
}

export const clearAccessToken = () => {
  try {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
    window.localStorage.removeItem(REFRESH_TOKEN_KEY)
  } catch {
    // ignore
  }
}
