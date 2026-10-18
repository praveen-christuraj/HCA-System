"""Extended Configurations APIs:
  - Location Operation Availability & Location Operation Summary
  - Location Accounting Day Setting
  - Company Report Profile Master
  - Material Balance Template Master (typed columns & operation mappings — zero JSON)
"""

from __future__ import annotations

from datetime import date, datetime, time
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
    CompanyReportProfile,
    Location,
    LocationAccountingDaySetting,
    LocationOperationAvailability,
    MaterialBalanceTemplate,
    MaterialBalanceTemplateColumn,
    MaterialBalanceTemplateColumnOperation,
    Operation,
    User,
)
from app.services.audit_service import create_audit_log
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.operation_types import get_operation_type, operation_type_catalog
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(tags=["Configurations Extended"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ===========================================================================
# 1. Location Operation Availability & Location Operation Summary
# ===========================================================================
class LocationOperationAvailabilityPayload(StrictModel):
    location_id: int | None = None
    location_code: str = Field(min_length=1, max_length=50)
    operation_type_code: str = Field(min_length=1, max_length=50)
    status: Literal["Active", "Inactive"] = "Active"
    remarks: str | None = Field(default=None, max_length=2000)


def _serialize_availability(row: LocationOperationAvailability, loc: Location | None) -> dict:
    op_type = get_operation_type(row.operation_type_code)
    return {
        "id": row.id,
        "location_id": row.location_id,
        "location_code": row.location_code,
        "location_name": loc.location_name if loc else "",
        "operation_type_code": row.operation_type_code,
        "operation_type_name": op_type["name"] if op_type else row.operation_type_code,
        "asset_type_code": op_type["asset_type_code"] if op_type else "",
        "status": row.status,
        "remarks": row.remarks or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/location-operation-availability")
def list_location_operation_availability(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    operation_type_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(
        require_any_permission(
            "location_operation_availability:read",
            "operations:read",
            "operation_entries:read",
        )
    ),
    db: Session = Depends(get_db),
):
    query = db.query(LocationOperationAvailability)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        query = query.filter(LocationOperationAvailability.location_id.in_(allowed))
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                LocationOperationAvailability.location_code.ilike(term),
                LocationOperationAvailability.operation_type_code.ilike(term),
                LocationOperationAvailability.remarks.ilike(term),
            )
        )
    if status:
        query = query.filter(LocationOperationAvailability.status == status)
    if location_code:
        query = query.filter(
            func.upper(LocationOperationAvailability.location_code) == location_code.strip().upper()
        )
    if operation_type_code:
        query = query.filter(LocationOperationAvailability.operation_type_code == operation_type_code)
    if date_from:
        query = query.filter(LocationOperationAvailability.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(LocationOperationAvailability.created_at <= datetime.combine(date_to, time.max))

    result = paginate_query(
        query.order_by(LocationOperationAvailability.location_code.asc(), LocationOperationAvailability.id.asc()),
        page=page,
        page_size=page_size,
    )
    locs = {l.id: l for l in db.query(Location).all()}
    result["items"] = [_serialize_availability(r, locs.get(r.location_id)) for r in result["items"]]
    result["operation_types"] = operation_type_catalog()
    return result


@router.get("/location-operation-availability/summary")
def location_operation_summary(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    location_code: str | None = None,
    operation_type_code: str | None = None,
    status: str | None = None,
    actor: User = Depends(
        require_any_permission(
            "location_operation_availability:read",
            "operations:read",
        )
    ),
    db: Session = Depends(get_db),
):
    """Matrix summary of Locations × Operation Types × Configured Operations."""
    allowed = get_user_location_ids(db, actor)
    loc_q = db.query(Location)
    if allowed is not None:
        loc_q = loc_q.filter(Location.id.in_(allowed))
    if location_code:
        loc_q = loc_q.filter(func.upper(Location.location_code) == location_code.strip().upper())
    if status:
        loc_q = loc_q.filter(Location.status == status)
    if search:
        term = f"%{search.strip()}%"
        loc_q = loc_q.filter(or_(Location.location_code.ilike(term), Location.location_name.ilike(term)))

    locations = loc_q.order_by(Location.location_code.asc()).all()
    avail_rows = db.query(LocationOperationAvailability).all()
    avail_by_loc: dict[int, list[LocationOperationAvailability]] = {}
    for a in avail_rows:
        avail_by_loc.setdefault(a.location_id, []).append(a)

    ops = db.query(Operation).all()
    ops_by_loc: dict[int, list[Operation]] = {}
    for op in ops:
        ops_by_loc.setdefault(op.location_id, []).append(op)

    summary_rows = []
    for loc in locations:
        loc_avails = avail_by_loc.get(loc.id, [])
        loc_ops = ops_by_loc.get(loc.id, [])
        if operation_type_code:
            loc_avails = [a for a in loc_avails if a.operation_type_code == operation_type_code]
            loc_ops = [o for o in loc_ops if o.operation_type_code == operation_type_code]

        type_breakdown = []
        for op_type in operation_type_catalog():
            code = op_type["code"]
            if operation_type_code and code != operation_type_code:
                continue
            avail = next((a for a in loc_avails if a.operation_type_code == code), None)
            matching_ops = [o for o in loc_ops if o.operation_type_code == code]
            active_ops = [o for o in matching_ops if o.status == "Active"]
            type_breakdown.append(
                {
                    "operation_type_code": code,
                    "operation_type_name": op_type["name"],
                    "availability_status": avail.status if avail else ("Implicit" if active_ops else "Not Configured"),
                    "total_operations": len(matching_ops),
                    "active_operations": len(active_ops),
                    "operation_codes": [o.operation_code for o in active_ops],
                }
            )
        summary_rows.append(
            {
                "location_id": loc.id,
                "location_code": loc.location_code,
                "location_name": loc.location_name,
                "location_type": loc.location_type,
                "location_status": loc.status,
                "configured_type_count": sum(
                    1 for t in type_breakdown if t["availability_status"] in ("Active", "Implicit")
                ),
                "total_operations": len(loc_ops),
                "active_operations": sum(1 for o in loc_ops if o.status == "Active"),
                "types": type_breakdown,
            }
        )

    total = len(summary_rows)
    start = (page - 1) * page_size
    paged = summary_rows[start : start + page_size]
    pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": paged,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "has_more": page < pages,
        "operation_types": operation_type_catalog(),
    }


@router.get("/location-operation-availability/export")
def export_location_operation_availability(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    operation_type_code: str | None = None,
    actor: User = Depends(require_permission("location_operation_availability:read")),
    db: Session = Depends(get_db),
):
    query = db.query(LocationOperationAvailability)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        query = query.filter(LocationOperationAvailability.location_id.in_(allowed))
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                LocationOperationAvailability.location_code.ilike(term),
                LocationOperationAvailability.operation_type_code.ilike(term),
            )
        )
    if status:
        query = query.filter(LocationOperationAvailability.status == status)
    if location_code:
        query = query.filter(
            func.upper(LocationOperationAvailability.location_code) == location_code.strip().upper()
        )
    if operation_type_code:
        query = query.filter(LocationOperationAvailability.operation_type_code == operation_type_code)

    records = query.order_by(LocationOperationAvailability.location_code.asc()).limit(MAX_EXPORT_ROWS).all()
    locs = {l.id: l for l in db.query(Location).all()}
    headers = ["Location Code", "Location Name", "Operation Type Code", "Operation Type Name", "Status", "Remarks"]
    rows = []
    for r in records:
        s = _serialize_availability(r, locs.get(r.location_id))
        rows.append([s["location_code"], s["location_name"], s["operation_type_code"], s["operation_type_name"], s["status"], s["remarks"]])

    create_audit_log(
        db,
        module_name="Location Operation Availability",
        action="Export Location Operation Availability",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} availability rows as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("location-operation-availability", headers, rows)
    if format == "xlsx":
        return xlsx_response("location-operation-availability", "Location Availability", headers, rows)
    return pdf_response("location-operation-availability", "Location Operation Availability", headers, rows)


@router.post("/location-operation-availability", status_code=201)
def create_location_operation_availability(
    payload: LocationOperationAvailabilityPayload,
    request: Request,
    actor: User = Depends(require_permission("location_operation_availability:create")),
    db: Session = Depends(get_db),
):
    loc = (
        db.get(Location, payload.location_id)
        if payload.location_id
        else db.query(Location).filter(func.upper(Location.location_code) == payload.location_code.upper()).first()
    )
    if loc is None:
        raise HTTPException(status_code=400, detail="Location not found")
    if loc.status != "Active":
        raise HTTPException(status_code=400, detail="Only Active locations can be configured")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and loc.id not in allowed:
        raise HTTPException(status_code=403, detail="Location is outside your assigned scope")

    op_type = get_operation_type(payload.operation_type_code)
    if op_type is None:
        raise HTTPException(status_code=400, detail="Unknown operation type code")

    dup = (
        db.query(LocationOperationAvailability)
        .filter(
            LocationOperationAvailability.location_id == loc.id,
            LocationOperationAvailability.operation_type_code == op_type["code"],
        )
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="This operation type is already configured for this location")

    row = LocationOperationAvailability(
        location_id=loc.id,
        location_code=loc.location_code,
        operation_type_code=op_type["code"],
        status=payload.status,
        remarks=(payload.remarks or "").strip() or None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()

    create_audit_log(
        db,
        module_name="Location Operation Availability",
        action="Create Location Operation Availability",
        category="Data Change",
        current_user=actor,
        entity_type="LocationOperationAvailability",
        entity_id=row.id,
        entity_label=f"{loc.location_code} - {op_type['code']}",
        new_status=row.status,
        request=request,
        remarks="Location operation availability created",
        details_summary=f"location={loc.location_code}; operation_type={op_type['code']}; status={row.status}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_availability(row, loc)


@router.put("/location-operation-availability/{availability_id}")
def update_location_operation_availability(
    availability_id: int,
    payload: LocationOperationAvailabilityPayload,
    request: Request,
    actor: User = Depends(require_permission("location_operation_availability:update")),
    db: Session = Depends(get_db),
):
    row = db.get(LocationOperationAvailability, availability_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Location operation availability not found")
    loc = (
        db.get(Location, payload.location_id)
        if payload.location_id
        else db.query(Location).filter(func.upper(Location.location_code) == payload.location_code.upper()).first()
    )
    if loc is None or loc.status != "Active":
        raise HTTPException(status_code=400, detail="Select an Active location")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and (row.location_id not in allowed or loc.id not in allowed):
        raise HTTPException(status_code=403, detail="Location is outside your assigned scope")

    op_type = get_operation_type(payload.operation_type_code)
    if op_type is None:
        raise HTTPException(status_code=400, detail="Unknown operation type code")

    dup = (
        db.query(LocationOperationAvailability)
        .filter(
            LocationOperationAvailability.location_id == loc.id,
            LocationOperationAvailability.operation_type_code == op_type["code"],
            LocationOperationAvailability.id != availability_id,
        )
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="This operation type is already configured for this location")

    old_status = row.status
    row.location_id = loc.id
    row.location_code = loc.location_code
    row.operation_type_code = op_type["code"]
    row.status = payload.status
    row.remarks = (payload.remarks or "").strip() or None
    row.updated_at = utcnow()

    create_audit_log(
        db,
        module_name="Location Operation Availability",
        action="Update Location Operation Availability",
        category="Data Change",
        current_user=actor,
        entity_type="LocationOperationAvailability",
        entity_id=row.id,
        entity_label=f"{loc.location_code} - {op_type['code']}",
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Location operation availability updated",
        details_summary=f"location={loc.location_code}; operation_type={op_type['code']}; status={row.status}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_availability(row, loc)


@router.delete("/location-operation-availability/{availability_id}")
def delete_location_operation_availability(
    availability_id: int,
    request: Request,
    actor: User = Depends(require_permission("location_operation_availability:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(LocationOperationAvailability, availability_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Location operation availability not found")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and row.location_id not in allowed:
        raise HTTPException(status_code=403, detail="Location is outside your assigned scope")

    label = f"{row.location_code} - {row.operation_type_code}"
    create_audit_log(
        db,
        module_name="Location Operation Availability",
        action="Delete Location Operation Availability",
        category="Data Change",
        current_user=actor,
        entity_type="LocationOperationAvailability",
        entity_id=row.id,
        entity_label=label,
        old_status=row.status,
        request=request,
        remarks="Location operation availability deleted",
        details_summary=f"location={row.location_code}; operation_type={row.operation_type_code}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Location operation availability deleted successfully"}


# ===========================================================================
# 2. Location Accounting Day Setting
# ===========================================================================
class LocationAccountingDayPayload(StrictModel):
    location_id: int | None = None
    location_code: str = Field(min_length=1, max_length=50)
    day_start_time: time
    day_end_time: time
    effective_from: date
    effective_to: date | None = None
    timezone_name: str = Field(default="Africa/Lagos", min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    status: Literal["Active", "Inactive"] = "Active"


def _serialize_accounting_day(row: LocationAccountingDaySetting, loc: Location | None) -> dict:
    return {
        "id": row.id,
        "location_id": row.location_id,
        "location_code": row.location_code,
        "location_name": loc.location_name if loc else "",
        "day_start_time": row.day_start_time.strftime("%H:%M") if row.day_start_time else "06:00",
        "day_end_time": row.day_end_time.strftime("%H:%M") if row.day_end_time else "05:59",
        "effective_from": row.effective_from,
        "effective_to": row.effective_to,
        "timezone_name": row.timezone_name,
        "description": row.description or "",
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _validate_accounting_day(
    db: Session,
    actor: User,
    payload: LocationAccountingDayPayload,
    *,
    setting_id: int | None = None,
) -> Location:
    loc = (
        db.get(Location, payload.location_id)
        if payload.location_id
        else db.query(Location).filter(func.upper(Location.location_code) == payload.location_code.upper()).first()
    )
    if loc is None:
        raise HTTPException(status_code=400, detail="Location not found")
    if loc.status != "Active":
        raise HTTPException(status_code=400, detail="Only Active locations can be configured")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and loc.id not in allowed:
        raise HTTPException(status_code=403, detail="Location is outside your assigned scope")
    if payload.effective_to and payload.effective_to < payload.effective_from:
        raise HTTPException(status_code=400, detail="Effective To cannot be earlier than Effective From")
    if payload.day_start_time == payload.day_end_time:
        raise HTTPException(status_code=400, detail="Day Start Time and Day End Time cannot be the same")

    if payload.status == "Active":
        new_from = payload.effective_from
        new_to = payload.effective_to or date(9999, 12, 31)
        q = db.query(LocationAccountingDaySetting).filter(
            LocationAccountingDaySetting.location_id == loc.id,
            LocationAccountingDaySetting.status == "Active",
        )
        if setting_id is not None:
            q = q.filter(LocationAccountingDaySetting.id != setting_id)
        for existing in q.all():
            ex_from = existing.effective_from
            ex_to = existing.effective_to or date(9999, 12, 31)
            if new_from <= ex_to and new_to >= ex_from:
                raise HTTPException(
                    status_code=400,
                    detail="Another Active accounting day setting already exists for this location within the selected effective period",
                )
    return loc


@router.get("/location-accounting-day-settings")
def list_location_accounting_day_settings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("location_accounting_day_settings:read")),
    db: Session = Depends(get_db),
):
    query = db.query(LocationAccountingDaySetting)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        query = query.filter(LocationAccountingDaySetting.location_id.in_(allowed))
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                LocationAccountingDaySetting.location_code.ilike(term),
                LocationAccountingDaySetting.timezone_name.ilike(term),
                LocationAccountingDaySetting.description.ilike(term),
            )
        )
    if status:
        query = query.filter(LocationAccountingDaySetting.status == status)
    if location_code:
        query = query.filter(
            func.upper(LocationAccountingDaySetting.location_code) == location_code.strip().upper()
        )
    if date_from:
        query = query.filter(LocationAccountingDaySetting.effective_from >= date_from)
    if date_to:
        query = query.filter(LocationAccountingDaySetting.effective_from <= date_to)

    result = paginate_query(
        query.order_by(
            LocationAccountingDaySetting.location_code.asc(),
            LocationAccountingDaySetting.effective_from.desc(),
        ),
        page=page,
        page_size=page_size,
    )
    locs = {l.id: l for l in db.query(Location).all()}
    result["items"] = [_serialize_accounting_day(r, locs.get(r.location_id)) for r in result["items"]]
    return result


@router.get("/location-accounting-day-settings/export")
def export_location_accounting_day_settings(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    actor: User = Depends(require_permission("location_accounting_day_settings:read")),
    db: Session = Depends(get_db),
):
    query = db.query(LocationAccountingDaySetting)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        query = query.filter(LocationAccountingDaySetting.location_id.in_(allowed))
    if status:
        query = query.filter(LocationAccountingDaySetting.status == status)
    if location_code:
        query = query.filter(
            func.upper(LocationAccountingDaySetting.location_code) == location_code.strip().upper()
        )
    records = query.order_by(LocationAccountingDaySetting.location_code.asc()).limit(MAX_EXPORT_ROWS).all()
    locs = {l.id: l for l in db.query(Location).all()}
    headers = [
        "Location Code",
        "Location Name",
        "Day Start",
        "Day End",
        "Timezone",
        "Effective From",
        "Effective To",
        "Status",
        "Description",
    ]
    rows = []
    for r in records:
        s = _serialize_accounting_day(r, locs.get(r.location_id))
        rows.append(
            [
                s["location_code"],
                s["location_name"],
                s["day_start_time"],
                s["day_end_time"],
                s["timezone_name"],
                s["effective_from"],
                s["effective_to"] or "Open-ended",
                s["status"],
                s["description"],
            ]
        )
    create_audit_log(
        db,
        module_name="Location Accounting Day Setting",
        action="Export Location Accounting Day Settings",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} accounting day settings as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("location-accounting-day-settings", headers, rows)
    if format == "xlsx":
        return xlsx_response("location-accounting-day-settings", "Accounting Day Settings", headers, rows)
    return pdf_response("location-accounting-day-settings", "Location Accounting Day Settings", headers, rows)


@router.post("/location-accounting-day-settings", status_code=201)
def create_location_accounting_day_setting(
    payload: LocationAccountingDayPayload,
    request: Request,
    actor: User = Depends(require_permission("location_accounting_day_settings:create")),
    db: Session = Depends(get_db),
):
    loc = _validate_accounting_day(db, actor, payload)
    row = LocationAccountingDaySetting(
        location_id=loc.id,
        location_code=loc.location_code,
        day_start_time=payload.day_start_time,
        day_end_time=payload.day_end_time,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        timezone_name=payload.timezone_name.strip(),
        description=(payload.description or "").strip() or None,
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    create_audit_log(
        db,
        module_name="Location Accounting Day Setting",
        action="Create Location Accounting Day Setting",
        category="Data Change",
        current_user=actor,
        entity_type="LocationAccountingDaySetting",
        entity_id=row.id,
        entity_label=f"{loc.location_code} ({row.day_start_time}-{row.day_end_time})",
        new_status=row.status,
        request=request,
        remarks="Location accounting day setting created",
        details_summary=f"location={loc.location_code}; start={row.day_start_time}; end={row.day_end_time}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_accounting_day(row, loc)


@router.put("/location-accounting-day-settings/{setting_id}")
def update_location_accounting_day_setting(
    setting_id: int,
    payload: LocationAccountingDayPayload,
    request: Request,
    actor: User = Depends(require_permission("location_accounting_day_settings:update")),
    db: Session = Depends(get_db),
):
    row = db.get(LocationAccountingDaySetting, setting_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Accounting day setting not found")
    loc = _validate_accounting_day(db, actor, payload, setting_id=setting_id)
    old_status = row.status
    row.location_id = loc.id
    row.location_code = loc.location_code
    row.day_start_time = payload.day_start_time
    row.day_end_time = payload.day_end_time
    row.effective_from = payload.effective_from
    row.effective_to = payload.effective_to
    row.timezone_name = payload.timezone_name.strip()
    row.description = (payload.description or "").strip() or None
    row.status = payload.status
    row.updated_at = utcnow()

    create_audit_log(
        db,
        module_name="Location Accounting Day Setting",
        action="Update Location Accounting Day Setting",
        category="Data Change",
        current_user=actor,
        entity_type="LocationAccountingDaySetting",
        entity_id=row.id,
        entity_label=f"{loc.location_code} ({row.day_start_time}-{row.day_end_time})",
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Location accounting day setting updated",
        details_summary=f"location={loc.location_code}; start={row.day_start_time}; end={row.day_end_time}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_accounting_day(row, loc)


@router.delete("/location-accounting-day-settings/{setting_id}")
def delete_location_accounting_day_setting(
    setting_id: int,
    request: Request,
    actor: User = Depends(require_permission("location_accounting_day_settings:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(LocationAccountingDaySetting, setting_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Accounting day setting not found")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and row.location_id not in allowed:
        raise HTTPException(status_code=403, detail="Location is outside your assigned scope")
    label = f"{row.location_code} ({row.day_start_time}-{row.day_end_time})"
    create_audit_log(
        db,
        module_name="Location Accounting Day Setting",
        action="Delete Location Accounting Day Setting",
        category="Data Change",
        current_user=actor,
        entity_type="LocationAccountingDaySetting",
        entity_id=row.id,
        entity_label=label,
        old_status=row.status,
        request=request,
        remarks="Location accounting day setting deleted",
        details_summary=f"location={row.location_code}; effective_from={row.effective_from}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Accounting day setting deleted successfully"}


# ===========================================================================
# 3. Company Report Profile Master
# ===========================================================================
class CompanyReportProfilePayload(StrictModel):
    profile_code: str = Field(min_length=1, max_length=50)
    company_name: str = Field(min_length=1, max_length=200)
    company_short_name: str | None = Field(default=None, max_length=100)
    report_header_line_1: str | None = Field(default=None, max_length=250)
    report_header_line_2: str | None = Field(default=None, max_length=250)
    address_line: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=200)
    tax_registration_number: str | None = Field(default=None, max_length=100)
    logo_url: str | None = None
    primary_color: str = Field(default="#0B3B66", max_length=30)
    accent_color: str = Field(default="#1F5F99", max_length=30)
    footer_text: str | None = Field(default=None, max_length=300)
    prepared_by_label: str = Field(default="Prepared By", max_length=100)
    checked_by_label: str = Field(default="Checked By", max_length=100)
    approved_by_label: str = Field(default="Approved By", max_length=100)
    show_signature_block: bool = True
    show_generated_timestamp: bool = True
    show_page_number: bool = True
    is_default: bool = False
    status: Literal["Active", "Inactive"] = "Active"


def _serialize_report_profile(row: CompanyReportProfile) -> dict:
    return {
        "id": row.id,
        "profile_code": row.profile_code,
        "company_name": row.company_name,
        "company_short_name": row.company_short_name or "",
        "report_header_line_1": row.report_header_line_1 or "",
        "report_header_line_2": row.report_header_line_2 or "",
        "address_line": row.address_line or "",
        "email": row.email or "",
        "phone": row.phone or "",
        "website": row.website or "",
        "tax_registration_number": row.tax_registration_number or "",
        "logo_url": row.logo_url or "",
        "primary_color": row.primary_color,
        "accent_color": row.accent_color,
        "footer_text": row.footer_text or "",
        "prepared_by_label": row.prepared_by_label,
        "checked_by_label": row.checked_by_label,
        "approved_by_label": row.approved_by_label,
        "show_signature_block": bool(row.show_signature_block),
        "show_generated_timestamp": bool(row.show_generated_timestamp),
        "show_page_number": bool(row.show_page_number),
        "is_default": bool(row.is_default),
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _ensure_default_report_profile(db: Session) -> CompanyReportProfile:
    active = (
        db.query(CompanyReportProfile)
        .filter(CompanyReportProfile.status == "Active")
        .order_by(CompanyReportProfile.is_default.desc(), CompanyReportProfile.id.asc())
        .first()
    )
    if active:
        return active
    any_row = db.query(CompanyReportProfile).order_by(CompanyReportProfile.id.asc()).first()
    if any_row:
        return any_row
    seeded = CompanyReportProfile(
        profile_code="DEFAULT",
        company_name="Hydrocarbon Accounting Enterprise",
        company_short_name="HCA Enterprise",
        report_header_line_1="Hydrocarbon Accounting & Operations Management System",
        report_header_line_2="Terminal & Marine Custody Transfer Reporting",
        primary_color="#0B3B66",
        accent_color="#1F5F99",
        footer_text="Confidential — Hydrocarbon Accounting Official Report",
        is_default=True,
        status="Active",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(seeded)
    db.commit()
    db.refresh(seeded)
    return seeded


@router.get("/company-report-profiles")
def list_company_report_profiles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(
        require_any_permission(
            "company_report_profiles:read",
            "reports:read",
            "operation_entries:read",
        )
    ),
    db: Session = Depends(get_db),
):
    _ensure_default_report_profile(db)
    query = db.query(CompanyReportProfile)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                CompanyReportProfile.profile_code.ilike(term),
                CompanyReportProfile.company_name.ilike(term),
                CompanyReportProfile.company_short_name.ilike(term),
            )
        )
    if status:
        query = query.filter(CompanyReportProfile.status == status)
    if date_from:
        query = query.filter(CompanyReportProfile.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(CompanyReportProfile.created_at <= datetime.combine(date_to, time.max))

    result = paginate_query(
        query.order_by(CompanyReportProfile.is_default.desc(), CompanyReportProfile.id.asc()),
        page=page,
        page_size=page_size,
    )
    result["items"] = [_serialize_report_profile(r) for r in result["items"]]
    return result


@router.get("/company-report-profiles/active")
def get_active_company_report_profile(
    actor: User = Depends(
        require_any_permission(
            "company_report_profiles:read",
            "reports:read",
            "operation_entries:read",
            "dashboard:read",
        )
    ),
    db: Session = Depends(get_db),
):
    return _serialize_report_profile(_ensure_default_report_profile(db))


@router.get("/company-report-profiles/export")
def export_company_report_profiles(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    actor: User = Depends(require_permission("company_report_profiles:read")),
    db: Session = Depends(get_db),
):
    query = db.query(CompanyReportProfile)
    if status:
        query = query.filter(CompanyReportProfile.status == status)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                CompanyReportProfile.profile_code.ilike(term),
                CompanyReportProfile.company_name.ilike(term),
            )
        )
    records = query.order_by(CompanyReportProfile.id.asc()).limit(MAX_EXPORT_ROWS).all()
    headers = ["Code", "Company Name", "Short Name", "Header Line 1", "Email", "Phone", "Default", "Status"]
    rows = [
        [
            r.profile_code,
            r.company_name,
            r.company_short_name or "",
            r.report_header_line_1 or "",
            r.email or "",
            r.phone or "",
            "Yes" if r.is_default else "No",
            r.status,
        ]
        for r in records
    ]
    create_audit_log(
        db,
        module_name="Company Report Profiles",
        action="Export Company Report Profiles",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} report profiles as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("company-report-profiles", headers, rows)
    if format == "xlsx":
        return xlsx_response("company-report-profiles", "Report Profiles", headers, rows)
    return pdf_response("company-report-profiles", "Company Report Profiles", headers, rows)


@router.post("/company-report-profiles", status_code=201)
def create_company_report_profile(
    payload: CompanyReportProfilePayload,
    request: Request,
    actor: User = Depends(require_permission("company_report_profiles:create")),
    db: Session = Depends(get_db),
):
    code = payload.profile_code.strip().upper()
    if db.query(CompanyReportProfile).filter(func.upper(CompanyReportProfile.profile_code) == code).first():
        raise HTTPException(status_code=400, detail="Profile code already exists")

    if payload.is_default:
        db.query(CompanyReportProfile).update({CompanyReportProfile.is_default: False})

    row = CompanyReportProfile(
        profile_code=code,
        company_name=payload.company_name.strip(),
        company_short_name=(payload.company_short_name or "").strip() or None,
        report_header_line_1=(payload.report_header_line_1 or "").strip() or None,
        report_header_line_2=(payload.report_header_line_2 or "").strip() or None,
        address_line=(payload.address_line or "").strip() or None,
        email=(payload.email or "").strip() or None,
        phone=(payload.phone or "").strip() or None,
        website=(payload.website or "").strip() or None,
        tax_registration_number=(payload.tax_registration_number or "").strip() or None,
        logo_url=(payload.logo_url or "").strip() or None,
        primary_color=payload.primary_color,
        accent_color=payload.accent_color,
        footer_text=(payload.footer_text or "").strip() or None,
        prepared_by_label=payload.prepared_by_label,
        checked_by_label=payload.checked_by_label,
        approved_by_label=payload.approved_by_label,
        show_signature_block=payload.show_signature_block,
        show_generated_timestamp=payload.show_generated_timestamp,
        show_page_number=payload.show_page_number,
        is_default=payload.is_default,
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    create_audit_log(
        db,
        module_name="Company Report Profiles",
        action="Create Company Report Profile",
        category="Data Change",
        current_user=actor,
        entity_type="CompanyReportProfile",
        entity_id=row.id,
        entity_label=f"{row.company_name} ({row.profile_code})",
        new_status=row.status,
        request=request,
        remarks="Company report profile created",
        details_summary=f"profile_code={row.profile_code}; company_name={row.company_name}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_report_profile(row)


@router.put("/company-report-profiles/{profile_id}")
def update_company_report_profile(
    profile_id: int,
    payload: CompanyReportProfilePayload,
    request: Request,
    actor: User = Depends(require_permission("company_report_profiles:update")),
    db: Session = Depends(get_db),
):
    row = db.get(CompanyReportProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Company report profile not found")
    code = payload.profile_code.strip().upper()
    dup = (
        db.query(CompanyReportProfile)
        .filter(func.upper(CompanyReportProfile.profile_code) == code, CompanyReportProfile.id != profile_id)
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="Profile code already exists")

    if payload.is_default:
        db.query(CompanyReportProfile).filter(CompanyReportProfile.id != profile_id).update(
            {CompanyReportProfile.is_default: False}
        )

    old_status = row.status
    row.profile_code = code
    row.company_name = payload.company_name.strip()
    row.company_short_name = (payload.company_short_name or "").strip() or None
    row.report_header_line_1 = (payload.report_header_line_1 or "").strip() or None
    row.report_header_line_2 = (payload.report_header_line_2 or "").strip() or None
    row.address_line = (payload.address_line or "").strip() or None
    row.email = (payload.email or "").strip() or None
    row.phone = (payload.phone or "").strip() or None
    row.website = (payload.website or "").strip() or None
    row.tax_registration_number = (payload.tax_registration_number or "").strip() or None
    row.logo_url = (payload.logo_url or "").strip() or None
    row.primary_color = payload.primary_color
    row.accent_color = payload.accent_color
    row.footer_text = (payload.footer_text or "").strip() or None
    row.prepared_by_label = payload.prepared_by_label
    row.checked_by_label = payload.checked_by_label
    row.approved_by_label = payload.approved_by_label
    row.show_signature_block = payload.show_signature_block
    row.show_generated_timestamp = payload.show_generated_timestamp
    row.show_page_number = payload.show_page_number
    row.is_default = payload.is_default
    row.status = payload.status
    row.updated_at = utcnow()

    create_audit_log(
        db,
        module_name="Company Report Profiles",
        action="Update Company Report Profile",
        category="Data Change",
        current_user=actor,
        entity_type="CompanyReportProfile",
        entity_id=row.id,
        entity_label=f"{row.company_name} ({row.profile_code})",
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Company report profile updated",
        details_summary=f"profile_code={row.profile_code}; is_default={row.is_default}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_report_profile(row)


@router.delete("/company-report-profiles/{profile_id}")
def delete_company_report_profile(
    profile_id: int,
    request: Request,
    actor: User = Depends(require_permission("company_report_profiles:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(CompanyReportProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Company report profile not found")
    if row.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete the default company report profile")
    label = f"{row.company_name} ({row.profile_code})"
    create_audit_log(
        db,
        module_name="Company Report Profiles",
        action="Delete Company Report Profile",
        category="Data Change",
        current_user=actor,
        entity_type="CompanyReportProfile",
        entity_id=row.id,
        entity_label=label,
        old_status=row.status,
        request=request,
        remarks="Company report profile deleted",
        details_summary=f"profile_code={row.profile_code}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Company report profile deleted successfully"}


# ===========================================================================
# 4. Material Balance Template Master (Typed columns & operation mappings)
# ===========================================================================
DEFAULT_MB_COLUMNS = [
    {
        "column_code": "ACCOUNTING_DATE",
        "column_label": "Date",
        "column_group": "DATE",
        "column_type": "DATE",
        "unit": None,
        "display_order": 1,
        "source_metric": "NSV",
        "sign_multiplier": 1,
        "visible": True,
        "is_system_column": True,
        "mapped_operation_codes": [],
        "excluded_operation_codes": [],
        "formula_expression": None,
    },
    {
        "column_code": "OPENING_STOCK",
        "column_label": "Opening Stock",
        "column_group": "STOCK",
        "column_type": "OPENING_STOCK",
        "unit": "BBL",
        "display_order": 2,
        "source_metric": "NSV",
        "sign_multiplier": 1,
        "visible": True,
        "is_system_column": True,
        "mapped_operation_codes": ["OPENING_STOCK"],
        "excluded_operation_codes": [],
        "formula_expression": None,
    },
    {
        "column_code": "RECEIPTS",
        "column_label": "Total Receipts",
        "column_group": "RECEIPTS",
        "column_type": "OPERATION_SUM",
        "unit": "BBL",
        "display_order": 3,
        "source_metric": "NSV",
        "direction_filter": "IN",
        "category_filter": "RECEIPT",
        "sign_multiplier": 1,
        "visible": True,
        "is_system_column": False,
        "mapped_operation_codes": [],
        "excluded_operation_codes": [],
        "formula_expression": None,
    },
    {
        "column_code": "DISPATCHES",
        "column_label": "Total Dispatches",
        "column_group": "DISPATCHES",
        "column_type": "OPERATION_SUM",
        "unit": "BBL",
        "display_order": 4,
        "source_metric": "NSV",
        "direction_filter": "OUT",
        "category_filter": "DISPATCH",
        "sign_multiplier": 1,
        "visible": True,
        "is_system_column": False,
        "mapped_operation_codes": [],
        "excluded_operation_codes": [],
        "formula_expression": None,
    },
    {
        "column_code": "BOOK_CLOSING_STOCK",
        "column_label": "Book Closing Stock",
        "column_group": "BOOK",
        "column_type": "BOOK_CLOSING",
        "unit": "BBL",
        "display_order": 5,
        "source_metric": "NSV",
        "sign_multiplier": 1,
        "visible": True,
        "is_system_column": True,
        "mapped_operation_codes": [],
        "excluded_operation_codes": [],
        "formula_expression": "+OPENING_STOCK,+RECEIPTS,-DISPATCHES",
    },
    {
        "column_code": "PHYSICAL_CLOSING_STOCK",
        "column_label": "Physical Closing Stock",
        "column_group": "CLOSING",
        "column_type": "PHYSICAL_CLOSING",
        "unit": "BBL",
        "display_order": 6,
        "source_metric": "NSV",
        "sign_multiplier": 1,
        "visible": True,
        "is_system_column": True,
        "mapped_operation_codes": ["CLOSING_STOCK"],
        "excluded_operation_codes": [],
        "formula_expression": None,
    },
    {
        "column_code": "LOSS_GAIN",
        "column_label": "Loss / Gain",
        "column_group": "VARIANCE",
        "column_type": "LOSS_GAIN",
        "unit": "BBL",
        "display_order": 7,
        "source_metric": "NSV",
        "sign_multiplier": 1,
        "visible": True,
        "is_system_column": True,
        "mapped_operation_codes": [],
        "excluded_operation_codes": [],
        "formula_expression": "+PHYSICAL_CLOSING_STOCK,-BOOK_CLOSING_STOCK",
    },
    {
        "column_code": "LOSS_GAIN_PCT",
        "column_label": "Loss / Gain (%)",
        "column_group": "VARIANCE",
        "column_type": "LOSS_GAIN_PCT",
        "unit": "%",
        "display_order": 8,
        "source_metric": "NSV",
        "sign_multiplier": 1,
        "visible": True,
        "is_system_column": True,
        "mapped_operation_codes": [],
        "excluded_operation_codes": [],
        "formula_expression": None,
    },
]


class MaterialBalanceColumnInput(StrictModel):
    column_code: str = Field(min_length=1, max_length=80)
    column_label: str = Field(min_length=1, max_length=150)
    column_group: str = Field(default="MOVEMENTS", max_length=80)
    column_type: str = Field(min_length=1, max_length=40)
    unit: str | None = Field(default="BBL", max_length=30)
    display_order: int = Field(default=1, ge=1)
    source_metric: str = Field(default="NSV", max_length=30)
    direction_filter: str | None = Field(default=None, max_length=20)
    category_filter: str | None = Field(default=None, max_length=40)
    sign_multiplier: int = 1
    mapped_operation_codes: list[str] = Field(default_factory=list)
    excluded_operation_codes: list[str] = Field(default_factory=list)
    formula_expression: str | None = Field(default=None, max_length=500)
    visible: bool = True
    is_system_column: bool = False
    status: Literal["Active", "Inactive"] = "Active"


class MaterialBalanceTemplatePayload(StrictModel):
    template_name: str = Field(min_length=2, max_length=150)
    template_code: str = Field(min_length=2, max_length=80)
    location_id: int | None = None
    location_code: str = Field(min_length=1, max_length=50)
    basis: Literal["GOV", "GSV", "NSV"] = "NSV"
    reporting_unit: str = Field(default="BBL", max_length=20)
    auto_carry_opening_stock: bool = True
    opening_operation_code: str = Field(default="OPENING_STOCK", max_length=80)
    closing_operation_code: str = Field(default="CLOSING_STOCK", max_length=80)
    is_default: bool = False
    status: Literal["Active", "Inactive"] = "Active"
    description: str | None = Field(default=None, max_length=2000)
    columns: list[MaterialBalanceColumnInput] = Field(default_factory=list)


def serialize_mb_template(row: MaterialBalanceTemplate, loc: Location | None = None) -> dict:
    cols = []
    for c in sorted(row.columns, key=lambda x: (x.display_order, x.id or 0)):
        inc = [m.operation_code for m in c.operation_mappings if m.mapping_mode == "INCLUDE"]
        exc = [m.operation_code for m in c.operation_mappings if m.mapping_mode == "EXCLUDE"]
        cols.append(
            {
                "id": c.id,
                "template_id": c.template_id,
                "column_code": c.column_code,
                "column_label": c.column_label,
                "column_group": c.column_group,
                "column_type": c.column_type,
                "unit": c.unit or "",
                "display_order": c.display_order,
                "source_metric": c.source_metric,
                "direction_filter": c.direction_filter or "",
                "category_filter": c.category_filter or "",
                "sign_multiplier": c.sign_multiplier,
                "mapped_operation_codes": inc,
                "excluded_operation_codes": exc,
                "formula_expression": c.formula_expression or "",
                "visible": bool(c.visible),
                "is_system_column": bool(c.is_system_column),
                "status": c.status,
            }
        )
    location_obj = loc or row.location
    return {
        "id": row.id,
        "template_name": row.template_name,
        "template_code": row.template_code,
        "location_id": row.location_id,
        "location_code": row.location_code,
        "location_name": location_obj.location_name if location_obj else "",
        "basis": row.basis,
        "reporting_unit": row.reporting_unit,
        "auto_carry_opening_stock": bool(row.auto_carry_opening_stock),
        "opening_operation_code": row.opening_operation_code,
        "closing_operation_code": row.closing_operation_code,
        "is_default": bool(row.is_default),
        "status": row.status,
        "description": row.description or "",
        "column_count": len(cols),
        "columns": cols,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _save_mb_columns(db: Session, template: MaterialBalanceTemplate, col_inputs: list[MaterialBalanceColumnInput]):
    template.columns.clear()
    db.flush()
    effective_cols = col_inputs if col_inputs else [MaterialBalanceColumnInput(**c) for c in DEFAULT_MB_COLUMNS]
    for idx, col in enumerate(effective_cols, start=1):
        col_row = MaterialBalanceTemplateColumn(
            template_id=template.id,
            column_code=col.column_code.strip().upper(),
            column_label=col.column_label.strip(),
            column_group=col.column_group.strip().upper() or "MOVEMENTS",
            column_type=col.column_type.strip().upper(),
            unit=(col.unit or "").strip() or None,
            display_order=col.display_order or idx,
            source_metric=col.source_metric.strip().upper() or template.basis,
            direction_filter=(col.direction_filter or "").strip().upper() or None,
            category_filter=(col.category_filter or "").strip().upper() or None,
            sign_multiplier=col.sign_multiplier,
            formula_expression=(col.formula_expression or "").strip() or None,
            visible=col.visible,
            is_system_column=col.is_system_column,
            status=col.status,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(col_row)
        db.flush()
        for op_code in sorted({c.strip().upper() for c in col.mapped_operation_codes if c.strip()}):
            db.add(
                MaterialBalanceTemplateColumnOperation(
                    column_id=col_row.id,
                    operation_code=op_code,
                    mapping_mode="INCLUDE",
                )
            )
        for op_code in sorted({c.strip().upper() for c in col.excluded_operation_codes if c.strip()}):
            db.add(
                MaterialBalanceTemplateColumnOperation(
                    column_id=col_row.id,
                    operation_code=op_code,
                    mapping_mode="EXCLUDE",
                )
            )


@router.get("/material-balance-templates")
def list_material_balance_templates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    basis: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(
        require_any_permission("material_balance_templates:read", "reports:read")
    ),
    db: Session = Depends(get_db),
):
    query = db.query(MaterialBalanceTemplate)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        query = query.filter(
            or_(
                MaterialBalanceTemplate.location_id.in_(allowed),
                MaterialBalanceTemplate.location_id.is_(None),
            )
        )
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                MaterialBalanceTemplate.template_name.ilike(term),
                MaterialBalanceTemplate.template_code.ilike(term),
                MaterialBalanceTemplate.location_code.ilike(term),
            )
        )
    if status:
        query = query.filter(MaterialBalanceTemplate.status == status)
    if location_code:
        query = query.filter(
            func.upper(MaterialBalanceTemplate.location_code) == location_code.strip().upper()
        )
    if basis:
        query = query.filter(MaterialBalanceTemplate.basis == basis.upper())
    if date_from:
        query = query.filter(MaterialBalanceTemplate.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(MaterialBalanceTemplate.created_at <= datetime.combine(date_to, time.max))

    result = paginate_query(
        query.order_by(MaterialBalanceTemplate.is_default.desc(), MaterialBalanceTemplate.id.asc()),
        page=page,
        page_size=page_size,
    )
    locs = {l.id: l for l in db.query(Location).all()}
    result["items"] = [serialize_mb_template(r, locs.get(r.location_id)) for r in result["items"]]
    result["default_columns"] = DEFAULT_MB_COLUMNS
    return result


@router.get("/material-balance-templates/export")
def export_material_balance_templates(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    actor: User = Depends(require_permission("material_balance_templates:read")),
    db: Session = Depends(get_db),
):
    query = db.query(MaterialBalanceTemplate)
    if status:
        query = query.filter(MaterialBalanceTemplate.status == status)
    if location_code:
        query = query.filter(
            func.upper(MaterialBalanceTemplate.location_code) == location_code.strip().upper()
        )
    records = query.order_by(MaterialBalanceTemplate.id.asc()).limit(MAX_EXPORT_ROWS).all()
    headers = ["Code", "Template Name", "Location", "Basis", "Unit", "Default", "Columns", "Status"]
    rows = [
        [
            r.template_code,
            r.template_name,
            r.location_code,
            r.basis,
            r.reporting_unit,
            "Yes" if r.is_default else "No",
            len(r.columns),
            r.status,
        ]
        for r in records
    ]
    create_audit_log(
        db,
        module_name="Material Balance Template Master",
        action="Export Material Balance Templates",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} material balance templates as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("material-balance-templates", headers, rows)
    if format == "xlsx":
        return xlsx_response("material-balance-templates", "Material Balance Templates", headers, rows)
    return pdf_response("material-balance-templates", "Material Balance Templates", headers, rows)


@router.get("/material-balance-templates/{template_id}")
def get_material_balance_template(
    template_id: int,
    actor: User = Depends(
        require_any_permission("material_balance_templates:read", "reports:read")
    ),
    db: Session = Depends(get_db),
):
    row = db.get(MaterialBalanceTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Material balance template not found")
    return serialize_mb_template(row)


@router.post("/material-balance-templates", status_code=201)
def create_material_balance_template(
    payload: MaterialBalanceTemplatePayload,
    request: Request,
    actor: User = Depends(require_permission("material_balance_templates:create")),
    db: Session = Depends(get_db),
):
    code = payload.template_code.strip().upper()
    if db.query(MaterialBalanceTemplate).filter(func.upper(MaterialBalanceTemplate.template_code) == code).first():
        raise HTTPException(status_code=400, detail="Template code already exists")

    loc = (
        db.get(Location, payload.location_id)
        if payload.location_id
        else db.query(Location).filter(func.upper(Location.location_code) == payload.location_code.upper()).first()
    )
    if loc is None:
        raise HTTPException(status_code=400, detail="Location not found")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and loc.id not in allowed:
        raise HTTPException(status_code=403, detail="Location is outside your assigned scope")

    if payload.is_default:
        db.query(MaterialBalanceTemplate).filter(MaterialBalanceTemplate.location_id == loc.id).update(
            {MaterialBalanceTemplate.is_default: False}
        )

    row = MaterialBalanceTemplate(
        template_name=payload.template_name.strip(),
        template_code=code,
        location_id=loc.id,
        location_code=loc.location_code,
        basis=payload.basis,
        reporting_unit=payload.reporting_unit.strip().upper(),
        auto_carry_opening_stock=payload.auto_carry_opening_stock,
        opening_operation_code=payload.opening_operation_code.strip().upper(),
        closing_operation_code=payload.closing_operation_code.strip().upper(),
        is_default=payload.is_default,
        status=payload.status,
        description=(payload.description or "").strip() or None,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    _save_mb_columns(db, row, payload.columns)

    create_audit_log(
        db,
        module_name="Material Balance Template Master",
        action="Create Material Balance Template",
        category="Data Change",
        current_user=actor,
        entity_type="MaterialBalanceTemplate",
        entity_id=row.id,
        entity_label=f"{row.template_name} ({row.template_code})",
        new_status=row.status,
        request=request,
        remarks="Material balance template created",
        details_summary=f"code={row.template_code}; location={row.location_code}; basis={row.basis}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return serialize_mb_template(row, loc)


@router.put("/material-balance-templates/{template_id}")
def update_material_balance_template(
    template_id: int,
    payload: MaterialBalanceTemplatePayload,
    request: Request,
    actor: User = Depends(require_permission("material_balance_templates:update")),
    db: Session = Depends(get_db),
):
    row = db.get(MaterialBalanceTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Material balance template not found")
    code = payload.template_code.strip().upper()
    dup = (
        db.query(MaterialBalanceTemplate)
        .filter(func.upper(MaterialBalanceTemplate.template_code) == code, MaterialBalanceTemplate.id != template_id)
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="Template code already exists")

    loc = (
        db.get(Location, payload.location_id)
        if payload.location_id
        else db.query(Location).filter(func.upper(Location.location_code) == payload.location_code.upper()).first()
    )
    if loc is None:
        raise HTTPException(status_code=400, detail="Location not found")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and loc.id not in allowed:
        raise HTTPException(status_code=403, detail="Location is outside your assigned scope")

    if payload.is_default:
        db.query(MaterialBalanceTemplate).filter(
            MaterialBalanceTemplate.location_id == loc.id,
            MaterialBalanceTemplate.id != template_id,
        ).update({MaterialBalanceTemplate.is_default: False})

    old_status = row.status
    row.template_name = payload.template_name.strip()
    row.template_code = code
    row.location_id = loc.id
    row.location_code = loc.location_code
    row.basis = payload.basis
    row.reporting_unit = payload.reporting_unit.strip().upper()
    row.auto_carry_opening_stock = payload.auto_carry_opening_stock
    row.opening_operation_code = payload.opening_operation_code.strip().upper()
    row.closing_operation_code = payload.closing_operation_code.strip().upper()
    row.is_default = payload.is_default
    row.status = payload.status
    row.description = (payload.description or "").strip() or None
    row.updated_at = utcnow()

    _save_mb_columns(db, row, payload.columns)

    create_audit_log(
        db,
        module_name="Material Balance Template Master",
        action="Update Material Balance Template",
        category="Data Change",
        current_user=actor,
        entity_type="MaterialBalanceTemplate",
        entity_id=row.id,
        entity_label=f"{row.template_name} ({row.template_code})",
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Material balance template updated",
        details_summary=f"code={row.template_code}; location={row.location_code}; basis={row.basis}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return serialize_mb_template(row, loc)


@router.post("/material-balance-templates/{template_id}/set-default")
def set_default_material_balance_template(
    template_id: int,
    request: Request,
    actor: User = Depends(require_permission("material_balance_templates:update")),
    db: Session = Depends(get_db),
):
    row = db.get(MaterialBalanceTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Material balance template not found")
    db.query(MaterialBalanceTemplate).filter(
        MaterialBalanceTemplate.location_code == row.location_code,
        MaterialBalanceTemplate.id != template_id,
    ).update({MaterialBalanceTemplate.is_default: False})
    row.is_default = True
    row.updated_at = utcnow()
    create_audit_log(
        db,
        module_name="Material Balance Template Master",
        action="Set Default Material Balance Template",
        category="Data Change",
        current_user=actor,
        entity_type="MaterialBalanceTemplate",
        entity_id=row.id,
        entity_label=f"{row.template_name} ({row.template_code})",
        request=request,
        remarks=f"Set {row.template_code} as default for {row.location_code}",
        details_summary=f"code={row.template_code}; location={row.location_code}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return serialize_mb_template(row)


@router.delete("/material-balance-templates/{template_id}")
def delete_material_balance_template(
    template_id: int,
    request: Request,
    actor: User = Depends(require_permission("material_balance_templates:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(MaterialBalanceTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Material balance template not found")
    label = f"{row.template_name} ({row.template_code})"
    create_audit_log(
        db,
        module_name="Material Balance Template Master",
        action="Delete Material Balance Template",
        category="Data Change",
        current_user=actor,
        entity_type="MaterialBalanceTemplate",
        entity_id=row.id,
        entity_label=label,
        old_status=row.status,
        request=request,
        remarks="Material balance template deleted",
        details_summary=f"code={row.template_code}; location={row.location_code}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Material balance template deleted successfully"}
