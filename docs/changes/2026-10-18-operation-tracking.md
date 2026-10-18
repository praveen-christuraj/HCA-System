# Operation Tracking — OTMS tracking modules and the Operation Transaction Register

**Date:** 2026-10-18
**Reference:** `praveen-christuraj/hydrocarbon-accounting-otms` at `e26eb7c`
**Routes:** top navigation → **Operation Tracking** (between Business and Reports):

| Page | Route | Read permission |
| --- | --- | --- |
| Module Dashboard | `/modules/operation-tracking` | any of the six reads below |
| Operation Transaction Register | `/operation-transactions` | `operation_transactions:read` |
| Transaction detail | `/operation-transactions/:id` | `operation_transactions:read` |
| Barge Tracking | `/barge-tracking` (`?convoy=` opens a convoy) | `barge_tracking:read` |
| Tanker Tracking | `/tanker-tracking` | `tanker_tracking:read` |
| Shuttle Tracking | `/shuttle-tracking` (`?voyage=` opens a voyage) | `shuttle_tracking:read` |
| FSO Tracking | `/fso-tracking` (`?view=otr|material-balance|outturn`) | `fso_tracking:read` |
| Tanker Transaction Report | `/tanker-transaction-report` | `tanker_transaction_reports:read` |

## Request

The owner asked for the OTMS tracking modules and their core functions in a new **Operation
Tracking** module, with as little UI change as possible. Operation Entry should list only Draft
tickets. Submit, review, approve, cancel and the other workflow actions move to an **Operation
Transaction Register**, as in OTMS.

## Operation Entry and the Transaction Register

- **Operation Entry** (`/operation-entry`) now lists only **Draft and Rejected** tickets: a
  Rejected ticket goes back to its creator for editing, as in OTMS. The status filter offers only
  Draft / Rejected. Each row has two actions: **Edit** (or **View** without `operation_entries:update`)
  and **Workflow**, which opens the ticket in the register. The form's *Review & Submit* button is
  replaced by **Open in Transaction Register**. Workflow buttons and the *Receive* row action are
  gone from this page. Receiving tickets are now started from Barge / Tanker Tracking, which still
  prefill Operation Entry through `?linked_ticket_id=`.
- **Operation Transaction Register** lists every ticket in the user's location scope. Status tabs
  (All, Draft, Submitted, Approved, Rejected, Cancelled) show counts that ignore the status filter.
  It has quick search, advanced filters (type, location, asset, product), a separate date-range
  group, removable chips, 20/50/100/200 server pagination and CSV/XLSX/PDF export. The row actions
  follow OTMS:
  - **Draft:** Submit, Cancel.
  - **Submitted:** Approve, Reject, Recall.
  - **Rejected:** Re-submit, Cancel.
- **Transaction detail** shows the saved snapshot, read-only and not recalculated. It also has the
  same workflow actions, a review dialog (confirmation checkbox plus remarks), the status history
  (expanded), Back / Print / Refresh, ticket CSV/XLSX/PDF export, *Edit in Operation Entry* for
  editable tickets, and a link to Barge / Tanker Tracking for Approved movements.
- The workflow API is unchanged: `POST /api/operation-entries/{id}/{submit|recall|approve|reject|cancel}`
  keeps its capabilities, optimistic version check and audit. Detail, history, export and
  transitions now also accept `operation_transactions:read`, so a register user does not need
  Operation Entry access. `GET /api/operation-entries` (the entry list) still needs
  `operation_entries:read`.

## Tracking modules (computed on read)

Tracking is computed when a page is read, from **Approved** tickets. Only explicit user facts are
stored, in typed tables: `barge_timeline_events` and `tanker_receipt_acknowledgements`. Voyage
close/reopen state uses the existing `operation_voyages`. A GET request never writes.

**Barge Tracking**
- Convoys come from Approved barge tickets and have OPEN / CLOSED tabs.
- The convoy view shows:
  - the tickets;
  - a per-barge timeline (LOAD_1 / LOAD_2_TOPUP / UNLOAD / STS, plus RECEIVED / RECEIPT_REVOKED events);
  - the **LOAD AFTER vs UNLOAD BEFORE** comparison: totals, quality, per-tank and temporary /
    permanent seal checks, with delta = left − right;
  - an MTR export (CSV/XLSX/PDF) and Print.
- Barge actions:
  - **Acknowledge receipt**: `barge_tracking:update` or `shipment_receipts:create`.
  - **Revoke receipt**: `barge_tracking:update` or `shipment_receipts:delete`. Blocked once a
    receiving ticket exists.
  - **Create receiving ticket**: shown only after the receipt is acknowledged.
  - **Fix timeline**: `barge_tracking:update`. This stores an audited event-type override and does
    not change the ticket.
- **Close / Reopen movement** needs `operation_voyages:update`. Close is blocked when the convoy has:
  - fewer than two Approved tickets;
  - a barge without a comparison;
  - open Draft / Submitted / Rejected tickets.

  A closed convoy blocks new tickets.

**Tanker Tracking**
- Each row is one Approved sender ticket. Status KPIs (All, Pending receipt, Acknowledged, Seal
  mismatch, Quantity variance, Matched, Closed) also act as filters.
- Rows show the latest Approved receiver ticket, the seal cross-check (C1/C2/M1/M2) and the
  receiver − sender GOV / GSV / NSV / LT / MT variance.
- Row actions:
  - **View / Print MTR**;
  - **Acknowledge**: `tanker_tracking:update` or `shipment_receipts:create`;
  - **Create receiver entry**: only once the receipt is acknowledged;
  - **Revoke**;
  - **Close**: `tanker_tracking:update`, and only once an Approved receiver exists.
- Exports are available in all three formats.

**Shuttle Tracking**
- Voyages are grouped by location + shuttle vessel + shuttle number and have OPEN / CLOSED tabs.
- Totals follow the OTMS `shuttle_movement_totals` rules:
  - net receipt and net discharge;
  - STS transfers;
  - TOV / FW / NSV;
  - |net stock| + |net water|, never netted.
- The voyage view lists the Approved tickets. It has Close / Reopen (`operation_voyages:update`,
  blocked while open tickets exist) and a voyage MTR export.

**FSO Tracking**
- **Voyages:** FSO receipt, export, water in/out, and shuttle discharge vs FSO receipt variance.
  Close / Reopen works the same way as for shuttle voyages.
- **Reports:** OTR (transaction-wise), Material Balance (daily book vs physical, loss/gain =
  physical − book) and Outturn (max source discharge − FSO receipt).
  - Location, FSO and date range are required. Each report can be exported in all three formats.
  - **Accounting date = operation date.** OTMS's Location Accounting Day Setting is **Planned**,
    and the pages say so.

**Tanker Transaction Report**
- One row per tanker ticket, with these columns:
  - Date, Ticket, Location, Tanker / Prime mover, Convoy, Cargo, Destination;
  - GOV, GSV, NSV, LT, MT;
  - Status (default Approved).
- Totals cover every matching row, not just the current page. The report can be exported in all
  three formats.

**Module dashboard**
- The home card shows:
  - Submitted tickets;
  - open barge convoys;
  - open shuttle / FSO voyages.
- The module page adds:
  - KPIs, including Approved today;
  - a status breakdown;
  - quick links filtered by permission;
  - recent tracking audit activity. Location-scoped users see only their own activity there.

## Permissions (standard `resource:action`, category "Operation Tracking")

| Resource | Actions | Use |
| --- | --- | --- |
| `operation_transactions` | read | Register and detail. Workflow actions keep their existing capabilities. |
| `barge_tracking` | read, update | update = Fix Timeline, plus acknowledge/revoke barge receipts |
| `tanker_tracking` | read, update | update = acknowledge/revoke, close a tanker movement |
| `shuttle_tracking` | read | Shuttle voyages |
| `fso_tracking` | read | FSO voyages and FSO reports |
| `tanker_transaction_reports` | read | Tanker Transaction Report |
| `shipment_receipts` | create, delete | OTMS "Acknowledge Shipment Receipt": acknowledge / revoke without tracking update |

The catalogue is now **70 permissions**. Closing or reopening a voyage or convoy uses the existing
`operation_voyages:update`. The bounded location / asset lookups that the filters use also accept
any tracking read permission, so tracking users need no master-data grants.

## Audit

Every mutation and export is audited under one of these modules: "Operation Transaction
Register", "Barge Tracking", "Tanker Tracking", "Shuttle Tracking" or "FSO Tracking". Each entry
records old/new status and remarks, for example:
- Acknowledge Receipt;
- Revoke Receipt;
- Fix Timeline;
- Close / Reopen Barge Movement;
- Close Tanker Movement;
- Close / Reopen Shuttle / FSO Voyage;
- Export;
- Export MTR.

Ticket transitions keep their existing "Operation Entry" audit and status history.

## Deliberate differences and Planned items

- The correction / revoke workflow for an Approved ticket is **Planned**. Approved tickets stay
  immutable.
- Receipt acknowledgement gates *Create receiving ticket* in the UI. The receiving ticket API
  keeps its existing linked-sender rules and does not require an acknowledgement.
- The barge comparison is computed only when both tickets use the multi-tank payload.
- Fix Timeline is a permission (`barge_tracking:update`) rather than an Admin-only button.
- The Location Accounting Day Setting (FSO accounting-day boundary) and the editable OTMS Tracking
  Module Configuration are **not** delivered. HCA keeps its fixed operation types (ADR-019).

## Schema

There are two new typed tables, `barge_timeline_events` and `tanker_receipt_acknowledgements`,
for **44 tables** in total and no JSON columns. They are created by `create_all` at startup. The
`operation_voyages` and `operation_entries` columns are unchanged; only ORM relationships were
added.

## Verification

- Backend: `python -m pytest -q` → **193 passed** (186 before). The new
  `tests/test_operation_tracking.py` (7 tests) covers:
  - register counts, filters, exports and audit;
  - register vs entry permission separation;
  - the full barge flow: receipt, receiver, comparison, timeline fix, MTR, close blockers, closed
    convoy blocking new tickets, reopen;
  - barge permission splits and location scoping;
  - tanker acknowledge, revoke, compare, close and the report;
  - shuttle / FSO voyages, close/reopen and the OTR / Material Balance / Outturn figures;
  - the module dashboard's any-of access and the tracking-user lookups.
- Frontend: `npm run build` → success. All seven pages are lazy chunks. The existing ~520 kB
  main-bundle advisory remains.
- Smoke test against a live API with seeded data: every list, detail and dashboard endpoint used by
  the pages returned 200 with the expected counts. The Vite dev server compiled every new module.
- Playwright: `operation-entry.spec.js` now submits through the transaction detail page. Browser
  execution was **not** performed here because there is no Chromium binary in this environment.
  Screens have not been visually inspected in a browser.
