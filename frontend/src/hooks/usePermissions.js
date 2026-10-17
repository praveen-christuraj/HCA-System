import { useMemo } from 'react'
import { useAuth } from '../context/AuthContext'

/**
 * Single source of truth for frontend RBAC checks.
 * The API remains the authorization authority; this hook only shapes the UI.
 */

const normalise = (value) => String(value || '').trim().toLowerCase()

export const isAdminUser = (user) => {
  if (!user) return false
  if (user.isAdmin === true || user.is_admin === true) return true
  if (normalise(user.username) === 'admin') return true

  const roles = user.roles || []
  if (
    Array.isArray(roles) &&
    roles.some((role) => normalise(role?.role_name || role?.roleName) === 'admin')
  ) {
    return true
  }
  const singleRole = user.role?.role_name || user.role?.roleName
  return normalise(singleRole) === 'admin'
}

export const userHasPermission = (user, permissionName) => {
  if (!permissionName) return true
  if (!user) return false
  if (isAdminUser(user)) return true
  if (!Array.isArray(user.permissions)) return false
  return user.permissions.some(
    (permission) =>
      permission?.permissionName === permissionName ||
      permission?.permission_name === permissionName,
  )
}

export const usePermissions = (explicitUser) => {
  const { loggedInUser } = useAuth()
  const user = explicitUser || loggedInUser

  return useMemo(() => {
    const hasPermission = (permissionName) => userHasPermission(user, permissionName)
    return {
      user,
      isAdmin: isAdminUser(user),
      hasPermission,
      hasAll: (names = []) => names.every(hasPermission),
      hasAny: (names = []) => names.some(hasPermission),
    }
  }, [user])
}

export default usePermissions
