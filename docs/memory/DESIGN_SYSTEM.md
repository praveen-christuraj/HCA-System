# HCA System — Design System

> Applies the **Costing** `docs/UI_skills` guidance (frontend-design, UI/UX Pro Max, taste-skill,
> impeccable, interface-design, Vercel web-design-guidelines, shadcn/ui conventions, webapp
> testing) to HCA System. Read before writing or reviewing any interface code.
> Mandatory companion to [`PROJECT_MEMORY.md`](PROJECT_MEMORY.md) rules 2, 3, 9, 10, 15.

---

## 1. Direction

An **enterprise navy instrument panel**: dense, quiet, data-first. Navy on white, one accent,
hairline rules instead of heavy shadows, hierarchy carried by size and weight rather than by
colour. It must look like a hydrocarbon accounting system used for eight hours a day, not a
marketing site.

Consequences that follow automatically:

- No centred hero, no three-card marketing row, no gradients used as decoration, no glass, no
  emojis, no decorative motion.
- One accent colour (navy). Status colours appear only to say something about data.
- Whitespace is generous around groups of controls and tight inside tables.
- Anything the user must read twice is a layout bug, not a user problem.

---

## 2. Colour

Navy ramp `navy[50…950]`. Light mode primary `#12315f` (navy-800); dark mode interactive
`#4a7fd0`. Surfaces: canvas `#f3f5f9` / `#0b1220`, paper `#ffffff` / `#121b2e`, raised
`#ffffff` / `#182339`. Borders: `#d8e0ea` / `#27354d`, strong `#b9c6d8` / `#3a4a66`, dividers
`#e6ebf2` / `#223049`. Text: `#0f1f3d` / `#e7edf6`, secondary `#2f3f5c` / `#c6d2e3`, muted
`#5b6b85` / `#a3b2c8`.

- Never green branding; green is a status colour only.
- Never pair one tone's foreground with another tone's background.
- Charts use the navy ramp plus semantic colours, in that order; grid lines use the divider
  colour.
- Contrast target: WCAG 2.1 AA (4.5:1 body, 3:1 large text and UI boundaries). Disabled text is
  the only permitted exception.
- All values live in `frontend/src/styles/tokens.css`; pages must not hardcode colours.
- Button tokens are the exception to raw-ramp usage: `--button-primary-bg`,
  `--button-primary-hover` and `--button-primary-text` exist so the primary action can be
  retuned for a theme without touching component CSS. Components use those tokens, never
  `--navy-*` directly.

Semantic pairs: success `#1f7a4d` / `#e8f5ee`, warning `#b36b00` / `#fff4e0`, danger
`#b42318` / `#fdecea`, info `#1b4f9c` / `#e8f0fb`, with dark-mode variants.

---

## 3. Type

Two families: **Inter Variable** for interface text, and a mono stack
(`JetBrains Mono, Cascadia Code, Consolas`) for codes, identifiers and log excerpts.

| Role | Size / line-height | Weight |
| --- | --- | --- |
| Page title (h1/h2) | 26–30 / 1.2 | 700, tracking −0.03em |
| Section title (h3) | 16 / 1.35 | 600 |
| Body / control | 14 / 1.45 | 400 / 500 |
| Secondary / meta | 12.5–13 / 1.4 | 400–600 |
| Eyebrow / label | 10.5–11.5, +0.08em tracking | 700, uppercase |
| KPI value | 30–34, tabular numerals | 700 |

Rules: numbers use `font-variant-numeric: tabular-nums`; one h1-level title per page; do not go
below 11.5px for text a user must read; uppercase is reserved for eyebrows, table headers and
tiny labels.

---

## 4. Spacing, radius, elevation, motion

- **4pt rhythm**: gaps and paddings are multiples of 4. Page gutters 16/24/32px; card padding
  20–24px; card gaps 16–20px.
- **Radii**: 6px controls, 8px panels/inputs, 10px cards/menus, 14px dialogs. Never mix two
  radii in one component.
- **Elevation is quiet**: cards are outlined with a hairline border; only menus/popovers use a
  float shadow and dialogs use an overlay shadow. Never animate elevation.
- **Motion is state feedback only**: 120–160ms, `cubic-bezier(0.2, 0, 0, 1)`, limited to
  `background-color`, `border-color`, `color`, `opacity`. No transform-based movement, no
  springs, no loops. `prefers-reduced-motion` disables all of it.
- Control heights: compact 30px, standard 36px, comfortable 44px. Table rows 44–52px.

---

## 5. Layout

- **Top bar**: navy brand band (system name + subtitle, theme toggle, user menu) with a white
  navigation band underneath holding the module dropdowns.
- **Top navigation**: horizontal, grouped by module, permission-filtered. Active group gets a
  navy underline; the open dropdown uses a floating panel. No side navigation.
- **Page heading**: eyebrow (`MODULE / PAGE`) → title → description on the left, actions on the
  right, aligned to the flex-end baseline.
- **Module dashboards**: KPI row (3–5 cards) → status breakdown / recent activity → quick links.
  Cards are outlined, not shadowed. No decorative illustrations.
- **Lists**: toolbar (search, advanced filters, separate date group, page size, export) →
  table → footer (count + pagination). Toolbar controls wrap on narrow screens.
- **Forms**: two-column grid at ≥ 960px, one column below; labels above controls; help text
  under the field; errors directly under the offending field.
- **Dialogs**: 480–640px wide, title, optional description, body, sticky footer with
  Cancel + primary action. Destructive actions use the danger colour. Close only via Cancel or
  successful save; no X icon; ignore Escape and backdrop.
- **Login**: split screen — navy identity panel (brand, headline, values) + light form panel.
  Theme choice available on the page itself. Same layout in dark mode with navy surfaces.

---

## 6. Components

- `Icon` — inline stroke SVG set (24px viewBox). Decorative by default; pass `title` for a
  meaningful icon. Never use emoji characters as icons.
- `Tag` — status chips with tones `neutral | info | success | warning | error`. One status per
  row; do not stack chips. Chips carry text, never colour alone.
- `Button` variants: `primary` (navy), `secondary` (outlined), `ghost`, `danger`. Loading state
  shows a label change and disables the button; no spinner-only buttons.
- `Alert` — inline, next to the data or action; `role="alert"` for errors, `role="status"` for
  success. Pop-up dialogs are preferred for confirmation and blocking errors.
- `DataTable` — the only list surface: quick search, advanced filters, separate date range,
  20/50/100/200 pagination, selection, CSV/XLSX/PDF export.
- `KpiCard` — label, value, delta/context line. No sparkline unless it carries real
  information.
- `EmptyState` — short explanation and the primary action; no illustration.

---

## 7. Accessibility (pre-ship checklist)

- Every interactive element is keyboard reachable with a visible focus ring; never
  `outline: none` without a replacement.
- "Skip to main content" link targets `#main-content`.
- Icon-only buttons have `aria-label`; disclosure buttons have `aria-expanded`; menus have
  `aria-haspopup`; errors are `role="alert"`; counts are `aria-live="polite"`.
- Form controls have a real label (`label htmlFor`).
- Dialogs have `aria-labelledby` and `aria-describedby`; focus is trapped and restored.
- `color-scheme` follows the theme so native widgets do not flash white in dark mode.
- No information is carried by colour alone.
- Test at 1440 / 1024 / 768px, in both themes, and once with `prefers-reduced-motion`.

---

## 8. Copy

- Sentence case for labels and headings; uppercase only for eyebrows and table headers.
- Verbs are specific: `Create user`, `Export CSV`, `Assign role` — not `Submit` or `Go`.
- Errors say what happened and what to do next, without blaming the user.
- No exclamation marks, no emojis, no marketing superlatives inside the application.

---

## 9. Verification

1. `cd frontend && npm run build` — production bundle succeeds.
2. Login page checked in light and dark at 1440 / 1024 / 768 / 360px.
3. Keyboard pass: tab through login, top navigation, menu, user menu; Escape closes menus.
4. Contrast spot-check on navy buttons, muted text, status chips in both themes.
5. Backend tests unaffected.


## 10. Operation Entry layout preservation

Operation Entry is an intentional exception to generic form auto-layout: the owner requires the
OTMS module rows and calculation-card positions. Keep the extracted two-column entry header,
Tank Gauging field/card order, Barge BEFORE/AFTER/net columns, tanker entry/sticky-results panels,
and Shuttle/FSO/meter row groups. Scope their geometry in `styles/operation-entry.css`; use HCA
colour tokens in both themes. Do not replace these with a generic template/JSON editor. New
lookup, confirmation and import controls must remain keyboard-accessible without moving the
source's measurement/result sections.
