# 2026-10-18 — Full OTMS Module Parity Across User Management, Master Data, Configurations, Business, Export Operations, Reports, Backup & System

## Summary

Ported the remaining operational, configuration, reporting, export, backup, and system modules from `hydrocarbon-accounting-otms` into HCA System while preserving all core OTMS business logic and adhering strictly to HCA System's 15 standing rules and architectural decisions (ADR-001 through ADR-022).

## Delivered Modules & Endpoints

1. **User Management & Profile Security**:
   - **Permission Master** (`/permissions`, `/api/permissions`, `/api/permissions/export`): Read-only catalog of all 119 `resource:action` permissions with search, module/action filters, date range filter, pagination, and CSV/XLSX/PDF export.
   - **User Location Assignment** (`/user-locations`, `/api/user-locations`): Direct user-to-location scope assignments (`user_locations` table) and `users.all_locations_access` flag, integrated into `get_user_location_ids` alongside role-inherited locations, with CSV/XLSX import preview/commit and CSV/XLSX/PDF export.
   - **Access Summary** (`/access-summary`, `/api/access-summary`): Consolidated effective access matrix showing roles, permissions, direct/role/effective locations, and 2FA status, with CSV/XLSX/PDF export.
   - **Profile & Security** (`/profile-security`, `/modules/profile`, `/api/auth/2fa/*`, `/api/auth/password-reset-requests*`): Self-service password change, RFC-6238 TOTP 2FA setup/enable/disable, single-use backup code regeneration, and administrator password reset request queue.

2. **Master Data Management**:
   - **Asset Assignment** (`/asset-assignments`, `/api/asset-assignments`) and **Asset Assignment Summary** (`/asset-assignment-summary`, `/api/asset-assignments/summary`): Assign assets to locations, users, or operational units with single-active-assignment enforcement, import preview/commit, and CSV/XLSX/PDF export.

3. **Configurations**:
   - **Location Operation Availability** (`/location-operation-availability`, `/api/location-operation-availability`) and **Location Operation Summary** (`/location-operation-summary`, `/api/location-operation-availability/summary`).
   - **Location Accounting Day Setting** (`/location-accounting-day-settings`, `/api/location-accounting-day-settings`) with overlap validation and date-shift calculation for FSO and Material Balance reports.
   - **Company Report Profile Master** (`/company-report-profiles`, `/api/company-report-profiles`) with active default profile enforcement.
   - **Material Balance Template Master** (`/material-balance-template-master`, `/api/material-balance-templates`) with typed child tables (`material_balance_template_columns`, `material_balance_template_column_operations`).
   - **Operation References shortcuts** (`/table11-factors`, `/barge-seal-master`, `/flowmeter-configs`, `/operation-workflow-policies`) and **Flowmeter Configuration Change History** (`flowmeter_config_history` table, `/api/flowmeter-configs/history`).

4. **Business & Operation Tracking**:
   - **Flowmeter Record Entry** (`/flowmeter-records`, `/api/flowmeter-records`): Standalone flowmeter reading register with automatic gross/MF/CTL/CPL/GSV/NSV calculation, import preview/commit, and CSV/XLSX/PDF export.
   - **Movement Mapping** (`/movement-mappings`, `/api/movement-mappings`): Cross-location sender-to-receiver operation pairing with typed child items (`movement_mapping_items`).
   - **Operation Task Manager** (`/operation-tasks`, `/api/operation-tasks`): Workflow inbox synchronized automatically with `OperationEntry` lifecycle transitions (`Submitted`, `Reviewed`, `Approved`, `Rejected`, `Recalled`, `Cancelled`) using typed `operation_tasks`, `operation_task_roles`, `operation_task_users`, and `operation_task_events` tables.
   - **Correction Requests** (`/correction-requests`, `/api/correction-requests`): Maker-checker workflow (`approved_transaction_correction_requests`) to request, approve, or reject revoking an `Approved` operation entry back to `Draft` for correction while reversing its `OperationPosting`.

5. **Export Operations** (`/export-operations/*`, `/api/export-operations/*`):
   - Complete suite of 9 pages and 10 typed tables: **Export Dashboard**, **Export Transactions** (multi-block Bill of Lading allocation with permit limit checks and override), **Export Reports** (Entity/Quarter, Location/Entity, Block/Permit, Country/Consignee), **Export Permits** (with block assignments), **Export Locations** (with entity links), **Export Entities** (with equity split validation), **Export Blocks**, **Export Consignees**, and **Export Settings**.

6. **Report Modules** (`/modules/reports`, `/api/reports/*`):
   - **Tank Operation Summary & Stock Ledger** (`/tank-operation-summary`, `/api/reports/tank-operation-summary`, `/api/reports/tank-stock-ledger`) with daily reconciliation and variance tracking.
   - **Out-Turn Summary Report** (`/out-turn-summary`, `/api/reports/out-turn-summary`) with customizable column builder (`out_turn_summary_configs`, `out_turn_summary_config_columns`).
   - **Material Balance Report** (`/material-balance-report`, `/api/reports/material-balance`) driven by Material Balance Templates and Location Accounting Day windows.

7. **Back-up & System Modules** (`/modules/backup`, `/modules/system`):
   - **Backup & Recovery** (`/backup-recovery`, `/api/backup-recovery/*`): Real SQLite/archive snapshot creation in `backend/backups/`, SHA-256 checksum verification, download, restore request workflow, and pre-restore validation (`backup_settings`, `backup_jobs`, `backup_restore_requests`, `backup_restore_validations`).
   - **System Notification Master** (`/system-notifications`, `/api/system-notifications`): Targeted broadcasts (`All`, `Role`, `User`, `Location`) with typed target and read-receipt tables.
   - **Database Browser** (`/database-browser`, `/api/database-browser/tables`): Read-only SQLAlchemy inspector and paginated row viewer with sensitive credential column redaction and CSV/XLSX/PDF export.

## Verification

- **Database Schema Invariant (Rule 4)**: 82 tables total in `Base.metadata.tables`, **0 JSON/JSONB columns** verified by `test_no_json_database_columns` and `test_zero_json_columns_across_all_models`.
- **RBAC Catalog (Rule 11)**: 119 standard `resource:action` permissions across 29 resources seeded idempotently.
- **Backend Test Suite**: `.venv/bin/python -m pytest -q` → **201 passed, 1 warning**.
- **Frontend Production Build**: `npm run build` → succeeded (`dist/` built cleanly).
