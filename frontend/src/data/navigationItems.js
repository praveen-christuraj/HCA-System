/**
 * Permission-filtered top-side navigation (no side navigation).
 * Resource pages use only standard resource:action keys; assignments are
 * read with the relevant standard resource read permissions and written with
 * assignments:write.
 */
export const navigationItems = [
  {
    label: 'Home',
    path: '/',
    type: 'link',
    permission: 'dashboard:read',
  },
  {
    label: 'User Management',
    type: 'dropdown',
    // Owner ordering: User Master, Role Master, Location Master, Role Permission
    // Assignment, Role Location Assignment, User Role Assignment.
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/user-management',
        permission: 'users:read',
      },
      { label: 'User Master', path: '/users', permission: 'users:read' },
      { label: 'Role Master', path: '/roles', permission: 'roles:read' },
      { label: 'Location Master', path: '/locations', permission: 'locations:read' },
      {
        label: 'Role Permission Assignment',
        path: '/role-permissions',
        allPermissions: ['roles:read', 'permissions:read'],
      },
      {
        label: 'Role Location Assignment',
        path: '/role-locations',
        allPermissions: ['roles:read', 'locations:read'],
      },
      {
        label: 'User Role Assignment',
        path: '/user-roles',
        allPermissions: ['users:read', 'roles:read'],
      },
    ],
  },
  {
    label: 'Master Data',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/master-data',
        permission: 'assets:read',
      },
      { label: 'Asset Master', path: '/assets', permission: 'assets:read' },
      { label: 'Asset Calibration', path: '/asset-calibration', permission: 'assets:read' },
    ],
  },
  {
    label: 'Business',
    type: 'dropdown',
    items: [
      { label: 'Module Dashboard', path: '/modules/business', permission: 'dashboard:read' },
    ],
  },
  {
    label: 'Reports',
    type: 'dropdown',
    items: [
      { label: 'Module Dashboard', path: '/modules/reports', permission: 'dashboard:read' },
    ],
  },
  {
    label: 'Back-up',
    type: 'dropdown',
    items: [
      { label: 'Module Dashboard', path: '/modules/backup', permission: 'dashboard:read' },
    ],
  },
  {
    label: 'Auditing',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/auditing',
        permission: 'audit:read',
      },
      { label: 'Audit Trail', path: '/audit', permission: 'audit:read' },
    ],
  },
  {
    label: 'System',
    type: 'dropdown',
    items: [
      { label: 'Module Dashboard', path: '/modules/system', permission: 'system:read' },
    ],
  },
]

export const hiddenRouteLabels = {
  '/users': 'User Master',
  '/roles': 'Role Master',
  '/locations': 'Location Master',
  '/role-permissions': 'Role Permission Assignment',
  '/role-locations': 'Role Location Assignment',
  '/user-roles': 'User Role Assignment',
  '/assets': 'Asset Master',
  '/asset-calibration': 'Asset Calibration',
  '/audit': 'Audit Trail',
}

export const findNavigationItem = (pathname) => {
  let best = null
  for (const group of navigationItems) {
    const candidates = group.type === 'link' ? [group] : group.items || []
    for (const item of candidates) {
      if (!item.path) continue
      const exact = item.path === pathname
      const nested = item.path !== '/' && pathname.startsWith(`${item.path}/`)
      if ((exact || nested) && (!best || item.path.length > best.item.path.length)) {
        best = { item, group }
      }
    }
  }
  return best
}
