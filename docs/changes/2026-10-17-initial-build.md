# Initial build — 2026-10-17

## Purpose

Stand up HCA System as a working rebuild of OTMS: the same application architecture and
deployment shape, with the changed structures the owner requires (no JSON storage, top-side
navigation, mandatory light/dark themes, 20/50/100/200 pagination, XLSX/CSV import and export,
PDF export, module dashboards, audit + RBAC everywhere). The first vertical slice must be real
enough to sign in, navigate, read the audit trail and manage users.

## Scope delivered

1. Repository scaffold: backend, frontend, PostgreSQL, compose, Makefile, environment template,
   permanent memory under `docs/`.
2. Authentication: login, 2FA verification, refresh rotation, logout revocation, forgot-password
   request, change password, security profile.
3. Identity and access: users, roles, permissions, per-role permission assignment, reserved
   Admin role.
4. Auditing: server audit trail, middleware fallback, browser UI-event capture.
5. Dashboards: system summary and module dashboards.
6. User Master: list, filters, detail, export, import.
7. Audit Trail: list, filters, export.
8. Design system and application shell (top navigation only, light/dark/system themes).
9. Test suite (19 tests).

## Design decisions applied

- **Rule 4 — no JSON columns.** OTMS stores `AuditLog.details` as JSON/JSONB and arrays of
  backup codes in JSON. HCA System stores audit context in typed columns
  (`details_summary` text plus discrete entity fields) and keeps recovery codes in their own
  table. A regression test asserts that no model column uses the `JSON` type.
- **Rule 3 — top-side navigation.** The shell renders a navy brand bar, a white navigation
  band with permission-filtered dropdown groups, and a user menu. There is no sidebar.
- **Rule 2 — themes.** `ThemeProvider` stores `hca.theme` as `light | dark | system`, applies
  `data-theme` to `<html>` and follows `prefers-color-scheme` when set to system. Both themes
  are token-driven; no component hardcodes a colour.
- **Rule 14 — seeding as part of the container.** `backend/docker-entrypoint.sh` waits for
  PostgreSQL, runs `init_db()` (creates tables), seeds permissions and the Admin role, then
  creates the administrator only when absent. Credentials are printed once. The Docker build
  also imports the seed module so an unbuildable seed fails the image, not the deployment.
- **Rule 11 — RBAC + audit by default.** Every router uses `require_permission(...)`; the API
  middleware writes an audit fallback for mutating requests that did not create a specific
  record, so a forgotten call cannot produce an unaudited write.

## Database

New schema, created by `init_db()` on first start:

| Table | Purpose |
| --- | --- |
| `users` | Account, profile, lockout, 2FA and lifecycle columns (no JSON). |
| `roles` | Role definition and reserved-admin flag. |
| `permissions` | Catalog with category, module key and description. |
| `role_permissions` | Many-to-many grant table. |
| `user_roles` | Many-to-many assignment table. |
| `audit_logs` | Immutable audit trail with typed context columns. |
| `refresh_tokens` | Server-side refresh-token record with `jti`, revocation and rotation. |
| `password_reset_requests` | Audited reset requests with requester and reason. |
| `password_history` | Previous hashes for reuse prevention. |

## API changes

New API surface under `/api` (37 routes): `health`, `system/status`, `auth/*`, `users`
(+ `export`, `import`, `/{id}/roles`, `/{id}/reset-password`), `roles`, `permissions`,
`audit-logs` (+ `export`, `ui-events`), `dashboard/summary`, `dashboard/modules/{key}`.

## RBAC and audit impact

- Permissions introduced: 26, grouped as Platform, User Management, Auditing and Reporting,
  System.
- `Export User` and `Export Audit Log` gate spreadsheet/PDF downloads; `Create User` gates
  import commits; imports preview without the write permission being exercised.
- Import and export produce dedicated audit rows. Import rejects partial commits: all rows must
  validate before anything is written.
- Failed sign-ins, lockouts, refresh reuse, logout and permission checks that deny access are
  audited.

## UI changes

- New token set (`frontend/src/styles/tokens.css`) with paired light/dark values, including
  `--button-primary-bg`, `--button-primary-hover` and `--button-primary-text`.
- New shell: brand bar, navigation band, dropdown menus with keyboard support, user menu with
  theme selection, footer.
- Login page mirrors the OTMS split-panel identity: navy panel with brand lockup and values,
  light form panel with password reveal, strength meter, 2FA challenge and reset request.
- User Master and Audit Trail use the shared page kit (heading, KPI/stat rows, toolbar,
  advanced filters, separate date group, table, pagination, export).
- Import dialog: file selection, CSV template download, server-side preview table with row
  errors, then a single explicit commit action.

## Migration and rollback

No prior schema exists. Rollback is `docker compose down -v` (destroys the volume) and
redeploying the previous image; the database is created and seeded automatically on start.

## Verification

```
cd backend && .venv/bin/python -m pytest -q          # 19 passed
cd frontend && npm run build                         # success
curl http://127.0.0.1:8000/api/health                # status ok, admin_seeded true
curl http://127.0.0.1:5173/api/health                # same, through the Vite proxy
```

Manual smoke: sign in as `admin`, confirm 26 permissions in `/auth/me`, open User Master and
Audit Trail, export CSV/XLSX/PDF, import a CSV, switch theme.

## Follow-ups

- Create/edit user dialogs, role assignment and password reset screens.
- Master Data, Business, Reports and Back-up module implementation.
- Per-module dashboards for the planned modules.
- Optional CSV/PDF row limits surfaced in the UI.
