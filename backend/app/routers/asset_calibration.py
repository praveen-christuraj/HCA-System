"""Asset calibration — chart upload, validation and dip-to-volume lookup.

One active chart per asset (owner decision 2026-10-17). Uploading a new chart
replaces the previous rows, and the audit trail records what was replaced so the
change is never silent.

Charts always have three columns — tank name, dip/ullage, volume — supplied in
any of the accepted depth and volume units. Rows are converted to canonical cm
and bbl on the way in and stored next to the values as supplied.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db
from app.dependencies.permissions import require_permission
from app.models import Asset, AssetCalibrationRow, AssetCalibrationTable, AssetTank, User
from app.schemas import VolumeLookupBatchRequest, VolumeLookupRequest
from app.services.audit_service import create_audit_log
from app.services.calibration_engine import (
    CalibrationError,
    CalibrationPoint,
    curve_summary,
    interpolate_3d,
    validate_curve_monotonic,
)
from app.services.calibration_import import parse_calibration_chart
from app.services.serializers import calibration_row_to_dict, calibration_table_to_dict
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.helpers import clean_optional_text
from app.utils.time import utcnow
from app.utils.units import (
    from_canonical_dip,
    from_canonical_volume,
    normalize_dip_unit,
    normalize_measurement_basis,
    normalize_volume_unit,
    to_canonical_dip,
)

router = APIRouter(prefix="/assets", tags=["Asset Calibration"])

MODULE_NAME = "Asset Calibration"

# Depth readings further than this outside the certified range are refused even
# when clamping is allowed.
BATCH_LOOKUP_LIMIT = 200


def _load_asset(db: Session, asset_id: int) -> Asset:
    asset = (
        db.query(Asset)
        .options(
            joinedload(Asset.location),
            selectinload(Asset.tanks),
            joinedload(Asset.calibration_table).selectinload(AssetCalibrationTable.rows).joinedload(
                AssetCalibrationRow.tank
            ),
        )
        .filter(Asset.id == asset_id)
        .first()
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


def _require_calibration(asset: Asset) -> AssetCalibrationTable:
    table = asset.calibration_table
    if table is None or table.status != "Active":
        raise HTTPException(
            status_code=404,
            detail="This asset has no active calibration chart. Upload one first.",
        )
    return table


def _curves_by_tank(table: AssetCalibrationTable) -> dict[str, list[CalibrationPoint]]:
    """The chart grouped by tank name, each curve in canonical cm and bbl."""
    curves: dict[str, list[CalibrationPoint]] = {}
    for row in table.rows:
        name = row.tank.tank_name if row.tank else ""
        if not name:
            continue
        curves.setdefault(name, []).append(
            CalibrationPoint(dip_cm=float(row.dip_cm), volume_bbl=float(row.volume_bbl))
        )
    return curves


# ---------------------------------------------------------------------------
# Chart read
# ---------------------------------------------------------------------------
@router.get("/{asset_id}/calibration")
def get_calibration(
    asset_id: int,
    include_rows: bool = Query(True),
    user: User = Depends(require_permission("assets:read")),
    db: Session = Depends(get_db),
):
    """The active chart, its per-tank ranges and (optionally) its rows."""
    asset = _load_asset(db, asset_id)
    table = asset.calibration_table
    payload = {
        "asset_id": asset.id,
        "asset_code": asset.asset_code,
        "asset_name": asset.asset_name,
        "calibration_required": bool(asset.calibration_required),
        "asset_dip_unit": asset.dip_unit,
        "asset_volume_unit": asset.volume_unit,
        "tanks": [
            {"id": tank.id, "tank_name": tank.tank_name, "tank_code": tank.tank_code or ""}
            for tank in sorted(asset.tanks, key=lambda item: (item.sort_order or 0, item.tank_name))
        ],
        "chart": calibration_table_to_dict(table, include_rows=False),
    }
    if table is not None:
        curves = _curves_by_tank(table)
        payload["tank_curves"] = [
            {
                "tank_name": name,
                **curve_summary(curve),
                "warnings": validate_curve_monotonic(
                    sorted(curve, key=lambda point: point.dip_cm),
                    basis=table.measurement_basis,
                ),
            }
            for name, curve in sorted(curves.items())
        ]
        # A declared tank with no rows cannot be gauged, so the page reports it
        # instead of leaving the user to notice the missing compartment.
        payload["tanks_without_rows"] = sorted(
            {tank.tank_name for tank in asset.tanks} - set(curves),
            key=str.casefold,
        )
        if include_rows:
            payload["chart"] = calibration_table_to_dict(table, include_rows=True, row_limit=5000)
    return payload


@router.get("/{asset_id}/calibration/export")
def export_calibration(
    asset_id: int,
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    tank_name: str | None = None,
    actor: User = Depends(require_permission("assets:read")),
    db: Session = Depends(get_db),
):
    """Export a chart in the units it was supplied in, alongside canonical values."""
    asset = _load_asset(db, asset_id)
    table = _require_calibration(asset)

    rows = sorted(
        table.rows,
        key=lambda row: (
            row.tank.tank_name if row.tank else "",
            float(row.dip_cm or 0),
        ),
    )
    if tank_name:
        wanted = tank_name.strip().casefold()
        rows = [
            row
            for row in rows
            if row.tank and row.tank.tank_name.strip().casefold() == wanted
        ]

    headers = [
        "Tank name",
        f"Dip/Ullage ({table.source_dip_unit})",
        f"Volume ({table.source_volume_unit})",
        "Depth (cm)",
        "Volume (bbl)",
    ]
    body = [
        [
            row.tank.tank_name if row.tank else "",
            float(row.source_dip_value) if row.source_dip_value is not None else float(row.dip_cm),
            (
                float(row.source_volume_value)
                if row.source_volume_value is not None
                else float(row.volume_bbl)
            ),
            float(row.dip_cm),
            float(row.volume_bbl),
        ]
        for row in rows
    ]
    filters_summary = (
        f"asset={asset.asset_code}; chart={table.chart_name}; "
        f"basis={table.measurement_basis}; tank={tank_name or 'all'}"
    )
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Export Calibration Chart",
        category="Export",
        current_user=actor,
        request=request,
        entity_type="AssetCalibrationTable",
        entity_id=table.id,
        entity_label=f"{asset.asset_code} / {table.chart_name}",
        remarks=f"Calibration chart exported as {format.upper()}",
        details_summary=f"format={format}; rows={len(body)}; {filters_summary}",
    )
    db.commit()
    if format == "xlsx":
        return xlsx_response(
            f"calibration-{asset.asset_code}", "Calibration Chart", headers, body, [24, 22, 22, 16, 18]
        )
    if format == "pdf":
        return pdf_response(
            f"calibration-{asset.asset_code}", "Calibration Chart", headers, body,
            [40, 34, 34, 26, 30],
            filters_summary=filters_summary,
            orientation="P",
        )
    return csv_response(f"calibration-{asset.asset_code}", headers, body)


# ---------------------------------------------------------------------------
# Chart upload (preview then commit)
# ---------------------------------------------------------------------------
@router.post("/{asset_id}/calibration/upload")
def upload_calibration(
    asset_id: int,
    request: Request,
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    chart_name: str = Form(""),
    measurement_basis: str = Form("Dip"),
    dip_unit: str = Form("cm"),
    volume_unit: str = Form("bbl"),
    effective_date: date | None = Form(None),
    remarks: str = Form(""),
    actor: User = Depends(require_permission("assets:update")),
    db: Session = Depends(get_db),
):
    """Validate a calibration chart, then replace the asset's chart on confirm."""
    asset = _load_asset(db, asset_id)

    if not asset.calibration_required:
        raise HTTPException(
            status_code=422,
            detail=(
                "This asset is configured as not requiring calibration. "
                "Enable 'Calibration required' on the asset before uploading a chart."
            ),
        )
    if asset.status != "Active":
        raise HTTPException(status_code=422, detail="Calibration cannot be uploaded to an inactive asset")
    if not asset.tanks:
        raise HTTPException(
            status_code=422,
            detail="Declare the tanks on this asset before uploading a calibration chart",
        )

    basis = normalize_measurement_basis(measurement_basis)
    if basis is None:
        raise HTTPException(status_code=422, detail="Measurement basis must be Dip or Ullage")
    resolved_dip_unit = normalize_dip_unit(dip_unit)
    if resolved_dip_unit is None:
        raise HTTPException(status_code=422, detail="Dip unit must be cm, mm or m")
    resolved_volume_unit = normalize_volume_unit(volume_unit)
    if resolved_volume_unit is None:
        raise HTTPException(status_code=422, detail="Volume unit must be litres, kilolitres or barrels")

    try:
        parsed = parse_calibration_chart(
            file.file.read(),
            file.filename or "",
            tank_names=[tank.tank_name for tank in asset.tanks],
            dip_unit=resolved_dip_unit,
            volume_unit=resolved_volume_unit,
            measurement_basis=basis,
        )
    except ValueError as exc:
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Preview Calibration Upload",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            entity_type="Asset",
            entity_id=asset.id,
            entity_label=f"{asset.asset_code}",
            remarks=f"Calibration upload rejected for {file.filename or 'upload'}",
            details_summary=str(exc),
            status_code=422,
        )
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc))

    # Physical sanity checks that do not block the upload but must be visible:
    # a chart that gains volume as the dip falls is almost always mis-keyed.
    curve_warnings: list[str] = []
    per_tank: dict[str, list[CalibrationPoint]] = {}
    for row in parsed.rows:
        if not row["valid"]:
            continue
        per_tank.setdefault(row["tank_name"], []).append(
            CalibrationPoint(row["dip_cm"], row["volume_bbl"])
        )
    for name, curve in sorted(per_tank.items()):
        for warning in validate_curve_monotonic(
            sorted(curve, key=lambda point: point.dip_cm), basis=basis
        ):
            curve_warnings.append(f"{name}: {warning}")

    declared_tanks = {tank.tank_name for tank in asset.tanks}
    uncovered = sorted(
        declared_tanks - set(parsed.tanks_found),
        key=str.casefold,
    )
    if uncovered:
        curve_warnings.append(
            "No calibration rows for: " + ", ".join(uncovered)
        )

    payload = {
        "filename": parsed.filename,
        "format": parsed.file_format,
        "layout": parsed.layout,
        "columns_detected": parsed.columns_detected,
        "total_rows": parsed.total_rows,
        "valid_rows": parsed.valid_rows,
        "invalid_rows": parsed.invalid_rows,
        "missing_columns": parsed.missing_columns,
        "rows": parsed.rows[:500],
        "tanks_found": parsed.tanks_found,
        "tanks_without_rows": uncovered,
        "warnings": curve_warnings,
        "declared_units": {
            "measurement_basis": basis,
            "dip_unit": resolved_dip_unit,
            "volume_unit": resolved_volume_unit,
        },
        "canonical_units": {"dip_unit": "cm", "volume_unit": "bbl"},
        "message": parsed.message,
    }

    if parsed.missing_columns or parsed.total_rows == 0:
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Preview Calibration Upload",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            entity_type="Asset",
            entity_id=asset.id,
            entity_label=asset.asset_code,
            remarks=f"Calibration upload preview rejected for {parsed.filename}",
            details_summary=(
                f"file={parsed.filename}; missing={', '.join(parsed.missing_columns) or 'none'}"
            ),
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=payload)

    if not confirm:
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Preview Calibration Upload",
            category="Import",
            current_user=actor,
            request=request,
            entity_type="Asset",
            entity_id=asset.id,
            entity_label=asset.asset_code,
            remarks=f"Calibration chart previewed from {parsed.filename}",
            details_summary=(
                f"file={parsed.filename}; layout={parsed.layout}; rows={parsed.total_rows}; "
                f"valid={parsed.valid_rows}; invalid={parsed.invalid_rows}; "
                f"tanks={len(parsed.tanks_found)}; basis={basis}; "
                f"units={resolved_dip_unit}/{resolved_volume_unit}"
            ),
        )
        db.commit()
        return payload

    if parsed.invalid_rows:
        payload["message"] = "Fix every row error before importing."
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Upload Calibration Chart",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            entity_type="Asset",
            entity_id=asset.id,
            entity_label=asset.asset_code,
            remarks=f"Calibration upload rejected for {parsed.filename}",
            details_summary=f"file={parsed.filename}; invalid={parsed.invalid_rows}",
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=payload)

    tank_by_name = {tank.tank_name.casefold(): tank for tank in asset.tanks}
    existing = asset.calibration_table
    previous_rows = len(existing.rows) if existing else 0
    previous_name = existing.chart_name if existing else ""
    chart_label = clean_optional_text(chart_name) or f"{asset.asset_code} calibration chart"

    if existing is None:
        # chart_name is NOT NULL, so it is set before the row is flushed.
        existing = AssetCalibrationTable(
            asset_id=asset.id,
            chart_name=chart_label,
            measurement_basis=basis,
            source_dip_unit=resolved_dip_unit,
            source_volume_unit=resolved_volume_unit,
            status="Active",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(existing)
        db.flush()
    else:
        for row in list(existing.rows):
            existing.rows.remove(row)
        db.flush()

    existing.chart_name = chart_label
    existing.measurement_basis = basis
    existing.source_dip_unit = resolved_dip_unit
    existing.source_volume_unit = resolved_volume_unit
    existing.source_file_name = (file.filename or "")[:255] or None
    existing.effective_date = effective_date
    existing.remarks = clean_optional_text(remarks)
    existing.status = "Active"
    existing.updated_at = utcnow()
    db.flush()

    for index, row in enumerate(
        [item for item in parsed.rows if item["valid"]], start=1
    ):
        tank = tank_by_name.get(str(row["tank_name"]).casefold())
        if tank is None:
            continue
        db.add(
            AssetCalibrationRow(
                calibration_table_id=existing.id,
                tank_id=tank.id,
                row_number=index,
                dip_cm=row["dip_cm"],
                volume_bbl=row["volume_bbl"],
                source_dip_value=row["dip_value"],
                source_volume_value=row["volume_value"],
                created_at=utcnow(),
            )
        )
    db.flush()

    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Upload Calibration Chart",
        category="Import",
        current_user=actor,
        request=request,
        entity_type="AssetCalibrationTable",
        entity_id=existing.id,
        entity_label=f"{asset.asset_code} / {existing.chart_name}",
        remarks=(
            f"Calibration chart replaced ({previous_rows} previous rows) "
            if previous_rows
            else "Calibration chart uploaded"
        ),
        details_summary=(
            f"file={parsed.filename}; layout={parsed.layout}; rows={parsed.valid_rows}; "
            f"tanks={len(parsed.tanks_found)}; basis={basis}; "
            f"units={resolved_dip_unit}/{resolved_volume_unit} -> cm/bbl; "
            f"previous_rows={previous_rows}; previous_chart={previous_name or 'none'}"
        ),
        status_code=201,
    )
    db.commit()

    payload["imported"] = parsed.valid_rows
    payload["message"] = (
        f"{parsed.valid_rows} calibration point(s) saved across {len(parsed.tanks_found)} tank(s)"
    )
    return payload


@router.delete("/{asset_id}/calibration")
def delete_calibration(
    asset_id: int,
    request: Request,
    actor: User = Depends(require_permission("assets:delete")),
    db: Session = Depends(get_db),
):
    asset = _load_asset(db, asset_id)
    table = _require_calibration(asset)
    row_count = len(table.rows)
    chart_name = table.chart_name
    db.delete(table)
    db.flush()
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Delete Calibration Chart",
        current_user=actor,
        request=request,
        entity_type="AssetCalibrationTable",
        entity_id=asset_id,
        entity_label=f"{asset.asset_code} / {chart_name}",
        remarks="Calibration chart deleted",
        details_summary=f"asset={asset.asset_code}; chart={chart_name}; rows={row_count}",
    )
    db.commit()
    return {"message": "Calibration chart deleted", "rows_removed": row_count}


# ---------------------------------------------------------------------------
# Dip -> volume lookup (2D within a tank, 3D across the asset's tanks)
# ---------------------------------------------------------------------------
@router.post("/{asset_id}/calibration/lookup")
def lookup_volume(
    asset_id: int,
    payload: VolumeLookupRequest,
    request: Request,
    actor: User = Depends(require_permission("assets:read")),
    db: Session = Depends(get_db),
):
    asset = _load_asset(db, asset_id)
    table = _require_calibration(asset)
    curves = _curves_by_tank(table)

    dip_unit = payload.dip_unit or asset.dip_unit
    volume_unit = payload.volume_unit or asset.volume_unit
    dip_cm = round(to_canonical_dip(payload.dip_value, dip_unit), 4)

    try:
        result = interpolate_3d(
            curves,
            payload.tank_name,
            dip_cm,
            basis=table.measurement_basis,
            allow_clamping=payload.allow_clamping,
        )
    except CalibrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    body = result.as_dict(dip_unit=dip_unit, volume_unit=volume_unit)
    body.update(
        {
            "asset_code": asset.asset_code,
            "asset_name": asset.asset_name,
            "tank_name": payload.tank_name,
            "chart_name": table.chart_name,
            "measurement_basis": table.measurement_basis,
            "interpolation": "3D (tank + depth) resolved to 2D (depth -> volume)",
        }
    )

    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Interpolate Volume",
        category="Data Change",
        current_user=actor,
        request=request,
        entity_type="AssetCalibrationTable",
        entity_id=table.id,
        entity_label=f"{asset.asset_code} / {payload.tank_name}",
        remarks=(
            f"{table.measurement_basis} {payload.dip_value:g} {dip_unit} resolved to "
            f"{body['volume_bbl']:g} bbl"
        ),
        details_summary=(
            f"asset={asset.asset_code}; tank={payload.tank_name}; "
            f"depth={payload.dip_value:g} {dip_unit}; volume={body['volume_bbl']:g} bbl; "
            f"method={result.method}; in_range={result.in_range}"
        ),
    )
    db.commit()
    return body


@router.post("/{asset_id}/calibration/lookup-batch")
def lookup_volume_batch(
    asset_id: int,
    payload: VolumeLookupBatchRequest,
    actor: User = Depends(require_permission("assets:read")),
    db: Session = Depends(get_db),
):
    """Resolve many readings for one tank in a single request.

    Per-reading failures are returned in the results rather than failing the
    whole batch, so one out-of-range gauging does not hide the rest.
    """
    if len(payload.dip_values) > BATCH_LOOKUP_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"At most {BATCH_LOOKUP_LIMIT} readings can be resolved at once",
        )

    asset = _load_asset(db, asset_id)
    table = _require_calibration(asset)
    curves = _curves_by_tank(table)

    dip_unit = payload.dip_unit or asset.dip_unit
    volume_unit = payload.volume_unit or asset.volume_unit

    results = []
    for value in payload.dip_values:
        dip_cm = round(to_canonical_dip(value, dip_unit), 4)
        try:
            result = interpolate_3d(
                curves,
                payload.tank_name,
                dip_cm,
                basis=table.measurement_basis,
                allow_clamping=payload.allow_clamping,
            )
        except CalibrationError as exc:
            results.append(
                {
                    "dip_value": value,
                    "dip_unit": dip_unit,
                    "dip_cm": dip_cm,
                    "error": str(exc),
                }
            )
            continue
        entry = result.as_dict(dip_unit=dip_unit, volume_unit=volume_unit)
        entry["dip_value"] = value
        results.append(entry)

    resolved = sum(1 for item in results if "error" not in item)
    return {
        "asset_code": asset.asset_code,
        "asset_name": asset.asset_name,
        "tank_name": payload.tank_name,
        "chart_name": table.chart_name,
        "measurement_basis": table.measurement_basis,
        "requested": len(payload.dip_values),
        "resolved": resolved,
        "failed": len(payload.dip_values) - resolved,
        "results": results,
    }
