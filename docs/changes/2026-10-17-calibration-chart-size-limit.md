# Calibration chart upload — the 5,000-row ceiling removed

**Date:** 2026-10-17 · **Module:** Asset Calibration · **Type:** Defect fix + limit policy

## The problem

Uploading a calibration chart was refused above 5,000 rows:

> `File exceeds the 5000-row import limit.`

The chart parser shared the master-data reader
(`app/services/master_import.py`, `MAX_IMPORT_ROWS = 5000`) and then applied a
second cap of its own (`calibration_import.MAX_CHART_ROWS = 5000`). That ceiling
is right for a user list or a location master, and wrong for a calibration book:
real barge and FSO strapping tables run past 25,000 points, so a legitimate chart
could not be uploaded at all.

Two further limits sat behind it and would have blocked the same upload:

- `MAX_IMPORT_BYTES = 5 MB` on the shared reader.
- nginx had no `client_max_body_size`, so the default 1 MB answered `413` before
  FastAPI ever saw a large file in the Docker deployment.

A stored chart was also silently truncated on the way out: `GET
/assets/{id}/calibration` returned at most 5,000 rows while reporting the true
`row_count`, and `GET /assets/{id}` at most 2,000.

## What changed

| Place | Before | After |
| --- | --- | --- |
| `app/config.py` | — | `CALIBRATION_MAX_ROWS` (default `100000`) and `CALIBRATION_MAX_UPLOAD_MB` (default `50`); `0` lifts either ceiling |
| `services/master_import.py` | Fixed 5,000 rows / 5 MB for every caller | `read_master_import(..., max_rows=, max_bytes=)`; defaults unchanged for master data, `None` means no ceiling |
| `services/calibration_import.py` | `MAX_CHART_ROWS = 5000`, read through the master cap | Reads with the calibration ceilings; the point ceiling is `CALIBRATION_MAX_ROWS` and `0` disables it. Working sets are released before the preview rows are built so a large chart does not hold points, grouping and preview rows at once |
| `routers/asset_calibration.py` | Read endpoint capped at 5,000 rows; rows inserted one mapped object at a time; PDF export rendered every row | Read cap follows `CALIBRATION_MAX_ROWS`, so a stored chart is never returned truncated; rows are written with one bulk statement; the PDF export is bounded by `MAX_EXPORT_ROWS` (50,000) and says so, while CSV/XLSX still carry the whole chart |
| `services/serializers.py` | `rows` + `rows_returned` | Also `rows_truncated`, so a bounded response says so instead of implying a smaller chart |
| `frontend/nginx.conf` | nginx default (1 MB) | `client_max_body_size 100m` on `/api/`, above the backend's own ceiling so the API reports the limit in its own words |
| `pages/AssetCalibration.jsx` | Requested every chart row on page load; preview note quoted the 500-row response slice | Requests the chart without rows (the page renders counts, not rows); preview note quotes the real file size |

The ceiling now counts **calibration points, not file rows**. A wide (printed
book) layout expands one file row into one point per tank column, so the two are
not the same number and the message says "points".

Master data, user import, operation references and ticket imports keep their
5,000-row / 5 MB ceilings — only calibration was lifted.

`GET /assets/{id}` still returns its 2,000-row calibration preview; it is a
summary payload and the asset page renders counts, not rows. It now reports
`rows_truncated: true` instead of implying a smaller chart.

Lifting the cap also exposed the exporters: `pdf_response` renders every row it
is given, and a chart could never previously exceed 5,000 rows. A 100,000-point
chart would have asked fpdf for ~2,000 pages, so the calibration PDF export is
now bounded by the existing `MAX_EXPORT_ROWS` and states the truncation in its
own header line and in the audit row. CSV and XLSX are untouched — they are how
a strapping table leaves the system.

## Why a ceiling at all

The owner asked for no limit. A ceiling of 100,000 points is 4× the largest chart
described (25,000+) and is far above anything a calibration book reaches; it
exists only so a runaway file cannot exhaust the container, and
`CALIBRATION_MAX_ROWS=0` removes it on a host with the memory. Measured with the
SQLite test stack in a single process:

| Points | Preview | Commit | Peak RSS |
| --- | --- | --- | --- |
| 12,000 | 0.24 s | 1.24 s | 161 MB |
| 25,000 | 0.58 s | 2.42 s | 223 MB |
| 100,000 | 2.39 s | 3.62 s | 478 MB |

The 100,000-point commit took 10.62 s through the unit of work before the bulk
insert, and 543 MB peak; the bulk write cut that to 3.62 s and 478 MB.

## Verification

- `cd backend && python -m pytest -q` → **186 passed** (182 before this change).
- Four new tests in `backend/tests/test_asset_master.py`:
  - `test_chart_of_12000_points_uploads_in_full` — preview, commit, stored
    `row_count`/`rows_returned`/`rows_truncated`, and an exact lookup on the last
    point of the chart.
  - `test_chart_point_ceiling_is_configurable_and_can_be_lifted` — a patched
    ceiling refuses the commit with `422`; `0` accepts it.
  - `test_shared_master_import_keeps_its_cap_for_master_data` — the shared reader
    still refuses 6,000 rows by default and accepts them when lifted.
  - `test_large_chart_exports_complete_csv_and_bounded_pdf` — a 6,000-point chart
    exports to CSV complete to its last point, and the PDF export stays bounded
    with the limit recorded in the audit trail.
- All four **fail on the pre-fix source** (checked by stashing `backend/app`,
  `frontend/src` and `nginx.conf`), so they cover the reported defect.
- `cd frontend && npm run build` → succeeds (the pre-existing >500 kB main-bundle
  warning is unchanged).
- Not verified here: the Playwright suite (needs the Docker stack) and a
  PostgreSQL deployment. The nginx directive is not syntax-checked in this
  environment — no nginx binary is installed.
