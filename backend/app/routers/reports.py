"""Operational Reports Suite API (ported from OTMS reports / tank_operation_summary / out_turn_summary / stock_ledger):
  - Tank Stock Ledger
  - Vessel Stock Ledger
  - Tank Operation Summary (All Tanks & Single Tank views, NSV/GSV/GOV basis)
  - Out-Turn Summary & Per-Location Column Configuration (typed child table, no JSON)
  - Material Balance Report (template-driven daily reconciliation, carry-forward opening stock, book vs physical loss/gain)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import (
    get_user_location_ids,
    require_any_permission,
    require_permission,
)
from app.models import (
    ApprovedTransactionCorrectionRequest,
    Asset,
    Location,
    MaterialBalanceTemplate,
    Operation,
    OperationEntry,
    OutTurnSummaryConfig,
    OutTurnSummaryConfigColumn,
    User,
)
from app.routers.configurations_extended import DEFAULT_MB_COLUMNS, serialize_mb_template
from app.services.audit_service import create_audit_log
from app.services.operation_entry_service import payload_from_entry
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/reports", tags=["Operational Reports"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _f(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _rnd(value, digits: int = 2) -> float:
    return round(_f(value), digits)


def _active_approved_entries_query(db: Session, actor: User):
    """Approved OperationEntry rows that are not on correction hold."""
    held_ids = db.query(ApprovedTransactionCorrectionRequest.entry_id).filter(
        ApprovedTransactionCorrectionRequest.status == "Pending Admin Review"
    )
    q = db.query(OperationEntry).filter(
        OperationEntry.status == "Approved",
        ~OperationEntry.id.in_(held_ids),
    )
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        q = q.filter(OperationEntry.location_id.in_(allowed))
    return q


def _extract_tank_ledger_dict(entry: OperationEntry) -> dict:
    p = payload_from_entry(entry)
    inp = p.get("inputs") or {}
    calc = p.get("calculated") or {}
    tg = entry.tank_gauging

    tov = _f(tg.tov_bbl if tg else calc.get("tovBbl"))
    fw = _f(tg.free_water_bbl if tg else calc.get("freeWaterBbl"))
    gov = _f(tg.gov_bbl if tg else calc.get("govBbl"))
    gsv = _f(tg.gsv_bbl if tg else calc.get("gsvBbl"))
    bsw_bbl = _f(tg.bsw_bbl if tg else calc.get("bswBbl"))
    nsv = _f(tg.nsv_bbl if tg else calc.get("nsvBbl"))
    lt = _f(tg.lt if tg else calc.get("lt"))
    mt = _f(tg.mt if tg else calc.get("mt"))

    if entry.payload_code == "single_stock_payload" and not tg:
        nsv = _f(calc.get("nsv_bbl") or calc.get("net_nsv") or inp.get("quantity_bbl"))
        gsv = nsv
        gov = nsv

    op_code = (entry.operation_code_snapshot or "").strip().upper()
    op_cat = (entry.operation_category_snapshot or "").strip().upper()
    op_sign = (entry.operation_sign_snapshot or "").strip().upper()

    is_opening = op_code == "OPENING_STOCK" or "OPENING" in op_code or op_cat == "OPENING"
    is_closing = op_code == "CLOSING_STOCK" or "CLOSING" in op_code or op_cat == "CLOSING"

    return {
        "entry_id": entry.id,
        "ticket_number": entry.ticket_number,
        "accounting_date": entry.operation_date,
        "operation_datetime": entry.operation_end_datetime or entry.operation_start_datetime or entry.created_at,
        "location_id": entry.location_id,
        "location_code": entry.location.location_code if entry.location else "",
        "tank_asset_id": entry.asset_id,
        "tank_asset_code": entry.asset_code_snapshot,
        "tank_asset_name": entry.asset_name_snapshot,
        "operation_code": op_code,
        "operation_label": entry.operation_label_snapshot,
        "operation_category": op_cat,
        "operation_sign": op_sign,
        "is_opening": is_opening,
        "is_closing": is_closing,
        "total_dip_cm": _rnd(tg.total_dip_cm if tg else inp.get("totalDipCm"), 2),
        "water_dip_cm": _rnd(tg.water_dip_cm if tg else inp.get("waterDipCm"), 2),
        "tank_temp_c": _rnd(tg.tank_temperature if tg else inp.get("tankTemp"), 2),
        "sample_temp_f": _rnd(tg.sample_temperature if tg else inp.get("sampleTemp"), 2),
        "observed_api": _rnd(tg.observed_api if tg else inp.get("observedApi"), 2),
        "api60": _rnd(tg.api60 if tg else calc.get("api60"), 2),
        "ctl": _rnd(tg.vcf if tg else calc.get("vcf"), 5),
        "bsw_pct": _rnd(tg.bsw_percent if tg else inp.get("bswPercent"), 3),
        "tov_bbl": _rnd(tov, 2),
        "fw_bbl": _rnd(fw, 2),
        "gov_bbl": _rnd(gov, 2),
        "gsv_bbl": _rnd(gsv, 2),
        "bsw_bbl": _rnd(bsw_bbl, 2),
        "nsv_bbl": _rnd(nsv, 2),
        "lt": _rnd(lt, 2),
        "mt": _rnd(mt, 2),
        "product_name": entry.product_name or "Crude Oil",
        "remarks": entry.remarks or "",
    }


# ===========================================================================
# 1. Tank Stock Ledger & Vessel Stock Ledger
# ===========================================================================
@router.get("/tank-stock-ledger")
def list_tank_stock_ledger(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    location_code: str | None = None,
    tank_asset_code: str | None = None,
    operation_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_any_permission("reports:read", "operation_transactions:read")),
    db: Session = Depends(get_db),
):
    q = _active_approved_entries_query(db, actor).filter(
        OperationEntry.operation_type_code == "TANK_OPERATIONS"
    )
    if location_code:
        loc = db.query(Location).filter(func.upper(Location.location_code) == location_code.strip().upper()).first()
        q = q.filter(OperationEntry.location_id == (loc.id if loc else -1))
    if tank_asset_code:
        q = q.filter(func.upper(OperationEntry.asset_code_snapshot) == tank_asset_code.strip().upper())
    if operation_code:
        q = q.filter(func.upper(OperationEntry.operation_code_snapshot) == operation_code.strip().upper())
    if date_from:
        q = q.filter(OperationEntry.operation_date >= date_from)
    if date_to:
        q = q.filter(OperationEntry.operation_date <= date_to)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                OperationEntry.ticket_number.ilike(term),
                OperationEntry.asset_code_snapshot.ilike(term),
                OperationEntry.operation_label_snapshot.ilike(term),
            )
        )

    result = paginate_query(
        q.order_by(OperationEntry.operation_date.desc(), OperationEntry.id.desc()),
        page=page,
        page_size=page_size,
    )
    result["items"] = [_extract_tank_ledger_dict(e) for e in result["items"]]
    return result


@router.get("/vessel-stock-ledger")
def list_vessel_stock_ledger(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    location_code: str | None = None,
    operation_type_code: str | None = None,
    asset_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_any_permission("reports:read", "operation_transactions:read")),
    db: Session = Depends(get_db),
):
    q = _active_approved_entries_query(db, actor).filter(
        OperationEntry.operation_type_code.in_(
            ["BARGE_OPERATIONS", "SHUTTLE_OPERATIONS", "FSO_OPERATIONS", "TANKER_OPERATIONS"]
        )
    )
    if location_code:
        loc = db.query(Location).filter(func.upper(Location.location_code) == location_code.strip().upper()).first()
        q = q.filter(OperationEntry.location_id == (loc.id if loc else -1))
    if operation_type_code:
        q = q.filter(OperationEntry.operation_type_code == operation_type_code)
    if asset_code:
        q = q.filter(func.upper(OperationEntry.asset_code_snapshot) == asset_code.strip().upper())
    if date_from:
        q = q.filter(OperationEntry.operation_date >= date_from)
    if date_to:
        q = q.filter(OperationEntry.operation_date <= date_to)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                OperationEntry.ticket_number.ilike(term),
                OperationEntry.asset_code_snapshot.ilike(term),
                OperationEntry.convoy_number.ilike(term),
            )
        )

    result = paginate_query(
        q.order_by(OperationEntry.operation_date.desc(), OperationEntry.id.desc()),
        page=page,
        page_size=page_size,
    )
    items = []
    for e in result["items"]:
        p = payload_from_entry(e)
        c = p.get("calculated") or {}
        if e.payload_code == "multi_tank_payload":
            net = c.get("net") or {}
            gov, gsv, nsv, fw = _f(net.get("GOV")), _f(net.get("GSV")), _f(net.get("NSV")), _f(net.get("FW"))
        elif e.payload_code in ("shuttle_payload", "fso_payload"):
            net = c.get("net") or {}
            nsv = _f(net.get("net_stock_bbl"))
            fw = _f(net.get("net_water_bbl"))
            gov = nsv + fw
            gsv = nsv
        elif e.payload_code == "tanker_payload":
            gov, gsv, nsv, fw = _f(c.get("govBbl")), _f(c.get("gsvBbl")), _f(c.get("nsvBbl")), _f(c.get("freeWaterBbl"))
        else:
            nsv = _f(c.get("net_nsv") or c.get("nsv_bbl"))
            gov = gsv = nsv
            fw = 0.0
        items.append(
            {
                "entry_id": e.id,
                "ticket_number": e.ticket_number,
                "accounting_date": e.operation_date,
                "operation_type_code": e.operation_type_code,
                "location_code": e.location.location_code if e.location else "",
                "asset_code": e.asset_code_snapshot,
                "asset_name": e.asset_name_snapshot,
                "convoy_number": e.convoy_number or "",
                "operation_code": e.operation_code_snapshot,
                "operation_label": e.operation_label_snapshot,
                "operation_sign": e.operation_sign_snapshot,
                "gov_bbl": _rnd(gov, 2),
                "gsv_bbl": _rnd(gsv, 2),
                "fw_bbl": _rnd(fw, 2),
                "nsv_bbl": _rnd(nsv, 2),
            }
        )
    result["items"] = items
    return result


# ===========================================================================
# 2. Tank Operation Summary (All Tanks & Single Tank views)
# ===========================================================================
def _metric_value(ledger_row: dict, metric: str) -> float:
    m = metric.upper()
    if m == "GOV":
        return ledger_row["gov_bbl"]
    if m == "GSV":
        return ledger_row["gsv_bbl"]
    return ledger_row["nsv_bbl"]


def _build_tank_operation_summary_data(
    db: Session,
    actor: User,
    *,
    location_code: str,
    view: str = "all_tanks",
    tank_asset_code: str | None = None,
    metric: str = "NSV",
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    loc = db.query(Location).filter(func.upper(Location.location_code) == location_code.strip().upper()).first()
    if loc is None:
        raise HTTPException(status_code=404, detail=f"Location '{location_code}' not found")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and loc.id not in allowed:
        raise HTTPException(status_code=403, detail="Location is outside your assigned scope")

    if view == "single_tank" and not tank_asset_code:
        raise HTTPException(status_code=400, detail="Tank asset is required for Single Tank view")

    q = _active_approved_entries_query(db, actor).filter(
        OperationEntry.location_id == loc.id,
        OperationEntry.operation_type_code == "TANK_OPERATIONS",
    )
    if view == "single_tank" and tank_asset_code:
        q = q.filter(func.upper(OperationEntry.asset_code_snapshot) == tank_asset_code.strip().upper())
    if date_from:
        q = q.filter(OperationEntry.operation_date >= date_from)
    if date_to:
        q = q.filter(OperationEntry.operation_date <= date_to)

    entries = q.order_by(OperationEntry.operation_date.asc(), OperationEntry.id.asc()).all()
    ledger_rows = [_extract_tank_ledger_dict(e) for e in entries]

    # Discover all configured tank operations at this location + any observed in tickets
    loc_ops = (
        db.query(Operation)
        .filter(
            Operation.location_id == loc.id,
            Operation.operation_type_code == "TANK_OPERATIONS",
            Operation.status == "Active",
        )
        .order_by(Operation.sort_order.asc(), Operation.id.asc())
        .all()
    )
    dynamic_ops: dict[str, dict] = {}
    for op in loc_ops:
        code = op.operation_code.strip().upper()
        if code in ("OPENING_STOCK", "CLOSING_STOCK") or op.operation_category in ("OPENING", "CLOSING"):
            continue
        dynamic_ops[code] = {
            "key": f"op_{code.lower()}",
            "operation_code": code,
            "label": op.operation_label,
            "category": op.operation_category,
            "sign": op.operation_sign,
        }
    for lr in ledger_rows:
        if lr["is_opening"] or lr["is_closing"]:
            continue
        code = lr["operation_code"]
        if code and code not in dynamic_ops:
            dynamic_ops[code] = {
                "key": f"op_{code.lower()}",
                "operation_code": code,
                "label": lr["operation_label"] or code,
                "category": lr["operation_category"],
                "sign": lr["operation_sign"],
            }

    op_columns = list(dynamic_ops.values())

    # Group by date
    by_date: dict[date, list[dict]] = defaultdict(list)
    for lr in ledger_rows:
        by_date[lr["accounting_date"]].append(lr)

    rows = []
    totals = {"opening_stock": 0.0, "closing_stock": 0.0, "stock_diff": 0.0}
    for col in op_columns:
        totals[col["key"]] = 0.0

    for d in sorted(by_date.keys()):
        day_items = by_date[d]
        opening_ByTank: dict[str, float] = {}
        closing_ByTank: dict[str, float] = {}
        op_sums: dict[str, float] = {col["key"]: 0.0 for col in op_columns}
        closing_gauge = None

        for item in day_items:
            val = _metric_value(item, metric)
            tcode = item["tank_asset_code"]
            if item["is_opening"]:
                if tcode not in opening_ByTank:
                    opening_ByTank[tcode] = val
            elif item["is_closing"]:
                closing_ByTank[tcode] = val
                closing_gauge = item
            else:
                col_info = dynamic_ops.get(item["operation_code"])
                if col_info:
                    op_sums[col_info["key"]] += val

        opening_total = _rnd(sum(opening_ByTank.values()), 2)
        closing_total = _rnd(sum(closing_ByTank.values()), 2)
        stock_diff = _rnd(closing_total - opening_total, 2)

        row_dict = {
            "date": str(d),
            "opening_stock": opening_total,
            "closing_stock": closing_total,
            "stock_diff": stock_diff,
        }
        if view == "single_tank":
            g = closing_gauge or (day_items[-1] if day_items else {})
            row_dict.update(
                {
                    "dip_cm": g.get("total_dip_cm"),
                    "water_cm": g.get("water_dip_cm"),
                    "tank_temp_c": g.get("tank_temp_c"),
                    "api_60": g.get("api60"),
                    "ctl": g.get("ctl"),
                    "tov_bbl": g.get("tov_bbl"),
                    "fw_bbl": g.get("fw_bbl"),
                    "gov_bbl": g.get("gov_bbl"),
                    "gsv_bbl": g.get("gsv_bbl"),
                    "bsw_pct": g.get("bsw_pct"),
                    "bsw_bbl": g.get("bsw_bbl"),
                    "nsv_bbl": g.get("nsv_bbl"),
                    "lt": g.get("lt"),
                    "mt": g.get("mt"),
                }
            )
        for col in op_columns:
            k = col["key"]
            row_dict[k] = _rnd(op_sums[k], 2)
            totals[k] = _rnd(totals[k] + op_sums[k], 2)

        totals["opening_stock"] = _rnd(totals["opening_stock"] + opening_total, 2)
        totals["closing_stock"] = _rnd(totals["closing_stock"] + closing_total, 2)
        totals["stock_diff"] = _rnd(totals["stock_diff"] + stock_diff, 2)
        rows.append(row_dict)

    return {
        "view": view,
        "location_code": loc.location_code,
        "location_name": loc.location_name,
        "tank_asset_code": tank_asset_code or "",
        "metric": metric.upper(),
        "operation_columns": op_columns,
        "rows": rows,
        "totals": totals,
        "total_rows": len(rows),
    }


@router.get("/tank-operation-summary")
def get_tank_operation_summary(
    location_code: str = Query(..., min_length=1),
    view: Literal["all_tanks", "single_tank"] = "all_tanks",
    tank_asset_code: str | None = None,
    metric: Literal["NSV", "GSV", "GOV"] = "NSV",
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("reports:read")),
    db: Session = Depends(get_db),
):
    return _build_tank_operation_summary_data(
        db,
        actor,
        location_code=location_code,
        view=view,
        tank_asset_code=tank_asset_code,
        metric=metric,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/tank-operation-summary/export")
def export_tank_operation_summary(
    request: Request,
    location_code: str = Query(..., min_length=1),
    view: Literal["all_tanks", "single_tank"] = "all_tanks",
    tank_asset_code: str | None = None,
    metric: Literal["NSV", "GSV", "GOV"] = "NSV",
    date_from: date | None = None,
    date_to: date | None = None,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    actor: User = Depends(require_permission("reports:read")),
    db: Session = Depends(get_db),
):
    data = _build_tank_operation_summary_data(
        db,
        actor,
        location_code=location_code,
        view=view,
        tank_asset_code=tank_asset_code,
        metric=metric,
        date_from=date_from,
        date_to=date_to,
    )
    op_cols = data["operation_columns"]
    headers = ["Date", "Opening Stock", "Closing Stock", "Stock Diff"] + [c["label"] for c in op_cols]
    rows = []
    for r in data["rows"]:
        rows.append(
            [r["date"], r["opening_stock"], r["closing_stock"], r["stock_diff"]]
            + [r.get(c["key"], 0.0) for c in op_cols]
        )
    create_audit_log(
        db,
        module_name="Operational Reports",
        action="Export Tank Operation Summary",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported Tank Operation Summary ({location_code}) as {format.upper()}",
        details_summary=f"location={location_code}; view={view}; metric={metric}; rows={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("tank-operation-summary", headers, rows)
    if format == "xlsx":
        return xlsx_response("tank-operation-summary", "Tank Operation Summary", headers, rows)
    return pdf_response("tank-operation-summary", f"Tank Operation Summary — {location_code} ({metric})", headers, rows)


# ===========================================================================
# 3. Out-Turn Summary & Per-Location Column Configuration (No JSON)
# ===========================================================================
class OutTurnColumnConfigInput(StrictModel):
    column_key: str = Field(min_length=1, max_length=80)
    operation_code: str = Field(min_length=1, max_length=80)
    column_label: str = Field(min_length=1, max_length=150)
    sign: Literal["+", "-"] = "+"
    visible: bool = True
    sort_order: int = Field(default=1, ge=1)


class OutTurnConfigPayload(StrictModel):
    location_code: str = Field(min_length=1, max_length=50)
    columns: list[OutTurnColumnConfigInput] = Field(default_factory=list)


def _get_or_build_out_turn_columns(db: Session, loc: Location) -> list[dict]:
    cfg = (
        db.query(OutTurnSummaryConfig)
        .filter(func.upper(OutTurnSummaryConfig.location_code) == loc.location_code.upper())
        .first()
    )
    loc_ops = (
        db.query(Operation)
        .filter(
            Operation.location_id == loc.id,
            Operation.operation_type_code == "TANK_OPERATIONS",
            Operation.status == "Active",
        )
        .order_by(Operation.sort_order.asc(), Operation.id.asc())
        .all()
    )
    default_by_code: dict[str, dict] = {}
    for idx, op in enumerate(loc_ops, start=1):
        code = op.operation_code.strip().upper()
        if code in ("OPENING_STOCK", "CLOSING_STOCK") or op.operation_category in ("OPENING", "CLOSING"):
            continue
        default_sign = "-" if op.operation_sign == "IN" else "+"
        default_by_code[code] = {
            "column_key": f"op_{code.lower()}",
            "operation_code": code,
            "column_label": op.operation_label,
            "sign": default_sign,
            "visible": True,
            "sort_order": idx,
        }

    if not cfg or not cfg.columns:
        return list(default_by_code.values())

    saved = []
    seen_codes = set()
    for c in sorted(cfg.columns, key=lambda x: (x.sort_order, x.id or 0)):
        seen_codes.add(c.operation_code.upper())
        saved.append(
            {
                "column_key": c.column_key,
                "operation_code": c.operation_code.upper(),
                "column_label": c.column_label,
                "sign": c.sign if c.sign in ("+", "-") else "+",
                "visible": bool(c.visible),
                "sort_order": c.sort_order,
            }
        )
    for code, dcol in default_by_code.items():
        if code not in seen_codes:
            saved.append(dcol)
    return saved


@router.get("/out-turn-summary/config")
def get_out_turn_summary_config(
    location_code: str = Query(..., min_length=1),
    actor: User = Depends(require_permission("reports:read")),
    db: Session = Depends(get_db),
):
    loc = db.query(Location).filter(func.upper(Location.location_code) == location_code.strip().upper()).first()
    if loc is None:
        raise HTTPException(status_code=404, detail="Location not found")
    return {
        "location_code": loc.location_code,
        "location_name": loc.location_name,
        "columns": _get_or_build_out_turn_columns(db, loc),
    }


@router.put("/out-turn-summary/config")
def save_out_turn_summary_config(
    payload: OutTurnConfigPayload,
    request: Request,
    actor: User = Depends(require_permission("reports:update")),
    db: Session = Depends(get_db),
):
    loc = db.query(Location).filter(func.upper(Location.location_code) == payload.location_code.strip().upper()).first()
    if loc is None:
        raise HTTPException(status_code=404, detail="Location not found")
    cfg = (
        db.query(OutTurnSummaryConfig)
        .filter(func.upper(OutTurnSummaryConfig.location_code) == loc.location_code.upper())
        .first()
    )
    if cfg is None:
        cfg = OutTurnSummaryConfig(
            location_id=loc.id,
            location_code=loc.location_code,
            status="Active",
            updated_by_user_id=actor.id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(cfg)
        db.flush()
    else:
        cfg.updated_by_user_id = actor.id
        cfg.updated_at = utcnow()
        cfg.columns.clear()
        db.flush()

    for idx, col in enumerate(payload.columns, start=1):
        db.add(
            OutTurnSummaryConfigColumn(
                config_id=cfg.id,
                column_key=col.column_key.strip(),
                operation_code=col.operation_code.strip().upper(),
                column_label=col.column_label.strip(),
                sign=col.sign,
                visible=col.visible,
                sort_order=col.sort_order or idx,
            )
        )

    create_audit_log(
        db,
        module_name="Operational Reports",
        action="Update Out-Turn Summary Configuration",
        category="Configuration",
        current_user=actor,
        entity_type="OutTurnSummaryConfig",
        entity_id=cfg.id,
        entity_label=loc.location_code,
        request=request,
        remarks=f"Updated Out-Turn Summary column configuration for {loc.location_code}",
        details_summary=f"location={loc.location_code}; columns={len(payload.columns)}",
    )
    db.commit()
    db.refresh(cfg)
    request.state.audit_written = True
    return {
        "location_code": loc.location_code,
        "location_name": loc.location_name,
        "columns": _get_or_build_out_turn_columns(db, loc),
    }


def _build_out_turn_summary_data(
    db: Session,
    actor: User,
    *,
    location_code: str,
    metric: str = "NSV",
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    base = _build_tank_operation_summary_data(
        db,
        actor,
        location_code=location_code,
        view="all_tanks",
        metric=metric,
        date_from=date_from,
        date_to=date_to,
    )
    loc = db.query(Location).filter(func.upper(Location.location_code) == location_code.strip().upper()).first()
    configured_cols = _get_or_build_out_turn_columns(db, loc)
    visible_cols = [c for c in configured_cols if c["visible"]]

    out_rows = []
    totals = {"opening_stock": 0.0, "closing_stock": 0.0, "stock_diff": 0.0, "out_turn": 0.0}
    for c in visible_cols:
        totals[c["column_key"]] = 0.0

    for r in base["rows"]:
        stock_diff = _f(r["stock_diff"])
        out_turn = stock_diff
        row_out = {
            "date": r["date"],
            "opening_stock": r["opening_stock"],
            "closing_stock": r["closing_stock"],
            "stock_diff": stock_diff,
        }
        for c in visible_cols:
            k = c["column_key"]
            val = _f(r.get(k, 0.0))
            row_out[k] = _rnd(val, 2)
            totals[k] = _rnd(totals[k] + val, 2)
            if c["sign"] == "-":
                out_turn -= val
            else:
                out_turn += val
        row_out["out_turn"] = _rnd(out_turn, 2)
        totals["opening_stock"] = _rnd(totals["opening_stock"] + r["opening_stock"], 2)
        totals["closing_stock"] = _rnd(totals["closing_stock"] + r["closing_stock"], 2)
        totals["stock_diff"] = _rnd(totals["stock_diff"] + stock_diff, 2)
        totals["out_turn"] = _rnd(totals["out_turn"] + row_out["out_turn"], 2)
        out_rows.append(row_out)

    return {
        "location_code": loc.location_code,
        "location_name": loc.location_name,
        "metric": metric.upper(),
        "columns": configured_cols,
        "visible_columns": visible_cols,
        "rows": out_rows,
        "totals": totals,
        "total_rows": len(out_rows),
    }


@router.get("/out-turn-summary")
def get_out_turn_summary(
    location_code: str = Query(..., min_length=1),
    metric: Literal["NSV", "GSV", "GOV"] = "NSV",
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("reports:read")),
    db: Session = Depends(get_db),
):
    return _build_out_turn_summary_data(
        db,
        actor,
        location_code=location_code,
        metric=metric,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/out-turn-summary/export")
def export_out_turn_summary(
    request: Request,
    location_code: str = Query(..., min_length=1),
    metric: Literal["NSV", "GSV", "GOV"] = "NSV",
    date_from: date | None = None,
    date_to: date | None = None,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    actor: User = Depends(require_permission("reports:read")),
    db: Session = Depends(get_db),
):
    data = _build_out_turn_summary_data(
        db,
        actor,
        location_code=location_code,
        metric=metric,
        date_from=date_from,
        date_to=date_to,
    )
    vis = data["visible_columns"]
    headers = (
        ["Date", "Opening Stock", "Closing Stock", "Stock Diff"]
        + [f"{c['column_label']} ({c['sign']})" for c in vis]
        + ["Out-Turn"]
    )
    rows = []
    for r in data["rows"]:
        rows.append(
            [r["date"], r["opening_stock"], r["closing_stock"], r["stock_diff"]]
            + [r.get(c["column_key"], 0.0) for c in vis]
            + [r["out_turn"]]
        )
    create_audit_log(
        db,
        module_name="Operational Reports",
        action="Export Out-Turn Summary",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported Out-Turn Summary ({location_code}) as {format.upper()}",
        details_summary=f"location={location_code}; metric={metric}; rows={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("out-turn-summary", headers, rows)
    if format == "xlsx":
        return xlsx_response("out-turn-summary", "Out-Turn Summary", headers, rows)
    return pdf_response("out-turn-summary", f"Out-Turn Summary — {location_code} ({metric})", headers, rows)


# ===========================================================================
# 4. Material Balance Report
# ===========================================================================
def _build_material_balance_report(
    db: Session,
    actor: User,
    *,
    location_code: str,
    template_id: int | None = None,
    basis: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    loc = db.query(Location).filter(func.upper(Location.location_code) == location_code.strip().upper()).first()
    if loc is None:
        raise HTTPException(status_code=404, detail="Location not found")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and loc.id not in allowed:
        raise HTTPException(status_code=403, detail="Location is outside your assigned scope")

    template = None
    if template_id:
        template = db.get(MaterialBalanceTemplate, template_id)
    if template is None:
        template = (
            db.query(MaterialBalanceTemplate)
            .filter(
                func.upper(MaterialBalanceTemplate.location_code) == loc.location_code.upper(),
                MaterialBalanceTemplate.status == "Active",
            )
            .order_by(MaterialBalanceTemplate.is_default.desc(), MaterialBalanceTemplate.id.asc())
            .first()
        )

    effective_basis = (basis or (template.basis if template else "NSV")).upper()
    auto_carry = bool(template.auto_carry_opening_stock) if template else True
    columns_meta = serialize_mb_template(template)["columns"] if template else DEFAULT_MB_COLUMNS
    visible_cols = [c for c in columns_meta if c.get("visible", True)]

    q = _active_approved_entries_query(db, actor).filter(
        OperationEntry.location_id == loc.id,
        OperationEntry.operation_type_code == "TANK_OPERATIONS",
    )
    if date_from:
        q = q.filter(OperationEntry.operation_date >= date_from)
    if date_to:
        q = q.filter(OperationEntry.operation_date <= date_to)

    entries = q.order_by(OperationEntry.operation_date.asc(), OperationEntry.id.asc()).all()
    ledger_rows = [_extract_tank_ledger_dict(e) for e in entries]
    by_date: dict[date, list[dict]] = defaultdict(list)
    for lr in ledger_rows:
        by_date[lr["accounting_date"]].append(lr)

    rows = []
    prev_physical_closing: float | None = None
    summary = {
        "opening_stock": 0.0,
        "total_receipts": 0.0,
        "total_dispatches": 0.0,
        "book_closing_stock": 0.0,
        "physical_closing_stock": 0.0,
        "total_loss_gain": 0.0,
    }

    for d in sorted(by_date.keys()):
        day_items = by_date[d]
        opening_by_tank: dict[str, float] = {}
        closing_by_tank: dict[str, float] = {}
        movements = []

        for item in day_items:
            val = _metric_value(item, effective_basis)
            if item["is_opening"]:
                if item["tank_asset_code"] not in opening_by_tank:
                    opening_by_tank[item["tank_asset_code"]] = val
            elif item["is_closing"]:
                closing_by_tank[item["tank_asset_code"]] = val
            else:
                movements.append((item, val))

        if opening_by_tank:
            opening_val = _rnd(sum(opening_by_tank.values()), 2)
        elif auto_carry and prev_physical_closing is not None:
            opening_val = _rnd(prev_physical_closing, 2)
        else:
            opening_val = 0.0

        receipts_val = _rnd(
            sum(val for item, val in movements if item["operation_sign"] == "IN" or item["operation_category"] == "RECEIPT"),
            2,
        )
        dispatches_val = _rnd(
            sum(val for item, val in movements if item["operation_sign"] == "OUT" or item["operation_category"] == "DISPATCH"),
            2,
        )
        book_closing = _rnd(opening_val + receipts_val - dispatches_val, 2)
        physical_closing = _rnd(sum(closing_by_tank.values()), 2) if closing_by_tank else book_closing
        loss_gain = _rnd(physical_closing - book_closing, 2)
        loss_gain_pct = _rnd((loss_gain / book_closing) * 100.0, 4) if book_closing else 0.0

        row_values = {
            "ACCOUNTING_DATE": str(d),
            "OPENING_STOCK": opening_val,
            "RECEIPTS": receipts_val,
            "DISPATCHES": dispatches_val,
            "BOOK_CLOSING_STOCK": book_closing,
            "PHYSICAL_CLOSING_STOCK": physical_closing,
            "LOSS_GAIN": loss_gain,
            "LOSS_GAIN_PCT": loss_gain_pct,
        }

        # Evaluate any custom template columns
        for col in visible_cols:
            ccode = col["column_code"]
            if ccode in row_values:
                continue
            ctype = col["column_type"]
            if ctype == "OPERATION_SUM":
                inc = {x.upper() for x in (col.get("mapped_operation_codes") or [])}
                exc = {x.upper() for x in (col.get("excluded_operation_codes") or [])}
                d_filt = (col.get("direction_filter") or "").upper()
                c_filt = (col.get("category_filter") or "").upper()
                total_c = 0.0
                for item, val in movements:
                    if inc and item["operation_code"] not in inc:
                        continue
                    if exc and item["operation_code"] in exc:
                        continue
                    if d_filt and item["operation_sign"] != d_filt:
                        continue
                    if c_filt and item["operation_category"] != c_filt:
                        continue
                    total_c += val * int(col.get("sign_multiplier") or 1)
                row_values[ccode] = _rnd(total_c, 2)
            else:
                row_values[ccode] = 0.0

        rows.append(row_values)
        prev_physical_closing = physical_closing
        summary["total_receipts"] = _rnd(summary["total_receipts"] + receipts_val, 2)
        summary["total_dispatches"] = _rnd(summary["total_dispatches"] + dispatches_val, 2)
        summary["total_loss_gain"] = _rnd(summary["total_loss_gain"] + loss_gain, 2)

    if rows:
        summary["opening_stock"] = rows[0]["OPENING_STOCK"]
        summary["book_closing_stock"] = rows[-1]["BOOK_CLOSING_STOCK"]
        summary["physical_closing_stock"] = rows[-1]["PHYSICAL_CLOSING_STOCK"]

    return {
        "location_code": loc.location_code,
        "location_name": loc.location_name,
        "basis": effective_basis,
        "template": serialize_mb_template(template) if template else None,
        "columns": visible_cols,
        "rows": rows,
        "summary": summary,
        "total_rows": len(rows),
    }


@router.get("/material-balance")
def get_material_balance_report(
    location_code: str = Query(..., min_length=1),
    template_id: int | None = None,
    basis: Literal["GOV", "GSV", "NSV"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("reports:read")),
    db: Session = Depends(get_db),
):
    return _build_material_balance_report(
        db,
        actor,
        location_code=location_code,
        template_id=template_id,
        basis=basis,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/material-balance/export")
def export_material_balance_report(
    request: Request,
    location_code: str = Query(..., min_length=1),
    template_id: int | None = None,
    basis: Literal["GOV", "GSV", "NSV"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    actor: User = Depends(require_permission("reports:read")),
    db: Session = Depends(get_db),
):
    data = _build_material_balance_report(
        db,
        actor,
        location_code=location_code,
        template_id=template_id,
        basis=basis,
        date_from=date_from,
        date_to=date_to,
    )
    cols = data["columns"]
    headers = [c["column_label"] for c in cols]
    rows = [[r.get(c["column_code"], 0.0) for c in cols] for r in data["rows"]]

    create_audit_log(
        db,
        module_name="Operational Reports",
        action="Export Material Balance Report",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported Material Balance Report ({location_code}) as {format.upper()}",
        details_summary=f"location={location_code}; basis={data['basis']}; rows={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("material-balance-report", headers, rows)
    if format == "xlsx":
        return xlsx_response("material-balance-report", "Material Balance Report", headers, rows)
    return pdf_response(
        "material-balance-report",
        f"Material Balance Report — {location_code} ({data['basis']})",
        headers,
        rows,
    )
