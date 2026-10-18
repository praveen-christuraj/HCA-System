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
        // Named, reusable permission sets (capped at 20) applied to roles.
        label: 'Permission Presets',
        path: '/permission-presets',
        permission: 'permission_presets:read',
      },
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
      {
        // Prime movers and the tanker trailers they pull, with one Active link each.
        label: 'Prime Mover-Tanker Link',
        path: '/prime-mover-tanker-links',
        permission: 'prime_mover_tanker_links:read',
      },
    ],
  },
  {
    label: 'Configurations',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/configurations',
        permission: 'operation_types:read',
      },
      { label: 'Operation Types', path: '/operation-types', permission: 'operation_types:read' },
      { label: 'Operation Master', path: '/operations', permission: 'operations:read' },
      { label: 'Operation References', path: '/operation-references', anyPermission: ['operation_references:read', 'operation_policies:read', 'operation_voyages:read'] },
    ],
  },
  {
    label: 'Business',
    type: 'dropdown',
    items: [
      { label: 'Module Dashboard', path: '/modules/business', permission: 'operation_entries:read' },
      { label: 'Operation Entry', path: '/operation-entry', permission: 'operation_entries:read' },
    ],
  },
  {
    // OTMS tracking modules: the ticket workflow register plus movement tracking.
    label: 'Operation Tracking',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/operation-tracking',
        anyPermission: [
          'operation_transactions:read',
          'barge_tracking:read',
          'tanker_tracking:read',
          'shuttle_tracking:read',
          'fso_tracking:read',
          'tanker_transaction_reports:read',
        ],
      },
      { label: 'Operation Transaction Register', path: '/operation-transactions', permission: 'operation_transactions:read' },
      { label: 'Barge Tracking', path: '/barge-tracking', permission: 'barge_tracking:read' },
      { label: 'Tanker Tracking', path: '/tanker-tracking', permission: 'tanker_tracking:read' },
      { label: 'Shuttle Tracking', path: '/shuttle-tracking', permission: 'shuttle_tracking:read' },
      { label: 'FSO Tracking', path: '/fso-tracking', permission: 'fso_tracking:read' },
      { label: 'Tanker Transaction Report', path: '/tanker-transaction-report', permission: 'tanker_transaction_reports:read' },
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
  '/permission-presets': 'Permission Presets',
  '/role-permissions': 'Role Permission Assignment',
  '/role-locations': 'Role Location Assignment',
  '/user-roles': 'User Role Assignment',
  '/assets': 'Asset Master',
  '/asset-calibration': 'Asset Calibration',
  '/prime-mover-tanker-links': 'Prime Mover-Tanker Link',
  '/operation-types': 'Operation Types',
  '/operations': 'Operation Master',
  '/operation-entry': 'Operation Entry',
  '/operation-references': 'Operation References',
  '/operation-transactions': 'Operation Transaction Register',
  '/barge-tracking': 'Barge Tracking',
  '/tanker-tracking': 'Tanker Tracking',
  '/shuttle-tracking': 'Shuttle Tracking',
  '/fso-tracking': 'FSO Tracking',
  '/tanker-transaction-report': 'Tanker Transaction Report',
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
