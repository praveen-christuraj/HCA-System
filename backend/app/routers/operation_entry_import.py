"""Fixed column-wise CSV/XLSX entry imports. No JSON cells and no custom templates.

One file contains one fixed layout. Multi-tank rows group by ticket_key (one
row per declared tank); meter rows group by ticket_key (one row per config).
The entire file is validated before any Draft ticket is written.
"""
from collections import defaultdict
from datetime import datetime, time
from fastapi import APIRouter, Depends, File, Form, UploadFile, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.dependencies.permissions import require_permission
from app.models import OperationEntry, Asset
from app.schemas import OperationEntryCreate
from app.routers.operation_entries import _validate, _save_header, _history, _voyage_guard
from app.services.operation_entry_service import (TANK_INPUTS, TANKER_INPUTS, FLOW_INPUTS, STOCK_INPUTS, STAGE_INPUTS, generate_ticket_number, persist_payload)
from app.services.master_import import read_master_import, MAX_IMPORT_BYTES, normalise_header
from app.services.audit_service import create_audit_log
from app.utils.operation_entry_payloads import entry_definition_catalog, MANUAL_LAYOUTS
from app.utils.exporters import csv_response, xlsx_response

router = APIRouter(prefix="/operation-entry-import", tags=["Operation Entry Import"])
COMMON = ["ticket_key", "operation_id", "asset_id", "location_id", "destination_location_id", "sender_location_id", "receiver_location_id", "convoy_number", "operation_date", "operation_start_datetime", "operation_end_datetime", "product_name", "remarks", "barge_event_type"]


def layout_fields(code):
    if code == "tank_gauging_payload": return list(TANK_INPUTS)
    if code == "tanker_payload": return list(TANKER_INPUTS)
    if code == "shuttle_payload": return STOCK_INPUTS + ["barge_reference"]
    if code == "fso_payload": return STOCK_INPUTS + ["shuttle_number", "vessel_name", "vessel_quantity_bbl"]
    if code == "flowmeter_payload": return FLOW_INPUTS
    if code in MANUAL_LAYOUTS: return [k for k in MANUAL_LAYOUTS[code]["fields"] if not k.startswith("net_") and k != "nsv_bbl"]
    if code == "multi_tank_payload": return []
    raise HTTPException(400, "Unknown fixed layout")


def headers_for(code):
    headers = COMMON + ["input_" + k for k in layout_fields(code)]
    if code == "multi_tank_payload":
        headers += [f"{stage}_{k}" for stage in ("before", "after") for k in list(STAGE_INPUTS) + ["total", "water"]]
        headers += ["tank_name", "seal_MH1", "seal_MH2", "seal_LOCK", "seal_DIPHATCH", "portManifoldSeal", "stbdManifoldSeal", "pumproomSeal", "otherSeal", "otherRemarks"]
    if code == "flowmeter_payload": headers += ["config_id", "opening_reading", "closing_reading"]
    return headers


def _definition(code):
    return next((d for d in entry_definition_catalog() if d["payload_field_code"] == code), MANUAL_LAYOUTS.get(code))


@router.get("/template")
def template(payload_code: str, format: str = "csv", user=Depends(require_permission("operation_entries:create"))):
    headers = headers_for(payload_code)
    if format == "xlsx": return xlsx_response(payload_code, "Entry Import", headers, [])
    if format == "metadata": return {"headers": headers, "group_key": "ticket_key"}
    if format != "csv": raise HTTPException(400, "Use csv, xlsx or metadata")
    return csv_response(payload_code, headers, [])


def _body(code, group):
    definition = _definition(code)
    if not definition: raise HTTPException(400, "Unknown fixed layout")
    group = [dict(row) for row in group]
    for row in group:
        for key, value in row.items():
            if not isinstance(value, str) or not value: continue
            if key.endswith("date"):
                try: row[key] = datetime.fromisoformat(value).date().isoformat()
                except ValueError: pass  # Normal validators provide the row-specific error.
            if key.endswith("time") and not key.endswith("datetime"):
                try:
                    parsed_time = time.fromisoformat(value)
                    if not parsed_time.second and not parsed_time.microsecond: row[key] = parsed_time.strftime("%H:%M")
                except ValueError: pass
    first = group[0]
    data = {k: first[k] for k in COMMON if k != "ticket_key" and first.get(k)}
    data.update(operation_type_code=definition["operation_type_code"], payload_code=code)
    row_specific = {"tank_name", "before_total", "before_water", "after_total", "after_water", "config_id", "opening_reading", "closing_reading"}
    row_specific |= {"seal_" + pos.lower() for pos in ("MH1", "MH2", "LOCK", "DIPHATCH")}
    shared = {normalise_header(h) for h in headers_for(code)} - row_specific
    for row in group[1:]:
        for k in shared:
            if row.get(k) and row[k] != first.get(k): raise ValueError(f"Repeated header/parameter '{k}' disagrees within ticket_key")
    inputs = {k: first.get(normalise_header("input_" + k)) or None for k in layout_fields(code)}
    payload = {"inputs": inputs}
    if code == "multi_tank_payload":
        tanks = [r.get("tank_name") for r in group]
        if len(tanks) != len(set(tanks)): raise ValueError("Duplicate tank row within ticket_key")
        inputs.update({stage: {**{k: first.get(normalise_header(f"{stage}_{k}")) or None for k in STAGE_INPUTS},
            "dips": {r["tank_name"]: {"total": r.get(stage + "_total"), "water": r.get(stage + "_water")} for r in group}} for stage in ("before", "after")})
        payload["meta"] = {"tankIds": tanks}
        payload["seals"] = {"after": {"tankSeals": {r["tank_name"]: {pos: {"observed": r.get("seal_" + pos.lower(), ""), "master": ""} for pos in ("MH1", "MH2", "LOCK", "DIPHATCH")} for r in group},
            "temporary": {k: first.get(k.lower(), "") for k in ("portManifoldSeal", "stbdManifoldSeal", "pumproomSeal", "otherSeal", "otherRemarks")}}}
    elif code == "flowmeter_payload":
        inputs["meters"] = [{"config_id": int(r.get("config_id") or 0), "opening_reading": r.get("opening_reading"), "closing_reading": r.get("closing_reading"), "meter_label": "Configured meter"} for r in group]
    elif len(group) != 1: raise ValueError("This layout requires one row per ticket_key")
    data["payload"] = payload
    return OperationEntryCreate(**data)


@router.post("")
async def import_entries(request: Request, file: UploadFile = File(...), confirm: bool = Form(False), payload_code: str = Form(...),
                         db=Depends(get_db), user=Depends(require_permission("operation_entries:create"))):
    headers_for(payload_code)
    try: parsed = read_master_import(await file.read(MAX_IMPORT_BYTES + 1), file.filename)
    except ValueError as e: raise HTTPException(400, str(e))
    allowed = {normalise_header(k) for k in headers_for(payload_code)}
    if set(parsed["columns"]) - allowed: raise HTTPException(400, "Unknown import columns. Download the fixed layout template.")
    groups = defaultdict(list)
    for r in parsed["rows"]: groups[r.get("ticket_key") or f"row-{r['row_number']}"] .append(r)
    preview, ready, shuttle_numbers = [], [], set()
    for key, group in groups.items():
        error = None
        try:
            body = _body(payload_code, group)
            asset, operation, payload, result = _validate(db, user, body)
            if payload_code == "shuttle_payload":
                folded = body.convoy_number.strip().casefold()
                if folded in shuttle_numbers: raise ValueError("Duplicate Shuttle Number in file")
                shuttle_numbers.add(folded)
            ready.append((body, asset, operation, payload, result))
        except (HTTPException, ValueError, KeyError, TypeError) as e:
            error = str(getattr(e, "detail", e))
        for r in group: preview.append({"row_number": r["row_number"], "ticket_key": key, "asset_id": r.get("asset_id"), "operation_date": r.get("operation_date"), "valid": error is None, "errors": [error] if error else []})
    result = {"rows": preview, "valid_rows": sum(r["valid"] for r in preview), "invalid_rows": sum(not r["valid"] for r in preview), "total_rows": len(preview), "ticket_count": len(groups), "imported": 0}
    if confirm and not result["invalid_rows"]:
        try:
            for body, asset, operation, payload, calc in ready:
                db.query(Asset).filter_by(id=asset.id).with_for_update().first()
                entry = OperationEntry(status="Draft", created_by_user_id=user.id, updated_by_user_id=user.id)
                _save_header(entry, body, asset, operation)
                entry.ticket_number = generate_ticket_number(db, operation.location.location_code, asset.asset_code, body.operation_date)
                db.add(entry); db.flush()
                persist_payload(db, entry, payload=payload, result=calc)
                _voyage_guard(db, body, create=True)
                _history(db, entry, user, "Import")
                create_audit_log(db, "Operation Entry", "Import Ticket", current_user=user, request=request, entity_type="OperationEntry", entity_id=entry.id, entity_label=entry.ticket_number, new_status="Draft")
            result["imported"] = len(ready)
        except IntegrityError:
            db.rollback(); raise HTTPException(409, "A concurrent write conflicted with this import. No tickets were imported.")
    create_audit_log(db, "Operation Entry", "Import" if confirm else "Import Preview", current_user=user, request=request,
        details_summary=f"{file.filename}; {payload_code}; valid rows {result['valid_rows']}; invalid rows {result['invalid_rows']}; tickets imported {result['imported']}")
    try: db.commit()
    except IntegrityError:
        db.rollback(); request.state.audit_written = False
        raise HTTPException(409, "A concurrent write conflicted with this import. No tickets were imported.")
    return JSONResponse(status_code=400, content=result) if confirm and result["invalid_rows"] else result
