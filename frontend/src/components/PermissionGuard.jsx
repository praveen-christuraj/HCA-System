import { Link } from 'react-router-dom'
import Icon from './common/Icon'
import { userHasPermission } from '../hooks/usePermissions'

/**
 * Route guard (owner rule 11). Hiding UI is not security — the API checks
 * every request — but users should never reach a page they cannot use.
 */
export default function PermissionGuard({
  loggedInUser,
  requiredPermission,
  allOfPermissions,
  anyOfPermissions,
  children,
  fallbackTitle = 'Access denied',
  fallbackMessage = 'You do not have permission to access this page.',
}) {
  const permissionList = [
    ...(requiredPermission ? [requiredPermission] : []),
    ...(Array.isArray(allOfPermissions) ? allOfPermissions.filter(Boolean) : []),
  ]
  const anyList = Array.isArray(anyOfPermissions) ? anyOfPermissions.filter(Boolean) : []

  const hasAll = permissionList.every((name) => userHasPermission(loggedInUser, name))
  const hasAny = anyList.length === 0 || anyList.some((name) => userHasPermission(loggedInUser, name))

  if (!hasAll || !hasAny) {
    return (
      <div className="page">
        <div className="page-head">
          <div className="page-head-copy">
            <div className="page-eyebrow">SECURITY / ACCESS</div>
            <h1 className="page-title">{fallbackTitle}</h1>
            <p className="page-subtitle">{fallbackMessage}</p>
          </div>
        </div>
        <div className="alert alert-warning" role="alert">
          <Icon name="alertTriangle" size={16} className="alert-icon" />
          <div>
            {permissionList.length > 0
              ? `Required permission: ${permissionList.join(', ')}.`
              : `Requires one of: ${anyList.join(', ')}.`}{' '}
            Ask an administrator to grant access through Role Permission Assignment.
          </div>
        </div>
        <div>
          <Link to="/" className="btn btn-secondary">
            Back to dashboard
          </Link>
        </div>
      </div>
    )
  }

  return children
}
