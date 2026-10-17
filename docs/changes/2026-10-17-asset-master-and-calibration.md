# 2026-10-17 — User Management regrouping and the Asset & Calibration module

## What changed

### 1. Location Master and Role Location Assignment moved under User Management

Both pages moved out of Master Data into the User Management group, in the order the owner
specified:

1. User Master
2. Role Master
3. Location Master
4. Role Permission Assignment
5. Role Location Assignment
6. User Role Assignment

The `locations` permission resource moved to the `User Management` catalog category. Bootstrap
migrates existing rows idempotently, so no manual data change is needed. The User Management
module dashboard now carries a Locations KPI and quick links to both pages; the Location Master
page eyebrow reads `USER MANAGEMENT / LOCATION MASTER`.

Master Data Management is now the asset module and is gated by `assets:read`.

### 2. Master Data Management — Asset Master and Asset Calibration

Combines what OTMS kept as three separate masters (asset type, asset, calibration template) into
one module.

**Asset types are hard coded.** Seven fixed types — Storage Tank, Barge, Shuttle Vessel, FSO,
Prime Mover, Tanker Trailer, Flowmeter — in `backend/app/utils/asset_types.py`. There is no
`asset_types` table and no CRUD. The catalog drives the dropdown, validation, and whether a type
carries tanks or takes calibration. Import aliases fold onto one code (`YADE` → `BARGE`), so OTMS
data imports cleanly.

**Assets are asset-type scoped.** `asset_scope` is `Local` or `Global`. A Local asset must sit on
an active location; a Global asset carries none. Non-admin users see global assets plus assets in
their assigned locations, reusing the Role Location Assignment configuration.

**Tanks are declared with the asset.** Typed `asset_tanks` child table, unique on
`(asset_id, tank_name)`, edited in the same dialog. A barge declares 1P, 1S, 2P and so on; the
calibration chart is keyed by those exact names. Prime Mover and Flowmeter reject tank
declarations and cannot be marked as requiring calibration.

**Calibration is simplified to three columns.** A chart is always tank name, dip/ullage, volume.
The template column designer is gone — the shape is fixed in code, and the user supplies only the
measurement basis and the units the file is written in.

**Units and canonical storage.** Depth may be supplied in cm, mm or m; volume in litres,
kilolitres or barrels. Everything is converted once on the way in and stored as typed `Numeric`
columns in canonical **cm** and **bbl**, next to the values as supplied. Basis: 1 bbl =
158.987294928 L = 0.158987294928 m³ — the same constant OTMS used, so results reconcile.

**Upload accepts two shapes.** The canonical long table, and the wide matrix a printed barge or
FSO calibration book uses (depths down the rows, one column per tank). Both normalise to the same
rows.

**Interpolation.** 2D is depth → volume inside one tank; 3D resolves the tank name exactly first,
then runs the 2D curve — a barge's `2P` can never return `2S`'s volume. One active chart per
asset; a new upload replaces it and the audit row records the row count and chart name replaced.

## Where it differs from OTMS, deliberately

| Area | OTMS | HCA System |
| --- | --- | --- |
| Asset types | Editable `asset_types` table; tracking guessed a barge from free text | Closed catalog of seven types in code; aliases fold onto one code |
| Tanks | No tank master; tank identity lived inside calibration rows | Typed `asset_tanks`, declared with the asset, foreign-keyed from chart rows |
| Calibration schema | User-designed template columns with `interpolation_role` | Fixed three columns; no designer |
| Calibration rows | `row_data JSONB` keyed by invented names | Typed `Numeric` columns in canonical cm and bbl |
| Units | Assumed cm and bbl; no conversion | cm/mm/m and L/kL/bbl accepted, converted once, source values kept |
| Out-of-range reading | Silently clamped to the end row; empty table returned `0` | Refused by default; clamping is opt-in, flagged, and capped at 5 cm |
| Interpolation | Browser-only | Server-side engine the UI and future business modules share |
| Upload shapes | Long table only | Long table and wide printed matrix |
| Result provenance | A number | `method`, bracketing points, `in_range`, warnings |

## Files

**Backend (new)**

- `app/utils/asset_types.py` — hard-coded catalog, aliases, capability flags
- `app/utils/units.py` — unit catalog, conversion factors, canonical units
- `app/services/calibration_engine.py` — 2D/3D interpolation, curve validation
- `app/services/calibration_import.py` — chart parser and validator (long and wide)
- `app/routers/assets.py` — asset CRUD, tanks, import/export, reference endpoint
- `app/routers/asset_calibration.py` — chart upload, lookup, batch lookup, export
- `tests/test_asset_master.py` — 37 tests

**Backend (changed)**

- `app/models.py` — `Asset`, `AssetTank`, `AssetCalibrationTable`, `AssetCalibrationRow`
- `app/schemas.py` — asset and lookup payloads
- `app/services/serializers.py` — asset, tank and chart representations
- `app/utils/default_permissions.py` — `assets` resource; `locations` moved to User Management
- `app/dependencies/permissions.py` — `get_user_location_ids` for asset location scoping
- `app/routers/dashboard.py` — Master Data is the asset module; User Management gains locations
- `app/main.py` — routers registered

**Frontend**

- `data/navigationItems.js` — regrouping and ordering
- `api/assetsApi.js` (new), `pages/Assets.jsx` (new), `pages/AssetCalibration.jsx` (new)
- `App.jsx` — `/assets` and `/asset-calibration` routes
- `pages/Locations.jsx` — eyebrow

**Docs** — `CHANGELOG.md`, `memory/MODULES.md`, `memory/ARCHITECTURE.md`,
`memory/DECISIONS.md` (ADR-013 to ADR-017)

## Verification

- `cd backend && ./.venv/bin/python -m pytest -q` → **70 passed, 1 warning** (28 pre-existing + 42
  new). New coverage: the seven fixed types and their aliases, conversion factors
  (158.987294928 L → exactly 1 bbl; 1 kL → 6.289810770432105 bbl; 5 m → 500 cm), scope rules,
  tank declaration rules, chart preview/commit, mm+litre conversion on the way in, wide-layout
  normalisation, undeclared-tank rejection, single-point and duplicate-depth rejection,
  ullage basis, non-monotonic warning, 2D midpoint interpolation, 3D tank resolution,
  unit-agnostic readings, out-of-range refusal and flagged clamping, batch lookup, re-upload
  replacement audit, three-format export, and `assets:read`-only RBAC.
- `cd frontend && npm run build` → **success**, Vite 8.3.4, 66 modules.
- Live HTTP smoke test against uvicorn + Vite proxy → **36/36 checks passed**: login, reference
  catalog, location, barge with three tanks, Prime Mover refusing calibration, Local requiring a
  location, 11-point mm/litre chart preview and commit, 750 mm → 7.5 bbl interpolation,
  1P/2P tank-axis separation, unknown-tank refusal, out-of-range refusal then flagged clamp,
  litre and kilolitre results, batch 4-of-5, wide layout, CSV/XLSX/PDF export, audit actions,
  both module dashboards and the permission catalog placement.
- Vite dev server serves the SPA and proxies `/api` to the backend (`/api/health` → ok, login →
  token).
- The four new tables compile through SQLAlchemy's PostgreSQL dialect to well-formed DDL:
  every `String` is a bounded `VARCHAR`, the canonical columns are `NUMERIC(14,4)` and
  `NUMERIC(16,6)`, both unique constraints survive as named constraints, and no JSON type
  appears. This checks the DDL the server would receive, not a live `create_all`.
- Every field the two new pages read was cross-checked against live API responses: 20
  snake_case field reads in `Assets.jsx` and 38 in `AssetCalibration.jsx`, with no read of a
  field the backend does not return, and every list read off API data is either guaranteed
  present-and-typed by the serializer or rendered behind a guard.
- Location-scope enforcement for non-admin users: a user whose role has location
  assignments sees only those locations plus Global assets, and a single-asset read
  outside them returns 404 rather than leaking the record.
- XLSX chart upload and the XLSX asset register import are covered by real generated
  workbooks: a long sheet in m and kL (converted to cm and bbl on import), a multi-tank
  wide sheet, an undeclared-tank rejection, and a register import whose `Barge` alias
  folds onto the fixed `BARGE` code.

## Not verified in this delivery

- Manual light/dark visual review of the two new pages in a browser.
- PostgreSQL schema creation against a live server. The four new tables were compiled through
  SQLAlchemy's PostgreSQL dialect and the emitted DDL is well formed (bounded `VARCHAR` lengths
  throughout, `NUMERIC(14,4)` / `NUMERIC(16,6)` for the canonical columns, both unique
  constraints surviving as named constraints, `ON DELETE CASCADE` on the child tables, no JSON
  type anywhere), but the sandbox has no PostgreSQL server binary, so `create_all` has not been
  executed against one. Tests run on SQLite and no Alembic baseline exists yet.
