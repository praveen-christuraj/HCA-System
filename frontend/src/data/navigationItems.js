/**
 * Top-side navigation (owner rule 3). Groups mirror the module map; every
 * item is permission-filtered. Planned modules link to their honest module
 * dashboard, which states the delivery status.
 */
export const navigationItems = [
  {
    label: 'Home',
    path: '/',
    type: 'link',
    permission: 'View System Dashboard',
  },
  {
    label: 'User Management',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/user-management',
        permission: 'View User Management Dashboard',
      },
      { label: 'User Master', path: '/users', permission: 'View User' },
    ],
  },
  {
    label: 'Master Data',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/master-data',
        permission: 'View System Dashboard',
      },
    ],
  },
  {
    label: 'Business',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/business',
        permission: 'View System Dashboard',
      },
    ],
  },
  {
    label: 'Reports',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/reports',
        permission: 'View System Dashboard',
      },
    ],
  },
  {
    label: 'Back-up',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/backup',
        permission: 'View System Dashboard',
      },
    ],
  },
  {
    label: 'Auditing',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/auditing',
        permission: 'View Auditing Dashboard',
      },
      { label: 'Audit Trail', path: '/audit', permission: 'View Audit Log' },
    ],
  },
  {
    label: 'System',
    type: 'dropdown',
    items: [
      {
        label: 'Module Dashboard',
        path: '/modules/system',
        permission: 'View System Health',
      },
    ],
  },
]

export const hiddenRouteLabels = {
  '/users': 'User Master',
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
