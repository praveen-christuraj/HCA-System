"""One entry API for fixed OTMS module payloads and their ticket lifecycle."""
from copy import deepcopy
from datetime import date, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.database import get_db
from app.models import (Asset, Location, Operation, OperationEntry, OperationEntryStatusHistory,
    PrimeMoverTankerLink, FlowmeterConfig, BargeSealMaster, OperationVoyage, OperationPosting)
from app.dependencies.permissions import require_permission, require_any_permission, get_user_location_ids
from app.schemas import OperationEntryCreate, OperationEntryUpdate, OperationEntryCalculateRequest, OperationEntryStatusChange
from app.services.operation_entry_access import (get_entry, scoped_entries, scoped_asset, ensure_location,
    require_capability, check_policy, check_entry_policy)
from app.services.operation_entry_service import (calculate_payload, persist_payload, payload_from_entry,
    operation_entry_to_dict, operation_entry_status_history_to_dict, resolve_calibration_context, generate_ticket_number, EDITABLE_STATUSES)
from app.services.audit_service import create_audit_log
from app.services.table11 import lookup_table11_factor
from app.utils.operation_entry_payloads import entry_definition_catalog, resolve_entry_definition, MANUAL_LAYOUTS
from app.utils.operation_types import get_operation_type
from app.utils.pagination import paginate_query
from app.utils.time import utcnow
from app.utils.exporters import csv_response, xlsx_response
from app.config import MAX_EXPORT_ROWS

router = APIRouter(prefix="/operation-entries", tags=["Operation Entry"])
entry_read = require_permission("operation_entries:read")
# Ticket detail, history, snapshot export and status actions are also reached
# from the Operation Transaction Register (Operation Tracking), which is
# granted separately from the Operation Entry page. Each status action still
# requires its own submission / review / approval / cancel capability.
ticket_read = require_any_permission("operation_entries:read", "operation_transactions:read")
entry_write = require_any_permission("operation_entries:create", "receiving_tickets:create")


def _commit(db, request):
    try:
        db.commit()
    except (IntegrityError, StaleDataError):
        db.rollback()
        request.state.audit_written = False
        raise HTTPException(409, "This ticket or its reference changed concurrently. Reload before saving; nothing was overwritten.")


def _audit(db, request, user, action, row=None, **kw):
    create_audit_log(db, "Operation Entry", action, current_user=user, request=request,
        entity_type="OperationEntry", entity_id=row.id if row else None, entity_label=row.ticket_number if row else None, **kw)


def _version(entry, version):
    if entry.version != version:
        raise HTTPException(409, "The ticket has changed since it was opened. Reload and review the current version.")


def _location(db, location_id):
    loc = db.get(Location, location_id)
    if not loc or loc.status != "Active":
        raise HTTPException(400, "Select an Active location")
    return loc


def _canonical_operation_payload(payload, operation, code):
    p = deepcopy(payload)
    inputs = p["inputs"] = dict(p.get("inputs") or {})
    meta = p["meta"] = dict(p.get("meta") or {})
    op = {k: getattr(operation, "operation_" + k) for k in ("code", "label", "category", "sign")}
    if code == "tank_gauging_payload":
        if inputs.get("tankOperationCode") not in (None, "", op["code"]):
            raise HTTPException(400, "Tank Operation must match the selected Operation Master record")
        inputs.update({"tankOperation" + k.title(): v for k, v in op.items()})
    if code in ("shuttle_payload", "fso_payload"):
        prefix = "vessel_operation_" if code == "shuttle_payload" else "operation_"
        if meta.get(prefix + "code") not in (None, "", op["code"]):
            raise HTTPException(400, "Payload operation must match the selected Operation Master record")
        meta.update({prefix + k: v for k, v in op.items()})
    if code in MANUAL_LAYOUTS:
        inputs["vessel_operation_code"] = op["code"]
    return p


def _validate_seals(payload, asset, db, *, existing=None):
    after = (payload.get("seals") or {}).get("after") or {}
    tank_seals = after.get("tankSeals") or {}
    if not isinstance(tank_seals, dict):
        raise HTTPException(400, "seals.after.tankSeals must be an object")
    names = {t.tank_name for t in asset.tanks}
    master = {(s.tank.tank_name, s.seal_position): s.seal_number for s in db.query(BargeSealMaster).filter_by(asset_id=asset.id, status="Active")}
    if existing and existing.multi_tank:
        master = {(s.tank_name, s.position): s.master_number or "" for s in existing.multi_tank.seals if s.seal_group == "Tank"}
    for tank, cells in tank_seals.items():
        if tank not in names or not isinstance(cells, dict):
            raise HTTPException(400, "Seal tank must be declared on this asset")
        for pos, cell in cells.items():
            if pos not in ("MH1", "MH2", "LOCK", "DIPHATCH") or not isinstance(cell, dict):
                raise HTTPException(400, "Invalid permanent seal position")
            if any(len(str(cell.get(k) or "")) > 120 for k in ("master", "observed")):
                raise HTTPException(400, "Seal numbers may not exceed 120 characters")
            # The master is a reference, not a user-editable way to hide a mismatch.
            cell["master"] = master.get((tank, pos), "")
    # Include all reference positions even if a malicious client omitted one.
    for (tank, pos), number in master.items():
        tank_seals.setdefault(tank, {}).setdefault(pos, {"master": number, "observed": ""})
    after["tankSeals"] = tank_seals
    temporary = after.get("temporary") or {}
    for key, val in temporary.items():
        if key not in ("portManifoldSeal", "stbdManifoldSeal", "pumproomSeal", "otherSeal", "otherRemarks"):
            raise HTTPException(400, "Unknown temporary seal field")
        if len(str(val or "")) > (4000 if key == "otherRemarks" else 120):
            raise HTTPException(400, "Seal value is too long")
    payload["seals"] = {"after": after}


def _voyage_guard(db, body, *, create=False):
    if body.operation_type_code not in ("BARGE_OPERATIONS", "SHUTTLE_OPERATIONS", "FSO_OPERATIONS") or not body.convoy_number:
        return
    query = db.query(OperationVoyage).filter_by(operation_type_code=body.operation_type_code, reference=body.convoy_number)
    if body.operation_type_code != "BARGE_OPERATIONS":
        query = query.filter_by(asset_id=body.asset_id, location_id=body.location_id)
    rows = query.with_for_update().all()
    if any(r.status == "CLOSED" for r in rows):
        raise HTTPException(400, "This voyage/trip is CLOSED. Reopen it before creating or changing a ticket.")
    if create and not rows:
        db.add(OperationVoyage(reference=body.convoy_number, operation_type_code=body.operation_type_code,
            asset_id=body.asset_id, location_id=body.location_id))


def _validate(db, user, body, *, existing=None):
    try:
        definition = resolve_entry_definition(body.operation_type_code, body.payload_code)
    except ValueError as e:
        raise HTTPException(400, str(e))
    body.operation_type_code = definition["operation_type_code"]
    body.payload_code = definition["payload_field_code"]
    body.convoy_number = str(body.convoy_number or "").strip() or None
    ensure_location(db, user, body.location_id)
    _location(db, body.location_id)
    asset = scoped_asset(db, user, body.asset_id, location_id=body.location_id, active=True, linked_ticket_id=body.linked_ticket_id)
    if asset.asset_type_code != get_operation_type(body.operation_type_code)["asset_type_code"]:
        raise HTTPException(400, "Operation Type does not accept this asset type")
    operation = db.get(Operation, body.operation_id)
    if not operation or operation.status != "Active" or operation.location_id != body.location_id or operation.operation_type_code != body.operation_type_code:
        raise HTTPException(400, "Select an Active Operation Master record for this origin and operation type")
    for location_id in (body.destination_location_id, body.sender_location_id, body.receiver_location_id):
        if location_id: _location(db, location_id)
    linked = None
    if body.linked_ticket_id:
        linked = get_entry(db, user, body.linked_ticket_id, party=True)
        if linked.status != "Approved" or linked.linked_ticket_id:
            raise HTTPException(400, "A receiving ticket must link directly to an Approved sender ticket")
        if linked.operation_type_code not in ("BARGE_OPERATIONS", "TANKER_OPERATIONS"):
            raise HTTPException(400, "This ticket is not a barge/tanker sender reference")
        target = linked.receiver_location_id or linked.destination_location_id
        if not target or body.location_id != target:
            raise HTTPException(403, "Receiving ticket origin must be the sender's receiving terminal")
        if body.asset_id != linked.asset_id or body.operation_type_code != linked.operation_type_code:
            raise HTTPException(400, "Receiving ticket asset and operation type must match the sender")
        if operation.operation_category != "RECEIPT":
            raise HTTPException(400, "A linked receiving ticket requires a RECEIPT operation")
        if body.convoy_number != linked.convoy_number or body.sender_location_id != linked.location_id or body.receiver_location_id != target or body.destination_location_id != target:
            raise HTTPException(400, "Linked route and convoy are locked to the sender ticket")
        duplicate = db.query(OperationEntry).filter_by(receiver_link_key=linked.id).first()
        if duplicate and (not existing or duplicate.id != existing.id):
            raise HTTPException(409, "This sender already has a non-cancelled receiving ticket")
    elif body.sender_location_id:
        ensure_location(db, user, body.sender_location_id)
    if not existing:
        require_capability(db, user, "receiving_tickets:create" if linked and not _can(db, user, "operation_entries:create") else "operation_entries:create")
    if definition.get("requires_convoy_number") and not str(body.convoy_number or "").strip():
        raise HTTPException(400, f"{definition['convoy_label']} is required")
    for field in ("operation_start_datetime", "operation_end_datetime"):
        value = getattr(body, field)
        if value and value.tzinfo:
            setattr(body, field, value.astimezone(timezone.utc).replace(tzinfo=None))
    if body.operation_start_datetime and body.operation_end_datetime and body.operation_end_datetime < body.operation_start_datetime:
        raise HTTPException(400, "End Date/Time cannot be earlier than Start Date/Time")
    if body.payload_code == "shuttle_payload":
        duplicates = db.query(OperationEntry.id).filter(func.lower(OperationEntry.convoy_number) == str(body.convoy_number).strip().lower())
        if existing: duplicates = duplicates.filter(OperationEntry.id != existing.id)
        if duplicates.first():
            raise HTTPException(400, "Shuttle Number must be unique and cannot be repeated across tickets")
    from app.services.operation_entry_service import validate_payload_shape
    try: validate_payload_shape(body.payload, body.payload_code)
    except ValueError as e: raise HTTPException(400, str(e))
    p = _canonical_operation_payload(body.payload, operation, body.payload_code)
    inputs = p.setdefault("inputs", {})
    if body.payload_code == "tanker_payload":
        link = db.query(PrimeMoverTankerLink).filter_by(tanker_asset_id=asset.id, status="Active").first()
        pm = link.prime_mover_asset if link else None
        inputs.update(convoyNumber=body.convoy_number or "", cargo=body.product_name or "", tankerName=asset.asset_name,
            chassisNumber=asset.serial_number or "", primeMoverNumber=pm.asset_code if pm else inputs.get("primeMoverNumber", ""))
        p["prime_mover_asset"] = {"asset_code": pm.asset_code, "asset_name": pm.asset_name, "asset_type_code": pm.asset_type_code} if pm else None
    if body.payload_code == "multi_tank_payload":
        _validate_seals(p, asset, db, existing=existing)
    if body.payload_code == "vessel_cycle" and inputs.get("counterparty_asset_code"):
        counterparty = db.query(Asset).filter_by(asset_code=inputs["counterparty_asset_code"]).first()
        if not counterparty: raise HTTPException(400, "Counterparty asset not found")
        scoped_asset(db, user, counterparty.id, active=True)
    if body.payload_code == "fso_payload":
        shuttle_no = str(inputs.get("shuttle_number") or "").strip()
        if operation.operation_sign == "IN" and not shuttle_no:
            raise HTTPException(400, "Shuttle Number is required for an FSO receipt")
        body.convoy_number = shuttle_no or body.convoy_number
        if (p.get("meta") or {}).get("source_shuttle_discharge_bbl") is not None:
            ref = _closed_shuttle(db, user, shuttle_no)
            p["meta"]["source_shuttle_discharge_bbl"] = ref["netDischargeBbl"]
    _voyage_guard(db, body)
    check_policy(db, user, "EDIT_ENTRY" if existing else "CREATE_ENTRY", operation_type_code=body.operation_type_code,
        asset_type_code=asset.asset_type_code, location_id=body.location_id, payload_code=body.payload_code)
    result = calculate_payload(db, operation_type_code=body.operation_type_code, asset=asset, payload=p,
        location_id=body.location_id, payload_code=body.payload_code)
    if result["validation"]["errors"]:
        raise HTTPException(400, {"message": "Correct the entry validation errors", "errors": result["validation"]["errors"]})
    if body.payload_code == "fso_payload" and (p.get("meta") or {}).get("source_shuttle_discharge_bbl") is not None:
        result["source_voyage_id"] = ref["id"]
    return asset, operation, p, result


def _can(db, user, name):
    from app.dependencies.permissions import user_has_permission
    return user_has_permission(db, user, name)


def _save_header(entry, body, asset, operation):
    for field in ("operation_type_code", "payload_code", "operation_id", "asset_id", "location_id", "destination_location_id", "sender_location_id",
        "receiver_location_id", "linked_ticket_id", "barge_event_type", "convoy_number", "operation_date", "operation_start_datetime", "operation_end_datetime", "product_name", "remarks"):
        setattr(entry, field, getattr(body, field))
    entry.asset = asset
    entry.asset_type_code = asset.asset_type_code
    entry.asset_code_snapshot, entry.asset_name_snapshot = asset.asset_code, asset.asset_name
    for key in ("code", "label", "category", "sign"):
        setattr(entry, "operation_" + key + "_snapshot", getattr(operation, "operation_" + key))
    entry.receiver_link_key = body.linked_ticket_id


def _history(db, row, user, action, old_status=None, remarks=None):
    db.add(OperationEntryStatusHistory(entry_id=row.id, from_status=old_status, to_status=row.status,
        action=action, actor_user_id=user.id, remarks=remarks))


@router.get("/options")
def options(user=Depends(entry_read)):
    return {"entry_definitions": [{**d, "alternatives": [m for m in MANUAL_LAYOUTS.values() if m["operation_type_code"] == d["operation_type_code"]]} for d in entry_definition_catalog()]}


@router.get("/lookups/{kind}")
def lookups(kind: Literal["locations", "all-locations", "assets", "operations"], search: str = Query("", max_length=150),
            location_id: int | None = None, location_code: str | None = None, asset_code: str | None = None, operation_type_code: str | None = None, asset_type_code: str | None = None,
            id: int | None = None, page: int = 1, page_size: int = 20, db=Depends(get_db), user=Depends(require_any_permission("operation_entries:read", "operation_references:read", "operation_policies:read", "operation_transactions:read", "barge_tracking:read", "tanker_tracking:read", "shuttle_tracking:read", "fso_tracking:read", "tanker_transaction_reports:read"))):
    allowed = get_user_location_ids(db, user)
    if location_code:
        loc = db.query(Location).filter_by(location_code=location_code).first()
        location_id = loc.id if loc else -1
    if kind == "operations" and asset_type_code:
        from app.utils.operation_types import operation_type_catalog
        operation_type_code = next((t["code"] for t in operation_type_catalog() if t["asset_type_code"] == asset_type_code), "UNKNOWN")
    if kind in ("locations", "all-locations"):
        q = db.query(Location).filter_by(status="Active")
        if kind == "locations" and allowed is not None: q = q.filter(Location.id.in_(allowed))
        if search: q = q.filter(or_(Location.location_name.ilike(f"%{search}%"), Location.location_code.ilike(f"%{search}%")))
        if id: q = q.filter(Location.id == id)
        result = paginate_query(q.order_by(Location.location_code), page, page_size)
        result["items"] = [{"id": x.id, "location_code": x.location_code, "location_name": x.location_name} for x in result["items"]]
    elif kind == "assets":
        q = db.query(Asset).filter_by(status="Active")
        if allowed is not None: q = q.filter(or_(Asset.asset_scope == "Global", Asset.location_id.in_(allowed)))
        if location_id: q = q.filter(or_(Asset.asset_scope == "Global", Asset.location_id == location_id))
        if asset_type_code: q = q.filter(Asset.asset_type_code == asset_type_code)
        if asset_code: q = q.filter(Asset.asset_code == asset_code)
        if search: q = q.filter(or_(Asset.asset_name.ilike(f"%{search}%"), Asset.asset_code.ilike(f"%{search}%")))
        if id: q = q.filter(Asset.id == id)
        result = paginate_query(q.order_by(Asset.asset_code), page, page_size)
        result["items"] = [{"id": x.id, "asset_code": x.asset_code, "asset_name": x.asset_name, "asset_type_code": x.asset_type_code,
            "asset_scope": x.asset_scope, "location_id": x.location_id, "serial_number": x.serial_number, "status": x.status,
            "tanks": [{"id": t.id, "tank_name": t.tank_name} for t in x.tanks]} for x in result["items"]]
    else:
        q = db.query(Operation).filter_by(status="Active")
        if allowed is not None: q = q.filter(Operation.location_id.in_(allowed))
        if location_id: q = q.filter(Operation.location_id == location_id)
        if operation_type_code: q = q.filter(Operation.operation_type_code == operation_type_code)
        if search: q = q.filter(or_(Operation.operation_code.ilike(f"%{search}%"), Operation.operation_label.ilike(f"%{search}%")))
        if id: q = q.filter(Operation.id == id)
        result = paginate_query(q.order_by(Operation.sort_order, Operation.id), page, page_size)
        result["items"] = [{"id": x.id, "operation_code": x.operation_code, "operation_label": x.operation_label,
            "operation_category": x.operation_category, "operation_sign": x.operation_sign, "operation_type_code": x.operation_type_code,
            "location_id": x.location_id} for x in result["items"]]
    return result


@router.get("/asset-context/{asset_id}")
def asset_context(asset_id: int, linked_ticket_id: int | None = None, db=Depends(get_db), user=Depends(entry_read)):
    asset = scoped_asset(db, user, asset_id, linked_ticket_id=linked_ticket_id)
    context = resolve_calibration_context(db, asset)
    table = context["table"]
    chart = None
    # A chart is a single bounded calculation document, not an unbounded master list.
    if table:
        if sum(len(points) for points in context["curves"].values()) > 50000:
            raise HTTPException(400, "Chart exceeds the 50,000-point entry limit")
        chart = {"id": table.id, "assetCode": asset.asset_code, "templateId": 1, "templateName": "Fixed tank / dip-ullage / volume",
            "calibrationName": table.chart_name, "effectiveDate": table.effective_date, "measurementBasis": table.measurement_basis,
            "status": "Active", "rowsLoaded": True,
            "rows": [{"rowData": {"tank_name": name, "dip_cm": dip, "volume_bbl": volume}} for name, points in context["curves"].items() for dip, volume in points]}
    link = db.query(PrimeMoverTankerLink).filter_by(tanker_asset_id=asset.id, status="Active").first()
    link_row = None
    if link:
        # Do not leak a locally-scoped prime mover in an unrelated location.
        pm = link.prime_mover_asset
        allowed = get_user_location_ids(db, user)
        if linked_ticket_id or allowed is None or pm.asset_scope == "Global" or pm.location_id in allowed:
            link_row = {"primeMoverAssetCode": pm.asset_code, "primeMoverAssetName": pm.asset_name, "primeMoverAssetTypeCode": pm.asset_type_code,
                "tankerAssetCode": asset.asset_code, "tankerAssetName": asset.asset_name, "tankerAssetTypeCode": asset.asset_type_code,
                "tankerChassisNumber": asset.serial_number}
    seals = [{"tankId": s.tank.tank_name, "sealPosition": s.seal_position, "sealNumber": s.seal_number}
        for s in db.query(BargeSealMaster).filter_by(asset_id=asset.id, status="Active").limit(800)]
    return {"chart": chart, "link": link_row, "tank_names": context["tank_names"], "seals": seals,
        "asset": {"id": asset.id, "asset_code": asset.asset_code, "asset_name": asset.asset_name, "asset_type_code": asset.asset_type_code,
                  "asset_scope": asset.asset_scope, "serial_number": asset.serial_number, "location_id": asset.location_id, "status": asset.status,
                  "tanks": [{"id": t.id, "tank_name": t.tank_name} for t in asset.tanks]}}


@router.get("/table11")
def table11(api60: float, db=Depends(get_db), user=Depends(entry_read)):
    try: return lookup_table11_factor(api60, db)
    except ValueError as e: raise HTTPException(400, str(e))


@router.post("/calculate")
def calculate(body: OperationEntryCalculateRequest, request: Request, db=Depends(get_db), user=Depends(entry_read)):
    ensure_location(db, user, body.location_id)
    asset = scoped_asset(db, user, body.asset_id, location_id=body.location_id, active=True, linked_ticket_id=body.linked_ticket_id)
    if (get_operation_type(body.operation_type_code) or {}).get("asset_type_code") != asset.asset_type_code:
        raise HTTPException(400, "Operation Type does not accept this asset type")
    try:
        result = calculate_payload(db, operation_type_code=body.operation_type_code, payload_code=body.payload_code,
            asset=asset, location_id=body.location_id, payload=body.payload)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    _audit(db, request, user, "Calculate", category="Calculation", details_summary=f"Live validation for asset {asset.asset_code}; {len(result['validation']['errors'])} errors")
    db.commit()
    return result


def _filtered(db, user, search="", status=None, operation_type_code=None, location_id=None, asset_id=None, date_from=None, date_to=None, product_name=None, created_by_user_id=None):
    q = scoped_entries(db, user, party=True)
    if status: q = q.filter(OperationEntry.status.in_(status.split(",")))
    if operation_type_code: q = q.filter(OperationEntry.operation_type_code == operation_type_code)
    if location_id: q = q.filter(OperationEntry.location_id == location_id)
    if asset_id: q = q.filter(OperationEntry.asset_id == asset_id)
    if created_by_user_id: q = q.filter(OperationEntry.created_by_user_id == created_by_user_id)
    if product_name: q = q.filter(OperationEntry.product_name.ilike(f"%{product_name}%"))
    if date_from: q = q.filter(OperationEntry.operation_date >= date_from)
    if date_to: q = q.filter(OperationEntry.operation_date <= date_to)
    if search:
        q = q.filter(or_(*(col.ilike(f"%{search}%") for col in (OperationEntry.ticket_number, OperationEntry.convoy_number,
            OperationEntry.asset_code_snapshot, OperationEntry.asset_name_snapshot, OperationEntry.product_name))))
    return q.order_by(OperationEntry.operation_date.desc(), OperationEntry.id.desc())


def entry_filters(search: str = Query("", max_length=200), status: str | None = None, operation_type_code: str | None = None,
                  location_id: int | None = None, asset_id: int | None = None, product_name: str | None = None,
                  created_by_user_id: int | None = None, date_from: date | None = None, date_to: date | None = None):
    if date_from and date_to and date_to < date_from: raise HTTPException(400, "Date To must not precede Date From")
    return locals()


@router.get("")
def list_entries(filters=Depends(entry_filters), page: int = 1, page_size: int = 20, db=Depends(get_db), user=Depends(entry_read)):
    result = paginate_query(_filtered(db, user, **filters), page, page_size)
    result["items"] = [operation_entry_to_dict(e, include_payload=False) for e in result["items"]]
    return result


@router.get("/export")
def export_entries(request: Request, format: Literal["csv", "xlsx", "pdf"] = "csv", filters=Depends(entry_filters), db=Depends(get_db), user=Depends(entry_read)):
    q = _filtered(db, user, **filters)
    if q.count() > MAX_EXPORT_ROWS:
        raise HTTPException(400, "Narrow the filters before exporting this many tickets")
    entries = q.all()
    headers = ["Ticket", "Status", "Operation Type", "Layout", "Asset", "Origin", "Date", "Convoy", "Product", "Created By"]
    rows = [[e.ticket_number, e.status, get_operation_type(e.operation_type_code)["name"], resolve_entry_definition(e.operation_type_code, e.payload_code)["entry_layout_type"],
        e.asset_code_snapshot, e.location.location_code, e.operation_date, e.convoy_number, e.product_name, e.created_by.username if e.created_by else ""] for e in entries]
    _audit(db, request, user, "Export", category="Export", details_summary=f"{len(rows)} tickets as {format}; " + "; ".join(f"{k}={v}" for k, v in filters.items() if v))
    db.commit()
    if format == "csv": return csv_response("operation-entries", headers, rows)
    if format == "xlsx": return xlsx_response("operation-entries", "Operation Entry", headers, rows)
    from app.services.operation_entry_exports import ticket_register_pdf
    return ticket_register_pdf(headers, rows, filters)


@router.post("", status_code=201)
def create_entry(body: OperationEntryCreate, request: Request, db=Depends(get_db), user=Depends(entry_write)):
    body.convoy_number = str(body.convoy_number or "").strip() or None
    asset, operation, payload, result = _validate(db, user, body)
    # Serial allocation is protected on PostgreSQL; uniqueness also catches races on SQLite.
    db.query(Asset).filter_by(id=asset.id).with_for_update().first()
    entry = OperationEntry(status="Draft", created_by_user_id=user.id, updated_by_user_id=user.id)
    _save_header(entry, body, asset, operation)
    entry.ticket_number = generate_ticket_number(db, _location(db, body.location_id).location_code, asset.asset_code, body.operation_date)
    db.add(entry)
    try:
        db.flush()
        persist_payload(db, entry, payload=payload, result=result)
        _voyage_guard(db, body, create=True)
        _history(db, entry, user, "Create")
        _audit(db, request, user, "Create", entry, new_status="Draft", details_summary=f"{entry.payload_code}; operation {operation.operation_code}; asset {asset.asset_code}")
        _commit(db, request)
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Ticket number or receiving link was allocated concurrently; reload and retry")
    db.refresh(entry)
    return operation_entry_to_dict(entry)


@router.put("/{entry_id}")
def update_entry(entry_id: int, body: OperationEntryUpdate, request: Request, db=Depends(get_db), user=Depends(require_permission("operation_entries:update"))):
    entry = get_entry(db, user, entry_id, lock=True)
    _version(entry, body.version)
    if entry.status not in EDITABLE_STATUSES:
        raise HTTPException(400, "Only Draft or Rejected tickets can be edited. Recall Submitted tickets first.")
    data = {key: getattr(entry, key) for key in OperationEntryCreate.model_fields if hasattr(entry, key)}
    data["payload"] = payload_from_entry(entry)
    data.update(body.model_dump(exclude_unset=True, exclude={"version"}))
    try: merged = OperationEntryCreate(**data)
    except ValueError as e: raise HTTPException(400, "Invalid ticket header: " + str(e))
    # An asset/route change cannot reuse measurements/calibration from the previous asset.
    if (merged.asset_id != entry.asset_id or merged.location_id != entry.location_id) and body.payload is None:
        raise HTTPException(400, "Changing asset/origin requires a complete new payload")
    asset, operation, payload, result = _validate(db, user, merged, existing=entry)
    _save_header(entry, merged, asset, operation)
    entry.updated_by_user_id, entry.updated_at = user.id, utcnow()
    entry.reviewed_at = entry.reviewed_by_user_id = None
    persist_payload(db, entry, payload=payload, result=result)
    _audit(db, request, user, "Update", entry, old_status=entry.status, new_status=entry.status,
        details_summary=f"Recalculated {entry.payload_code}; prior version {body.version}")
    _commit(db, request); db.refresh(entry)
    return operation_entry_to_dict(entry)


@router.get("/linked-sender/{entry_id}")
def linked_sender(entry_id: int, db=Depends(get_db), user=Depends(entry_read)):
    entry = get_entry(db, user, entry_id, party=True)
    if entry.status != "Approved": raise HTTPException(400, "Sender ticket must be Approved")
    return operation_entry_to_dict(entry)


def _closed_shuttle(db, user, number):
    voyages = db.query(OperationVoyage).filter_by(reference=number, operation_type_code="SHUTTLE_OPERATIONS", status="CLOSED").all()
    visible = []
    for v in voyages:
        q = scoped_entries(db, user, party=True).filter_by(convoy_number=v.reference, asset_id=v.asset_id, location_id=v.location_id, status="Approved")
        if q.first(): visible.append(v)
    if len(visible) != 1:
        raise HTTPException(404, "No unique CLOSED shuttle voyage found for this Shuttle Number")
    v = visible[0]
    tickets = db.query(OperationEntry).filter_by(convoy_number=v.reference, asset_id=v.asset_id, location_id=v.location_id, status="Approved").all()
    def unloading(e):
        code, label = e.operation_code_snapshot.upper(), e.operation_label_snapshot.upper()
        is_unload = code == "UNLOADING" or "UNLOAD" in label
        is_sts = code == "STS_OUT" or "STS OUT" in label or "STS_OUT" in label
        return is_unload and not is_sts
    # OTMS tracking_helpers.shuttle_movement_totals: do not net opposite-sign water
    # against product, and do not treat STS transfers as discharge to an FSO.
    qty = sum(abs(float(e.shuttle.net_stock_bbl or 0)) + abs(float(e.shuttle.net_water_bbl or 0))
        for e in tickets if e.shuttle and unloading(e))
    return {"id": v.id, "shuttleNumber": v.reference, "shuttleAssetName": v.asset.asset_name, "netDischargeBbl": qty}


@router.get("/closed-shuttle")
def closed_shuttle(shuttle_number: str, db=Depends(get_db), user=Depends(entry_read)):
    return {"rows": [_closed_shuttle(db, user, shuttle_number)]}


def _submit_seals(entry, remarks):
    if not entry.multi_tank: return
    temp = {s.position: s.observed_number for s in entry.multi_tank.seals if s.seal_group == "Temporary"}
    missing = [p for p in ("portManifoldSeal", "stbdManifoldSeal", "pumproomSeal") if not str(temp.get(p) or "").strip()]
    if missing: raise HTTPException(400, "Seal details are incomplete. Enter AFTER temporary seals: " + ", ".join(missing))
    mismatch = [s for s in entry.multi_tank.seals if s.seal_group == "Tank" and s.master_number and s.master_number != (s.observed_number or "")]
    if mismatch and not str(remarks or "").strip():
        raise HTTPException(400, f"Seal mismatch detected ({len(mismatch)}). Add remarks before submitting.")


def _posting(db, entry):
    p = payload_from_entry(entry)
    c = p.get("calculated") or {}
    if entry.payload_code in ("tank_gauging_payload", "tanker_payload"):
        quantity, water = c["nsvBbl"], c["freeWaterBbl"]
    elif entry.payload_code == "multi_tank_payload":
        quantity, water = abs(c["net"]["NSV"]), abs(c["net"]["FW"])
    elif entry.payload_code in ("shuttle_payload", "fso_payload"):
        quantity, water = abs(c["net"]["net_stock_bbl"]), abs(c["net"]["net_water_bbl"])
        if entry.operation_sign_snapshot == "SET":
            quantity, water = p["inputs"]["closing_stock_bbl"], p["inputs"]["closing_water_bbl"]
    elif entry.payload_code == "flowmeter_payload": quantity, water = c["nsv_bbl"], c["bsw_bbl"]
    else: quantity, water = c.get("net_nsv", c.get("nsv_bbl", 0)), c.get("net_water", 0)
    db.add(OperationPosting(entry_id=entry.id, asset_id=entry.asset_id, location_id=entry.location_id,
        operation_date=entry.operation_date, operation_category=entry.operation_category_snapshot, operation_sign=entry.operation_sign_snapshot,
        quantity_bbl=quantity, water_bbl=water, event_type=entry.barge_event_type))


@router.post("/{entry_id}/{action}")
def transition(entry_id: int, action: Literal["submit", "recall", "reject", "approve", "cancel"], body: OperationEntryStatusChange,
               request: Request, db=Depends(get_db), user=Depends(ticket_read)):
    capability, target, sources = {
        "submit": ("operation_submissions:create", "Submitted", EDITABLE_STATUSES),
        "recall": ("operation_submissions:delete", "Draft", ("Submitted",)),
        "reject": ("operation_approvals:update", "Rejected", ("Submitted",)),
        "approve": ("operation_approvals:create", "Approved", ("Submitted",)),
        "cancel": ("operation_entries:delete", "Cancelled", EDITABLE_STATUSES),
    }[action]
    require_capability(db, user, capability)
    entry = get_entry(db, user, entry_id, lock=True)
    _version(entry, body.version)
    if entry.status not in sources:
        raise HTTPException(400, f"Cannot {action} a {entry.status} ticket")
    _voyage_guard(db, entry)
    check_entry_policy(db, user, action.upper(), entry)
    if action in ("submit", "approve"):
        if not body.review_confirmed: raise HTTPException(400, "Review confirmation is required for Submit/Approve")
        require_capability(db, user, "operation_reviews:create")
        check_entry_policy(db, user, "REVIEW", entry)
        entry.reviewed_at, entry.reviewed_by_user_id = utcnow(), user.id
    if action == "submit": _submit_seals(entry, body.remarks)
    if action == "reject" and not str(body.remarks or "").strip(): raise HTTPException(400, "Rejection remarks are required")
    previous = entry.status
    entry.status, entry.status_remarks = target, body.remarks
    entry.updated_by_user_id, entry.updated_at = user.id, utcnow()
    if action == "submit": entry.submitted_by_user_id, entry.submitted_at = user.id, utcnow()
    if action == "approve":
        entry.approved_by_user_id, entry.approved_at = user.id, utcnow()
        _posting(db, entry)
    if action == "cancel": entry.receiver_link_key = None
    _history(db, entry, user, action.title(), previous, body.remarks)
    _audit(db, request, user, action.title(), entry, old_status=previous, new_status=target, remarks=body.remarks,
        details_summary=f"Version {body.version}; review confirmed={body.review_confirmed}")
    _commit(db, request); db.refresh(entry)
    return operation_entry_to_dict(entry)


@router.get("/{entry_id}/export")
def export_ticket(entry_id: int, request: Request, format: Literal["csv", "xlsx", "pdf"] = "pdf", db=Depends(get_db), user=Depends(ticket_read)):
    entry = get_entry(db, user, entry_id, party=True)
    data = operation_entry_to_dict(entry)
    rows = []
    def flatten(value, path):
        if isinstance(value, dict):
            for key, item in value.items(): flatten(item, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, item in enumerate(value): flatten(item, f"{path}[{index}]")
        else: rows.append([path, value])
    flatten(data, "")
    _audit(db, request, user, "Export Ticket", entry, category="Export", details_summary=f"Saved snapshot version {entry.version} as {format}; {len(rows)} fields")
    db.commit()
    if format == "csv": return csv_response("operation-ticket", ["Field", "Value"], rows)
    if format == "xlsx": return xlsx_response("operation-ticket", entry.ticket_number, ["Field", "Value"], rows, [55, 45])
    from app.services.operation_entry_exports import ticket_snapshot_pdf
    return ticket_snapshot_pdf(entry.ticket_number, rows)


@router.get("/{entry_id}/history")
def history(entry_id: int, page: int = 1, page_size: int = 20, db=Depends(get_db), user=Depends(ticket_read)):
    get_entry(db, user, entry_id, party=True)
    result = paginate_query(db.query(OperationEntryStatusHistory).filter_by(entry_id=entry_id).order_by(OperationEntryStatusHistory.id.desc()), page, page_size)
    result["items"] = [operation_entry_status_history_to_dict(h) for h in result["items"]]
    return result


@router.get("/{entry_id}")
def detail(entry_id: int, db=Depends(get_db), user=Depends(ticket_read)):
    entry = get_entry(db, user, entry_id, party=True)
    result = operation_entry_to_dict(entry)
    recent = db.query(OperationEntryStatusHistory).filter_by(entry_id=entry_id).order_by(OperationEntryStatusHistory.id.desc()).limit(20).all()
    result["status_history"] = [operation_entry_status_history_to_dict(h) for h in reversed(recent)]
    result["status_history_total"] = db.query(OperationEntryStatusHistory).filter_by(entry_id=entry_id).count()
    return result
