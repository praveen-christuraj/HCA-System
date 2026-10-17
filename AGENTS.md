# Agent Instructions — HCA System

> Read this file first, then [docs/memory/PROJECT_MEMORY.md](docs/memory/PROJECT_MEMORY.md).
> The memory is the source of truth. This file is only the entry point.

## Repository aliases (owner vocabulary)

- **OTMS** → <https://github.com/praveen-christuraj/hydrocarbon-accounting-otms>
  (application architecture and source of modules to extract)
- **Costing** → <https://github.com/praveen-christuraj/WellCostingPro>
  (critical basic modules and UI guidance in `docs/UI_skills`)

If the owner says "OTMS" or "Costing", these are the repositories meant. Never substitute.

## Mandatory reading before changing code

1. [docs/memory/PROJECT_MEMORY.md](docs/memory/PROJECT_MEMORY.md) — the 15 standing rules.
2. [docs/memory/ARCHITECTURE.md](docs/memory/ARCHITECTURE.md) — stack, layers, deployment.
3. [docs/memory/DESIGN_SYSTEM.md](docs/memory/DESIGN_SYSTEM.md) — visual language.
4. [docs/memory/MODULES.md](docs/memory/MODULES.md) — what is actually delivered.

## Non-negotiable implementation rules (summary)

Every page/module delivered must have:

1. **Auditing** — backend audit rows for every mutation, middleware fallback, persisted UI
   actions, append-only.
2. **RBAC** — permission in the catalog, API enforcement (`require_permission`), UI gating,
   admin-controlled.
3. **Light + dark themes** from design tokens; theme choice persisted and audited.
4. **Top-side navigation** with dropdowns; no side navigation.
5. **No JSON database columns** — typed columns and child tables only.
6. **Pagination** on every list: 20/50/100/200, default 20, server-driven.
7. **Filters** — quick search + advanced filters + a separate date/date-range group.
8. **Import/export** — XLSX + CSV import, XLSX + CSV + PDF export where applicable.
9. **Module dashboard** with live KPIs and honest Planned labels.
10. **Navy blue & white enterprise UI**, no emojis, no decorative animation.
11. **Alerts** inline next to the data or as pop-ups; dialogs close only via Cancel.
12. **Documentation** — update `docs/CHANGELOG.md` and add `docs/changes/<date>-<topic>.md`.

## Deployment rule

`docker compose up --build` must be the only command needed. The backend entrypoint waits for
PostgreSQL, runs the idempotent administrator seed (`python -m app.seed_admin`) and starts the
API. Never require a manual seed step.

## Definition of done

- [ ] Backend tests pass (`cd backend && python -m pytest -q`).
- [ ] Frontend production build passes (`cd frontend && npm run build`).
- [ ] Login and the changed pages verified in light and dark at desktop widths.
- [ ] `docs/CHANGELOG.md` and the delivery note are updated.
- [ ] Memory updated if a pattern, module status or decision changed.
