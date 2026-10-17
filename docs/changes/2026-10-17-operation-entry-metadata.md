# Operation Entry metadata and register refinement

## Scope

Metadata now contains only Operation Type, Primary Asset, Sender Location, Receiver Location
(for Global assets), Operation Date and Remarks. Removed duplicate Operation, Origin,
Destination, start/end times, Product, Created By and Status controls. Existing saved values
remain in transport/state; API-controlled creator/status and workflow permissions are unchanged.

The existing native payload operation selectors are preserved. For barge, tanker and meter
layouts without a native operation selector, the one searchable selector is in the payload
section. Layout selection/summary and required convoy reference are also outside metadata.
Measurement components and calculation formulas are unchanged.

Sender replaces the editable origin and writes both origin and sender IDs for ordinary tickets.
One accessible location is automatically selected and locked; multiple accessible locations
remain searchable and selectable. New ticket resets restore the assigned-location default.
Linked receiving routes retain their existing locked sender/receiver and receiving-origin rules.
Receiver selection writes receiver and destination IDs. Selecting a local asset clears those
IDs; selecting a Global asset exposes a required receiver selector. Global receiver omission
is rejected before the save-confirmation dialog.

Operation Date remains the existing date-only API field. Today uses the browser's local date,
not UTC, and is audited. It intentionally does not write hidden start/end timestamps.

## Register

Seven columns group ticket/date, operation/layout and asset/code; location, product, status
and actions remain visible. Fixed column sizing, wrapping descriptive content, horizontal
scrolling on narrow screens and a two-column action grid prevent irregular button placement.
Existing search, advanced/date filters, server pagination, exports and permission gates remain.
Colours inherit theme tokens; measurement geometry is untouched.

## Verification

- `npm run build`: passed (existing >500 kB main-bundle advisory remains).
- Backend `python -m pytest -q`: **186 passed**, one dependency deprecation warning.
- `npx playwright test --list`: **20 tests discovered**. Updated existing tests for payload-only
  operation selection and metadata exclusions, and added single-location/global-receiver cases
  for both themes.
- Live browser tests and visual light/dark checks were not run: no browser binary or configured
  live E2E service/credentials in this environment. Test discovery is not browser verification.
- No schema, new permissions or backend workflow changes.
