"""Extended Business / Operations APIs:
  - Flowmeter Record Entry & Flowmeter Config History
  - Movement Mapping (Sender / Receiver Reconciliation)
  - Operation Task Manager (Approval & Revoke Inbox)
  - Approved Transaction Correction Requests
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Integer, String, and_, case, cast, exists, func, or_, select
from sqlalchemy.orm import Session

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import (
    get_user_location_ids,
    get_user_role_ids,
    is_admin_user,
    require_any_permission,
    require_permission,
    user_has_permission,
)
from app.models import (
    ApprovedTransactionCorrectionRequest,
    Asset,
    FlowmeterConfig,
    FlowmeterConfigHistory,
    FlowmeterRecord,
    Location,
    MovementMapping,
    MovementMappingItem,
    OperationEntry,
    OperationEntryStatusHistory,
    OperationPosting,
    OperationTask,
    OperationTaskEvent,
    OperationTaskRole,
    OperationTaskUser,
    OperationWorkflowPolicy,
    Role,
    User,
)
from app.services.audit_service import create_audit_log
from app.services.operation_entry_service import operation_entry_to_dict, payload_from_entry
from app.services.table11 import lookup_table11_factor
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.helpers import display_name
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(tags=["Business Extended"])


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


# ===========================================================================
# 1. Flowmeter Record Entry & Flowmeter Config History
# ===========================================================================
class FlowmeterCalculatePayload(StrictModel):
    opening_reading: float = Field(ge=0)
    closing_reading: float = Field(ge=0)
    meter_factor: float = Field(default=1.0, gt=0, le=10)
    ctl: float = Field(default=1.0, gt=0, le=2)
    cpl: float = Field(default=1.0, gt=0, le=2)
    bsw_pct: float = Field(default=0.0, ge=0, lt=100)
    api60: float | None = Field(default=None, ge=-10, le=150)


class FlowmeterRecordPayload(FlowmeterCalculatePayload):
    location_id: int | None = None
    location_code: str = Field(min_length=1, max_length=50)
    flowmeter_asset_id: int | None = None
    flowmeter_asset_code: str = Field(min_length=1, max_length=50)
    stream_name: str = Field(min_length=1, max_length=150)
    meter_label: str = Field(min_length=1, max_length=150)
    record_date: date
    start_time: str | None = Field(default=None, max_length=20)
    end_time: str | None = Field(default=None, max_length=20)
    temperature_deg: float | None = None
    pressure_psig: float | None = None
    remarks: str | None = Field(default=None, max_length=2000)
    status: Literal["Draft", "Submitted", "Approved", "Cancelled"] = "Approved"


def _compute_flowmeter(db: Session, payload: FlowmeterCalculatePayload) -> dict:
    if payload.closing_reading < payload.opening_reading:
        raise HTTPException(
            status_code=400,
            detail="Closing meter reading cannot be less than opening meter reading",
        )
    gross = round(payload.closing_reading - payload.opening_reading, 4)
    gsv = round(gross * payload.meter_factor * payload.ctl * payload.cpl, 4)
    bsw_bbl = round(gsv * (payload.bsw_pct / 100.0), 4)
    nsv = round(gsv - bsw_bbl, 4)
    lt = 0.0
    mt = 0.0
    lt_factor = None
    if payload.api60 is not None:
        try:
            factor_info = lookup_table11_factor(payload.api60, db)
            lt_factor = float(factor_info["lt_factor"])
            lt = round(nsv * lt_factor, 4)
            mt = round(lt * 1.01605, 4)
        except Exception:
            lt = 0.0
            mt = 0.0
    return {
        "gross_volume": gross,
        "gsv_bbl": gsv,
        "bsw_bbl": bsw_bbl,
        "nsv_bbl": nsv,
        "lt_factor": lt_factor,
        "lt": lt,
        "mt": mt,
    }


def _serialize_flowmeter_record(row: FlowmeterRecord) -> dict:
    return {
        "id": row.id,
        "record_number": row.record_number,
        "location_id": row.location_id,
        "location_code": row.location_code,
        "location_name": row.location.location_name if row.location else "",
        "flowmeter_asset_id": row.flowmeter_asset_id,
        "flowmeter_asset_code": row.flowmeter_asset_code,
        "flowmeter_asset_name": row.flowmeter_asset.asset_name if row.flowmeter_asset else "",
        "stream_name": row.stream_name,
        "meter_label": row.meter_label,
        "record_date": row.record_date,
        "start_time": row.start_time or "",
        "end_time": row.end_time or "",
        "opening_reading": _f(row.opening_reading),
        "closing_reading": _f(row.closing_reading),
        "gross_volume": _f(row.gross_volume),
        "meter_factor": _f(row.meter_factor),
        "ctl": _f(row.ctl),
        "cpl": _f(row.cpl),
        "bsw_pct": _f(row.bsw_pct),
        "gsv_bbl": _f(row.gsv_bbl),
        "bsw_bbl": _f(row.bsw_bbl),
        "nsv_bbl": _f(row.nsv_bbl),
        "lt": _f(row.lt),
        "mt": _f(row.mt),
        "temperature_deg": _f(row.temperature_deg) if row.temperature_deg is not None else None,
        "pressure_psig": _f(row.pressure_psig) if row.pressure_psig is not None else None,
        "api60": _f(row.api60) if row.api60 is not None else None,
        "remarks": row.remarks or "",
        "status": row.status,
        "created_by": row.created_by.username if row.created_by else "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.post("/flowmeter-records/calculate")
def calculate_flowmeter_record(
    payload: FlowmeterCalculatePayload,
    actor: User = Depends(require_any_permission("flowmeter_records:read", "operation_entries:read")),
    db: Session = Depends(get_db),
):
    return _compute_flowmeter(db, payload)


@router.get("/flowmeter-records")
def list_flowmeter_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    flowmeter_asset_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_any_permission("flowmeter_records:read", "operation_entries:read")),
    db: Session = Depends(get_db),
):
    query = db.query(FlowmeterRecord)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        query = query.filter(FlowmeterRecord.location_id.in_(allowed))
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                FlowmeterRecord.record_number.ilike(term),
                FlowmeterRecord.stream_name.ilike(term),
                FlowmeterRecord.meter_label.ilike(term),
                FlowmeterRecord.flowmeter_asset_code.ilike(term),
                FlowmeterRecord.location_code.ilike(term),
            )
        )
    if status:
        query = query.filter(FlowmeterRecord.status == status)
    if location_code:
        query = query.filter(func.upper(FlowmeterRecord.location_code) == location_code.strip().upper())
    if flowmeter_asset_code:
        query = query.filter(
            func.upper(FlowmeterRecord.flowmeter_asset_code) == flowmeter_asset_code.strip().upper()
        )
    if date_from:
        query = query.filter(FlowmeterRecord.record_date >= date_from)
    if date_to:
        query = query.filter(FlowmeterRecord.record_date <= date_to)

    result = paginate_query(
        query.order_by(FlowmeterRecord.record_date.desc(), FlowmeterRecord.id.desc()),
        page=page,
        page_size=page_size,
    )
    result["items"] = [_serialize_flowmeter_record(r) for r in result["items"]]
    return result


@router.get("/flowmeter-records/export")
def export_flowmeter_records(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    flowmeter_asset_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_any_permission("flowmeter_records:read", "operation_entries:read")),
    db: Session = Depends(get_db),
):
    query = db.query(FlowmeterRecord)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        query = query.filter(FlowmeterRecord.location_id.in_(allowed))
    if status:
        query = query.filter(FlowmeterRecord.status == status)
    if location_code:
        query = query.filter(func.upper(FlowmeterRecord.location_code) == location_code.strip().upper())
    if date_from:
        query = query.filter(FlowmeterRecord.record_date >= date_from)
    if date_to:
        query = query.filter(FlowmeterRecord.record_date <= date_to)

    records = query.order_by(FlowmeterRecord.record_date.desc()).limit(MAX_EXPORT_ROWS).all()
    headers = [
        "Record #",
        "Date",
        "Location",
        "Asset",
        "Stream",
        "Meter",
        "Opening",
        "Closing",
        "Gross Vol",
        "MF",
        "GSV (bbl)",
        "BS&W %",
        "NSV (bbl)",
        "LT",
        "MT",
        "Status",
    ]
    rows = [
        [
            r.record_number,
            r.record_date,
            r.location_code,
            r.flowmeter_asset_code,
            r.stream_name,
            r.meter_label,
            _f(r.opening_reading),
            _f(r.closing_reading),
            _f(r.gross_volume),
            _f(r.meter_factor),
            _f(r.gsv_bbl),
            _f(r.bsw_pct),
            _f(r.nsv_bbl),
            _f(r.lt),
            _f(r.mt),
            r.status,
        ]
        for r in records
    ]
    create_audit_log(
        db,
        module_name="Flowmeter Records",
        action="Export Flowmeter Records",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} flowmeter records as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("flowmeter-records", headers, rows)
    if format == "xlsx":
        return xlsx_response("flowmeter-records", "Flowmeter Records", headers, rows)
    return pdf_response("flowmeter-records", "Flowmeter Records Register", headers, rows)


@router.post("/flowmeter-records", status_code=201)
def create_flowmeter_record(
    payload: FlowmeterRecordPayload,
    request: Request,
    actor: User = Depends(require_permission("flowmeter_records:create")),
    db: Session = Depends(get_db),
):
    loc = (
        db.get(Location, payload.location_id)
        if payload.location_id
        else db.query(Location).filter(func.upper(Location.location_code) == payload.location_code.upper()).first()
    )
    if loc is None or loc.status != "Active":
        raise HTTPException(status_code=400, detail="Select an Active location")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and loc.id not in allowed:
        raise HTTPException(status_code=403, detail="Location is outside your assigned scope")

    asset = (
        db.get(Asset, payload.flowmeter_asset_id)
        if payload.flowmeter_asset_id
        else db.query(Asset).filter(func.upper(Asset.asset_code) == payload.flowmeter_asset_code.upper()).first()
    )
    if asset is None or asset.status != "Active":
        raise HTTPException(status_code=400, detail="Select an Active Flowmeter asset")

    calc = _compute_flowmeter(db, payload)
    today_str = payload.record_date.strftime("%Y%m%d")
    prefix = f"FMR-{loc.location_code}-{today_str}"
    seq = db.query(FlowmeterRecord).filter(FlowmeterRecord.record_number.like(f"{prefix}%")).count() + 1

    row = FlowmeterRecord(
        record_number=f"{prefix}-{seq:04d}",
        location_id=loc.id,
        location_code=loc.location_code,
        flowmeter_asset_id=asset.id,
        flowmeter_asset_code=asset.asset_code,
        stream_name=payload.stream_name.strip(),
        meter_label=payload.meter_label.strip(),
        record_date=payload.record_date,
        start_time=(payload.start_time or "").strip() or None,
        end_time=(payload.end_time or "").strip() or None,
        opening_reading=payload.opening_reading,
        closing_reading=payload.closing_reading,
        gross_volume=calc["gross_volume"],
        meter_factor=payload.meter_factor,
        ctl=payload.ctl,
        cpl=payload.cpl,
        bsw_pct=payload.bsw_pct,
        gsv_bbl=calc["gsv_bbl"],
        bsw_bbl=calc["bsw_bbl"],
        nsv_bbl=calc["nsv_bbl"],
        lt=calc["lt"],
        mt=calc["mt"],
        temperature_deg=payload.temperature_deg,
        pressure_psig=payload.pressure_psig,
        api60=payload.api60,
        remarks=(payload.remarks or "").strip() or None,
        status=payload.status,
        created_by_user_id=actor.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    create_audit_log(
        db,
        module_name="Flowmeter Records",
        action="Create Flowmeter Record",
        category="Data Change",
        current_user=actor,
        entity_type="FlowmeterRecord",
        entity_id=row.id,
        entity_label=row.record_number,
        new_status=row.status,
        request=request,
        remarks="Flowmeter record created",
        details_summary=f"record={row.record_number}; asset={asset.asset_code}; nsv_bbl={calc['nsv_bbl']}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_flowmeter_record(row)


@router.put("/flowmeter-records/{record_id}")
def update_flowmeter_record(
    record_id: int,
    payload: FlowmeterRecordPayload,
    request: Request,
    actor: User = Depends(require_permission("flowmeter_records:update")),
    db: Session = Depends(get_db),
):
    row = db.get(FlowmeterRecord, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Flowmeter record not found")
    loc = (
        db.get(Location, payload.location_id)
        if payload.location_id
        else db.query(Location).filter(func.upper(Location.location_code) == payload.location_code.upper()).first()
    )
    if loc is None:
        raise HTTPException(status_code=400, detail="Location not found")
    asset = (
        db.get(Asset, payload.flowmeter_asset_id)
        if payload.flowmeter_asset_id
        else db.query(Asset).filter(func.upper(Asset.asset_code) == payload.flowmeter_asset_code.upper()).first()
    )
    if asset is None:
        raise HTTPException(status_code=400, detail="Flowmeter asset not found")

    calc = _compute_flowmeter(db, payload)
    old_status = row.status
    row.location_id = loc.id
    row.location_code = loc.location_code
    row.flowmeter_asset_id = asset.id
    row.flowmeter_asset_code = asset.asset_code
    row.stream_name = payload.stream_name.strip()
    row.meter_label = payload.meter_label.strip()
    row.record_date = payload.record_date
    row.start_time = (payload.start_time or "").strip() or None
    row.end_time = (payload.end_time or "").strip() or None
    row.opening_reading = payload.opening_reading
    row.closing_reading = payload.closing_reading
    row.gross_volume = calc["gross_volume"]
    row.meter_factor = payload.meter_factor
    row.ctl = payload.ctl
    row.cpl = payload.cpl
    row.bsw_pct = payload.bsw_pct
    row.gsv_bbl = calc["gsv_bbl"]
    row.bsw_bbl = calc["bsw_bbl"]
    row.nsv_bbl = calc["nsv_bbl"]
    row.lt = calc["lt"]
    row.mt = calc["mt"]
    row.temperature_deg = payload.temperature_deg
    row.pressure_psig = payload.pressure_psig
    row.api60 = payload.api60
    row.remarks = (payload.remarks or "").strip() or None
    row.status = payload.status
    row.updated_at = utcnow()

    create_audit_log(
        db,
        module_name="Flowmeter Records",
        action="Update Flowmeter Record",
        category="Data Change",
        current_user=actor,
        entity_type="FlowmeterRecord",
        entity_id=row.id,
        entity_label=row.record_number,
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Flowmeter record updated",
        details_summary=f"record={row.record_number}; nsv_bbl={calc['nsv_bbl']}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_flowmeter_record(row)


@router.delete("/flowmeter-records/{record_id}")
def delete_flowmeter_record(
    record_id: int,
    request: Request,
    actor: User = Depends(require_permission("flowmeter_records:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(FlowmeterRecord, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Flowmeter record not found")
    create_audit_log(
        db,
        module_name="Flowmeter Records",
        action="Delete Flowmeter Record",
        category="Data Change",
        current_user=actor,
        entity_type="FlowmeterRecord",
        entity_id=row.id,
        entity_label=row.record_number,
        old_status=row.status,
        request=request,
        remarks="Flowmeter record deleted",
        details_summary=f"record={row.record_number}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Flowmeter record deleted successfully"}


@router.get("/flowmeter-configs/history")
def list_flowmeter_config_history(
    config_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    actor: User = Depends(require_any_permission("operation_references:read", "flowmeter_records:read")),
    db: Session = Depends(get_db),
):
    q = db.query(FlowmeterConfigHistory)
    if config_id:
        q = q.filter(FlowmeterConfigHistory.config_id == config_id)
    result = paginate_query(q.order_by(FlowmeterConfigHistory.changed_at.desc()), page=page, page_size=page_size)
    result["items"] = [
        {
            "id": h.id,
            "config_id": h.config_id,
            "action": h.action,
            "changed_by": h.changed_by or "",
            "old_meter_factor": _f(h.old_meter_factor) if h.old_meter_factor is not None else None,
            "new_meter_factor": _f(h.new_meter_factor) if h.new_meter_factor is not None else None,
            "old_status": h.old_status or "",
            "new_status": h.new_status or "",
            "change_summary": h.change_summary or "",
            "changed_at": h.changed_at,
        }
        for h in result["items"]
    ]
    return result


# ===========================================================================
# 2. Movement Mapping & Reconciliation
# ===========================================================================
class MovementMappingItemInput(StrictModel):
    entry_id: int = Field(ge=1)
    role: Literal["SENDER", "RECEIVER"]
    allocated_gov: float | None = None
    allocated_gsv: float | None = None
    allocated_nsv: float | None = None


class MovementMappingPayload(StrictModel):
    mapping_type: Literal["TANK_TO_BARGE", "BARGE_TO_TANK", "TANK_TO_TANKER", "TANKER_TO_TANK", "SHUTTLE_TO_FSO", "INTER_TANK"] = "TANK_TO_BARGE"
    location_id: int | None = None
    location_code: str = Field(min_length=1, max_length=50)
    mapping_date: date
    remarks: str | None = Field(default=None, max_length=2000)
    status: Literal["Open", "Reconciled", "Closed"] = "Open"
    items: list[MovementMappingItemInput] = Field(min_length=1, max_length=100)


def _extract_entry_quantities(entry: OperationEntry) -> dict:
    p = payload_from_entry(entry)
    c = p.get("calculated") or {}
    if entry.payload_code in ("tank_gauging_payload", "tanker_payload"):
        gov = abs(_f(c.get("govBbl")))
        gsv = abs(_f(c.get("gsvBbl")))
        nsv = abs(_f(c.get("nsvBbl")))
    elif entry.payload_code == "multi_tank_payload":
        net = c.get("net") or {}
        gov = abs(_f(net.get("GOV")))
        gsv = abs(_f(net.get("GSV")))
        nsv = abs(_f(net.get("NSV")))
    elif entry.payload_code in ("shuttle_payload", "fso_payload"):
        net = c.get("net") or {}
        nsv = abs(_f(net.get("net_stock_bbl")))
        gov = nsv + abs(_f(net.get("net_water_bbl")))
        gsv = nsv
    elif entry.payload_code == "flowmeter_payload":
        gov = abs(_f(c.get("gross_volume") or c.get("gsv_bbl")))
        gsv = abs(_f(c.get("gsv_bbl")))
        nsv = abs(_f(c.get("nsv_bbl")))
    else:
        nsv = abs(_f(c.get("net_nsv") or c.get("nsv_bbl")))
        gov = nsv
        gsv = nsv
    return {"gov": round(gov, 3), "gsv": round(gsv, 3), "nsv": round(nsv, 3)}


def _serialize_movement_mapping(row: MovementMapping) -> dict:
    item_rows = []
    for item in row.items:
        e = item.entry
        q = _extract_entry_quantities(e) if e else {"gov": 0.0, "gsv": 0.0, "nsv": 0.0}
        item_rows.append(
            {
                "id": item.id,
                "entry_id": item.entry_id,
                "role": item.role,
                "ticket_number": e.ticket_number if e else "",
                "operation_date": e.operation_date if e else None,
                "operation_type_code": e.operation_type_code if e else "",
                "operation_label": e.operation_label_snapshot if e else "",
                "asset_code": e.asset_code_snapshot if e else "",
                "asset_name": e.asset_name_snapshot if e else "",
                "convoy_number": e.convoy_number if e else "",
                "allocated_gov": _f(item.allocated_gov) if item.allocated_gov is not None else q["gov"],
                "allocated_gsv": _f(item.allocated_gsv) if item.allocated_gsv is not None else q["gsv"],
                "allocated_nsv": _f(item.allocated_nsv) if item.allocated_nsv is not None else q["nsv"],
            }
        )
    return {
        "id": row.id,
        "mapping_number": row.mapping_number,
        "mapping_type": row.mapping_type,
        "location_id": row.location_id,
        "location_code": row.location_code,
        "mapping_date": row.mapping_date,
        "sender_total_gov": _f(row.sender_total_gov),
        "sender_total_gsv": _f(row.sender_total_gsv),
        "sender_total_nsv": _f(row.sender_total_nsv),
        "receiver_total_gov": _f(row.receiver_total_gov),
        "receiver_total_gsv": _f(row.receiver_total_gsv),
        "receiver_total_nsv": _f(row.receiver_total_nsv),
        "variance_gov": _f(row.variance_gov),
        "variance_gsv": _f(row.variance_gsv),
        "variance_nsv": _f(row.variance_nsv),
        "variance_nsv_pct": _f(row.variance_nsv_pct),
        "remarks": row.remarks or "",
        "status": row.status,
        "created_by": row.created_by or "",
        "sender_count": sum(1 for i in item_rows if i["role"] == "SENDER"),
        "receiver_count": sum(1 for i in item_rows if i["role"] == "RECEIVER"),
        "items": item_rows,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/movement-mappings/candidates")
def list_movement_mapping_candidates(
    location_code: str | None = None,
    operation_type_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    actor: User = Depends(require_any_permission("movement_mappings:read", "operation_entries:read")),
    db: Session = Depends(get_db),
):
    q = db.query(OperationEntry).filter(OperationEntry.status == "Approved")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        q = q.filter(OperationEntry.location_id.in_(allowed))
    if location_code:
        loc = db.query(Location).filter(func.upper(Location.location_code) == location_code.strip().upper()).first()
        if loc:
            q = q.filter(OperationEntry.location_id == loc.id)
    if operation_type_code:
        q = q.filter(OperationEntry.operation_type_code == operation_type_code)
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
    entries = q.order_by(OperationEntry.operation_date.desc(), OperationEntry.id.desc()).limit(200).all()
    items = []
    for e in entries:
        quantities = _extract_entry_quantities(e)
        items.append(
            {
                "id": e.id,
                "ticket_number": e.ticket_number,
                "operation_date": e.operation_date,
                "operation_type_code": e.operation_type_code,
                "operation_code": e.operation_code_snapshot,
                "operation_label": e.operation_label_snapshot,
                "operation_sign": e.operation_sign_snapshot,
                "location_code": e.location.location_code if e.location else "",
                "asset_code": e.asset_code_snapshot,
                "asset_name": e.asset_name_snapshot,
                "convoy_number": e.convoy_number or "",
                **quantities,
            }
        )
    return {"items": items}


@router.get("/movement-mappings")
def list_movement_mappings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    mapping_type: str | None = None,
    location_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("movement_mappings:read")),
    db: Session = Depends(get_db),
):
    q = db.query(MovementMapping)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        q = q.filter(MovementMapping.location_id.in_(allowed))
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                MovementMapping.mapping_number.ilike(term),
                MovementMapping.location_code.ilike(term),
                MovementMapping.remarks.ilike(term),
            )
        )
    if status:
        q = q.filter(MovementMapping.status == status)
    if mapping_type:
        q = q.filter(MovementMapping.mapping_type == mapping_type)
    if location_code:
        q = q.filter(func.upper(MovementMapping.location_code) == location_code.strip().upper())
    if date_from:
        q = q.filter(MovementMapping.mapping_date >= date_from)
    if date_to:
        q = q.filter(MovementMapping.mapping_date <= date_to)

    result = paginate_query(
        q.order_by(MovementMapping.mapping_date.desc(), MovementMapping.id.desc()),
        page=page,
        page_size=page_size,
    )
    result["items"] = [_serialize_movement_mapping(r) for r in result["items"]]
    return result


@router.get("/movement-mappings/export")
def export_movement_mappings(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    status: str | None = None,
    mapping_type: str | None = None,
    location_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("movement_mappings:read")),
    db: Session = Depends(get_db),
):
    q = db.query(MovementMapping)
    if status:
        q = q.filter(MovementMapping.status == status)
    if mapping_type:
        q = q.filter(MovementMapping.mapping_type == mapping_type)
    if location_code:
        q = q.filter(func.upper(MovementMapping.location_code) == location_code.strip().upper())
    if date_from:
        q = q.filter(MovementMapping.mapping_date >= date_from)
    if date_to:
        q = q.filter(MovementMapping.mapping_date <= date_to)

    records = q.order_by(MovementMapping.mapping_date.desc()).limit(MAX_EXPORT_ROWS).all()
    headers = [
        "Mapping #",
        "Date",
        "Type",
        "Location",
        "Sender NSV (bbl)",
        "Receiver NSV (bbl)",
        "Variance NSV (bbl)",
        "Variance %",
        "Status",
    ]
    rows = [
        [
            r.mapping_number,
            r.mapping_date,
            r.mapping_type,
            r.location_code,
            _f(r.sender_total_nsv),
            _f(r.receiver_total_nsv),
            _f(r.variance_nsv),
            _f(r.variance_nsv_pct),
            r.status,
        ]
        for r in records
    ]
    create_audit_log(
        db,
        module_name="Movement Mapping",
        action="Export Movement Mappings",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} movement mappings as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("movement-mappings", headers, rows)
    if format == "xlsx":
        return xlsx_response("movement-mappings", "Movement Mappings", headers, rows)
    return pdf_response("movement-mappings", "Movement Mapping & Reconciliation", headers, rows)


def _populate_mapping_totals_and_items(
    db: Session,
    row: MovementMapping,
    item_inputs: list[MovementMappingItemInput],
):
    row.items.clear()
    db.flush()
    s_gov = s_gsv = s_nsv = 0.0
    r_gov = r_gsv = r_nsv = 0.0

    for item_in in item_inputs:
        entry = db.get(OperationEntry, item_in.entry_id)
        if entry is None or entry.status != "Approved":
            raise HTTPException(
                status_code=400,
                detail=f"Ticket #{item_in.entry_id} must exist and be Approved",
            )
        q = _extract_entry_quantities(entry)
        gov = item_in.allocated_gov if item_in.allocated_gov is not None else q["gov"]
        gsv = item_in.allocated_gsv if item_in.allocated_gsv is not None else q["gsv"]
        nsv = item_in.allocated_nsv if item_in.allocated_nsv is not None else q["nsv"]
        if item_in.role == "SENDER":
            s_gov += gov
            s_gsv += gsv
            s_nsv += nsv
        else:
            r_gov += gov
            r_gsv += gsv
            r_nsv += nsv
        db.add(
            MovementMappingItem(
                mapping_id=row.id,
                entry_id=entry.id,
                role=item_in.role,
                allocated_gov=gov,
                allocated_gsv=gsv,
                allocated_nsv=nsv,
                created_at=utcnow(),
            )
        )

    row.sender_total_gov = round(s_gov, 3)
    row.sender_total_gsv = round(s_gsv, 3)
    row.sender_total_nsv = round(s_nsv, 3)
    row.receiver_total_gov = round(r_gov, 3)
    row.receiver_total_gsv = round(r_gsv, 3)
    row.receiver_total_nsv = round(r_nsv, 3)
    row.variance_gov = round(r_gov - s_gov, 3)
    row.variance_gsv = round(r_gsv - s_gsv, 3)
    row.variance_nsv = round(r_nsv - s_nsv, 3)
    row.variance_nsv_pct = round(((r_nsv - s_nsv) / s_nsv) * 100.0, 4) if s_nsv else 0.0


@router.post("/movement-mappings", status_code=201)
def create_movement_mapping(
    payload: MovementMappingPayload,
    request: Request,
    actor: User = Depends(require_permission("movement_mappings:create")),
    db: Session = Depends(get_db),
):
    loc = (
        db.get(Location, payload.location_id)
        if payload.location_id
        else db.query(Location).filter(func.upper(Location.location_code) == payload.location_code.upper()).first()
    )
    if loc is None:
        raise HTTPException(status_code=400, detail="Location not found")
    today_str = payload.mapping_date.strftime("%Y%m%d")
    prefix = f"MM-{loc.location_code}-{today_str}"
    seq = db.query(MovementMapping).filter(MovementMapping.mapping_number.like(f"{prefix}%")).count() + 1

    row = MovementMapping(
        mapping_number=f"{prefix}-{seq:04d}",
        mapping_type=payload.mapping_type,
        location_id=loc.id,
        location_code=loc.location_code,
        mapping_date=payload.mapping_date,
        remarks=(payload.remarks or "").strip() or None,
        status=payload.status,
        created_by_user_id=actor.id,
        created_by=display_name(actor),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    _populate_mapping_totals_and_items(db, row, payload.items)

    create_audit_log(
        db,
        module_name="Movement Mapping",
        action="Create Movement Mapping",
        category="Data Change",
        current_user=actor,
        entity_type="MovementMapping",
        entity_id=row.id,
        entity_label=row.mapping_number,
        new_status=row.status,
        request=request,
        remarks="Movement mapping created",
        details_summary=f"mapping={row.mapping_number}; variance_nsv={row.variance_nsv}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_movement_mapping(row)


@router.put("/movement-mappings/{mapping_id}")
def update_movement_mapping(
    mapping_id: int,
    payload: MovementMappingPayload,
    request: Request,
    actor: User = Depends(require_permission("movement_mappings:update")),
    db: Session = Depends(get_db),
):
    row = db.get(MovementMapping, mapping_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Movement mapping not found")
    loc = (
        db.get(Location, payload.location_id)
        if payload.location_id
        else db.query(Location).filter(func.upper(Location.location_code) == payload.location_code.upper()).first()
    )
    if loc is None:
        raise HTTPException(status_code=400, detail="Location not found")

    old_status = row.status
    row.mapping_type = payload.mapping_type
    row.location_id = loc.id
    row.location_code = loc.location_code
    row.mapping_date = payload.mapping_date
    row.remarks = (payload.remarks or "").strip() or None
    row.status = payload.status
    row.updated_at = utcnow()
    _populate_mapping_totals_and_items(db, row, payload.items)

    create_audit_log(
        db,
        module_name="Movement Mapping",
        action="Update Movement Mapping",
        category="Data Change",
        current_user=actor,
        entity_type="MovementMapping",
        entity_id=row.id,
        entity_label=row.mapping_number,
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Movement mapping updated",
        details_summary=f"mapping={row.mapping_number}; variance_nsv={row.variance_nsv}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_movement_mapping(row)


@router.delete("/movement-mappings/{mapping_id}")
def delete_movement_mapping(
    mapping_id: int,
    request: Request,
    actor: User = Depends(require_permission("movement_mappings:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(MovementMapping, mapping_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Movement mapping not found")
    create_audit_log(
        db,
        module_name="Movement Mapping",
        action="Delete Movement Mapping",
        category="Data Change",
        current_user=actor,
        entity_type="MovementMapping",
        entity_id=row.id,
        entity_label=row.mapping_number,
        old_status=row.status,
        request=request,
        remarks="Movement mapping deleted",
        details_summary=f"mapping={row.mapping_number}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Movement mapping deleted successfully"}


# ===========================================================================
# 3. Operation Task Manager & Approved Transaction Correction Requests
# ===========================================================================
class TaskActionPayload(StrictModel):
    remarks: str | None = Field(default=None, max_length=2000)
    review_confirmed: bool = True


class CorrectionRequestCreatePayload(StrictModel):
    entry_id: int = Field(ge=1)
    request_type: Literal[
        "DATA_ENTRY_ERROR",
        "SEAL_CORRECTION",
        "MEASUREMENT_CORRECTION",
        "WRONG_ASSET_OR_ROUTE",
        "DUPLICATE_TICKET",
        "OTHER",
    ] = "DATA_ENTRY_ERROR"
    suggested_action: Literal[
        "REVOKE_TO_SUBMITTED",
        "REVOKE_AND_EDIT",
        "REVOKE_AND_CANCEL",
    ] = "REVOKE_TO_SUBMITTED"
    reason: str = Field(min_length=5, max_length=2000)


class CorrectionAdminActionPayload(StrictModel):
    remarks: str = Field(min_length=3, max_length=2000)


def _next_task_number(db: Session) -> str:
    today_str = utcnow().strftime("%Y%m%d")
    prefix = f"TASK-{today_str}"
    count = db.query(OperationTask).filter(OperationTask.task_number.like(f"{prefix}%")).count()
    return f"{prefix}-{count + 1:04d}"


def _effective_task_status_expression():
    """Mirror OTMS legacy open-task projection: if entry already moved, task reflects it."""
    is_open_approval = and_(
        OperationTask.task_type == "OPERATION_APPROVAL",
        OperationTask.status.in_(["Pending", "In Progress"]),
    )
    return case(
        (and_(is_open_approval, OperationEntry.status == "Approved"), "Approved"),
        (and_(is_open_approval, OperationEntry.status == "Rejected"), "Rejected"),
        (and_(is_open_approval, OperationEntry.status.in_(["Draft", "Cancelled"])), "Cancelled"),
        else_=OperationTask.status,
    )


def _sync_approval_tasks_for_submitted_entries(db: Session):
    """Ensure every currently Submitted OperationEntry has an open approval task."""
    submitted_entries = (
        db.query(OperationEntry)
        .filter(OperationEntry.status == "Submitted")
        .all()
    )
    if not submitted_entries:
        return
    # Only consider OPEN tasks as existing, so resubmitted tickets get new tasks (OTMS parity)
    existing_open_entry_ids = {
        eid
        for (eid,) in db.query(OperationTask.entry_id)
        .filter(
            OperationTask.task_type == "OPERATION_APPROVAL",
            OperationTask.entry_id.isnot(None),
            OperationTask.status.in_(["Pending", "In Progress"]),
        )
        .all()
    }
    created = False
    for entry in submitted_entries:
        if entry.id in existing_open_entry_ids:
            continue
        loc = db.get(Location, entry.location_id)
        task = OperationTask(
            task_number=_next_task_number(db),
            task_type="OPERATION_APPROVAL",
            entry_id=entry.id,
            ticket_number=entry.ticket_number,
            operation_code=entry.operation_code_snapshot,
            operation_type_code=entry.operation_type_code,
            asset_type_code=entry.asset_type_code,
            primary_asset_code=entry.asset_code_snapshot,
            location_id=entry.location_id,
            location_code=loc.location_code if loc else "",
            raised_by_user_id=entry.submitted_by_user_id or entry.created_by_user_id,
            status="Pending",
            priority="Normal",
            created_at=entry.submitted_at or entry.created_at or utcnow(),
            updated_at=utcnow(),
        )
        db.add(task)
        db.flush()
        db.add(
            OperationTaskEvent(
                task_id=task.id,
                event_type="Created",
                new_status="Pending",
                actor_user_id=entry.submitted_by_user_id or entry.created_by_user_id,
                actor_display="System / Submission Workflow",
                notes=f"Approval task created for submitted ticket {entry.ticket_number}",
                created_at=utcnow(),
            )
        )
        created = True
    if created:
        db.commit()


def _normalize_task_status(value: str | None) -> str | None:
    """Map legacy/alias statuses (OTMS Used 'In Review') to canonical HCA status."""
    if not value:
        return None
    v = value.strip()
    if v.lower() == "in review":
        return "In Progress"
    return v


def _serialize_task(db: Session, task: OperationTask, include_entry: bool = False) -> dict:
    entry = task.entry
    effective_status = task.status
    if task.task_type == "OPERATION_APPROVAL" and task.status in ("Pending", "In Progress") and entry:
        effective_status = {
            "Approved": "Approved",
            "Rejected": "Rejected",
            "Draft": "Cancelled",
            "Cancelled": "Cancelled",
        }.get(entry.status, task.status)

    correction = (
        db.query(ApprovedTransactionCorrectionRequest)
        .filter(ApprovedTransactionCorrectionRequest.task_id == task.id)
        .first()
    )
    return {
        "id": task.id,
        "task_number": task.task_number,
        "task_type": task.task_type,
        "entry_id": task.entry_id,
        "ticket_number": task.ticket_number or (entry.ticket_number if entry else ""),
        "operation_code": task.operation_code or (entry.operation_code_snapshot if entry else ""),
        "operation_type_code": task.operation_type_code or (entry.operation_type_code if entry else ""),
        "asset_type_code": task.asset_type_code or (entry.asset_type_code if entry else ""),
        "primary_asset_code": task.primary_asset_code or (entry.asset_code_snapshot if entry else ""),
        "location_id": task.location_id,
        "location_code": task.location_code or "",
        "raised_by_user_id": task.raised_by_user_id,
        "assigned_role_ids": [r.role_id for r in task.assigned_roles],
        "assigned_user_ids": [u.user_id for u in task.assigned_users],
        "status": effective_status,
        "priority": task.priority,
        "due_at": task.due_at,
        "taken_by_user_id": task.taken_by_user_id,
        "taken_at": task.taken_at,
        "acted_by_user_id": task.acted_by_user_id,
        "acted_at": task.acted_at,
        "action_taken": task.action_taken or "",
        "remarks": task.remarks or "",
        "correction_request": _serialize_correction(correction) if correction else None,
        "entry": operation_entry_to_dict(entry) if (include_entry and entry) else None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _serialize_correction(row: ApprovedTransactionCorrectionRequest) -> dict:
    return {
        "id": row.id,
        "request_number": row.request_number,
        "entry_id": row.entry_id,
        "task_id": row.task_id,
        "ticket_number": row.ticket_number,
        "operation_code": row.operation_code or "",
        "request_type": row.request_type,
        "suggested_action": row.suggested_action,
        "reason": row.reason,
        "status": row.status,
        "requested_by_user_id": row.requested_by_user_id,
        "requested_by_display": row.requested_by_display,
        "requested_at": row.requested_at,
        "admin_action": row.admin_action or "",
        "admin_remarks": row.admin_remarks or "",
        "admin_user_id": row.admin_user_id,
        "admin_action_at": row.admin_action_at,
        "previous_status_before_revoke": row.previous_status_before_revoke or "",
        "new_status_after_revoke": row.new_status_after_revoke or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/operation-tasks")
def list_operation_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    task_type: str | None = None,
    priority: str | None = None,
    location_code: str | None = None,
    operation_type_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    # OTMS alias params (frontend may send created_from/created_to or dateFrom/dateTo)
    created_from: date | None = None,
    created_to: date | None = None,
    actor: User = Depends(
        require_any_permission("operation_tasks:read", "operation_approvals:create", "operation_entries:read")
    ),
    db: Session = Depends(get_db),
):
    _sync_approval_tasks_for_submitted_entries(db)
    # Normalize status aliases
    status = _normalize_task_status(status)
    # Handle OTMS date aliases
    if created_from and not date_from:
        date_from = created_from
    if created_to and not date_to:
        date_to = created_to

    # Build base query with join for effective status counting
    effective_status = _effective_task_status_expression()
    q = db.query(OperationTask).outerjoin(OperationEntry, OperationEntry.id == OperationTask.entry_id)

    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        q = q.filter(or_(OperationTask.location_id.in_(allowed), OperationTask.location_id.is_(None)))
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                OperationTask.task_number.ilike(term),
                OperationTask.ticket_number.ilike(term),
                OperationTask.operation_code.ilike(term),
                OperationTask.primary_asset_code.ilike(term),
                OperationTask.location_code.ilike(term),
                OperationTask.remarks.ilike(term),
            )
        )
    if task_type:
        q = q.filter(OperationTask.task_type == task_type)
    if priority:
        q = q.filter(OperationTask.priority == priority)
    if location_code:
        q = q.filter(func.upper(OperationTask.location_code) == location_code.strip().upper())
    if operation_type_code:
        q = q.filter(OperationTask.operation_type_code == operation_type_code)
    if date_from:
        q = q.filter(OperationTask.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        q = q.filter(OperationTask.created_at <= datetime.combine(date_to, time.max))

    # Compute counts using effective status (OTMS parity)
    counts_query = q.with_entities(effective_status.label("eff_status"), func.count(OperationTask.id)).group_by(effective_status)
    counts_raw_list = counts_query.all()
    counts_raw = {str(k): int(v) for k, v in counts_raw_list if k is not None}
    # Fallback for tasks without entry (closed statuses)
    total_all = sum(counts_raw.values())

    # For status filter, apply effective status as well
    if status:
        q = q.filter(effective_status == status)

    result = paginate_query(
        q.order_by(OperationTask.created_at.desc(), OperationTask.id.desc()),
        page=page,
        page_size=page_size,
    )
    result["items"] = [_serialize_task(db, t, include_entry=False) for t in result["items"]]
    # Provide both status_counts and kpis for frontend compatibility (OTMS vs HCA)
    sc = {
        "All": total_all,
        "Pending": counts_raw.get("Pending", 0),
        "In Progress": counts_raw.get("In Progress", 0),
        "Approved": counts_raw.get("Approved", 0),
        "Rejected": counts_raw.get("Rejected", 0),
        "Cancelled": counts_raw.get("Cancelled", 0),
        "Closed": counts_raw.get("Closed", 0),
    }
    # Also expose lowercase keys for older frontend
    result["status_counts"] = sc
    result["kpis"] = {
        "total": total_all,
        "pending": counts_raw.get("Pending", 0),
        "in_progress": counts_raw.get("In Progress", 0),
        "in_review": counts_raw.get("In Progress", 0),
        "approved": counts_raw.get("Approved", 0),
        "rejected": counts_raw.get("Rejected", 0),
        "completed": counts_raw.get("Approved", 0) + counts_raw.get("Rejected", 0) + counts_raw.get("Cancelled", 0) + counts_raw.get("Closed", 0),
    }
    # Legacy OTMS keys
    result["total_rows"] = total_all
    result["rows"] = result["items"]
    return result


@router.get("/operation-tasks/export")
def export_operation_tasks(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    status: str | None = None,
    task_type: str | None = None,
    location_code: str | None = None,
    actor: User = Depends(require_any_permission("operation_tasks:read", "operation_approvals:create")),
    db: Session = Depends(get_db),
):
    q = db.query(OperationTask)
    if status:
        q = q.filter(OperationTask.status == status)
    if task_type:
        q = q.filter(OperationTask.task_type == task_type)
    if location_code:
        q = q.filter(func.upper(OperationTask.location_code) == location_code.strip().upper())
    records = q.order_by(OperationTask.id.desc()).limit(MAX_EXPORT_ROWS).all()
    headers = ["Task #", "Type", "Ticket #", "Operation Type", "Asset", "Location", "Priority", "Status", "Action Taken", "Created"]
    rows = [
        [
            t.task_number,
            t.task_type,
            t.ticket_number or "",
            t.operation_type_code or "",
            t.primary_asset_code or "",
            t.location_code or "",
            t.priority,
            t.status,
            t.action_taken or "",
            t.created_at,
        ]
        for t in records
    ]
    create_audit_log(
        db,
        module_name="Operation Task Manager",
        action="Export Operation Tasks",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} operation tasks as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("operation-tasks", headers, rows)
    if format == "xlsx":
        return xlsx_response("operation-tasks", "Operation Tasks", headers, rows)
    return pdf_response("operation-tasks", "Operation Task Manager", headers, rows)


@router.get("/operation-tasks/my")
def get_my_operation_tasks(
    status: str | None = None,
    task_type: str | None = None,
    search: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    actor: User = Depends(require_any_permission("operation_tasks:read", "operation_approvals:create", "operation_entries:read")),
    db: Session = Depends(get_db),
):
    _sync_approval_tasks_for_submitted_entries(db)
    q = db.query(OperationTask).outerjoin(OperationEntry, OperationEntry.id == OperationTask.entry_id)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        q = q.filter(or_(OperationTask.location_id.in_(allowed), OperationTask.location_id.is_(None)))
    status = _normalize_task_status(status)
    if status and status.upper() != "ALL":
        q = q.filter(_effective_task_status_expression() == status)
    if task_type and task_type != "ALL":
        q = q.filter(OperationTask.task_type == task_type)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                OperationTask.task_number.ilike(term),
                OperationTask.ticket_number.ilike(term),
                OperationTask.primary_asset_code.ilike(term),
                OperationTask.location_code.ilike(term),
            )
        )
    if created_from:
        q = q.filter(OperationTask.created_at >= datetime.combine(created_from, time.min))
    if created_to:
        q = q.filter(OperationTask.created_at <= datetime.combine(created_to, time.max))
    tasks = q.order_by(OperationTask.created_at.desc(), OperationTask.id.desc()).all()
    if not is_admin_user(actor, db):
        tasks = [t for t in tasks if _user_can_act_on_task(db, actor, t)]
    return [_serialize_task(db, t) for t in tasks]


@router.get("/operation-tasks/my/paged")
def get_my_operation_tasks_paged(
    status: str | None = None,
    task_type: str | None = None,
    search: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    actor: User = Depends(require_any_permission("operation_tasks:read", "operation_approvals:create", "operation_entries:read")),
    db: Session = Depends(get_db),
):
    """OTMS-compatible paged endpoint: returns rows, total_rows, status_counts, has_more."""
    _sync_approval_tasks_for_submitted_entries(db)
    try:
        cf = None
        ct = None
        if created_from:
            cf = date.fromisoformat(created_from) if isinstance(created_from, str) else created_from
        if created_to:
            ct = date.fromisoformat(created_to) if isinstance(created_to, str) else created_to
    except Exception:
        raise HTTPException(status_code=400, detail="created_from/created_to must be YYYY-MM-DD")
    status_norm = _normalize_task_status(status)
    effective_status = _effective_task_status_expression()
    base_q = db.query(OperationTask).outerjoin(OperationEntry, OperationEntry.id == OperationTask.entry_id)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        base_q = base_q.filter(or_(OperationTask.location_id.in_(allowed), OperationTask.location_id.is_(None)))
    if task_type and task_type != "ALL":
        base_q = base_q.filter(OperationTask.task_type == task_type)
    if search:
        term = f"%{search.strip()}%"
        base_q = base_q.filter(
            or_(
                OperationTask.task_number.ilike(term),
                OperationTask.ticket_number.ilike(term),
                OperationTask.operation_code.ilike(term),
                OperationTask.primary_asset_code.ilike(term),
                OperationTask.location_code.ilike(term),
            )
        )
    if cf:
        base_q = base_q.filter(OperationTask.created_at >= datetime.combine(cf, time.min))
    if ct:
        base_q = base_q.filter(OperationTask.created_at <= datetime.combine(ct, time.max))
    if not is_admin_user(actor, db):
        all_tasks = base_q.order_by(OperationTask.created_at.desc(), OperationTask.id.desc()).all()
        assigned_tasks = [t for t in all_tasks if _user_can_act_on_task(db, actor, t)]
        counts = {}
        for t in assigned_tasks:
            eff = _serialize_task(db, t)["status"]
            counts[eff] = counts.get(eff, 0) + 1
        counts["ALL"] = len(assigned_tasks)
        total_rows = counts.get(status_norm, 0) if status_norm and status_norm.upper() != "ALL" else counts["ALL"]
        if status_norm and status_norm.upper() != "ALL":
            assigned_tasks = [t for t in assigned_tasks if _serialize_task(db, t)["status"] == status_norm]
        page = max(int(page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        start = (page - 1) * page_size
        page_rows = assigned_tasks[start : start + page_size]
        has_more = len(assigned_tasks) > start + page_size
        rows = [_serialize_task(db, t) for t in page_rows]
        return {
            "rows": rows,
            "total_rows": total_rows,
            "total": total_rows,
            "page": page,
            "page_size": page_size,
            "has_more": has_more,
            "status_counts": counts,
            "items": rows,
        }
    counts_list = base_q.with_entities(effective_status.label("eff"), func.count(OperationTask.id)).group_by(effective_status).all()
    status_counts = {str(k): int(v) for k, v in counts_list if k is not None}
    status_counts["ALL"] = sum(status_counts.values())
    wanted = status_norm
    total_rows = status_counts.get(wanted, 0) if wanted and wanted.upper() != "ALL" else status_counts["ALL"]
    page_q = base_q
    if wanted and wanted.upper() != "ALL":
        page_q = page_q.filter(effective_status == wanted)
    page_q = page_q.order_by(OperationTask.created_at.desc(), OperationTask.id.desc())
    page = max(int(page or 1), 1)
    page_size = max(min(int(page_size or 20), 100), 1)
    offset = (page - 1) * page_size
    page_rows = page_q.offset(offset).limit(page_size + 1).all()
    has_more = len(page_rows) > page_size
    page_rows = page_rows[:page_size]
    rows = [_serialize_task(db, t) for t in page_rows]
    return {
        "rows": rows,
        "total_rows": total_rows,
        "total": total_rows,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
        "status_counts": status_counts,
        "items": rows,
    }


@router.get("/operation-tasks/{task_id}")
def get_operation_task_detail(
    task_id: int,
    actor: User = Depends(
        require_any_permission("operation_tasks:read", "operation_approvals:create", "operation_entries:read")
    ),
    db: Session = Depends(get_db),
):
    task = db.get(OperationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Operation task not found")
    data = _serialize_task(db, task, include_entry=True)
    data["events"] = [
        {
            "id": ev.id,
            "event_type": ev.event_type,
            "old_status": ev.old_status or "",
            "new_status": ev.new_status or "",
            "actor_display": ev.actor_display or "",
            "notes": ev.notes or "",
            "created_at": ev.created_at,
        }
        for ev in task.events
    ]
    return data


@router.post("/operation-tasks/{task_id}/take")
def take_operation_task(
    task_id: int,
    payload: TaskActionPayload | None = None,
    request: Request = None,
    actor: User = Depends(require_any_permission("operation_tasks:update", "operation_approvals:create")),
    db: Session = Depends(get_db),
):
    task = db.get(OperationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Operation task not found")
    if task.status not in ("Pending", "In Progress"):
        raise HTTPException(status_code=400, detail="Only open tasks can be claimed")
    old_status = task.status
    task.status = "In Progress"
    task.taken_by_user_id = actor.id
    task.taken_at = utcnow()
    task.updated_at = utcnow()
    db.add(
        OperationTaskEvent(
            task_id=task.id,
            event_type="Claimed",
            old_status=old_status,
            new_status="In Progress",
            actor_user_id=actor.id,
            actor_display=display_name(actor),
            notes=(payload.remarks if payload else None) or "Task claimed for review",
            created_at=utcnow(),
        )
    )
    create_audit_log(
        db,
        module_name="Operation Task Manager",
        action="Claim Operation Task",
        category="Workflow",
        current_user=actor,
        entity_type="OperationTask",
        entity_id=task.id,
        entity_label=task.task_number,
        old_status=old_status,
        new_status=task.status,
        request=request,
        remarks="Operation task claimed",
        details_summary=f"task={task.task_number}; ticket={task.ticket_number}",
    )
    db.commit()
    db.refresh(task)
    request.state.audit_written = True
    return _serialize_task(db, task, include_entry=True)


@router.post("/operation-tasks/{task_id}/release")
def release_operation_task(
    task_id: int,
    payload: TaskActionPayload | None = None,
    request: Request = None,
    actor: User = Depends(require_any_permission("operation_tasks:update", "operation_approvals:create")),
    db: Session = Depends(get_db),
):
    task = db.get(OperationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Operation task not found")
    if task.status != "In Progress":
        raise HTTPException(status_code=400, detail="Only In Progress tasks can be released")
    task.status = "Pending"
    task.taken_by_user_id = None
    task.taken_at = None
    task.updated_at = utcnow()
    db.add(
        OperationTaskEvent(
            task_id=task.id,
            event_type="Released",
            old_status="In Progress",
            new_status="Pending",
            actor_user_id=actor.id,
            actor_display=display_name(actor),
            notes=(payload.remarks if payload else None) or "Task released back to queue",
            created_at=utcnow(),
        )
    )
    create_audit_log(
        db,
        module_name="Operation Task Manager",
        action="Release Operation Task",
        category="Workflow",
        current_user=actor,
        entity_type="OperationTask",
        entity_id=task.id,
        entity_label=task.task_number,
        old_status="In Progress",
        new_status="Pending",
        request=request,
        remarks="Operation task released",
        details_summary=f"task={task.task_number}",
    )
    db.commit()
    db.refresh(task)
    request.state.audit_written = True
    return _serialize_task(db, task, include_entry=True)


@router.post("/operation-tasks/{task_id}/approve")
def approve_operation_task(
    task_id: int,
    payload: TaskActionPayload,
    request: Request,
    actor: User = Depends(require_any_permission("operation_approvals:create", "operation_tasks:update")),
    db: Session = Depends(get_db),
):
    from app.routers.operation_entries import _posting

    task = db.get(OperationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Operation task not found")
    if task.status not in ("Pending", "In Progress"):
        raise HTTPException(status_code=400, detail="Only open tasks can be approved")

    entry = task.entry
    if entry and entry.status == "Submitted":
        old_entry_status = entry.status
        entry.status = "Approved"
        entry.status_remarks = (payload.remarks or "").strip() or "Approved via Operation Task Manager"
        entry.reviewed_by_user_id = actor.id
        entry.reviewed_at = utcnow()
        entry.approved_by_user_id = actor.id
        entry.approved_at = utcnow()
        entry.updated_by_user_id = actor.id
        entry.updated_at = utcnow()
        _posting(db, entry)
        db.add(
            OperationEntryStatusHistory(
                entry_id=entry.id,
                from_status=old_entry_status,
                to_status="Approved",
                action="Approve",
                actor_user_id=actor.id,
                remarks=entry.status_remarks,
                created_at=utcnow(),
            )
        )

    old_status = task.status
    task.status = "Approved"
    task.action_taken = "Approved"
    task.acted_by_user_id = actor.id
    task.acted_at = utcnow()
    task.remarks = (payload.remarks or "").strip() or "Approved"
    task.updated_at = utcnow()
    db.add(
        OperationTaskEvent(
            task_id=task.id,
            event_type="Approved",
            old_status=old_status,
            new_status="Approved",
            actor_user_id=actor.id,
            actor_display=display_name(actor),
            notes=task.remarks,
            created_at=utcnow(),
        )
    )
    create_audit_log(
        db,
        module_name="Operation Task Manager",
        action="Approve Operation Task",
        category="Workflow",
        current_user=actor,
        entity_type="OperationTask",
        entity_id=task.id,
        entity_label=task.task_number,
        old_status=old_status,
        new_status="Approved",
        request=request,
        remarks=task.remarks,
        details_summary=f"task={task.task_number}; ticket={task.ticket_number}",
    )
    db.commit()
    db.refresh(task)
    request.state.audit_written = True
    return _serialize_task(db, task, include_entry=True)


@router.post("/operation-tasks/{task_id}/reject")
def reject_operation_task(
    task_id: int,
    payload: TaskActionPayload,
    request: Request,
    actor: User = Depends(require_any_permission("operation_approvals:update", "operation_tasks:update")),
    db: Session = Depends(get_db),
):
    remarks = (payload.remarks or "").strip()
    if not remarks:
        raise HTTPException(status_code=400, detail="Rejection remarks are required")
    task = db.get(OperationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Operation task not found")
    if task.status not in ("Pending", "In Progress"):
        raise HTTPException(status_code=400, detail="Only open tasks can be rejected")

    entry = task.entry
    if entry and entry.status == "Submitted":
        old_entry_status = entry.status
        entry.status = "Rejected"
        entry.status_remarks = remarks
        entry.updated_by_user_id = actor.id
        entry.updated_at = utcnow()
        db.add(
            OperationEntryStatusHistory(
                entry_id=entry.id,
                from_status=old_entry_status,
                to_status="Rejected",
                action="Reject",
                actor_user_id=actor.id,
                remarks=remarks,
                created_at=utcnow(),
            )
        )

    old_status = task.status
    task.status = "Rejected"
    task.action_taken = "Rejected"
    task.acted_by_user_id = actor.id
    task.acted_at = utcnow()
    task.remarks = remarks
    task.updated_at = utcnow()
    db.add(
        OperationTaskEvent(
            task_id=task.id,
            event_type="Rejected",
            old_status=old_status,
            new_status="Rejected",
            actor_user_id=actor.id,
            actor_display=display_name(actor),
            notes=remarks,
            created_at=utcnow(),
        )
    )
    create_audit_log(
        db,
        module_name="Operation Task Manager",
        action="Reject Operation Task",
        category="Workflow",
        current_user=actor,
        entity_type="OperationTask",
        entity_id=task.id,
        entity_label=task.task_number,
        old_status=old_status,
        new_status="Rejected",
        request=request,
        remarks=remarks,
        details_summary=f"task={task.task_number}; ticket={task.ticket_number}",
    )
    db.commit()
    db.refresh(task)
    request.state.audit_written = True
    return _serialize_task(db, task, include_entry=True)


def _user_can_act_on_task(db: Session, user: User, task: OperationTask) -> bool:
    """Check if user is assigned via direct or role assignment (OTMS parity)."""
    if is_admin_user(user, db):
        return True
    # direct assignment
    direct = db.query(OperationTaskUser).filter(OperationTaskUser.task_id == task.id, OperationTaskUser.user_id == user.id).first()
    if direct:
        return True
    # role assignment
    user_role_ids = get_user_role_ids(db, user) or []
    if user_role_ids:
        role_match = (
            db.query(OperationTaskRole)
            .filter(OperationTaskRole.task_id == task.id, OperationTaskRole.role_id.in_(user_role_ids))
            .first()
        )
        if role_match:
            return True
    # If task has no assignments, allow any user with operation_tasks:read to act (fallback for legacy)
    if not task.assigned_roles and not task.assigned_users:
        return True
    return False


@router.get("/operation-tasks/{task_id}/events")
def get_operation_task_events(
    task_id: int,
    actor: User = Depends(require_any_permission("operation_tasks:read", "operation_approvals:create", "operation_entries:read")),
    db: Session = Depends(get_db),
):
    task = db.get(OperationTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Operation task not found")
    events = (
        db.query(OperationTaskEvent)
        .filter(OperationTaskEvent.task_id == task_id)
        .order_by(OperationTaskEvent.created_at.asc(), OperationTaskEvent.id.asc())
        .all()
    )
    return [
        {
            "id": ev.id,
            "event_type": ev.event_type,
            "old_status": ev.old_status or "",
            "new_status": ev.new_status or "",
            "actor_display": ev.actor_display or "",
            "actor_user_id": ev.actor_user_id,
            "notes": ev.notes or "",
            "created_at": ev.created_at,
        }
        for ev in events
    ]


@router.post("/operation-tasks/{task_id}/take-ownership")
def take_ownership_operation_task(
    task_id: int,
    payload: TaskActionPayload | None = None,
    request: Request = None,
    actor: User = Depends(require_any_permission("operation_tasks:update", "operation_approvals:create")),
    db: Session = Depends(get_db),
):
    """OTMS alias: take-ownership -> take"""
    return take_operation_task(task_id=task_id, payload=payload, request=request, actor=actor, db=db)


@router.post("/operation-tasks/{task_id}/admin-revoke-approved-transaction")
def admin_revoke_approved_transaction_task(
    task_id: int,
    payload: CorrectionAdminActionPayload | None = None,
    request: Request = None,
    actor: User = Depends(require_any_permission("correction_requests:update", "operation_approvals:update")),
    db: Session = Depends(get_db),
):
    task = db.get(OperationTask, task_id)
    if task is None or task.task_type != "APPROVED_TRANSACTION_REVOKE_REQUEST":
        raise HTTPException(status_code=404, detail="Approved transaction revoke task not found")
    if task.status not in ("Pending", "In Progress"):
        raise HTTPException(status_code=400, detail="Only open revoke tasks can be acted on")
    # Delegate to correction revoke logic via correction_id
    corr = db.query(ApprovedTransactionCorrectionRequest).filter(ApprovedTransactionCorrectionRequest.task_id == task.id).first()
    if not corr:
        raise HTTPException(status_code=404, detail="Correction request not found for this task")
    return admin_revoke_approved_transaction(correction_id=corr.id, payload=payload or CorrectionAdminActionPayload(remarks="Admin revoked via Task Manager"), request=request, actor=actor, db=db)


@router.post("/operation-tasks/{task_id}/admin-reject-approved-revoke")
def admin_reject_approved_revoke_task(
    task_id: int,
    payload: CorrectionAdminActionPayload | None = None,
    request: Request = None,
    actor: User = Depends(require_any_permission("correction_requests:update", "operation_approvals:update")),
    db: Session = Depends(get_db),
):
    task = db.get(OperationTask, task_id)
    if task is None or task.task_type != "APPROVED_TRANSACTION_REVOKE_REQUEST":
        raise HTTPException(status_code=404, detail="Approved transaction revoke task not found")
    if task.status not in ("Pending", "In Progress"):
        raise HTTPException(status_code=400, detail="Only open revoke tasks can be rejected")
    corr = db.query(ApprovedTransactionCorrectionRequest).filter(ApprovedTransactionCorrectionRequest.task_id == task.id).first()
    if not corr:
        raise HTTPException(status_code=404, detail="Correction request not found for this task")
    return admin_reject_correction_request(correction_id=corr.id, payload=payload or CorrectionAdminActionPayload(remarks="Admin rejected via Task Manager"), request=request, actor=actor, db=db)


# ---------------------------------------------------------------------------
# Approved Transaction Correction Requests
# ---------------------------------------------------------------------------
@router.get("/correction-requests")
def list_correction_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    request_type: str | None = None,
    entry_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(
        require_any_permission("correction_requests:read", "operation_transactions:read", "operation_entries:read")
    ),
    db: Session = Depends(get_db),
):
    q = db.query(ApprovedTransactionCorrectionRequest)
    if entry_id:
        q = q.filter(ApprovedTransactionCorrectionRequest.entry_id == entry_id)
    if status:
        q = q.filter(ApprovedTransactionCorrectionRequest.status == status)
    if request_type:
        q = q.filter(ApprovedTransactionCorrectionRequest.request_type == request_type)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                ApprovedTransactionCorrectionRequest.request_number.ilike(term),
                ApprovedTransactionCorrectionRequest.ticket_number.ilike(term),
                ApprovedTransactionCorrectionRequest.reason.ilike(term),
            )
        )
    if date_from:
        q = q.filter(ApprovedTransactionCorrectionRequest.requested_at >= datetime.combine(date_from, time.min))
    if date_to:
        q = q.filter(ApprovedTransactionCorrectionRequest.requested_at <= datetime.combine(date_to, time.max))

    result = paginate_query(
        q.order_by(ApprovedTransactionCorrectionRequest.id.desc()),
        page=page,
        page_size=page_size,
    )
    result["items"] = [_serialize_correction(r) for r in result["items"]]
    return result


@router.post("/correction-requests", status_code=201)
def create_correction_request(
    payload: CorrectionRequestCreatePayload,
    request: Request,
    actor: User = Depends(
        require_any_permission("correction_requests:create", "operation_entries:update", "operation_submissions:create")
    ),
    db: Session = Depends(get_db),
):
    entry = db.get(OperationEntry, payload.entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Operation ticket not found")
    if entry.status != "Approved":
        raise HTTPException(status_code=400, detail="Only Approved tickets can have a correction request")

    existing_open = (
        db.query(ApprovedTransactionCorrectionRequest)
        .filter(
            ApprovedTransactionCorrectionRequest.entry_id == entry.id,
            ApprovedTransactionCorrectionRequest.status == "Pending Admin Review",
        )
        .first()
    )
    if existing_open:
        raise HTTPException(status_code=409, detail="This ticket already has a pending correction request")

    today_str = utcnow().strftime("%Y%m%d")
    prefix = f"COR-{today_str}"
    count = (
        db.query(ApprovedTransactionCorrectionRequest)
        .filter(ApprovedTransactionCorrectionRequest.request_number.like(f"{prefix}%"))
        .count()
    )
    loc = db.get(Location, entry.location_id)
    corr = ApprovedTransactionCorrectionRequest(
        request_number=f"{prefix}-{count + 1:04d}",
        entry_id=entry.id,
        ticket_number=entry.ticket_number,
        operation_code=entry.operation_code_snapshot,
        request_type=payload.request_type,
        suggested_action=payload.suggested_action,
        reason=payload.reason.strip(),
        status="Pending Admin Review",
        requested_by_user_id=actor.id,
        requested_by_display=display_name(actor),
        requested_at=utcnow(),
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(corr)
    db.flush()

    task = OperationTask(
        task_number=_next_task_number(db),
        task_type="APPROVED_TRANSACTION_REVOKE_REQUEST",
        entry_id=entry.id,
        ticket_number=entry.ticket_number,
        operation_code=entry.operation_code_snapshot,
        operation_type_code=entry.operation_type_code,
        asset_type_code=entry.asset_type_code,
        primary_asset_code=entry.asset_code_snapshot,
        location_id=entry.location_id,
        location_code=loc.location_code if loc else "",
        raised_by_user_id=actor.id,
        status="Pending",
        priority="High",
        remarks=f"{corr.request_number}: {corr.request_type} ({corr.suggested_action}) — {corr.reason}",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(task)
    db.flush()
    corr.task_id = task.id

    db.add(
        OperationTaskEvent(
            task_id=task.id,
            event_type="Created",
            new_status="Pending",
            actor_user_id=actor.id,
            actor_display=display_name(actor),
            notes=f"Approved ticket correction request {corr.request_number} raised",
            created_at=utcnow(),
        )
    )
    create_audit_log(
        db,
        module_name="Approved Transaction Corrections",
        action="Create Correction Request",
        category="Workflow",
        current_user=actor,
        entity_type="ApprovedTransactionCorrectionRequest",
        entity_id=corr.id,
        entity_label=corr.request_number,
        new_status=corr.status,
        request=request,
        remarks=corr.reason,
        details_summary=f"request={corr.request_number}; ticket={entry.ticket_number}; type={corr.request_type}",
        status_code=201,
    )
    db.commit()
    db.refresh(corr)
    request.state.audit_written = True
    return _serialize_correction(corr)


@router.post("/correction-requests/{correction_id}/revoke")
def admin_revoke_approved_transaction(
    correction_id: int,
    payload: CorrectionAdminActionPayload,
    request: Request,
    actor: User = Depends(require_any_permission("correction_requests:update", "operation_approvals:update")),
    db: Session = Depends(get_db),
):
    corr = db.get(ApprovedTransactionCorrectionRequest, correction_id)
    if corr is None:
        raise HTTPException(status_code=404, detail="Correction request not found")
    if corr.status != "Pending Admin Review":
        raise HTTPException(status_code=400, detail="Correction request is already resolved")

    entry = db.get(OperationEntry, corr.entry_id)
    if entry is None or entry.status != "Approved":
        raise HTTPException(status_code=400, detail="Linked ticket is not currently Approved")

    # Reverse postings derived from this approved ticket
    db.query(OperationPosting).filter(OperationPosting.entry_id == entry.id).delete()

    old_entry_status = entry.status
    target_status = {
        "REVOKE_TO_SUBMITTED": "Submitted",
        "REVOKE_AND_EDIT": "Draft",
        "REVOKE_AND_CANCEL": "Cancelled",
    }.get(corr.suggested_action, "Submitted")

    entry.status = target_status
    entry.status_remarks = f"[ADMIN APPROVAL REVOKE] {payload.remarks.strip()}"
    entry.approved_by_user_id = None
    entry.approved_at = None
    entry.updated_by_user_id = actor.id
    entry.updated_at = utcnow()
    if target_status == "Cancelled":
        entry.receiver_link_key = None

    db.add(
        OperationEntryStatusHistory(
            entry_id=entry.id,
            from_status=old_entry_status,
            to_status=target_status,
            action="Admin Revoke Approval",
            actor_user_id=actor.id,
            remarks=entry.status_remarks,
            created_at=utcnow(),
        )
    )

    corr.status = "Admin Revoked"
    corr.admin_action = "Revoked"
    corr.admin_remarks = payload.remarks.strip()
    corr.admin_user_id = actor.id
    corr.admin_action_at = utcnow()
    corr.previous_status_before_revoke = old_entry_status
    corr.new_status_after_revoke = target_status
    corr.updated_at = utcnow()

    if corr.task_id:
        task = db.get(OperationTask, corr.task_id)
        if task:
            old_t = task.status
            task.status = "Approved"
            task.action_taken = "Admin Revoked"
            task.acted_by_user_id = actor.id
            task.acted_at = utcnow()
            task.remarks = payload.remarks.strip()
            task.updated_at = utcnow()
            db.add(
                OperationTaskEvent(
                    task_id=task.id,
                    event_type="Admin Revoked",
                    old_status=old_t,
                    new_status="Approved",
                    actor_user_id=actor.id,
                    actor_display=display_name(actor),
                    notes=payload.remarks.strip(),
                    created_at=utcnow(),
                )
            )

    create_audit_log(
        db,
        module_name="Approved Transaction Corrections",
        action="Admin Revoke Approved Ticket",
        category="Workflow",
        current_user=actor,
        entity_type="ApprovedTransactionCorrectionRequest",
        entity_id=corr.id,
        entity_label=corr.request_number,
        old_status="Pending Admin Review",
        new_status="Admin Revoked",
        request=request,
        remarks=payload.remarks.strip(),
        details_summary=f"request={corr.request_number}; ticket={entry.ticket_number}; new_ticket_status={target_status}",
    )
    db.commit()
    db.refresh(corr)
    request.state.audit_written = True
    return _serialize_correction(corr)


@router.post("/correction-requests/{correction_id}/reject")
def admin_reject_correction_request(
    correction_id: int,
    payload: CorrectionAdminActionPayload,
    request: Request,
    actor: User = Depends(require_any_permission("correction_requests:update", "operation_approvals:update")),
    db: Session = Depends(get_db),
):
    corr = db.get(ApprovedTransactionCorrectionRequest, correction_id)
    if corr is None:
        raise HTTPException(status_code=404, detail="Correction request not found")
    if corr.status != "Pending Admin Review":
        raise HTTPException(status_code=400, detail="Correction request is already resolved")

    corr.status = "Rejected"
    corr.admin_action = "Rejected"
    corr.admin_remarks = payload.remarks.strip()
    corr.admin_user_id = actor.id
    corr.admin_action_at = utcnow()
    corr.updated_at = utcnow()

    if corr.task_id:
        task = db.get(OperationTask, corr.task_id)
        if task:
            old_t = task.status
            task.status = "Rejected"
            task.action_taken = "Admin Rejected"
            task.acted_by_user_id = actor.id
            task.acted_at = utcnow()
            task.remarks = payload.remarks.strip()
            task.updated_at = utcnow()
            db.add(
                OperationTaskEvent(
                    task_id=task.id,
                    event_type="Admin Rejected",
                    old_status=old_t,
                    new_status="Rejected",
                    actor_user_id=actor.id,
                    actor_display=display_name(actor),
                    notes=payload.remarks.strip(),
                    created_at=utcnow(),
                )
            )

    create_audit_log(
        db,
        module_name="Approved Transaction Corrections",
        action="Reject Correction Request",
        category="Workflow",
        current_user=actor,
        entity_type="ApprovedTransactionCorrectionRequest",
        entity_id=corr.id,
        entity_label=corr.request_number,
        old_status="Pending Admin Review",
        new_status="Rejected",
        request=request,
        remarks=payload.remarks.strip(),
        details_summary=f"request={corr.request_number}; ticket={corr.ticket_number}",
    )
    db.commit()
    db.refresh(corr)
    request.state.audit_written = True
    return _serialize_correction(corr)
