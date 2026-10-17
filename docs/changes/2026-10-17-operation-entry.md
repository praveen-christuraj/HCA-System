# Operation Entry — fixed OTMS payloads, one entry page

**Date:** 2026-10-17
**Reference:** `praveen-christuraj/hydrocarbon-accounting-otms` at
`5eed361486fa56ad636da62e238d73059b0e2a2c`
**Routes:** Business → **Operation Entry** (`/operation-entry`); Configurations →
**Operation References** (`/operation-references`).

## Request and implementation boundary

The owner asked to use the existing module payloads directly, without an Operation Template
Master or payload designer, while retaining OTMS's entry rows, KPI cards, cautions, calculations,
validation, and creation/submission controls. Operation Entry is now implemented for all six
HCA operation types on one page. Prime Mover is resolved through the Tanker Trailer's link,
not given an independent operation (the existing ADR-019 decision).

The dedicated OTMS layout components were extracted rather than replaced with generic generated
forms. The before/after/net arrangement, tanker input/result panels, field order, quality-unit
switches, quick actions, copy confirmations, seals, and live result-card order remain in their
source locations. CSS is scoped to Operation Entry and uses HCA's light/dark tokens. The old
Operation Template selector is replaced by Operation Master selection and a fixed-layout
summary; there is no user-defined field/layout/calculation configuration.

This delivery is **not a claim that all OTMS tracking/report modules have been rebuilt**.
Detailed tracking screens, STS comparison reports, reconciliation dashboards, task-inbox routing,
correction requests, out-turn and material-balance reporting remain separate work. Entry now
provides the typed, approved records and immutable postings they can consume.

## Source study and parity map

Reviewed the source page and template master; all nine `operationLayouts` components (including
the read-only tanker preview); `tankQuantityEngine.js`; entry/transaction/template APIs and
routers; status transitions; review and seal submission gates; linked-sender services;
`tracking_helpers.shuttle_movement_totals`; reference lookup APIs; workflow policy evaluation;
`PERMISSION_CRITERIA_MODEL.md`; and the Operation Entry/Template manuals.

| HCA operation type | Primary asset | Fixed payload / layout | Retained behaviour |
| --- | --- | --- | --- |
| `TANK_OPERATIONS` | Storage Tank | `tank_gauging_payload` / Tank Gauging | Operation, date/time, dip/water, temperatures and units, observed API/density, sample quality, BS&W; validation/warnings before live quantities; original 15-card order |
| `BARGE_OPERATIONS` | Barge | `multi_tank_payload` / Multi-Tank Before/After | Before/After/net columns, dates/times, CCF, per-tank readings and maxima, stage totals, movement stage, copy parameters/dips, clear water, set time, permanent/temporary seals |
| `SHUTTLE_OPERATIONS` | Shuttle Vessel | `shuttle_payload` / Shuttle Tracking | Vessel operation, unique Shuttle Number, stock/water pairs, signed net, barge reference |
| `FSO_OPERATIONS` | FSO | `fso_payload` / FSO Tracking | Operation, shuttle reference, fetch closed-shuttle discharge, editable vessel quantity, stock/water pairs, variance, IN-operation shuttle caution |
| `TANKER_OPERATIONS` | Tanker Trailer | `tanker_payload` / Tanker Loading | Prime mover link, chassis, compartment, dip/water/quality, four seals, quick actions, live quantity panels, sender reference and guarded copy shortcuts, saved-ticket preview |
| `FLOWMETER_OPERATIONS` | Flowmeter stream | `flowmeter_payload` / Meter Reading | Configured meter rows, factors/units, opening/closing validation, stream totals, quality conversion and eight live cards |
| Shuttle alternative | Shuttle Vessel | Fixed scalar fields / Vessel Cycle | Operation, reference, searchable counterparty asset, quantity, water, NSV |
| FSO alternative | FSO | Fixed scalar fields / Stock Movement | Operation, reference, opening/closing stock/water, net stock/water/NSV |

The latter two are the source's scalar-field layouts, **not new user-customizable payloads**.
The arbitrary OTMS “Standard Form” designer is deliberately absent, as requested.

## Quantity calculations

- Tank/tanker: calibrated TOV and free water; GOV; observed API/density correction; API@60;
  density@15; VCF; GSV; BS&W volume; NSV; LT and MT. Constants and rounding follow OTMS.
- Barge: **CCF is applied to each tank before aggregation**; API@60 is rounded to **2 decimals**
  (tank/tanker use 3), VCF to 5; stage GSV/BS&W/NSV/LT/MT use JavaScript `Math.round` semantics.
  Net is **After − Before**, including negative movement. `perTank` remains keyed by tank name.
- Flowmeter: configuration is server-resolved, never a client-trusted factor. Preserve OTMS's
  `m3 × 6.289811` conversion and unrounded stream arithmetic; rounding is for card display.
- Shuttle: `net_stock = closing − opening`, `net_water = closing − opening`; the compatibility
  `TOV`, `FW`, `NSV` keys are retained.
- FSO: `variance = vessel quantity − abs(net stock + net water)`.
- Closed-shuttle source quantity follows OTMS's **`abs(net stock) + abs(net water)`** and unloading
  classification, excluding STS-out. It is not mistakenly netted to `abs(stock + water)`.
- Table 11 is **uploaded reference data**, not a generated density formula or a claimed certified
  dataset. Exact/interpolated/nearest-out-of-range method labels are retained. Empty-master
  behaviour is explicit: tank/tanker use the original approximate density mass path; barge uses
  zero LT/MT with a missing-reference caution, as OTMS does.

`backend/tests/fixtures/otms_quantity_golden.json` was generated by executing the original OTMS
functions at the reference commit. It contains nine independent numerical fixtures across
observed API, observed density, CCF, two units, signed/zero volumes and mixed-unit meters. The
synthetic `.133` LT factor in those fixtures is **test data only**. Python results are compared
to those fixtures, not simply to another implementation of the same Python formulas. An
additional test executes the ported JavaScript engine for cross-runtime parity.

These checks establish software parity, **not an independent metrology certification**. Before
production use, reconcile the results with the installation's approved calibration and Table 11
reference datasets.

## Deliberate integration differences / safety corrections

These are HCA integration requirements, not payload customization:

1. ADR-014/019's fixed asset/operation catalogues and location-scoped Operation Master remain
   authoritative. The header operation controls category/sign. OTMS's runtime template and
   operation-type flags are not reintroduced. Optional route fields retain the OTMS defaults;
   linked receiving routes have strict authoritative requirements.
2. ADR-016's charts are already **cm and bbl**. The source tanker's unconditional litres division
   is removed to avoid double conversion. Compartment names resolve exactly, not to an arbitrary
   first curve. Dip/Ullage basis is exposed in calibration metadata/labels and is kept in the
   stored snapshot.
3. ADR-017's shared server interpolation refuses missing curves and out-of-range readings.
   Inputs must fit their typed column precision; non-finite, malformed, missing mandatory,
   invalid temperature/API/density/BS&W, CCF and meter readings are refused instead of silently
   becoming zero. Unknown customizable input fields are refused.
4. The original client formulas provide immediate live cards. A debounced server calculation
   validates the same input, and save recalculates it again. Client `calculated` blocks are never
   trusted. Stale requests cannot replace newer API/mass results. Draft hydration is separated
   from payload emission so reopening a meter/barge ticket does not clear its saved readings.
5. Authenticated creator identity is server-owned. A `version` column prevents lost edits and
   stale workflow transitions; serial allocation locks the asset on PostgreSQL and a unique
   ticket key catches conflicts. Receiving links also have a unique live-link key.
6. Operation payload objects are rebuilt from **typed columns and child tables**, never JSON,
   JSONB, serialized-text blobs, or generic field/value storage. Calibration identity/name/basis,
   operation sign/label, calculated quantities, and warnings are snapshots, so subsequent master
   edits do not rewrite a saved ticket. The calibration ID-at-save is retained even if a chart
   reference is later removed.
7. Adding an asset compartment now reconciles tanks by identity instead of deleting/recreating
   every tank. Existing calibration and seal foreign keys survive. Removing a seal-referenced
   tank produces a validation error rather than a database failure.

## Workflow and permission gates

All grants are standard `resource:action` capabilities, seeded automatically. The active catalog
is now **60 permissions**. UI gating is a convenience; each API mutation checks permissions,
location scope and (when configured) workflow policy again.

| Action | Required capability in addition to page access |
| --- | --- |
| Read/list/detail/export/entry lookups | `operation_entries:read` |
| Create Draft | `operation_entries:create` |
| Create receiving Draft | `operation_entries:create` **or** `receiving_tickets:create`, only against an eligible Approved barge/tanker sender addressed to the receiving origin |
| Edit Draft/Rejected | `operation_entries:update` |
| Review | `operation_reviews:create` |
| Submit Draft/Rejected | `operation_submissions:create` **and** `operation_reviews:create`, with explicit `review_confirmed` |
| Recall Submitted to Draft | `operation_submissions:delete` |
| Approve Submitted | `operation_approvals:create` **and** `operation_reviews:create`, with explicit confirmation |
| Reject Submitted | `operation_approvals:update`, with remarks |
| Cancel Draft/Rejected | `operation_entries:delete` (logical cancellation; history is retained) |
| References | `operation_references:read/create/update/delete` |
| Additional workflow policies | `operation_policies:read/create/update/delete` |
| Voyage close/reopen | `operation_voyages:read/update` |

- Approved and Cancelled tickets are locked. No endpoint permits a new ticket to start Submitted
  or Approved, to change its creator, or to bypass the transition graph.
- Barge submission requires all three AFTER temporary seals. A permanent mismatch (including
  an omitted observed seal where a master exists) requires remarks. The client cannot forge the
  master seal to hide a mismatch.
- Policy matching uses action, operation type, asset type, location and fixed payload code,
  ordered by priority/id. Within each matched policy, a user override precedes role grants;
  no match falls back to normal RBAC. Matching policies with no eligible role/user deny access.
  The reserved Admin bypass is retained. Role/user policy membership is stored in child tables.
- Read visibility uses the OTMS **any-of-origin/sender/receiver/destination party rule**; writes
  remain origin-scoped. Destination/Receiver selectors use the minimal active-location directory,
  not the operator's own-side scope. Origin/Sender remain scoped.
- A receiving-only user cannot create arbitrary tickets. The API verifies sender approval,
  matching asset/type, RECEIPT operation, destination, convoy and immutable route, and refuses a
  duplicate live receiving link. Access to a locally-scoped sender asset's chart is narrowly
  allowed through the validated receiving link; bare foreign-asset access stays denied.
- One immutable `operation_postings` row is written atomically on approval. The sign/category and
  event are retained for later stock/tracking consumers; this is not a complete reconciliation
  reporting module.

## Supporting masters and controls

Operation References contains Table 11, Flowmeter Config, Barge Seal Master, workflow policies
and voyage controls. Each writable reference has gated create/edit, previewed CSV/XLSX import,
CSV/XLSX/PDF export, search, status/date filters and pagination. The physical references can be
read through entry-authorized endpoints without granting an operator `assets:read` or
administration rights. Policy and voyage administration remain separately gated.

Voyages are generated by tickets, not imported. Closing requires no outstanding
Draft/Rejected/Submitted tickets; close/reopen requires remarks and is audited. Entry respects
closed trip/voyage guards. The FSO Fetch action only uses a uniquely resolved, accessible,
CLOSED shuttle voyage and Approved unloading tickets.

## API and persistence

New routes:

- `/api/operation-entries/options` — fixed catalogue and alternatives, not a bulk master download.
- `/api/operation-entries/lookups/{locations|all-locations|assets|operations}` — scoped, searchable,
  server-paginated projections (20/50/100/200).
- `/api/operation-entries/asset-context/{asset_id}` — only the selected asset's chart/link/seals.
- `/api/operation-entries/table11`, `/calculate`, `/linked-sender/{id}`, `/closed-shuttle`.
- `/api/operation-entries` — list and create; `/{id}` — read/update;
  `/{id}/{submit|recall|reject|approve|cancel}` — explicit transitions with version checks.
- `/{id}/history` — paginated status history; `/{id}/export` — complete header/payload snapshot
  CSV/XLSX/PDF; `/export` — filtered register export.
- `/api/operation-entry-import/template` and `POST /api/operation-entry-import`.
- `/api/operation-references/{table11|meters|seals|policies|voyages}`, reference import/export and
  row create/update/deactivate controls.

Twenty-two new typed tables cover the header/history, six module payloads, stage/dip/seal/meter
children, scalar manual layouts, warnings, reference masters, policies and membership children,
voyages and immutable approval postings. The full schema contains **42 tables**. Existing core
identity, asset and Operation Master table columns are unchanged.

Bounded document exceptions to master-list pagination: the single selected asset chart may
contain at most 50,000 points; a ticket supports at most 200 compartments/meters; an asset's
permanent seal context is bounded at four positions per tank. General master selectors always
search/page on the server, and no complete asset/calibration database is downloaded on login.
Inline source operation selectors show the first bounded window; the header Operation picker
searches all eligible operations and injects the chosen option into the source layout.

## Import, export, audit and UI details

- CSV/XLSX templates have fixed scalar columns, no JSON cells. One file uses one layout.
  `ticket_key` groups barge rows (one per tank) and flowmeter rows (one per meter). Shared header
  and sample parameters must agree across a group. Native Excel date/time cells are supported.
- Imports are bounded at 5 MB / 5,000 rows and are atomic; any invalid ticket blocks the commit.
  They create Drafts only, and do not implicitly review, submit or approve.
- Register and complete saved-ticket exports are audited, sanitize spreadsheet cells and use
  wrapped print-grade PDF tables with page numbers. Snapshot exports are not import templates.
- Entry has an editable-ticket default filter, an all-status register, quick/advanced filters,
  a separate operation-date range, removable filter chips and server pagination.
- Shared master import preview now paginates all validation rows instead of hiding everything
  beyond the first 80. Status history is paginated too.
- Explicit domain audits, middleware fallback for denied/failed actions, and UI event persistence
  cover edits, workflow transitions, calculations, reference changes, imports, exports, filters,
  page visits and quick actions. No raw JSON is written into the audit table.
- The new pages are lazy-loaded. The pre-existing main bundle still triggers Vite's 500 kB
  advisory; Operation Entry and Operation References are separate chunks.
- Confirmation/review dialogs remain open on failure and close only through Cancel or success,
  with focus trapping. Numeric wheel behaviour, source cautions, field groups and result order
  are retained. The saved review uses stored quantities, not a new calculation against today's chart.

## Setup and deployment

1. Configure roles, locations and the existing Asset/Operation Masters.
2. Declare asset tanks and upload the actual charts in Asset Calibration.
3. Configure Table 11 factors, stream meters and permanent seals as applicable. Add the existing
   Prime Mover-Tanker Link where applicable. Do not use numerical test fixtures as reference data.
4. Grant page/create/edit rights independently from review/submit/approve rights; optionally add
   workflow policies. Then use Business → Operation Entry.

`docker compose up --build` remains the deployment command. On an installation at the prior
HCA baseline, startup `create_all` creates the new tables and bootstrap seeds the new permissions;
no manual seed step is introduced. No Alembic baseline or OTMS legacy-data migration is claimed.
For rollback, take a database backup first, deploy the previous application version and retain
these new tables as evidence; do not drop operational tickets to roll back UI code.

## Verification

- Backend pytest suite: **182 passed**, including **66 Operation Entry tests** and nine numerical
  fixtures executed from the OTMS source. Covers every payload, edit round-trips, precision and
  range errors, Ullage, Table 11, CCF, meter factors, seals, workflow, policy gates, role/location
  scope, local/global linked receiving, stale versions, grouped CSV/XLSX imports, native Excel
  date/time cells, exports, history pagination and tank-identity preservation.
- All tables compile through SQLAlchemy's PostgreSQL dialect; no JSON column is present.
- Frontend production build: success; new modules are code-split.
- Playwright against the live FastAPI service and Vite proxy: all six primary types in **light
  and dark**, real form entry/save/reopen/review/submit; tanker collapsed seals; barge card order;
  exact tank KPI label order; fixed Vessel Cycle/Stock Movement; query prefill; configuration tabs;
  linked tanker receipt; Cancel-only review dialogs; login and the entry shell at 1024/768 widths.
  See `frontend/tests/operation-entry.spec.js` and the final changelog for the run count.
- Not run: a live PostgreSQL/Docker deployment, production-data migration/reconciliation or
  installation-specific custody acceptance testing. The browser tests use an isolated SQLite
  preview with explicitly named E2E fixtures, never production reference data.

Run browser tests against a disposable seeded development environment:

```bash
cd frontend
npm ci
npx playwright install chromium  # on a machine allowed to download the browser
HCA_E2E_PASSWORD='<development-admin-password>' npm run test:e2e
```

Set `HCA_E2E_URL` when not using the normal Vite origin. `CHROMIUM_EXECUTABLE_PATH` can point to
an already installed Chromium. The sandbox run used an external Chromium installation; browser
binaries, databases, screenshots and traces are ignored and are not part of the Git patch.
