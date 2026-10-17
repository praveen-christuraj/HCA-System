# Prime Mover-Tanker Link and Configurations — 2026-10-17

## Summary

Imported the OTMS **Prime Mover-Tanker Link** module under **Master Data**, and created a new
top-level **Configurations** module next to it. Configurations holds the hard-coded **Operation
Types** and their **categories with stock signs**, and the location-scoped **Operation Master**
that will feed the Operation Entry dropdowns. Operation Entry itself is not part of this delivery
and waits for owner confirmation (ADR-019).

OTMS reference: <https://github.com/praveen-christuraj/hydrocarbon-accounting-otms> (HEAD 5eed361).

## Delivered

### Prime Mover-Tanker Link (Master Data)

- Model `prime_mover_tanker_links`: foreign keys to two `assets` rows (`PRIME_MOVER` and
  `TANKER_TRAILER`), `linked_from`, `linked_to`, `remarks`, `status` (Active/Inactive), audit
  columns. The chassis number is the asset's `serial_number`.
- Validation uses exact asset type codes, not text guessing as in OTMS. Both assets must exist and
  be Active for a new Active link. `linked_to` cannot be before `linked_from`. Only one Active link
  is allowed per prime mover and per tanker, case-insensitively, and an update excludes its own row.
- Endpoints: list (status, asset and linked-from filters; order by status, linked-from desc, id desc),
  `options`, `current-by-prime-mover/{id}`, `current-by-tanker/{id}`, create, get, update, close,
  delete, export (CSV/XLSX/PDF), import preview and commit.
- Close sets `linked_to` (defaults to today), appends `Close Remarks: …` to the remarks, and sets
  the link Inactive. A link that is already closed returns 409.
- Delete is permanent (default decision). Close is treated as an update action, so it uses the
  `update` permission.
- Import creates a link, or updates an existing one matched on prime mover + tanker +
  linked-from. A file is rejected as a whole when any row is invalid.
- Permissions: `prime_mover_tanker_links:read/create/update/delete` under Master Data Management.
- Audit: create, update, close and delete write snapshots with before and after values. Import
  and export are audited as Import and Export categories.
- UI: list with server pagination (20/50/100/200), quick search, advanced filters (status, prime
  mover, tanker), an independent linked-from date group, Active-only selects that show chassis
  numbers, a live warning in the dialog when a chosen asset already has another Active link, close
  dialog, permanent delete confirmation pop-up, import and export.

### Configurations

- **Operation Types** (`app/utils/operation_types.py`, hard coded, ADR-019): Tank Operations →
  Storage Tank, Barge Operations → Barge, Shuttle Operations → Shuttle, FSO Operations → FSO,
  Tanker Operations → Tanker Trailer, Flowmeter Operations → Flowmeter. A Prime Mover has no
  operation of its own.
- **Categories and signs**: OPENING STOCK=SET, RECEIPT=IN, DISPATCH=OUT, EXPORT=OUT,
  CLOSING STOCK=SET, DRAINING=OUT, DECANTING=OUT, ITT=NEUTRAL. SET overrides the stock, IN adds,
  OUT subtracts, NEUTRAL is accounted but does not override.
- **Operation Master** (`operations` table): location-scoped operations of a fixed type and
  category. The sign is derived from the category on every write and is never accepted from the
  client. A code and a name are unique per (location, type), ignoring case, across every status.
  An Active operation needs an Active location.
- Operation Master lifecycle: create, edit, deactivate (kept for history, 409 if already
  Inactive; no delete route), import (create-only, validated as a whole), export (CSV/XLSX/PDF).
  Filters include the fixed type and category, location, status, search and a created-date group.
  Non-admin users see only their assigned locations.
- **Read-only endpoints**: `GET /api/operation-types` and `GET /api/operation-types/categories`
  return the catalogue with live counts. There is no write route for the catalogue.
- Permissions: `operation_types:read`; `operations:read/create/update/delete`.
- UI: Configurations group in the top navigation (Module Dashboard, Operation Types, Operation
  Master). The Operation Types page shows the catalogue, the categories and the sign legend. The
  Operation Master uses the same toolbar, table and dialog pattern as Asset Master, with the sign
  shown live as the category is chosen.
- Module dashboard: live KPIs (operation types, categories, active operations, locations
  configured), status breakdown per type and quick links.

### Shared

- `components/common/ConfirmDialog.jsx` extracted from Permission Presets. It replaces
  `window.confirm` for new delete and deactivate actions and keeps the same markup.
- `utils/default_permissions.py` registers the three new resources (39 standard rows in total).
- `middleware.py` maps the three new prefixes to module names and categories for the audit fallback.
- Navigation, routes and `hiddenRouteLabels` are updated.

## Default decisions (for owner review)

1. **Link delete is permanent**, with a confirmation pop-up. Close is the way to keep history.
2. **Close is an update action** (`prime_mover_tanker_links:update`).
3. **Operation categories are global**: every operation type may use every category.
4. **Operations are deactivated, not deleted**, and their code and name stay reserved.
5. **Operation import is create-only.** Existing codes are rejected rather than overwritten.

## Scope exclusions

- **OTMS Tracking Module Configuration** (maps operation types to BARGE/TANKER tracking) is not
  part of this delivery.
- **Operation Entry** is not started. It waits for owner confirmation.

## Verification

- `cd backend && python -m pytest -q` → **116 passed, 1 warning**. New: 18 link tests
  (`tests/test_prime_mover_tanker_links.py`) and 18 Configurations tests
  (`tests/test_configurations.py`). Two earlier test drafts had incorrect expectations (preview
  returns 200 with row errors, and the commit is what returns 422). The tests and the code
  were aligned, and the dashboard module-branch scope bug was fixed.
- `cd frontend && npm run build` → **success** (Vite 8.3.4, 74 modules). Main chunk is 515 kB,
  above the 500 kB warning threshold (it was 473 kB before). Code splitting is not yet applied.
- Headless Chromium against the live backend and Vite proxy (seeded data): Prime Mover-Tanker
  Link (light), Operation Master, Operation Types and the Configurations dashboard (dark). No
  console or page errors were recorded.
- **Not verified in a browser**: dialogs (link, close, operation, deactivate, delete, import), the
  live conflict warning, light theme of the Configurations pages, and the Permission Presets confirm
  dialog after extraction. Export file contents were checked by header only (`PK` for XLSX, `%PDF`
  for PDF).
- PostgreSQL deployment schema was not run in this delivery.
