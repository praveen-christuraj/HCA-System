"""Typed supporting masters used by the unchanged OTMS entry payloads.

Read lookups require entry access, not master-admin rights. Mutations remain
separately permission-gated, scoped, audited, and previewed for CSV/XLSX imports.
"""
from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, Request, HTTPException, File, Form, UploadFile, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models import (Table11Factor, FlowmeterConfig, BargeSealMaster, OperationWorkflowPolicy,
    OperationWorkflowPolicyRole, OperationWorkflowPolicyUser, OperationVoyage, OperationEntry,
    Role, User, Asset, AssetTank, Location)
from app.dependencies.permissions import require_any_permission, get_user_location_ids, is_admin_user
from app.services.operation_entry_access import ensure_location, scoped_asset, require_capability, scoped_entries
from app.services.audit_service import create_audit_log
from app.services.master_import import read_master_import, MAX_IMPORT_BYTES
from app.utils.pagination import paginate_query
from app.utils.exporters import csv_response, xlsx_response
from app.utils.time import utcnow
from app.utils.operation_types import get_operation_type

router = APIRouter(prefix="/operation-references", tags=["Operation References"])
read_access = require_any_permission("operation_entries:read", "operation_references:read", "operation_policies:read", "operation_voyages:read")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class FactorInput(StrictModel):
    api60: float = Field(ge=-10, le=150)
    lt_factor: float = Field(gt=0, le=1)


class MeterInput(StrictModel):
    location_id: int = Field(ge=1)
    asset_id: int = Field(ge=1)
    stream_name: str = Field(min_length=1, max_length=150)
    meter_asset_id: int | None = Field(None, ge=1)
    meter_label: str = Field(min_length=1, max_length=150)
    meter_factor: float = Field(gt=0, le=10)
    meter_unit: Literal["bbls", "m3"] = "bbls"
    calibration_date: date | None = None
    remarks: str | None = Field(None, max_length=2000)
    status: Literal["Active", "Inactive"] = "Active"


class SealInput(StrictModel):
    asset_id: int = Field(ge=1)
    tank_id: int = Field(ge=1)
    seal_position: Literal["MH1", "MH2", "LOCK", "DIPHATCH"]
    seal_number: str = Field(min_length=1, max_length=120)
    effective_date: date | None = None
    remarks: str | None = Field(None, max_length=2000)
    status: Literal["Active", "Inactive"] = "Active"


class PolicyInput(StrictModel):
    policy_name: str = Field(min_length=2, max_length=150)
    action_code: Literal["CREATE_ENTRY", "EDIT_ENTRY", "REVIEW", "SUBMIT", "RECALL", "APPROVE", "REJECT", "CANCEL"]
    operation_type_code: str | None = None
    asset_type_code: str | None = None
    location_id: int | None = Field(None, ge=1)
    payload_code: str | None = None
    priority: int = Field(100, ge=0, le=10000)
    role_ids: list[int] = Field(default_factory=list, max_length=200)
    allow_user_ids: list[int] = Field(default_factory=list, max_length=200)
    deny_user_ids: list[int] = Field(default_factory=list, max_length=200)
    status: Literal["Active", "Inactive"] = "Active"


KINDS = {"table11": (Table11Factor, FactorInput), "meters": (FlowmeterConfig, MeterInput),
    "seals": (BargeSealMaster, SealInput), "policies": (OperationWorkflowPolicy, PolicyInput)}


def _resource(kind):
    return "operation_policies" if kind == "policies" else "operation_references"


def _read_gate(db, user, kind):
    if kind == "policies": require_capability(db, user, "operation_policies:read")
    elif kind == "voyages": require_capability(db, user, "operation_voyages:read")
    elif not (is_admin_user(user, db) or _has(db, user, "operation_entries:read")):
        require_capability(db, user, "operation_references:read")


def _has(db, user, capability):
    from app.dependencies.permissions import user_has_permission
    return user_has_permission(db, user, capability)


def _query(db, user, kind, *, search="", asset_id=None, location_id=None, status=None, date_from=None, date_to=None):
    _read_gate(db, user, kind)
    if date_from and date_to and date_to < date_from: raise HTTPException(400, "Date To must not precede Date From")
    if kind not in KINDS and kind != "voyages": raise HTTPException(404, "Unknown reference master")
    model = OperationVoyage if kind == "voyages" else KINDS[kind][0]
    q = db.query(model)
    allowed = get_user_location_ids(db, user)
    if hasattr(model, "location_id") and allowed is not None:
        q = q.filter(model.location_id.in_(allowed))
    if kind == "seals" and allowed is not None:
        q = q.join(Asset).filter(or_(Asset.asset_scope == "Global", Asset.location_id.in_(allowed)))
    if asset_id and hasattr(model, "asset_id"): q = q.filter(model.asset_id == asset_id)
    if location_id and hasattr(model, "location_id"): q = q.filter(model.location_id == location_id)
    if status and hasattr(model, "status"): q = q.filter(model.status == status)
    if date_from: q = q.filter(func.date(model.created_at) >= date_from)
    if date_to: q = q.filter(func.date(model.created_at) <= date_to)
    if search:
        fields = [getattr(model, k) for k in ("meter_label", "stream_name", "seal_number", "policy_name", "reference") if hasattr(model, k)]
        if fields: q = q.filter(or_(*(f.ilike(f"%{search}%") for f in fields)))
        elif kind == "table11":
            try: q = q.filter(Table11Factor.api60 == float(search))
            except ValueError: q = q.filter(Table11Factor.id == -1)
    return q.order_by(model.id)


def _serialize(kind, row):
    from decimal import Decimal
    d = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    d = {k: float(v) if isinstance(v, Decimal) else v for k, v in d.items()}
    if kind == "policies":
        d.update(role_ids=[r.role_id for r in row.roles], allow_user_ids=[u.user_id for u in row.users if u.mode == "ALLOW"], deny_user_ids=[u.user_id for u in row.users if u.mode == "DENY"])
    if kind in ("meters", "seals", "voyages"):
        d.update(asset_code=row.asset.asset_code, asset_name=row.asset.asset_name)
    if kind == "seals": d["tank_name"] = row.tank.tank_name
    if kind == "meters":
        d.update(meter_asset_code=row.meter_asset.asset_code if row.meter_asset else None,
                 meter_asset_name=row.meter_asset.asset_name if row.meter_asset else None)
    return d


def _validate(db, user, kind, data, row_id=None):
    if kind not in KINDS: raise HTTPException(404, "Unknown reference master")
    model, schema = KINDS[kind]
    try: body = schema(**data)
    except ValidationError as e: raise HTTPException(400, "; ".join(f"{'.'.join(map(str, er['loc']))}: {er['msg']}" for er in e.errors()))
    if kind == "table11":
        q = db.query(model).filter_by(api60=body.api60)
    elif kind == "meters":
        ensure_location(db, user, body.location_id)
        asset = scoped_asset(db, user, body.asset_id, location_id=body.location_id, active=True)
        if asset.asset_type_code != "FLOWMETER": raise HTTPException(400, "Select a FLOWMETER stream asset")
        if body.meter_asset_id:
            meter = scoped_asset(db, user, body.meter_asset_id, active=True)
            if meter.asset_type_code != "FLOWMETER": raise HTTPException(400, "Meter asset must be a FLOWMETER")
        q = db.query(model).filter_by(location_id=body.location_id, asset_id=body.asset_id, meter_label=body.meter_label)
    elif kind == "seals":
        asset = scoped_asset(db, user, body.asset_id, active=True)
        tank = db.get(AssetTank, body.tank_id)
        if asset.asset_type_code != "BARGE" or not tank or tank.asset_id != asset.id:
            raise HTTPException(400, "Select a tank declared on the Barge asset")
        q = db.query(model).filter_by(asset_id=body.asset_id, tank_id=body.tank_id, seal_position=body.seal_position)
    else:
        if body.location_id: ensure_location(db, user, body.location_id)
        elif not is_admin_user(user, db): raise HTTPException(403, "Only Admin may maintain location-independent policies")
        if body.operation_type_code and not get_operation_type(body.operation_type_code): raise HTTPException(400, "Unknown operation type")
        from app.utils.asset_types import get_asset_type
        from app.utils.operation_entry_payloads import PAYLOAD_FIELD_CODES, MANUAL_LAYOUTS
        if body.asset_type_code and not get_asset_type(body.asset_type_code): raise HTTPException(400, "Unknown asset type")
        if body.payload_code and body.payload_code not in (*PAYLOAD_FIELD_CODES, *MANUAL_LAYOUTS): raise HTTPException(400, "Unknown fixed payload")
        if body.location_id and not db.get(Location, body.location_id): raise HTTPException(400, "Policy location not found")
        if set(body.allow_user_ids) & set(body.deny_user_ids): raise HTTPException(400, "A user cannot be both allowed and denied")
        for rid in body.role_ids:
            r = db.get(Role, rid)
            if not r or r.status != "Active": raise HTTPException(400, "Policy roles must be Active")
        for uid in body.allow_user_ids + body.deny_user_ids:
            if not db.get(User, uid): raise HTTPException(400, "Policy user not found")
        q = db.query(model).filter_by(policy_name=body.policy_name)
    if row_id: q = q.filter(model.id != row_id)
    if q.first(): raise HTTPException(400, "A reference with this key already exists; edit that row instead")
    return body


def _write(db, kind, body, row=None):
    if row is None: row = KINDS[kind][0](); db.add(row)
    values = body.model_dump()
    for key, value in values.items():
        if key not in ("role_ids", "allow_user_ids", "deny_user_ids"): setattr(row, key, value)
    if kind == "policies":
        row.roles.clear(); row.users.clear(); db.flush()
        row.roles = [OperationWorkflowPolicyRole(role_id=r) for r in sorted(set(body.role_ids))]
        row.users = [OperationWorkflowPolicyUser(user_id=u, mode=mode) for mode, ids in (("ALLOW", body.allow_user_ids), ("DENY", body.deny_user_ids)) for u in sorted(set(ids))]
    return row


def _audit(db, request, user, kind, action, summary):
    create_audit_log(db, "Operation References" if kind != "policies" else "Operation Workflow Policies", action,
        current_user=user, request=request, details_summary=summary)


def _commit(db, request):
    try: db.commit()
    except IntegrityError:
        db.rollback(); request.state.audit_written = False; raise HTTPException(409, "This reference is already present or used by a ticket")


@router.get("/{kind}")
def listing(kind: str, search: str = "", asset_id: int | None = None, location_id: int | None = None, status: str | None = None,
            date_from: date | None = None, date_to: date | None = None, page: int = 1, page_size: int = 20,
            db=Depends(get_db), user=Depends(read_access)):
    q = _query(db, user, kind, search=search, asset_id=asset_id, location_id=location_id, status=status, date_from=date_from, date_to=date_to)
    result = paginate_query(q, page, page_size)
    result["items"] = [_serialize(kind, r) for r in result["items"]]
    return result


@router.post("/{kind}", status_code=201)
def create(kind: str, data: dict, request: Request, db=Depends(get_db), user=Depends(read_access)):
    require_capability(db, user, _resource(kind) + ":create")
    body = _validate(db, user, kind, data)
    row = _write(db, kind, body); db.flush()
    _audit(db, request, user, kind, "Create", f"{kind} #{row.id}: " + "; ".join(f"{k}={v}" for k,v in data.items()))
    _commit(db, request); db.refresh(row)
    return _serialize(kind, row)


@router.put("/{kind}/{row_id}")
def update(kind: str, row_id: int, data: dict, request: Request, db=Depends(get_db), user=Depends(read_access)):
    if kind == "voyages":
        require_capability(db, user, "operation_voyages:update")
        row = _query(db, user, kind).filter(OperationVoyage.id == row_id).with_for_update().first()
        if not row: raise HTTPException(404, "Voyage not found")
        status = data.get("status")
        if status not in ("OPEN", "CLOSED"): raise HTTPException(400, "Choose OPEN or CLOSED")
        remarks = str(data.get("closure_remarks") or "").strip()
        if not remarks: raise HTTPException(400, "Closure/reopen remarks are required")
        tickets = db.query(OperationEntry).filter_by(convoy_number=row.reference, operation_type_code=row.operation_type_code)
        if row.operation_type_code != "BARGE_OPERATIONS": tickets = tickets.filter_by(asset_id=row.asset_id, location_id=row.location_id)
        if status == "CLOSED" and tickets.filter(OperationEntry.status.in_(["Draft", "Rejected", "Submitted"])).first():
            raise HTTPException(400, "Finish or cancel open tickets before closing the voyage")
        row.status, row.closure_remarks = status, remarks
        row.closed_at, row.closed_by_user_id = (utcnow(), user.id) if status == "CLOSED" else (None, None)
        _audit(db, request, user, kind, "Close Voyage" if status == "CLOSED" else "Reopen Voyage", f"{row.reference}: {remarks}")
    else:
        require_capability(db, user, _resource(kind) + ":update")
        model = KINDS.get(kind, (None,))[0]
        if not model: raise HTTPException(404, "Unknown reference master")
        row = _query(db, user, kind).filter(model.id == row_id).first()
        if not row: raise HTTPException(404, "Reference not found")
        body = _validate(db, user, kind, data, row_id)
        before = "; ".join(f"{k}={v}" for k, v in _serialize(kind, row).items())
        _write(db, kind, body, row)
        _audit(db, request, user, kind, "Update", f"Before: {before}; After: " + "; ".join(f"{k}={v}" for k,v in data.items()))
    _commit(db, request); db.refresh(row)
    return _serialize(kind, row)


@router.delete("/{kind}/{row_id}")
def delete(kind: str, row_id: int, request: Request, db=Depends(get_db), user=Depends(read_access)):
    require_capability(db, user, _resource(kind) + ":delete")
    if kind not in KINDS: raise HTTPException(404, "Unknown reference master")
    model = KINDS[kind][0]
    row = _query(db, user, kind).filter(model.id == row_id).first()
    if not row: raise HTTPException(404, "Reference not found")
    if kind == "table11": db.delete(row)
    else: row.status = "Inactive"
    _audit(db, request, user, kind, "Delete" if kind == "table11" else "Deactivate", f"{kind} #{row_id}")
    _commit(db, request)
    return {"ok": True}


@router.post("/{kind}/import")
async def import_rows(kind: str, request: Request, file: UploadFile = File(...), confirm: bool = Form(False), db=Depends(get_db), user=Depends(read_access)):
    require_capability(db, user, _resource(kind) + ":create")
    if kind not in KINDS: raise HTTPException(400, "This generated reference cannot be imported")
    try: parsed = read_master_import(await file.read(MAX_IMPORT_BYTES + 1), file.filename)
    except ValueError as e: raise HTTPException(400, str(e))
    preview, bodies, seen = [], [], set()
    for item in parsed["rows"]:
        data = {k: v for k, v in item.items() if k != "row_number" and v != ""}
        for k in ("role_ids", "allow_user_ids", "deny_user_ids"):
            if k in data:
                try: data[k] = [int(v.strip()) for v in data[k].split(";") if v.strip()]
                except ValueError: data[k] = ["invalid"]
        errors = []
        try:
            body = _validate(db, user, kind, data)
            keys = {"table11": ["api60"], "meters": ["location_id", "asset_id", "meter_label"], "seals": ["asset_id", "tank_id", "seal_position"], "policies": ["policy_name"]}[kind]
            key = tuple(getattr(body, k) for k in keys)
            if key in seen: raise HTTPException(400, "Duplicate reference key in this file")
            seen.add(key); bodies.append(body)
        except HTTPException as e: errors.append(str(e.detail))
        preview.append({**item, "valid": not errors, "errors": errors})
    result = {"rows": preview, "valid_rows": sum(r["valid"] for r in preview), "invalid_rows": sum(not r["valid"] for r in preview), "total_rows": len(preview), "imported": 0}
    if confirm and not result["invalid_rows"]:
        for body in bodies: _write(db, kind, body)
        result["imported"] = len(bodies)
    _audit(db, request, user, kind, "Import" if confirm else "Import Preview", f"{file.filename}: valid {result['valid_rows']}; invalid {result['invalid_rows']}; imported {result['imported']}")
    _commit(db, request)
    return JSONResponse(status_code=400, content=result) if confirm and result["invalid_rows"] else result


@router.get("/{kind}/export")
def export(kind: str, request: Request, format: Literal["csv", "xlsx", "pdf"] = "csv", search: str = "", asset_id: int | None = None, location_id: int | None = None,
           status: str | None = None, date_from: date | None = None, date_to: date | None = None, db=Depends(get_db), user=Depends(read_access)):
    q = _query(db, user, kind, search=search, asset_id=asset_id, location_id=location_id, status=status, date_from=date_from, date_to=date_to)
    if q.count() > 5000: raise HTTPException(400, "Narrow filters to at most 5,000 reference rows")
    headers = list(KINDS[kind][1].model_fields) if kind in KINDS else ["reference", "operation_type_code", "asset_id", "location_id", "status", "closure_remarks"]
    rows = []
    for r in q:
        d = _serialize(kind, r)
        rows.append([";".join(str(v) for v in d.get(k, [])) if isinstance(d.get(k), list) else d.get(k) for k in headers])
    _audit(db, request, user, kind, "Export", f"{len(rows)} rows as {format}; search={search}; status={status}; asset={asset_id}; location={location_id}; dates={date_from}–{date_to}")
    db.commit()
    if format == "csv": return csv_response(kind, headers, rows)
    if format == "xlsx": return xlsx_response(kind, kind.title(), headers, rows)
    from app.services.operation_entry_exports import reference_pdf
    return reference_pdf(kind, headers, rows, f"Search={search}; status={status}; dates={date_from} to {date_to}")
