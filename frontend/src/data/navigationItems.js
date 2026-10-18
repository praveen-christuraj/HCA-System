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
    // Assignment, Role Location Assignment, User Role Assignment, followed by
    // Permission Master, User Location Assignment, Access Summary, Profile & Security.
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
      { label: 'Permission Master', path: '/permissions', permission: 'permissions:read' },
      {
        label: 'User Location Assignment',
        path: '/user-locations',
        allPermissions: ['users:read', 'locations:read'],
      },
      {
        label: 'Access Summary',
        path: '/access-summary',
        allPermissions: ['users:read', 'roles:read', 'permissions:read', 'locations:read'],
      },
      { label: 'Profile & Security', path: '/profile-security', permission: 'profile:read' },
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
      { label: 'Asset Assignment', path: '/asset-assignments', permission: 'asset_assignments:read' },
      { label: 'Asset Assignment Summary', path: '/asset-assignment-summary', permission: 'asset_assignments:read' },
      {
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
      { label: 'Location Operation Availability', path: '/location-operation-availability', permission: 'location_operation_availability:read' },
      { label: 'Location Operation Summary', path: '/location-operation-summary', permission: 'location_operation_availability:read' },
      { label: 'Location Accounting Day Setting', path: '/location-accounting-day-settings', permission: 'location_accounting_day_settings:read' },
      { label: 'Company Report Profile Master', path: '/company-report-profiles', permission: 'company_report_profiles:read' },
      { label: 'Material Balance Template Master', path: '/material-balance-template-master', permission: 'material_balance_templates:read' },
      { label: 'Table-11 Factor Master', path: '/table11-factors', permission: 'operation_references:read' },
      { label: 'Flowmeter Configuration Master', path: '/flowmeter-configs', permission: 'operation_references:read' },
      { label: 'Barge Seal Master', path: '/barge-seal-master', permission: 'operation_references:read' },
      { label: 'Operation Workflow Policies', path: '/operation-workflow-policies', permission: 'operation_policies:read' },
      {
        label: 'Operation References',
        path: '/operation-references',
        anyPermission: ['operation_references:read', 'operation_policies:read', 'operation_voyages:read'],
      },
    ],
  },
  {
    label: 'Business',
    type: 'dropdown',
    items: [
      { label: 'Module Dashboard', path: '/modules/business', permission: 'operation_entries:read' },
      { label: 'Operation Entry', path: '/operation-entry', permission: 'operation_entries:read' },
      { label: 'Flowmeter Record Entry', path: '/flowmeter-records', permission: 'flowmeter_records:read' },
      { label: 'Movement Mapping', path: '/movement-mappings', permission: 'movement_mappings:read' },
      { label: 'Operation Task Manager', path: '/operation-tasks', permission: 'operation_tasks:read' },
    ],
  },
  {
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
      { label: 'Correction Requests', path: '/correction-requests', permission: 'correction_requests:read' },
    ],
  },
  {
    label: 'Export Operations',
    type: 'dropdown',
    items: [
      { label: 'Export Dashboard', path: '/export-operations/dashboard', permission: 'export_operations:read' },
      { label: 'Export Transactions', path: '/export-operations/transactions', permission: 'export_operations:read' },
      { label: 'Export Reports', path: '/export-operations/reports', permission: 'export_operations:read' },
      { label: 'Export Permits', path: '/export-operations/permits', permission: 'export_operations:read' },
      { label: 'Export Locations', path: '/export-operations/locations', permission: 'export_operations:read' },
      { label: 'Export Entities', path: '/export-operations/entities', permission: 'export_operations:read' },
      { label: 'Export Blocks', path: '/export-operations/blocks', permission: 'export_operations:read' },
      { label: 'Export Consignees', path: '/export-operations/consignees', permission: 'export_operations:read' },
      { label: 'Export Settings', path: '/export-operations/settings', permission: 'export_operations:read' },
    ],
  },
  {
    label: 'Reports',
    type: 'dropdown',
    items: [
      { label: 'Module Dashboard', path: '/modules/reports', permission: 'dashboard:read' },
      { label: 'Tank Operation Summary', path: '/tank-operation-summary', permission: 'reports:read' },
      { label: 'Out-Turn Summary', path: '/out-turn-summary', permission: 'reports:read' },
      { label: 'Material Balance Report', path: '/material-balance-report', permission: 'reports:read' },
      { label: 'Tanker Transaction Report', path: '/tanker-transaction-report', permission: 'tanker_transaction_reports:read' },
    ],
  },
  {
    label: 'Back-up',
    type: 'dropdown',
    items: [
      { label: 'Module Dashboard', path: '/modules/backup', permission: 'dashboard:read' },
      { label: 'Backup & Recovery', path: '/backup-recovery', permission: 'backup_recovery:read' },
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
      { label: 'System Notification Master', path: '/system-notifications', permission: 'system_notifications:read' },
      { label: 'Database Browser', path: '/database-browser', permission: 'database_browser:read' },
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
  '/permissions': 'Permission Master',
  '/user-locations': 'User Location Assignment',
  '/access-summary': 'Access Summary',
  '/profile-security': 'Profile & Security',
  '/assets': 'Asset Master',
  '/asset-calibration': 'Asset Calibration',
  '/asset-assignments': 'Asset Assignment',
  '/asset-assignment-summary': 'Asset Assignment Summary',
  '/prime-mover-tanker-links': 'Prime Mover-Tanker Link',
  '/operation-types': 'Operation Types',
  '/operations': 'Operation Master',
  '/location-operation-availability': 'Location Operation Availability',
  '/location-operation-summary': 'Location Operation Summary',
  '/location-accounting-day-settings': 'Location Accounting Day Setting',
  '/company-report-profiles': 'Company Report Profile Master',
  '/material-balance-template-master': 'Material Balance Template Master',
  '/table11-factors': 'Table-11 Factor Master',
  '/flowmeter-configs': 'Flowmeter Configuration Master',
  '/barge-seal-master': 'Barge Seal Master',
  '/operation-workflow-policies': 'Operation Workflow Policies',
  '/operation-references': 'Operation References',
  '/operation-entry': 'Operation Entry',
  '/flowmeter-records': 'Flowmeter Record Entry',
  '/movement-mappings': 'Movement Mapping',
  '/operation-tasks': 'Operation Task Manager',
  '/operation-transactions': 'Operation Transaction Register',
  '/barge-tracking': 'Barge Tracking',
  '/tanker-tracking': 'Tanker Tracking',
  '/shuttle-tracking': 'Shuttle Tracking',
  '/fso-tracking': 'FSO Tracking',
  '/tanker-transaction-report': 'Tanker Transaction Report',
  '/correction-requests': 'Correction Requests',
  '/export-operations/dashboard': 'Export Operations Dashboard',
  '/export-operations/transactions': 'Export Transactions',
  '/export-operations/reports': 'Export Reports',
  '/export-operations/permits': 'Export Permits',
  '/export-operations/locations': 'Export Locations',
  '/export-operations/entities': 'Export Entities',
  '/export-operations/blocks': 'Export Blocks',
  '/export-operations/consignees': 'Export Consignees',
  '/export-operations/settings': 'Export Settings',
  '/tank-operation-summary': 'Tank Operation Summary',
  '/out-turn-summary': 'Out-Turn Summary',
  '/material-balance-report': 'Material Balance Report',
  '/backup-recovery': 'Backup & Recovery',
  '/system-notifications': 'System Notification Master',
  '/database-browser': 'Database Browser',
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
