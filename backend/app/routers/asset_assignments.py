"""Asset Assignment Master and Asset Assignment Summary APIs."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import get_user_location_ids, require_permission
from app.models import Asset, AssetAssignment, Location, User
from app.services.audit_service import create_audit_log
from app.services.master_import import read_master_import
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/asset-assignments", tags=["Asset Assignment"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssetAssignmentPayload(StrictModel):
    asset_id: int | None = None
    asset_code: str = Field(min_length=1, max_length=50)
    asset_scope: str | None = Field(default=None, max_length=30)
    assignment_location_id: int | None = None
    assignment_location_code: str = Field(min_length=1, max_length=50)
    assigned_to_type: Literal["User", "Location", "External"]
    assigned_to: str = Field(min_length=1, max_length=150)
    assignment_date: date
    return_date: date | None = None
    remarks: str | None = Field(default=None, max_length=2000)
    status: Literal["Active", "Inactive", "Returned", "Closed"] = "Active"


def _serialize_assignment(
    row: AssetAssignment,
    assets_by_code: dict[str, Asset],
    locations_by_code: dict[str, Location],
    users_by_username: dict[str, User],
) -> dict:
    asset = assets_by_code.get(row.asset_code.upper()) or row.asset
    loc = locations_by_code.get(row.assignment_location_code.upper()) or row.assignment_location
    assigned_display = row.assigned_to
    if row.assigned_to_type == "User":
        u = users_by_username.get(row.assigned_to.lower())
        if u:
            assigned_display = f"{u.full_name} ({u.username})"
    elif row.assigned_to_type == "Location":
        target_loc = locations_by_code.get(row.assigned_to.upper())
        if target_loc:
            assigned_display = f"{target_loc.location_name} ({target_loc.location_code})"

    return {
        "id": row.id,
        "asset_id": row.asset_id,
        "asset_code": row.asset_code,
        "asset_name": asset.asset_name if asset else "",
        "asset_type_code": asset.asset_type_code if asset else "",
        "asset_scope": row.asset_scope,
        "assignment_location_id": row.assignment_location_id,
        "assignment_location_code": row.assignment_location_code,
        "assignment_location_name": loc.location_name if loc else "",
        "assigned_to_type": row.assigned_to_type,
        "assigned_to": row.assigned_to,
        "assigned_to_display": assigned_display,
        "assignment_date": row.assignment_date,
        "return_date": row.return_date,
        "remarks": row.remarks or "",
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _load_refs(db: Session):
    assets = {a.asset_code.upper(): a for a in db.query(Asset).all()}
    locations = {l.location_code.upper(): l for l in db.query(Location).all()}
    users = {u.username.lower(): u for u in db.query(User).all()}
    return assets, locations, users


def _validate_and_resolve(
    db: Session,
    actor: User,
    payload: AssetAssignmentPayload,
    *,
    assignment_id: int | None = None,
) -> tuple[Asset, Location]:
    asset = (
        db.get(Asset, payload.asset_id)
        if payload.asset_id
        else db.query(Asset).filter(func.upper(Asset.asset_code) == payload.asset_code.upper()).first()
    )
    if asset is None:
        raise HTTPException(status_code=400, detail="Asset not found")
    if asset.status != "Active":
        raise HTTPException(status_code=400, detail="Only Active assets can be assigned")

    if payload.asset_scope and payload.asset_scope != asset.asset_scope:
        raise HTTPException(status_code=400, detail="Selected asset scope does not match Asset Master")

    loc = (
        db.get(Location, payload.assignment_location_id)
        if payload.assignment_location_id
        else db.query(Location).filter(func.upper(Location.location_code) == payload.assignment_location_code.upper()).first()
    )
    if loc is None:
        raise HTTPException(status_code=400, detail="Assignment location not found")
    if loc.status != "Active":
        raise HTTPException(status_code=400, detail="Only Active locations can be used for assignment")

    allowed = get_user_location_ids(db, actor)
    if allowed is not None and loc.id not in allowed:
        raise HTTPException(status_code=403, detail="Assignment location is outside your assigned scope")
    if allowed is not None and asset.location_id and asset.location_id not in allowed and asset.asset_scope != "Global":
        raise HTTPException(status_code=403, detail="Asset location is outside your assigned scope")

    if payload.return_date and payload.return_date < payload.assignment_date:
        raise HTTPException(status_code=400, detail="Return date cannot precede assignment date")

    if payload.assigned_to_type == "User":
        assigned_user = db.query(User).filter(func.lower(User.username) == payload.assigned_to.lower()).first()
        if assigned_user is None:
            raise HTTPException(status_code=400, detail="Assigned user not found")
        if assigned_user.status != "Active":
            raise HTTPException(status_code=400, detail="Only Active users can be assigned")
    elif payload.assigned_to_type == "Location":
        assigned_loc = (
            db.query(Location)
            .filter(
                or_(
                    func.upper(Location.location_code) == payload.assigned_to.upper(),
                    func.lower(Location.location_name) == payload.assigned_to.lower(),
                )
            )
            .first()
        )
        if assigned_loc is not None and assigned_loc.status != "Active":
            raise HTTPException(status_code=400, detail="Only Active locations can be assigned")

    if payload.status == "Active":
        dup_q = db.query(AssetAssignment).filter(
            AssetAssignment.asset_id == asset.id,
            AssetAssignment.status == "Active",
        )
        if assignment_id is not None:
            dup_q = dup_q.filter(AssetAssignment.id != assignment_id)
        if dup_q.first():
            raise HTTPException(status_code=400, detail="This asset already has an active assignment")

    return asset, loc


def _filtered_assignments(
    db: Session,
    actor: User,
    *,
    search: str | None = None,
    status: str | None = None,
    assigned_to_type: str | None = None,
    location_code: str | None = None,
    asset_scope: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    query = db.query(AssetAssignment)
    allowed = get_user_location_ids(db, actor)
    if allowed is not None:
        query = query.filter(AssetAssignment.assignment_location_id.in_(allowed))
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                AssetAssignment.asset_code.ilike(term),
                AssetAssignment.assignment_location_code.ilike(term),
                AssetAssignment.assigned_to.ilike(term),
                AssetAssignment.remarks.ilike(term),
            )
        )
    if status:
        query = query.filter(AssetAssignment.status == status)
    if assigned_to_type:
        query = query.filter(AssetAssignment.assigned_to_type == assigned_to_type)
    if location_code:
        query = query.filter(func.upper(AssetAssignment.assignment_location_code) == location_code.strip().upper())
    if asset_scope:
        query = query.filter(AssetAssignment.asset_scope == asset_scope)
    if date_from:
        query = query.filter(AssetAssignment.assignment_date >= date_from)
    if date_to:
        query = query.filter(AssetAssignment.assignment_date <= date_to)
    return query.order_by(AssetAssignment.assignment_date.desc(), AssetAssignment.id.desc())


@router.get("")
def list_asset_assignments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    assigned_to_type: str | None = None,
    location_code: str | None = None,
    asset_scope: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("asset_assignments:read")),
    db: Session = Depends(get_db),
):
    query = _filtered_assignments(
        db,
        actor,
        search=search,
        status=status,
        assigned_to_type=assigned_to_type,
        location_code=location_code,
        asset_scope=asset_scope,
        date_from=date_from,
        date_to=date_to,
    )
    result = paginate_query(query, page=page, page_size=page_size)
    assets_by_code, locations_by_code, users_by_username = _load_refs(db)
    result["items"] = [
        _serialize_assignment(row, assets_by_code, locations_by_code, users_by_username)
        for row in result["items"]
    ]
    return result


@router.get("/summary")
def asset_assignment_summary(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    asset_type_code: str | None = None,
    asset_scope: str | None = None,
    location_code: str | None = None,
    assignment_state: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("asset_assignments:read")),
    db: Session = Depends(get_db),
):
    """Combined view of all assets and their current assignment status."""
    assets_by_code, locations_by_code, users_by_username = _load_refs(db)
    allowed = get_user_location_ids(db, actor)

    assets_q = db.query(Asset)
    if allowed is not None:
        assets_q = assets_q.filter(or_(Asset.asset_scope == "Global", Asset.location_id.in_(allowed)))
    if status:
        assets_q = assets_q.filter(Asset.status == status)
    if asset_type_code:
        assets_q = assets_q.filter(Asset.asset_type_code == asset_type_code)
    if asset_scope:
        assets_q = assets_q.filter(Asset.asset_scope == asset_scope)
    if location_code:
        loc_obj = locations_by_code.get(location_code.strip().upper())
        if loc_obj:
            assets_q = assets_q.filter(Asset.location_id == loc_obj.id)
    if search:
        term = f"%{search.strip()}%"
        assets_q = assets_q.filter(or_(Asset.asset_code.ilike(term), Asset.asset_name.ilike(term)))

    all_assets = assets_q.order_by(Asset.asset_code.asc()).all()
    all_assignments = (
        db.query(AssetAssignment)
        .order_by(AssetAssignment.assignment_date.desc(), AssetAssignment.id.desc())
        .all()
    )
    assignments_by_asset: dict[int, list[AssetAssignment]] = {}
    for a in all_assignments:
        assignments_by_asset.setdefault(a.asset_id, []).append(a)

    rows = []
    for asset in all_assets:
        history = assignments_by_asset.get(asset.id, [])
        active = next((h for h in history if h.status == "Active"), None)
        latest = active or (history[0] if history else None)
        if date_from and latest and latest.assignment_date < date_from:
            continue
        if date_to and latest and latest.assignment_date > date_to:
            continue
        state = "Assigned" if active else ("Previously Assigned" if history else "Unassigned")
        if assignment_state and state != assignment_state:
            continue
        base_loc = db.get(Location, asset.location_id) if asset.location_id else None
        rows.append(
            {
                "asset_id": asset.id,
                "asset_code": asset.asset_code,
                "asset_name": asset.asset_name,
                "asset_type_code": asset.asset_type_code,
                "asset_scope": asset.asset_scope,
                "asset_status": asset.status,
                "base_location_code": base_loc.location_code if base_loc else "",
                "base_location_name": base_loc.location_name if base_loc else "",
                "assignment_state": state,
                "total_assignments": len(history),
                "current_assignment": (
                    _serialize_assignment(latest, assets_by_code, locations_by_code, users_by_username)
                    if latest
                    else None
                ),
            }
        )

    total = len(rows)
    start = (page - 1) * page_size
    paged = rows[start : start + page_size]
    pages = max(1, (total + page_size - 1) // page_size)
    return {
        "items": paged,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "has_more": page < pages,
        "kpis": {
            "total_assets": len(all_assets),
            "currently_assigned": sum(1 for r in rows if r["assignment_state"] == "Assigned"),
            "assigned_assets": sum(1 for r in rows if r["assignment_state"] == "Assigned"),
            "unassigned": sum(1 for r in rows if r["assignment_state"] == "Unassigned"),
            "previously_assigned": sum(1 for r in rows if r["assignment_state"] == "Previously Assigned"),
        },
    }


@router.get("/export")
def export_asset_assignments(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    assigned_to_type: str | None = None,
    location_code: str | None = None,
    asset_scope: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("asset_assignments:read")),
    db: Session = Depends(get_db),
):
    records = (
        _filtered_assignments(
            db,
            actor,
            search=search,
            status=status,
            assigned_to_type=assigned_to_type,
            location_code=location_code,
            asset_scope=asset_scope,
            date_from=date_from,
            date_to=date_to,
        )
        .limit(MAX_EXPORT_ROWS)
        .all()
    )
    assets_by_code, locations_by_code, users_by_username = _load_refs(db)
    headers = [
        "Asset Code",
        "Asset Name",
        "Scope",
        "Assignment Location",
        "Assigned To Type",
        "Assigned To",
        "Assignment Date",
        "Return Date",
        "Status",
        "Remarks",
    ]
    rows = []
    for r in records:
        item = _serialize_assignment(r, assets_by_code, locations_by_code, users_by_username)
        rows.append(
            [
                item["asset_code"],
                item["asset_name"],
                item["asset_scope"],
                f"{item['assignment_location_name']} ({item['assignment_location_code']})".strip(),
                item["assigned_to_type"],
                item["assigned_to_display"],
                item["assignment_date"],
                item["return_date"] or "",
                item["status"],
                item["remarks"],
            ]
        )
    create_audit_log(
        db,
        module_name="Asset Assignment",
        action="Export Asset Assignments",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} asset assignments as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("asset-assignments", headers, rows)
    if format == "xlsx":
        return xlsx_response("asset-assignments", "Asset Assignments", headers, rows)
    return pdf_response("asset-assignments", "Asset Assignments Register", headers, rows)


@router.post("/import")
def import_asset_assignments(
    request: Request,
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    actor: User = Depends(require_permission("asset_assignments:create")),
    db: Session = Depends(get_db),
):
    try:
        table = read_master_import(file.file.read(), file.filename or "")
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"message": str(exc), "rows": [], "valid_rows": 0, "invalid_rows": 0})

    required = {"asset_code", "assignment_location_code", "assigned_to_type", "assigned_to", "assignment_date"}
    missing = sorted(required - set(table["columns"]))
    assets_by_code, locations_by_code, users_by_username = _load_refs(db)

    preview_rows = []
    for row in table["rows"]:
        acode = row.get("asset_code", "").strip().upper()
        lcode = row.get("assignment_location_code", "").strip().upper()
        atype = row.get("assigned_to_type", "User").strip()
        ato = row.get("assigned_to", "").strip()
        adate_raw = row.get("assignment_date", "").strip()
        rdate_raw = row.get("return_date", "").strip()
        status = row.get("status", "Active").strip() or "Active"
        remarks = row.get("remarks", "").strip()

        errors = []
        asset = assets_by_code.get(acode)
        loc = locations_by_code.get(lcode)
        if not asset:
            errors.append(f"Asset '{acode}' not found")
        elif asset.status != "Active":
            errors.append(f"Asset '{acode}' is not Active")
        if not loc:
            errors.append(f"Location '{lcode}' not found")
        elif loc.status != "Active":
            errors.append(f"Location '{lcode}' is not Active")
        if atype not in {"User", "Location", "External"}:
            errors.append("assigned_to_type must be User, Location or External")
        if not ato:
            errors.append("assigned_to is required")
        parsed_adate = None
        if not adate_raw:
            errors.append("assignment_date is required")
        else:
            try:
                parsed_adate = date.fromisoformat(adate_raw[:10])
            except ValueError:
                errors.append("assignment_date must be YYYY-MM-DD")
        parsed_rdate = None
        if rdate_raw:
            try:
                parsed_rdate = date.fromisoformat(rdate_raw[:10])
            except ValueError:
                errors.append("return_date must be YYYY-MM-DD")

        preview_rows.append(
            {
                "row_number": row["row_number"],
                "asset_code": acode,
                "assignment_location_code": lcode,
                "assigned_to_type": atype,
                "assigned_to": ato,
                "assignment_date": str(parsed_adate) if parsed_adate else adate_raw,
                "return_date": str(parsed_rdate) if parsed_rdate else rdate_raw,
                "status": status,
                "remarks": remarks,
                "valid": not errors,
                "errors": errors,
                "_parsed": (asset, loc, parsed_adate, parsed_rdate),
            }
        )

    valid_count = sum(1 for r in preview_rows if r["valid"])
    response_body = {
        "filename": table["filename"],
        "format": table["format"],
        "total_rows": len(preview_rows),
        "valid_rows": valid_count,
        "invalid_rows": len(preview_rows) - valid_count,
        "columns_detected": table["columns"],
        "missing_columns": missing,
        "rows": [{k: v for k, v in r.items() if k != "_parsed"} for r in preview_rows],
        "message": f"{valid_count} row(s) ready to import" if not missing else "Missing required columns",
    }
    if missing or not confirm:
        create_audit_log(
            db,
            module_name="Asset Assignment",
            action="Preview Asset Assignment Import",
            category="Import",
            current_user=actor,
            request=request,
            remarks=f"Previewed asset assignment import from {table['filename']}",
            details_summary=f"rows={len(preview_rows)}; valid={valid_count}",
        )
        db.commit()
        request.state.audit_written = True
        return JSONResponse(status_code=422 if missing else 200, content=response_body)

    if response_body["invalid_rows"] > 0 or valid_count == 0:
        return JSONResponse(status_code=422, content=response_body)

    for r in preview_rows:
        asset, loc, parsed_adate, parsed_rdate = r["_parsed"]
        db.add(
            AssetAssignment(
                asset_id=asset.id,
                asset_code=asset.asset_code,
                asset_scope=asset.asset_scope,
                assignment_location_id=loc.id,
                assignment_location_code=loc.location_code,
                assigned_to_type=r["assigned_to_type"],
                assigned_to=r["assigned_to"],
                assignment_date=parsed_adate,
                return_date=parsed_rdate,
                remarks=r["remarks"] or None,
                status=r["status"],
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
    create_audit_log(
        db,
        module_name="Asset Assignment",
        action="Import Asset Assignments",
        category="Import",
        current_user=actor,
        request=request,
        remarks=f"Imported {valid_count} asset assignments from {table['filename']}",
        details_summary=f"file={table['filename']}; imported={valid_count}",
        status_code=201,
    )
    db.commit()
    request.state.audit_written = True
    response_body["imported"] = valid_count
    return response_body


@router.post("", status_code=201)
def create_asset_assignment(
    payload: AssetAssignmentPayload,
    request: Request,
    actor: User = Depends(require_permission("asset_assignments:create")),
    db: Session = Depends(get_db),
):
    asset, loc = _validate_and_resolve(db, actor, payload)
    row = AssetAssignment(
        asset_id=asset.id,
        asset_code=asset.asset_code,
        asset_scope=asset.asset_scope,
        assignment_location_id=loc.id,
        assignment_location_code=loc.location_code,
        assigned_to_type=payload.assigned_to_type,
        assigned_to=payload.assigned_to.strip(),
        assignment_date=payload.assignment_date,
        return_date=payload.return_date,
        remarks=(payload.remarks or "").strip() or None,
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()

    create_audit_log(
        db,
        module_name="Asset Assignment",
        action="Create Asset Assignment",
        category="Data Change",
        current_user=actor,
        entity_type="AssetAssignment",
        entity_id=row.id,
        entity_label=f"{asset.asset_name} ({asset.asset_code})",
        new_status=row.status,
        request=request,
        remarks="Asset assignment created",
        details_summary=f"asset={asset.asset_code}; location={loc.location_code}; assigned_to={row.assigned_to}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    assets_by_code, locations_by_code, users_by_username = _load_refs(db)
    return _serialize_assignment(row, assets_by_code, locations_by_code, users_by_username)


@router.put("/{assignment_id}")
def update_asset_assignment(
    assignment_id: int,
    payload: AssetAssignmentPayload,
    request: Request,
    actor: User = Depends(require_permission("asset_assignments:update")),
    db: Session = Depends(get_db),
):
    row = db.get(AssetAssignment, assignment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Asset assignment not found")
    asset, loc = _validate_and_resolve(db, actor, payload, assignment_id=assignment_id)

    old_status = row.status
    row.asset_id = asset.id
    row.asset_code = asset.asset_code
    row.asset_scope = asset.asset_scope
    row.assignment_location_id = loc.id
    row.assignment_location_code = loc.location_code
    row.assigned_to_type = payload.assigned_to_type
    row.assigned_to = payload.assigned_to.strip()
    row.assignment_date = payload.assignment_date
    row.return_date = payload.return_date
    row.remarks = (payload.remarks or "").strip() or None
    row.status = payload.status
    row.updated_at = utcnow()

    create_audit_log(
        db,
        module_name="Asset Assignment",
        action="Update Asset Assignment",
        category="Data Change",
        current_user=actor,
        entity_type="AssetAssignment",
        entity_id=row.id,
        entity_label=f"{asset.asset_name} ({asset.asset_code})",
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Asset assignment updated",
        details_summary=f"asset={asset.asset_code}; location={loc.location_code}; assigned_to={row.assigned_to}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    assets_by_code, locations_by_code, users_by_username = _load_refs(db)
    return _serialize_assignment(row, assets_by_code, locations_by_code, users_by_username)


@router.delete("/{assignment_id}")
def delete_asset_assignment(
    assignment_id: int,
    request: Request,
    actor: User = Depends(require_permission("asset_assignments:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(AssetAssignment, assignment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Asset assignment not found")
    allowed = get_user_location_ids(db, actor)
    if allowed is not None and row.assignment_location_id not in allowed:
        raise HTTPException(status_code=403, detail="Assignment location is outside your assigned scope")

    label = f"{row.asset_code} -> {row.assigned_to}"
    create_audit_log(
        db,
        module_name="Asset Assignment",
        action="Delete Asset Assignment",
        category="Data Change",
        current_user=actor,
        entity_type="AssetAssignment",
        entity_id=row.id,
        entity_label=label,
        old_status=row.status,
        request=request,
        remarks="Asset assignment deleted",
        details_summary=f"asset={row.asset_code}; location={row.assignment_location_code}; assigned_to={row.assigned_to}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Asset assignment deleted successfully"}
