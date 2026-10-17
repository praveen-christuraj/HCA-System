import { apiGet, apiPost } from './apiClient'
import {
  clearAccessToken,
  getStoredAccessToken,
  getStoredRefreshToken,
  saveAccessToken,
  saveRefreshToken,
} from './authToken'

export const convertLoggedInUserFromApi = (data) => {
  const user = data?.user || data || {}
  const backendRoles = Array.isArray(user.roles) ? user.roles : []
  const fallbackRole = user.role ? [user.role] : []
  const mappedRoles = [...backendRoles, ...fallbackRole]
    .filter(Boolean)
    .map((role) => ({
      id: role.id,
      role_name: role.role_name || role.roleName || role.name || '',
      description: role.description || '',
      status: role.status,
    }))
    .filter((role) => role.role_name)

  const primaryRole = mappedRoles[0] || null

  return {
    id: user.id,
    full_name: user.full_name || user.fullName || '',
    fullName: user.full_name || user.fullName || '',
    username: user.username,
    email: user.email || '',
    phone: user.phone || '',
    department: user.department || '',
    designation: user.designation || '',
    status: user.status,
    is_admin: user.is_admin === true || user.isAdmin === true,
    isAdmin: user.is_admin === true || user.isAdmin === true,
    security: user.security || {},
    role: primaryRole,
    roles: mappedRoles,
    role_name: primaryRole?.role_name || '',
    permissions: (user.permissions || []).map((permission) => ({
      id: permission.id,
      permission_name: permission.permission_name || permission.permissionName,
      permissionName: permission.permission_name || permission.permissionName,
      module_name: permission.module_name || permission.moduleName,
      moduleName: permission.module_name || permission.moduleName,
      category: permission.category || '',
      description: permission.description || '',
      status: permission.status,
    })),
  }
}

const saveLoginTokens = (data) => {
  if (data.access_token) saveAccessToken(data.access_token)
  if (data.refresh_token) saveRefreshToken(data.refresh_token)
}

export const loginUser = async (username, password) => {
  const data = await apiPost(
    '/auth/login',
    { username, password },
    { skipAuth: true, skipRefresh: true },
  )

  if (data.requires_2fa) {
    return {
      requires2FA: true,
      challengeId: data.challenge_id,
      userHint: data.user_hint || null,
    }
  }

  if (!data.access_token) {
    throw new Error('Login token missing from the server response')
  }

  saveLoginTokens(data)
  return convertLoggedInUserFromApi(data)
}

export const verifyLogin2FA = async (challengeId, code) => {
  const data = await apiPost(
    '/auth/2fa/verify',
    { challenge_id: challengeId, code },
    { skipAuth: true, skipRefresh: true },
  )
  saveLoginTokens(data)
  return convertLoggedInUserFromApi(data)
}

export const requestPasswordReset = async (username, reason = '', reset2FA = false) => {
  return apiPost(
    '/auth/forgot-password',
    { username, reason, reset_2fa: Boolean(reset2FA) },
    { skipAuth: true, skipRefresh: true },
  )
}

export const getCurrentUser = async () => {
  if (!getStoredAccessToken() && !getStoredRefreshToken()) {
    return null
  }
  try {
    const data = await apiGet('/auth/me')
    return convertLoggedInUserFromApi(data)
  } catch {
    clearAccessToken()
    return null
  }
}

export const logoutUser = async () => {
  try {
    await apiPost(
      '/auth/logout',
      { refresh_token: getStoredRefreshToken() || null },
      { skipRefresh: true },
    )
  } catch {
    // Best effort: clear locally even if the server call fails.
  }
  clearAccessToken()
}
