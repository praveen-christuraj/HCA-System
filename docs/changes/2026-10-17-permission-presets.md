# Permission Presets — 2026-10-17

## Summary

Added a **Permission Preset** module so an administrator can save a named set of standard
permissions once and apply it to a role — or to many roles at once — instead of ticking every
permission for every role. The catalog is capped at **20 presets** (`MAX_PERMISSION_PRESETS`), each
preset is named, and applying one is an explicit **replace** or **add** action that is audited per
role. Presets are templates only: applying one copies permission ids into `role_permissions`, so a
role's effective access is still read from `role_permissions` alone (ADR-018).

References used: **OTMS** for the master/assignment page structure and **Costing** for the
`resource:action` capability model and UI craft. No other repository was used.

## Delivered

### Backend

- Two new typed tables, no JSON columns (rule 4):
  - `permission_presets` — `preset_name` (unique, 2–120 characters), `description`, `status`,
    `times_applied`, `last_applied_at`, `created_by_user_id`, `updated_by_user_id`,
    `created_at`, `updated_at`.
  - `permission_preset_items` — one row per permission in a preset, unique on
    `(preset_id, permission_id)`, `ON DELETE CASCADE` to the preset and to the permission.
- New router `backend/app/routers/permission_presets.py`:

  | Endpoint | Capability | Behaviour |
  | --- | --- | --- |
  | `GET /api/permission-presets` | `permission_presets:read` | Server pagination (20/50/100/200), quick search, status / module / contains-permission filters, separate created-date range, plus `statuses`, `modules`, `preset_limit`, `presets_used`, `presets_remaining`. |
  | `GET /api/permission-presets/options` | `permission_presets:read` | Compact active-preset list for the assignment page. |
  | `GET /api/permission-presets/{id}` | `permission_presets:read` | Detail with the stored permission rows, active ids and deactivated-permission count. |
  | `POST /api/permission-presets` | `permission_presets:create` | Create; refuses the 21st preset (409), duplicate names (409, case-insensitive), empty or unknown/inactive permission sets (422) and permissions the actor does not hold (403). |
  | `PUT /api/permission-presets/{id}` | `permission_presets:update` | Rename, re-describe, reactivate/deactivate and rewrite the permission rows; returns `added`/`removed`; an active preset must keep at least one active permission. |
  | `DELETE /api/permission-presets/{id}` | `permission_presets:delete` | Soft deactivation by default. `?permanent=true` erases the rows and frees a cap slot, refused (409) once `times_applied > 0`. |
  | `POST /api/permission-presets/{id}/apply` | `permission_presets:read` **and** `assignments:write` | Applies the preset to 1–200 roles in `replace` or `add` mode. Validates every role before writing any grant; refuses the reserved Admin role (403), inactive roles/presets (422), unknown or duplicate role ids (422); enforces the "no grants outside your own access" rule for non-administrators. |
  | `GET /api/permission-presets/export` | `permission_presets:read` | CSV/XLSX/PDF, respects the current filters, one row per preset with semicolon-separated permission keys (the import shape), audited with format, row count and filter summary. |
  | `POST /api/permission-presets/import` | `permission_presets:create` | CSV/XLSX preview-then-commit. Columns `preset_name`, `permission_names` (semicolon-separated), optional `description`, `status`; aliases `name`/`preset`/`permissions`/`permission_keys` accepted. Every row is validated before anything is written: unknown or inactive keys, duplicate names (file and database), missing names, empty permission sets, bad status, and the remaining cap slots are all reported per row. |

- `require_all_permissions(...)` added to `app/dependencies/permissions.py` for actions that belong
  to two capabilities at once (reading the preset catalog **and** writing role grants).
- `AuditMiddleware` maps `/api/permission-presets` to the `Permission Presets` module, so any
  mutation the router did not already record still lands in the trail.
- User Management dashboard: `Permission presets` KPI (`active / 20` with saved count and total
  applications), a `Permission Presets` quick link, and `Permission Presets` added to the module's
  audited-activity set. The portfolio module card now reports presets instead of a duplicate
  locations count.

### RBAC and audit

- Registered the standard resource `permission_presets` (`read`, `create`, `update`, `delete`) in
  `RESOURCE_PERMISSION_DEFINITIONS`, module **Permission Presets**, category **User Management**
  (rule 11). Bootstrap provisions the four rows idempotently and grants them to the reserved Admin
  role; the catalog grows from 26 to 30 permissions on startup, with no manual seed step.
- Applying a preset writes one audit row **per role** (`Role Permission Assignment` /
  `Apply Permission Preset`) carrying `preset_id`, `preset`, `mode`, `added`, `removed` and `total`,
  and updates `times_applied` / `last_applied_at` on the preset. Preset create, update,
  deactivation, permanent delete, import preview, import commit and export are each audited with
  typed columns and a human-readable `details_summary`.
- Frontend actions that never reach a mutation endpoint (staging a preset onto the selection,
  filters, pagination, dialog outcomes) are persisted through `POST /api/audit/ui-events`.

### Frontend

- New page **Permission Presets** (`/permission-presets`), added to the User Management dropdown
  between Location Master and Role Permission Assignment, gated by `permission_presets:read`.
  It provides the standard toolbar (quick search, advanced filters, separate created-date group,
  removable filter chips), server pagination, CSV/XLSX/PDF export, CSV/XLSX import with
  preview-and-confirm, a `2 / 20 presets` slot indicator, and per-row **Apply**, **Edit**,
  **Deactivate** and (only when never applied) **Delete** actions.
- Preset dialog: name, description, status, a "load permissions from a role" shortcut, and the
  grouped permission picker with module select-all, a live `n of m selected` counter and clear.
  An empty selection is blocked inline before any request; a rejected name or cap error is shown
  inside the dialog, which closes only via Cancel or a successful save (rule 10). Deactivated
  catalog permissions are excluded from the picker with an explicit warning.
- Apply dialog: replace/add mode cards (replace warns that grants outside the preset are removed),
  searchable role list limited to active, non-reserved roles, select-listed/clear-listed, a live
  "Apply to n role(s)" button and an inline result summary (`+7 / −1 grants`).
- Role Permission Assignment now has a **preset bar**: choose a preset, see the exact delta
  (`replace adds 3 and removes 1 · add grants 3`), then **Replace selection** or **Add to
  selection**. Staging is reviewable and discardable; the write still goes through the existing
  audited `PUT /api/roles/{id}/permissions`. **Save selection as preset** stores the current
  selection as a new named preset (disabled when no slot is free). The bar is hidden for the
  reserved Admin role and for inactive roles.
- Navy/white tokens only, no emoji, no decorative animation; new styles
  (`.preset-bar`, `.preset-picker`, `.preset-mode-*`, `.preset-role-scroll`,
  `.preset-module-chip`) are theme-token based, so light and dark both resolve. Two icons added to
  the existing stroke set (`layers`, `copy`).

## Database changes

`SQLAlchemy create_all` adds `permission_presets` and `permission_preset_items` on startup; no
existing table changes and no Alembic baseline is introduced (consistent with the rest of the
project). Compiled through the PostgreSQL dialect the two tables are well formed: bounded
`VARCHAR(120)`/`VARCHAR(20)`, `TEXT` description, `INTEGER` counters, `TIMESTAMP WITHOUT TIME
ZONE`, `SERIAL` keys, both foreign keys with explicit `ON DELETE` rules, and
`CONSTRAINT unique_preset_permission UNIQUE (preset_id, permission_id)`. No JSON type appears.

## Migration and rollback

- Upgrade: start the API. Bootstrap creates the two tables, provisions the four new catalog
  permissions and grants them to Admin. Nothing else changes; existing roles, grants and presets are
  untouched.
- Rollback: remove the router registration and the `permission_presets` resource definition. The
  two tables are inert without the router (no role reads them), so leaving them in place is safe;
  dropping them loses only template data, never a role's effective permissions.

## Verification

- `cd backend && ./.venv/bin/python -m pytest -q` → **80 passed, 1 warning** (70 pre-existing +
  10 new in `tests/test_permission_presets.py`): CRUD and validation, duplicate/unknown/empty
  permission sets, soft deactivation and reactivation, the permanent-delete rule, the 20-preset cap
  (including the per-row cap error on import and slot release after a permanent delete), filters,
  date range and page-size snapping, replace/add application to one and many roles, idempotent
  re-application, all apply guards, non-administrator RBAC (403 on create/update/delete/apply and
  the "permissions you do not hold" rule), CSV/XLSX import preview-and-commit, three-format export
  and dashboard/navigation metadata.
- `cd frontend && npm run build` → **success** (Vite 8.3.4, 68 modules).
- Live HTTP smoke test through uvicorn and the Vite dev proxy → **78/78 checks**, covering login,
  the four new Admin grants, preset create/list/options/detail/update, replace-then-add
  application (role ends with exactly the preset, then the union), apply guards, three-format
  export, import preview/commit and rejection, deactivate → apply refused → reactivate, permanent
  delete of an unapplied preset and refusal of an applied one, filling the catalog to exactly 20
  and refusing the 21st, freeing slots, eight distinct audit actions, both dashboards, and a
  non-admin viewer's 403s (with the denial audited).
- DOM harness (temporary, jsdom + React 19 `createRoot`, stubbed API — not committed) →
  **58/58 checks** on the real components: page render, slot indicator, per-row action visibility,
  quick search issuing `search=…`, advanced filter selects, separate date group, preset dialog
  picker counters, module select-all, clear, inline empty-preset error, inline 409 from the API,
  apply dialog role eligibility and mode switching, apply request body, deactivate request,
  permanent-delete confirmation, and on Role Permission Assignment the hidden preset bar for Admin,
  preset loading, delta preview, replace/add staging, unsaved-changes state, save through the role
  endpoint, discard, and save-selection-as-preset.
- Not verified (honest): a manual light/dark browser review of the new page (no browser binary is
  installable in this sandbox — the DOM harness covers behaviour, not rendered colours), and
  `create_all` against a live PostgreSQL server (the dialect DDL was compiled and checked instead).
