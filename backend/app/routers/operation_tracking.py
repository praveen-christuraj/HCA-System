"""Operation Tracking API: OTMS Operation Transaction Register, Barge / Tanker /
Shuttle / FSO Tracking and the Tanker Transaction Report.

Tracking views are computed on read from Approved tickets (see
``app.services.operation_tracking``). Persisted tracking facts are receipt
acknowledgements, barge timeline corrections and voyage open/closed status
(``OperationVoyage``, shared with Voyage Controls). Every mutation and export is
audited. Ticket status actions stay on ``/operation-entries/{id}/{action}`` with
their existing capabilities; the register only adds a read surface.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import distinct, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import get_user_location_ids, require_any_permission, require_permission, user_has_permission
from app.models import (BargeTimelineEvent, Location, OperationEntry, OperationVoyage, TankerReceiptAcknowledgement)
from app.routers.operation_entries import _filtered, entry_filters
from app.services import operation_tracking as ot
from app.services.audit_service import create_audit_log
from app.services.operation_entry_access import ensure_location, get_entry, require_capability, scoped_entries
from app.services.operation_entry_exports import table_pdf
from app.services.operation_entry_service import operation_entry_to_dict
from app.utils.exporters import csv_response, xlsx_response
from app.utils.operation_entry_payloads import resolve_entry_definition
from app.utils.operation_types import get_operation_type
from app.utils.pagination import clamp_page, clamp_page_size, paginate_query, pagination_payload
from app.utils.time import utcnow

router = APIRouter(prefix="/operation-tracking", tags=["Operation Tracking"])

BARGE, TANKER, SHUTTLE, FSO = "BARGE_OPERATIONS", "TANKER_OPERATIONS", "SHUTTLE_OPERATIONS", "FSO_OPERATIONS"
TX_STATUSES = ("Draft", "Submitted", "Approved", "Rejected", "Cancelled")
Format = Literal["csv", "xlsx", "pdf"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class RemarksBody(StrictModel):
    remarks: str = Field(min_length=3, max_length=2000)


class ConvoyAction(RemarksBody):
    convoy_number: str = Field(min_length=1, max_length=50)


class BargeReceipt(StrictModel):
    convoy_number: str = Field(min_length=1, max_length=50)
    asset_id: int = Field(ge=1)
    remarks: str | None = Field(default=None, max_length=2000)


class BargeTimelineFix(StrictModel):
    convoy_number: str = Field(min_length=1, max_length=50)
    entry_id: int = Field(ge=1)
    event_type: Literal["LOAD_1", "LOAD_2_TOPUP", "UNLOAD", "STS"]
    remarks: str = Field(min_length=3, max_length=2000)


class TankerAcknowledge(StrictModel):
    sender_entry_id: int = Field(ge=1)
    receiver_location_id: int = Field(ge=1)
    remarks: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _commit(db, request):
    try:
        db.commit()
    except (IntegrityError, StaleDataError):
        db.rollback()
        request.state.audit_written = False
        raise HTTPException(409, "This tracking record changed concurrently. Reload and try again; nothing was overwritten.")


def _audit(db, request, user, module, action, entity_type, entity_id=None, label=None, **kw):
    create_audit_log(db, module, action, current_user=user, request=request, entity_type=entity_type,
                     entity_id=entity_id, entity_label=label, **kw)


def _need(db, user, *capabilities):
    """Require at least one of ``capabilities`` (all-of when chained)."""
    if not any(user_has_permission(db, user, c) for c in capabilities):
        raise HTTPException(403, "Permission required: " + " or ".join(capabilities))


def _date_range(date_from, date_to):
    if date_from and date_to and date_to < date_from:
        raise HTTPException(400, "Date To must not precede Date From")


def _export(fmt, name, title, headers, rows, filters=""):
    if fmt == "csv":
        return csv_response(name, headers, rows)
    if fmt == "xlsx":
        return xlsx_response(name, title, headers, rows)
    return table_pdf(title, name, headers, rows, filters)


def _filter_text(values: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in values.items() if v not in (None, "", [])) or "All accessible records"


def _location_code(db, location_id):
    loc = db.get(Location, location_id) if location_id else None
    return loc.location_code if loc else ""


def _user_name(user):
    return user.username if user else ""


# ---------------------------------------------------------------------------
# Operation Transaction Register
# ---------------------------------------------------------------------------


@router.get("/transactions")
def transactions(filters=Depends(entry_filters), page: int = 1, page_size: int = 20, db=Depends(get_db),
                 user=Depends(require_permission("operation_transactions:read"))):
    counts_query = _filtered(db, user, **{**filters, "status": None}).order_by(None)
    counts = dict(counts_query.with_entities(OperationEntry.status, func.count(OperationEntry.id)).group_by(OperationEntry.status).all())
    result = paginate_query(_filtered(db, user, **filters), page, page_size)
    result["items"] = [operation_entry_to_dict(e, include_payload=False) for e in result["items"]]
    result["status_counts"] = {"All": sum(counts.values()), **{s: counts.get(s, 0) for s in TX_STATUSES}}
    return result


@router.get("/transactions/export")
def export_transactions(request: Request, format: Format = "csv", filters=Depends(entry_filters), db=Depends(get_db),
                        user=Depends(require_permission("operation_transactions:read"))):
    q = _filtered(db, user, **filters)
    if q.count() > MAX_EXPORT_ROWS:
        raise HTTPException(400, "Narrow the filters before exporting this many tickets")
    headers = ["Ticket", "Status", "Operation Date", "Operation Type", "Layout", "Operation", "Location", "Primary Asset",
               "Convoy / Voyage", "Product", "Created By", "Submitted At", "Approved At", "Status Remarks"]
    rows = [[e.ticket_number, e.status, e.operation_date, get_operation_type(e.operation_type_code)["name"],
             resolve_entry_definition(e.operation_type_code, e.payload_code)["entry_layout_type"], e.operation_label_snapshot,
             e.location.location_code, f"{e.asset_name_snapshot} ({e.asset_code_snapshot})", e.convoy_number, e.product_name,
             _user_name(e.created_by), e.submitted_at, e.approved_at, e.status_remarks] for e in q.all()]
    _audit(db, request, user, "Operation Transaction Register", "Export", "OperationEntry", category="Export",
           details_summary=f"{len(rows)} tickets as {format}; {_filter_text(filters)}")
    db.commit()
    return _export(format, "operation-transactions", "Operation Transaction Register", headers, rows, _filter_text(filters))


# ---------------------------------------------------------------------------
# Barge Tracking
# ---------------------------------------------------------------------------


def _closed_refs(type_code):
    return select(OperationVoyage.reference).where(OperationVoyage.operation_type_code == type_code, OperationVoyage.status == "CLOSED")


def _barge_groups(db, user, tab, search="", location_id=None, date_from=None, date_to=None):
    _date_range(date_from, date_to)
    base = scoped_entries(db, user, party=True).filter(OperationEntry.operation_type_code == BARGE,
        OperationEntry.status == ot.APPROVED, OperationEntry.convoy_number.isnot(None))
    if search:
        like = f"%{search}%"
        base = base.filter(or_(OperationEntry.convoy_number.ilike(like), OperationEntry.asset_code_snapshot.ilike(like),
                               OperationEntry.asset_name_snapshot.ilike(like), OperationEntry.ticket_number.ilike(like)))
    if location_id:
        base = base.filter(or_(OperationEntry.location_id == location_id, OperationEntry.destination_location_id == location_id,
                               OperationEntry.receiver_location_id == location_id))
    if date_from:
        base = base.filter(OperationEntry.operation_date >= date_from)
    if date_to:
        base = base.filter(OperationEntry.operation_date <= date_to)
    grouped = base.with_entities(OperationEntry.convoy_number.label("convoy"), func.count(OperationEntry.id).label("tickets"),
        func.count(distinct(OperationEntry.asset_id)).label("barges"), func.min(OperationEntry.operation_date).label("first_date"),
        func.max(OperationEntry.operation_date).label("last_date")).group_by(OperationEntry.convoy_number)
    closed = OperationEntry.convoy_number.in_(_closed_refs(BARGE))
    counts = {"OPEN": grouped.filter(~closed).count(), "CLOSED": grouped.filter(closed).count()}
    selected = grouped.filter(closed if tab == "CLOSED" else ~closed).order_by(func.max(OperationEntry.operation_date).desc(), OperationEntry.convoy_number)
    return selected, counts


def _barge_rows(db, user, groups):
    convoys = [g.convoy for g in groups]
    tickets = scoped_entries(db, user, party=True).filter(OperationEntry.operation_type_code == BARGE,
        OperationEntry.status == ot.APPROVED, OperationEntry.convoy_number.in_(convoys)).all() if convoys else []
    voyages = db.query(OperationVoyage).filter(OperationVoyage.operation_type_code == BARGE, OperationVoyage.reference.in_(convoys)).all() if convoys else []
    by_convoy, voyage_by = defaultdict(list), defaultdict(list)
    for t in tickets:
        by_convoy[t.convoy_number].append(t)
    for v in voyages:
        voyage_by[v.reference].append(v)
    rows = []
    for g in groups:
        items, vs = by_convoy[g.convoy], voyage_by[g.convoy]
        closed = next((v for v in vs if v.status == "CLOSED"), None)
        barges = {}
        for t in items:
            barges.setdefault(t.asset_id, {"asset_id": t.asset_id, "asset_code": t.asset_code_snapshot, "asset_name": t.asset_name_snapshot})
        rows.append({
            "convoy_number": g.convoy, "status": "CLOSED" if closed else "OPEN", "ticket_count": g.tickets, "barge_count": g.barges,
            "barges": list(barges.values()), "first_operation_date": g.first_date, "last_operation_date": g.last_date,
            "origin_location_codes": sorted({t.location.location_code for t in items if not ot.is_barge_receiver(t)}),
            "destination_location_codes": sorted({(t.receiver_location or t.destination_location).location_code for t in items
                                                  if not ot.is_barge_receiver(t) and (t.receiver_location or t.destination_location)}),
            "closed_at": closed.closed_at if closed else None, "closed_by": _user_name(closed.closed_by) if closed else "",
            "closure_remarks": (closed or (vs[0] if vs else None)).closure_remarks if (closed or vs) else None,
        })
    return rows


@router.get("/barge/voyages")
def barge_voyages(tab: Literal["OPEN", "CLOSED"] = "OPEN", search: str = Query("", max_length=150), location_id: int | None = None,
                  date_from: date | None = None, date_to: date | None = None, page: int = 1, page_size: int = 20,
                  db=Depends(get_db), user=Depends(require_permission("barge_tracking:read"))):
    selected, counts = _barge_groups(db, user, tab, search, location_id, date_from, date_to)
    page, page_size = clamp_page(page), clamp_page_size(page_size)
    total = selected.count()
    groups = selected.offset((page - 1) * page_size).limit(page_size).all()
    result = pagination_payload(_barge_rows(db, user, groups), total, page, page_size)
    result.update(tab=tab, open_count=counts["OPEN"], closed_count=counts["CLOSED"])
    return result


@router.get("/barge/voyages/export")
def export_barge_voyages(request: Request, format: Format = "csv", tab: Literal["OPEN", "CLOSED"] = "OPEN",
                         search: str = Query("", max_length=150), location_id: int | None = None, date_from: date | None = None,
                         date_to: date | None = None, db=Depends(get_db), user=Depends(require_permission("barge_tracking:read"))):
    selected, _ = _barge_groups(db, user, tab, search, location_id, date_from, date_to)
    if selected.count() > MAX_EXPORT_ROWS:
        raise HTTPException(400, "Narrow the filters before exporting this many voyages")
    rows = _barge_rows(db, user, selected.all())
    headers = ["Convoy", "Status", "Barges", "Tickets", "First Date", "Last Date", "Origins", "Destinations", "Closed At", "Closed By", "Remarks"]
    data = [[r["convoy_number"], r["status"], ", ".join(b["asset_code"] for b in r["barges"]), r["ticket_count"], r["first_operation_date"],
             r["last_operation_date"], ", ".join(r["origin_location_codes"]), ", ".join(r["destination_location_codes"]),
             r["closed_at"], r["closed_by"], r["closure_remarks"]] for r in rows]
    filters = _filter_text(dict(tab=tab, search=search, location_id=location_id, date_from=date_from, date_to=date_to))
    _audit(db, request, user, "Barge Tracking", "Export", "BargeVoyage", category="Export", details_summary=f"{len(data)} voyages as {format}; {filters}")
    db.commit()
    return _export(format, "barge-voyages", "Barge Tracking", headers, data, filters)


def _convoy_state(db, user, convoy, *, lock=False):
    convoy = str(convoy or "").strip()
    tickets = scoped_entries(db, user, party=True).filter(OperationEntry.operation_type_code == BARGE,
                                                          OperationEntry.convoy_number == convoy).all()
    approved = [t for t in tickets if t.status == ot.APPROVED]
    if not approved:
        raise HTTPException(404, "No Approved barge tickets found for this convoy in your locations")
    events_q = db.query(BargeTimelineEvent).filter(BargeTimelineEvent.convoy_number == convoy)
    voyages_q = db.query(OperationVoyage).filter(OperationVoyage.operation_type_code == BARGE, OperationVoyage.reference == convoy)
    if lock:
        voyages_q = voyages_q.with_for_update()
    stored, voyages = events_q.all(), voyages_q.all()
    overrides = {e.entry_id: e for e in stored if e.entry_id}
    manual = [e for e in stored if not e.entry_id]
    resolved = ot.resolve_barge_events(approved, overrides)
    open_tickets = db.query(OperationEntry.id).filter(OperationEntry.operation_type_code == BARGE, OperationEntry.convoy_number == convoy,
                                                       OperationEntry.status.in_(ot.OPEN_STATUSES)).count()
    approved_ids = [t.id for t in approved]
    live_receivers = {key for (key,) in db.query(OperationEntry.receiver_link_key).filter(OperationEntry.receiver_link_key.in_(approved_ids)).all()}
    closed = next((v for v in voyages if v.status == "CLOSED"), None)
    barges, by_asset = [], defaultdict(list)
    for t in sorted(approved, key=lambda e: (ot.entry_moment(e), e.id)):
        by_asset[t.asset_id].append(t)
    all_comparisons = []
    for asset_id, items in by_asset.items():
        timeline = []
        for t in items:
            kind, source = resolved[t.id]
            timeline.append({"kind": "TICKET", "event_type": kind, "source": source, "event_datetime": ot.entry_moment(t),
                             "location_code": t.location.location_code, "ticket_id": t.id, "ticket_number": t.ticket_number,
                             "ticket_status": t.status, "remarks": overrides[t.id].remarks if t.id in overrides else None})
        asset_manual = [e for e in manual if e.asset_id == asset_id]
        for e in asset_manual:
            timeline.append({"kind": "MANUAL", "event_type": e.event_type, "source": "RECORDED", "event_datetime": e.event_datetime,
                             "location_code": e.location.location_code if e.location else "", "ticket_id": None, "ticket_number": None,
                             "ticket_status": None, "remarks": e.remarks, "recorded_by": _user_name(e.created_by)})
        timeline.sort(key=lambda row: (row["event_datetime"], 0 if row["kind"] == "TICKET" else 1))
        for index, row in enumerate(timeline, start=1):
            row["sequence_no"] = index
        loads = [t for t in items if resolved[t.id][0] in ot.LOAD_EVENTS]
        receivers = [t for t in items if resolved[t.id][0] == "UNLOAD"]
        comparisons = []
        for r in receivers:
            left = r.linked_ticket if r.linked_ticket and r.linked_ticket.status == ot.APPROVED and r.linked_ticket.asset_id == asset_id else None
            if left is None:
                earlier = [t for t in loads if (ot.entry_moment(t), t.id) <= (ot.entry_moment(r), r.id)]
                left = earlier[-1] if earlier else None
            if left is not None and left.payload_code == r.payload_code == "multi_tank_payload":
                comparisons.append(ot.compare_barge(left, r))
        receipt_events = [e for e in asset_manual if e.event_type in ("RECEIVED", "RECEIPT_REVOKED")]
        receipt_events.sort(key=lambda e: (e.event_datetime, e.id))
        last_receipt = receipt_events[-1] if receipt_events else None
        received = bool(last_receipt and last_receipt.event_type == "RECEIVED")
        last_load = loads[-1] if loads else None
        pending_sender = last_load if last_load and last_load.id not in live_receivers else None
        receipt_location_id = (last_load.receiver_location_id or last_load.destination_location_id) if last_load else None
        barges.append({
            "asset_id": asset_id, "asset_code": items[0].asset_code_snapshot, "asset_name": items[0].asset_name_snapshot,
            "ticket_count": len(items), "timeline": timeline, "comparisons": comparisons, "received": received,
            "received_at": last_receipt.event_datetime if received else None,
            "received_by": _user_name(last_receipt.created_by) if received else "",
            "receipt_location_id": receipt_location_id, "receipt_location_code": _location_code(db, receipt_location_id),
            "pending_sender_ticket": ot.ticket_ref(pending_sender) if pending_sender else None,
            "receiver_ticket_exists": bool(last_load and last_load.id in live_receivers),
        })
        all_comparisons += comparisons
    blockers = []
    if closed:
        blockers.append("Convoy is already CLOSED")
    if len(approved) < 2:
        blockers.append("At least two Approved tickets are required")
    missing = [b["asset_code"] for b in barges if not b["comparisons"]]
    if missing:
        blockers.append("Missing LOAD_AFTER vs UNLOAD_BEFORE comparison for: " + ", ".join(missing))
    if open_tickets:
        blockers.append(f"{open_tickets} Draft/Submitted/Rejected ticket(s) must be finished or cancelled")
    return {
        "convoy_number": convoy, "status": "CLOSED" if closed else "OPEN",
        "closed_at": closed.closed_at if closed else None, "closed_by": _user_name(closed.closed_by) if closed else "",
        "closure_remarks": next((v.closure_remarks for v in voyages if v.closure_remarks), None),
        "tickets": [ot.ticket_ref(t) | {"event_type": resolved.get(t.id, (None,))[0]} for t in sorted(tickets, key=lambda e: (ot.entry_moment(e), e.id))],
        "barges": barges, "comparison_count": len(all_comparisons), "open_ticket_count": open_tickets,
        "can_close": not blockers, "close_blockers": blockers, "_voyages": voyages, "_approved": approved, "_resolved": resolved,
        "_overrides": overrides,
    }


def _public(state):
    return {k: v for k, v in state.items() if not k.startswith("_")}


@router.get("/barge/convoy")
def barge_convoy(convoy_number: str = Query(min_length=1, max_length=50), db=Depends(get_db), user=Depends(require_permission("barge_tracking:read"))):
    return _public(_convoy_state(db, user, convoy_number))


@router.get("/barge/convoy/export")
def export_barge_convoy(request: Request, convoy_number: str = Query(min_length=1, max_length=50), format: Format = "csv",
                        db=Depends(get_db), user=Depends(require_permission("barge_tracking:read"))):
    state = _convoy_state(db, user, convoy_number)
    headers = ["Barge", "Section", "Left Ticket (After)", "Right Ticket (Before)", "Parameter", "Left", "Right", "Delta / Status"]
    rows = []
    for barge in state["barges"]:
        for row in barge["timeline"]:
            rows.append([barge["asset_code"], "Timeline", row["ticket_number"] or "", "", f"#{row['sequence_no']} {row['event_type']}",
                         row["event_datetime"], row["location_code"], row.get("remarks") or ""])
        for c in barge["comparisons"]:
            lt, rt = c["left_ticket"]["ticket_number"], c["right_ticket"]["ticket_number"]
            rows += [[barge["asset_code"], "Quantity", lt, rt, t["parameter"], t["left"], t["right"], t["delta"]] for t in c["totals"]]
            for tank in c["per_tank"]:
                rows += [[barge["asset_code"], f"Tank {tank['tank']}", lt, rt, key, v["left"], v["right"], v["delta"]] for key, v in tank.items() if key != "tank"]
            rows += [[barge["asset_code"], "Temporary Seal", lt, rt, s["seal"], s["sender"], s["receiver"], s["status"]] for s in c["temporary_seal_checks"]]
            rows += [[barge["asset_code"], "Permanent Seal", lt, rt, f"{s['tank']} {s['position']} (master {s['master']})", s["sender"], s["receiver"], s["status"]]
                     for s in c["permanent_seal_checks"]]
    _audit(db, request, user, "Barge Tracking", "Export MTR", "BargeVoyage", label=state["convoy_number"], category="Export",
           details_summary=f"Convoy {state['convoy_number']}: {len(rows)} rows as {format}")
    db.commit()
    return _export(format, "barge-mtr", f"Barge MTR {state['convoy_number']}", headers, rows, f"Convoy {state['convoy_number']}")


def _barge_for(state, asset_id):
    barge = next((b for b in state["barges"] if b["asset_id"] == asset_id), None)
    if not barge:
        raise HTTPException(404, "This barge has no Approved ticket in the convoy")
    if state["status"] == "CLOSED":
        raise HTTPException(400, "This convoy is CLOSED. Reopen it before changing its tracking.")
    return barge


@router.post("/barge/receipts")
def acknowledge_barge_receipt(body: BargeReceipt, request: Request, db=Depends(get_db), user=Depends(require_permission("barge_tracking:read"))):
    _need(db, user, "barge_tracking:update", "shipment_receipts:create")
    state = _convoy_state(db, user, body.convoy_number, lock=True)
    barge = _barge_for(state, body.asset_id)
    if barge["received"]:
        raise HTTPException(400, "Receipt is already acknowledged for this barge")
    if not barge["pending_sender_ticket"]:
        raise HTTPException(400, "No Approved load ticket is awaiting receipt for this barge")
    if barge["receipt_location_id"]:
        ensure_location(db, user, barge["receipt_location_id"])
    event = BargeTimelineEvent(convoy_number=state["convoy_number"], asset_id=body.asset_id, event_type="RECEIVED",
        location_id=barge["receipt_location_id"], event_datetime=utcnow(), remarks=body.remarks, created_by_user_id=user.id)
    db.add(event); db.flush()
    _audit(db, request, user, "Barge Tracking", "Acknowledge Receipt", "BargeTimelineEvent", event.id, f"{state['convoy_number']} / {barge['asset_code']}",
           remarks=body.remarks, new_status="RECEIVED",
           details_summary=f"Sender {barge['pending_sender_ticket']['ticket_number']} received at {barge['receipt_location_code'] or 'unspecified location'}")
    _commit(db, request)
    return _public(_convoy_state(db, user, body.convoy_number))


@router.post("/barge/receipts/revoke")
def revoke_barge_receipt(body: BargeReceipt, request: Request, db=Depends(get_db), user=Depends(require_permission("barge_tracking:read"))):
    _need(db, user, "barge_tracking:update", "shipment_receipts:delete")
    if not str(body.remarks or "").strip():
        raise HTTPException(400, "Revoke remarks are required")
    state = _convoy_state(db, user, body.convoy_number, lock=True)
    barge = _barge_for(state, body.asset_id)
    if not barge["received"]:
        raise HTTPException(400, "This barge has no active receipt acknowledgement")
    if barge["receiver_ticket_exists"]:
        raise HTTPException(400, "A receiving ticket already exists for this barge. Cancel it before revoking the receipt.")
    if barge["receipt_location_id"]:
        ensure_location(db, user, barge["receipt_location_id"])
    event = BargeTimelineEvent(convoy_number=state["convoy_number"], asset_id=body.asset_id, event_type="RECEIPT_REVOKED",
        location_id=barge["receipt_location_id"], event_datetime=utcnow(), remarks=body.remarks, created_by_user_id=user.id)
    db.add(event); db.flush()
    _audit(db, request, user, "Barge Tracking", "Revoke Receipt", "BargeTimelineEvent", event.id, f"{state['convoy_number']} / {barge['asset_code']}",
           remarks=body.remarks, old_status="RECEIVED", new_status="RECEIPT_REVOKED")
    _commit(db, request)
    return _public(_convoy_state(db, user, body.convoy_number))


@router.put("/barge/timeline")
def fix_barge_timeline(body: BargeTimelineFix, request: Request, db=Depends(get_db), user=Depends(require_permission("barge_tracking:update"))):
    state = _convoy_state(db, user, body.convoy_number, lock=True)
    if state["status"] == "CLOSED":
        raise HTTPException(400, "This convoy is CLOSED. Reopen it before fixing its timeline.")
    entry = next((t for t in state["_approved"] if t.id == body.entry_id), None)
    if not entry:
        raise HTTPException(404, "Ticket is not an Approved barge ticket of this convoy")
    before = state["_resolved"][entry.id][0]
    row = state["_overrides"].get(entry.id)
    if row:
        row.event_type, row.remarks, row.created_by_user_id, row.updated_at = body.event_type, body.remarks, user.id, utcnow()
    else:
        row = BargeTimelineEvent(convoy_number=state["convoy_number"], asset_id=entry.asset_id, entry_id=entry.id,
            event_type=body.event_type, location_id=entry.location_id, event_datetime=ot.entry_moment(entry), remarks=body.remarks,
            created_by_user_id=user.id)
        db.add(row)
    db.flush()
    _audit(db, request, user, "Barge Tracking", "Fix Timeline", "BargeTimelineEvent", row.id, f"{state['convoy_number']} / {entry.ticket_number}",
           remarks=body.remarks, old_status=before, new_status=body.event_type,
           details_summary=f"Ticket {entry.ticket_number} event type {before} -> {body.event_type}")
    _commit(db, request)
    return _public(_convoy_state(db, user, body.convoy_number))


@router.post("/barge/close")
def close_barge(body: ConvoyAction, request: Request, db=Depends(get_db), user=Depends(require_permission("barge_tracking:read"))):
    require_capability(db, user, "operation_voyages:update")
    state = _convoy_state(db, user, body.convoy_number, lock=True)
    if not state["can_close"]:
        raise HTTPException(400, "Cannot close this convoy: " + "; ".join(state["close_blockers"]))
    voyages = state["_voyages"]
    if not voyages:
        first = state["_approved"][0]
        voyages = [OperationVoyage(reference=state["convoy_number"], operation_type_code=BARGE, asset_id=first.asset_id, location_id=first.location_id)]
        db.add(voyages[0])
    for v in voyages:
        v.status, v.closure_remarks, v.closed_at, v.closed_by_user_id = "CLOSED", body.remarks, utcnow(), user.id
    db.flush()
    _audit(db, request, user, "Barge Tracking", "Close Barge Movement", "OperationVoyage", voyages[0].id, state["convoy_number"],
           remarks=body.remarks, old_status="OPEN", new_status="CLOSED",
           details_summary=f"{len(state['barges'])} barge(s), {state['comparison_count']} comparison(s)")
    _commit(db, request)
    return _public(_convoy_state(db, user, body.convoy_number))


@router.post("/barge/reopen")
def reopen_barge(body: ConvoyAction, request: Request, db=Depends(get_db), user=Depends(require_permission("barge_tracking:read"))):
    require_capability(db, user, "operation_voyages:update")
    state = _convoy_state(db, user, body.convoy_number, lock=True)
    if state["status"] != "CLOSED":
        raise HTTPException(400, "This convoy is not CLOSED")
    for v in state["_voyages"]:
        v.status, v.closure_remarks, v.closed_at, v.closed_by_user_id = "OPEN", body.remarks, None, None
    db.flush()
    _audit(db, request, user, "Barge Tracking", "Reopen Barge Movement", "OperationVoyage", state["_voyages"][0].id, state["convoy_number"],
           remarks=body.remarks, old_status="CLOSED", new_status="OPEN")
    _commit(db, request)
    return _public(_convoy_state(db, user, body.convoy_number))


# ---------------------------------------------------------------------------
# Tanker Tracking
# ---------------------------------------------------------------------------


def _tanker_query(db, user, *, date_from=None, date_to=None, convoy_number=None, location_id=None, asset_id=None, search=""):
    _date_range(date_from, date_to)
    q = scoped_entries(db, user, party=True).filter(OperationEntry.operation_type_code == TANKER, OperationEntry.status == ot.APPROVED)
    if date_from: q = q.filter(OperationEntry.operation_date >= date_from)
    if date_to: q = q.filter(OperationEntry.operation_date <= date_to)
    if convoy_number: q = q.filter(OperationEntry.convoy_number.ilike(f"%{convoy_number}%"))
    if location_id:
        q = q.filter(or_(OperationEntry.location_id == location_id, OperationEntry.destination_location_id == location_id,
                         OperationEntry.receiver_location_id == location_id))
    if asset_id: q = q.filter(OperationEntry.asset_id == asset_id)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(OperationEntry.ticket_number.ilike(like), OperationEntry.convoy_number.ilike(like),
                         OperationEntry.asset_code_snapshot.ilike(like), OperationEntry.asset_name_snapshot.ilike(like)))
    return q


def _ack_dict(db, ack):
    if not ack:
        return None
    return {"id": ack.id, "status": ack.status, "receiver_location_id": ack.receiver_location_id,
            "receiver_location_code": ack.receiver_location.location_code if ack.receiver_location else "",
            "acknowledged_by": _user_name(ack.acknowledged_by), "acknowledged_at": ack.acknowledged_at, "remarks": ack.remarks,
            "revoke_remarks": ack.revoke_remarks, "revoked_at": ack.revoked_at,
            "closed_by": _user_name(ack.closed_by), "closed_at": ack.closed_at, "closure_remarks": ack.closure_remarks}


def _tanker_rows(db, user, **filters):
    q = _tanker_query(db, user, **filters)
    if q.count() > MAX_EXPORT_ROWS:
        raise HTTPException(400, "Narrow the filters (date range / convoy / tanker) before loading this many tanker tickets")
    tickets = q.all()
    senders = [t for t in tickets if ot.tanker_role(t) == "SENDER"]
    orphans = [t for t in tickets if ot.tanker_role(t) == "RECEIVER" and not t.linked_ticket_id]
    sender_ids = [t.id for t in senders]
    approved_receivers, live, acks = defaultdict(list), {}, {}
    if sender_ids:
        for r in db.query(OperationEntry).filter(OperationEntry.linked_ticket_id.in_(sender_ids), OperationEntry.status == ot.APPROVED).all():
            approved_receivers[r.linked_ticket_id].append(r)
        for r in db.query(OperationEntry).filter(OperationEntry.receiver_link_key.in_(sender_ids)).all():
            live[r.receiver_link_key] = r
        for a in db.query(TankerReceiptAcknowledgement).filter(TankerReceiptAcknowledgement.sender_entry_id.in_(sender_ids)).all():
            acks[a.sender_entry_id] = a
    rows = []
    for s in senders:
        receivers = sorted(approved_receivers.get(s.id, []), key=lambda e: (ot.entry_moment(e), e.id))
        receiver = receivers[-1] if receivers else None
        sender_t, receiver_t = ot.tanker_ticket(s), ot.tanker_ticket(receiver)
        seals = ot.tanker_seal_checks(sender_t, receiver_t)
        quantity = ot.tanker_quantity(sender_t, receiver_t)
        ack = acks.get(s.id)
        status = ot.tanker_status(sender_t, receiver_t, seals, quantity, ack)
        warnings = []
        if len(receivers) > 1:
            warnings.append(f"{len(receivers)} Approved receiver tickets found; the latest is compared.")
        in_progress = live.get(s.id)
        if in_progress and in_progress.status != ot.APPROVED:
            warnings.append(f"Receiver ticket {in_progress.ticket_number} is {in_progress.status}; comparison appears after approval.")
        rows.append({
            "group_key": f"S{s.id}", "convoy_number": s.convoy_number, "product_name": s.product_name, "tracking_status": status,
            "tanker_asset_id": s.asset_id, "tanker_asset_code": s.asset_code_snapshot, "tanker_asset_name": s.asset_name_snapshot,
            "tanker_chassis_number": sender_t["chassis_number"], "prime_mover_asset_code": sender_t["prime_mover_code"],
            "prime_mover_asset_name": sender_t["prime_mover_name"], "sender_ticket": sender_t, "latest_receiver_ticket": receiver_t,
            "receiver_ticket_count": len(receivers), "receiver_in_progress": ot.ticket_ref(in_progress) if in_progress else None,
            "receiving_location_id": s.receiver_location_id or s.destination_location_id,
            "receiving_location_code": _location_code(db, s.receiver_location_id or s.destination_location_id),
            "seal_checks": seals, "quantity_comparison": quantity, "acknowledgement": _ack_dict(db, ack), "warning_messages": warnings,
            "can_create_receiver": status == "ACKNOWLEDGED" and not in_progress, "operation_date": s.operation_date,
        })
    for r in orphans:
        receiver_t = ot.tanker_ticket(r)
        rows.append({
            "group_key": f"R{r.id}", "convoy_number": r.convoy_number, "product_name": r.product_name, "tracking_status": "NO_SENDER",
            "tanker_asset_id": r.asset_id, "tanker_asset_code": r.asset_code_snapshot, "tanker_asset_name": r.asset_name_snapshot,
            "tanker_chassis_number": receiver_t["chassis_number"], "prime_mover_asset_code": receiver_t["prime_mover_code"],
            "prime_mover_asset_name": receiver_t["prime_mover_name"], "sender_ticket": None, "latest_receiver_ticket": receiver_t,
            "receiver_ticket_count": 1, "receiver_in_progress": None, "receiving_location_id": r.location_id,
            "receiving_location_code": r.location.location_code, "seal_checks": ot.tanker_seal_checks(None, receiver_t),
            "quantity_comparison": None, "acknowledgement": None, "can_create_receiver": False, "operation_date": r.operation_date,
            "warning_messages": ["Receiver ticket is not linked to an Approved sender ticket; no comparison is possible."],
        })
    rows.sort(key=lambda row: (row["operation_date"], row["group_key"]), reverse=True)
    return rows


def tanker_filters(date_from: date | None = None, date_to: date | None = None, convoy_number: str | None = Query(None, max_length=50),
                   location_id: int | None = None, asset_id: int | None = None, search: str = Query("", max_length=150)):
    return locals()


@router.get("/tanker")
def tanker_tracking(filters=Depends(tanker_filters), status: str | None = Query(None, max_length=40), page: int = 1, page_size: int = 20,
                    db=Depends(get_db), user=Depends(require_permission("tanker_tracking:read"))):
    rows = _tanker_rows(db, user, **filters)
    summary = ot.tanker_summary(rows)
    if status and status != "ALL":
        rows = [r for r in rows if r["tracking_status"] == status]
    page, page_size = clamp_page(page), clamp_page_size(page_size)
    result = pagination_payload(rows[(page - 1) * page_size: page * page_size], len(rows), page, page_size)
    result["summary"] = summary
    return result


@router.get("/tanker/export")
def export_tanker_tracking(request: Request, format: Format = "csv", filters=Depends(tanker_filters), status: str | None = Query(None, max_length=40),
                           db=Depends(get_db), user=Depends(require_permission("tanker_tracking:read"))):
    rows = _tanker_rows(db, user, **filters)
    if status and status != "ALL":
        rows = [r for r in rows if r["tracking_status"] == status]
    headers = ["Convoy", "Status", "Prime Mover", "Tanker", "Chassis", "Product", "Sender Ticket", "Receiver Ticket", "Sender NSV",
               "Receiver NSV", "NSV Variance", "Variance %", "Seal Check"]
    data = []
    for r in rows:
        q = r["quantity_comparison"] or {}
        seal_bad = any(c["status"] in ("MISMATCH", "RECEIVER_MISSING", "SENDER_MISSING") for c in r["seal_checks"])
        data.append([r["convoy_number"], r["tracking_status"], r["prime_mover_asset_code"], r["tanker_asset_code"], r["tanker_chassis_number"],
                     r["product_name"], (r["sender_ticket"] or {}).get("ticket_number"), (r["latest_receiver_ticket"] or {}).get("ticket_number"),
                     q.get("sender_nsv", (r["sender_ticket"] or {}).get("nsv_bbl")), q.get("receiver_nsv", (r["latest_receiver_ticket"] or {}).get("nsv_bbl")),
                     q.get("nsv_variance"), q.get("nsv_variance_pct"), "Mismatch" if seal_bad else "OK"])
    text_filters = _filter_text({**filters, "status": status})
    _audit(db, request, user, "Tanker Tracking", "Export", "TankerMovement", category="Export", details_summary=f"{len(data)} rows as {format}; {text_filters}")
    db.commit()
    return _export(format, "tanker-tracking", "Tanker Tracking", headers, data, text_filters)


def _ack_scope(db, user, ack, *, lock=False):
    get_entry(db, user, ack.sender_entry_id, party=True, lock=lock)
    return ack


@router.post("/tanker/acknowledgements", status_code=201)
def acknowledge_tanker(body: TankerAcknowledge, request: Request, db=Depends(get_db), user=Depends(require_permission("tanker_tracking:read"))):
    _need(db, user, "tanker_tracking:update", "shipment_receipts:create")
    sender = get_entry(db, user, body.sender_entry_id, party=True, lock=True)
    if sender.operation_type_code != TANKER or sender.status != ot.APPROVED or ot.tanker_role(sender) != "SENDER":
        raise HTTPException(400, "Only an Approved tanker sender ticket can be acknowledged")
    location = db.get(Location, body.receiver_location_id)
    if not location or location.status != "Active":
        raise HTTPException(400, "Select an Active receiver location")
    ensure_location(db, user, body.receiver_location_id)
    target = sender.receiver_location_id or sender.destination_location_id
    if target and target != body.receiver_location_id:
        raise HTTPException(400, "Receiver location must be the sender ticket's receiving terminal")
    ack = db.query(TankerReceiptAcknowledgement).filter_by(sender_entry_id=sender.id).with_for_update().first()
    if ack and ack.status != "Revoked":
        raise HTTPException(409, f"This tanker movement is already {ack.status}")
    old = ack.status if ack else None
    if not ack:
        ack = TankerReceiptAcknowledgement(sender_entry_id=sender.id, asset_id=sender.asset_id)
        db.add(ack)
    ack.convoy_number, ack.receiver_location_id, ack.status, ack.remarks = sender.convoy_number, body.receiver_location_id, "Acknowledged", body.remarks
    ack.acknowledged_by_user_id, ack.acknowledged_at = user.id, utcnow()
    ack.revoked_by_user_id = ack.revoked_at = None
    db.flush()
    _audit(db, request, user, "Tanker Tracking", "Acknowledge Receipt", "TankerReceiptAcknowledgement", ack.id,
           f"{sender.convoy_number or ''} - {sender.asset_code_snapshot}", remarks=body.remarks, old_status=old, new_status="Acknowledged",
           details_summary=f"Sender {sender.ticket_number} acknowledged at {location.location_code}")
    _commit(db, request)
    return _ack_dict(db, ack)


@router.post("/tanker/acknowledgements/{ack_id}/revoke")
def revoke_tanker(ack_id: int, body: RemarksBody, request: Request, db=Depends(get_db), user=Depends(require_permission("tanker_tracking:read"))):
    _need(db, user, "tanker_tracking:update", "shipment_receipts:delete")
    ack = db.query(TankerReceiptAcknowledgement).filter_by(id=ack_id).with_for_update().first()
    if not ack:
        raise HTTPException(404, "Tanker receipt acknowledgement not found")
    _ack_scope(db, user, ack)
    ensure_location(db, user, ack.receiver_location_id)
    if ack.status != "Acknowledged":
        raise HTTPException(400, f"Only an Acknowledged movement can be revoked (current: {ack.status})")
    if db.query(OperationEntry.id).filter(OperationEntry.receiver_link_key == ack.sender_entry_id).first():
        raise HTTPException(400, "A receiver ticket already exists. Cancel it before revoking the acknowledgement.")
    ack.status, ack.revoke_remarks, ack.revoked_by_user_id, ack.revoked_at = "Revoked", body.remarks, user.id, utcnow()
    db.flush()
    _audit(db, request, user, "Tanker Tracking", "Revoke Receipt Acknowledgement", "TankerReceiptAcknowledgement", ack.id,
           f"{ack.convoy_number or ''}", remarks=body.remarks, old_status="Acknowledged", new_status="Revoked")
    _commit(db, request)
    return _ack_dict(db, ack)


@router.post("/tanker/acknowledgements/{ack_id}/close")
def close_tanker(ack_id: int, body: RemarksBody, request: Request, db=Depends(get_db), user=Depends(require_permission("tanker_tracking:update"))):
    ack = db.query(TankerReceiptAcknowledgement).filter_by(id=ack_id).with_for_update().first()
    if not ack:
        raise HTTPException(404, "Tanker receipt acknowledgement not found")
    _ack_scope(db, user, ack)
    if ack.status != "Acknowledged":
        raise HTTPException(400, f"Only an Acknowledged movement can be closed (current: {ack.status})")
    receiver = db.query(OperationEntry).filter(OperationEntry.linked_ticket_id == ack.sender_entry_id, OperationEntry.status == ot.APPROVED).first()
    if not receiver:
        raise HTTPException(400, "An Approved receiver ticket (sender vs receiver comparison) is required before closing")
    ack.status, ack.closure_remarks, ack.closed_by_user_id, ack.closed_at = "Closed", body.remarks, user.id, utcnow()
    db.flush()
    _audit(db, request, user, "Tanker Tracking", "Close Tanker Movement", "TankerReceiptAcknowledgement", ack.id,
           f"{ack.convoy_number or ''}", remarks=body.remarks, old_status="Acknowledged", new_status="Closed",
           details_summary=f"Receiver ticket {receiver.ticket_number}")
    _commit(db, request)
    return _ack_dict(db, ack)


# ---------------------------------------------------------------------------
# Tanker Transaction Report
# ---------------------------------------------------------------------------
REPORT_TOTALS = ("tov_bbl", "free_water_bbl", "gov_bbl", "gsv_bbl", "bsw_bbl", "nsv_bbl", "lt", "mt")


def _tanker_report_query(db, user, date_from, date_to, location_id, asset_id, convoy_number, status, search):
    _date_range(date_from, date_to)
    q = scoped_entries(db, user, party=True).filter(OperationEntry.operation_type_code == TANKER, OperationEntry.payload_code == "tanker_payload")
    if status: q = q.filter(OperationEntry.status.in_(status.split(",")))
    if date_from: q = q.filter(OperationEntry.operation_date >= date_from)
    if date_to: q = q.filter(OperationEntry.operation_date <= date_to)
    if location_id: q = q.filter(OperationEntry.location_id == location_id)
    if asset_id: q = q.filter(OperationEntry.asset_id == asset_id)
    if convoy_number: q = q.filter(OperationEntry.convoy_number.ilike(f"%{convoy_number}%"))
    if search:
        like = f"%{search}%"
        q = q.filter(or_(OperationEntry.ticket_number.ilike(like), OperationEntry.convoy_number.ilike(like),
                         OperationEntry.asset_code_snapshot.ilike(like), OperationEntry.product_name.ilike(like)))
    return q.order_by(OperationEntry.operation_date.desc(), OperationEntry.id.desc())


def report_filters(date_from: date | None = None, date_to: date | None = None, location_id: int | None = None, asset_id: int | None = None,
                   convoy_number: str | None = Query(None, max_length=50), status: str | None = Query("Approved", max_length=80),
                   search: str = Query("", max_length=150)):
    return locals()


@router.get("/tanker/report")
def tanker_report(filters=Depends(report_filters), page: int = 1, page_size: int = 20, db=Depends(get_db),
                  user=Depends(require_permission("tanker_transaction_reports:read"))):
    q = _tanker_report_query(db, user, **filters)
    result = paginate_query(q, page, page_size)
    result["items"] = [ot.tanker_ticket(e) | {"role": ot.tanker_role(e)} for e in result["items"]]
    if q.count() > MAX_EXPORT_ROWS:
        result["totals"] = None
    else:
        tickets = [ot.tanker_ticket(e) for e in q.all()]
        result["totals"] = {key: ot.rnd(sum(t[key] for t in tickets)) for key in REPORT_TOTALS}
    return result


@router.get("/tanker/report/export")
def export_tanker_report(request: Request, format: Format = "csv", filters=Depends(report_filters), db=Depends(get_db),
                         user=Depends(require_permission("tanker_transaction_reports:read"))):
    q = _tanker_report_query(db, user, **filters)
    if q.count() > MAX_EXPORT_ROWS:
        raise HTTPException(400, "Narrow the filters before exporting this many tickets")
    headers = ["Date", "Ticket", "Status", "Location", "Tanker", "Prime Mover", "Chassis", "Convoy", "Cargo", "Destination", "Total Dip cm",
               "Water Dip cm", "Tank Temp", "Sample Temp", "Obs API", "API60", "VCF", "TOV", "FW", "GOV", "GSV", "BS&W %", "BS&W", "NSV",
               "LT", "MT", "Seal C1", "Seal C2", "Seal M1", "Seal M2"]
    rows = []
    for e in q.all():
        t = ot.tanker_ticket(e)
        rows.append([t["operation_date"], t["ticket_number"], t["status"], t["location_code"], t["asset_code"], t["prime_mover_code"],
                     t["chassis_number"], t["convoy_number"], t["product_name"], t["receiver_location_code"] or t["destination_location_code"],
                     t["total_dip_cm"], t["water_dip_cm"], t["tank_temperature"], t["sample_temperature"], t["observed_api"], t["api60"], t["vcf"],
                     t["tov_bbl"], t["free_water_bbl"], t["gov_bbl"], t["gsv_bbl"], t["bsw_percent"], t["bsw_bbl"], t["nsv_bbl"], t["lt"], t["mt"],
                     t["seal_c1"], t["seal_c2"], t["seal_m1"], t["seal_m2"]])
    text_filters = _filter_text(filters)
    _audit(db, request, user, "Tanker Transaction Report", "Export", "OperationEntry", category="Export", details_summary=f"{len(rows)} rows as {format}; {text_filters}")
    db.commit()
    return _export(format, "tanker-transaction-report", "Tanker Transaction Report", headers, rows, text_filters)


# ---------------------------------------------------------------------------
# Shuttle / FSO voyages
# ---------------------------------------------------------------------------
VESSEL = {"shuttle": (SHUTTLE, "shuttle_tracking:read", "Shuttle Tracking"), "fso": (FSO, "fso_tracking:read", "FSO Tracking")}


def _approved_for(type_code, date_from=None, date_to=None):
    cond = [OperationEntry.convoy_number == OperationVoyage.reference, OperationEntry.asset_id == OperationVoyage.asset_id,
            OperationEntry.location_id == OperationVoyage.location_id, OperationEntry.status == ot.APPROVED,
            OperationEntry.operation_type_code == type_code]
    if date_from: cond.append(OperationEntry.operation_date >= date_from)
    if date_to: cond.append(OperationEntry.operation_date <= date_to)
    return exists().where(*cond)


def _voyage_query(db, user, kind, *, location_id=None, asset_id=None, shuttle_number=None, date_from=None, date_to=None, search=""):
    type_code, capability, _ = VESSEL[kind]
    require_capability(db, user, capability)
    _date_range(date_from, date_to)
    q = db.query(OperationVoyage).filter(OperationVoyage.operation_type_code == type_code, _approved_for(type_code, date_from, date_to))
    allowed = get_user_location_ids(db, user)
    if allowed is not None:
        q = q.filter(OperationVoyage.location_id.in_(sorted(allowed)))
    if location_id: q = q.filter(OperationVoyage.location_id == location_id)
    if asset_id: q = q.filter(OperationVoyage.asset_id == asset_id)
    if shuttle_number: q = q.filter(OperationVoyage.reference.ilike(f"%{shuttle_number}%"))
    if search:
        from app.models import Asset
        like = f"%{search}%"
        q = q.join(Asset, Asset.id == OperationVoyage.asset_id).join(Location, Location.id == OperationVoyage.location_id).filter(
            or_(OperationVoyage.reference.ilike(like), Asset.asset_code.ilike(like), Asset.asset_name.ilike(like), Location.location_code.ilike(like)))
    return q


def _voyage_tickets(db, voyage, statuses=(ot.APPROVED,)):
    return db.query(OperationEntry).filter(OperationEntry.operation_type_code == voyage.operation_type_code,
        OperationEntry.convoy_number == voyage.reference, OperationEntry.asset_id == voyage.asset_id,
        OperationEntry.location_id == voyage.location_id, OperationEntry.status.in_(statuses)).all()


def _voyage_row(db, voyage, kind, tickets=None):
    tickets = sorted(tickets if tickets is not None else _voyage_tickets(db, voyage), key=lambda e: (ot.entry_moment(e), e.id))
    totals = ot.shuttle_movement_totals(tickets) if kind == "shuttle" else ot.fso_voyage_totals(tickets)
    last = tickets[-1] if tickets else None
    row = last.shuttle or last.fso if last else None
    return {
        "id": voyage.id, "group_key": f"{voyage.location.location_code}|{voyage.reference}|{voyage.asset.asset_code}",
        "shuttle_number": voyage.reference, "asset_id": voyage.asset_id, "asset_code": voyage.asset.asset_code,
        "asset_name": voyage.asset.asset_name, "location_id": voyage.location_id, "location_code": voyage.location.location_code,
        "location_name": voyage.location.location_name, "voyage_status": voyage.status, "closed_at": voyage.closed_at,
        "closed_by": _user_name(voyage.closed_by), "closure_remarks": voyage.closure_remarks, "ticket_count": len(tickets),
        "first_operation_date": tickets[0].operation_date if tickets else None, "last_operation_date": last.operation_date if last else None,
        "last_closing_stock_bbl": ot.num(row.closing_stock_bbl) if row else 0, "last_closing_water_bbl": ot.num(row.closing_water_bbl) if row else 0,
        **totals,
    }


def voyage_filters(location_id: int | None = None, asset_id: int | None = None, shuttle_number: str | None = Query(None, max_length=50),
                   date_from: date | None = None, date_to: date | None = None, search: str = Query("", max_length=150)):
    return locals()


vessel_read = require_any_permission("shuttle_tracking:read", "fso_tracking:read")


@router.get("/{kind}/voyages")
def vessel_voyages(kind: Literal["shuttle", "fso"], tab: Literal["OPEN", "CLOSED"] = "OPEN", filters=Depends(voyage_filters),
                   page: int = 1, page_size: int = 20, db=Depends(get_db), user=Depends(vessel_read)):
    q = _voyage_query(db, user, kind, **filters)
    counts = {"OPEN": q.filter(OperationVoyage.status == "OPEN").count(), "CLOSED": q.filter(OperationVoyage.status == "CLOSED").count()}
    result = paginate_query(q.filter(OperationVoyage.status == tab).order_by(OperationVoyage.updated_at.desc(), OperationVoyage.id.desc()), page, page_size)
    result["items"] = [_voyage_row(db, v, kind) for v in result["items"]]
    result.update(tab=tab, open_count=counts["OPEN"], closed_count=counts["CLOSED"])
    return result


@router.get("/{kind}/voyages/export")
def export_vessel_voyages(request: Request, kind: Literal["shuttle", "fso"], format: Format = "csv", tab: Literal["OPEN", "CLOSED", "ALL"] = "ALL",
                          filters=Depends(voyage_filters), db=Depends(get_db), user=Depends(vessel_read)):
    q = _voyage_query(db, user, kind, **filters)
    if tab != "ALL":
        q = q.filter(OperationVoyage.status == tab)
    if q.count() > MAX_EXPORT_ROWS:
        raise HTTPException(400, "Narrow the filters before exporting this many voyages")
    rows = [_voyage_row(db, v, kind) for v in q.order_by(OperationVoyage.id.desc()).all()]
    if kind == "shuttle":
        headers = ["Location", "Shuttle Asset", "Shuttle Number", "Status", "Tickets", "Net Receipt", "Net Discharge", "Transfer In",
                   "Transfer Out", "TOV", "FW", "NSV", "Last Closing Stock", "Last Closing Water", "Closed At", "Closed By", "Remarks"]
        data = [[r["location_code"], r["asset_code"], r["shuttle_number"], r["voyage_status"], r["ticket_count"], r["net_receipt_bbl"],
                 r["net_discharge_bbl"], r["transfer_in_bbl"], r["transfer_out_bbl"], r["tov_bbl"], r["fw_bbl"], r["nsv_bbl"],
                 r["last_closing_stock_bbl"], r["last_closing_water_bbl"], r["closed_at"], r["closed_by"], r["closure_remarks"]] for r in rows]
    else:
        headers = ["Location", "FSO Asset", "Shuttle Number", "Status", "Tickets", "FSO Receipt", "FSO Export", "Water In", "Water Out",
                   "Shuttle Discharge", "Variance", "Variance %", "Last Closing Stock", "Closed At", "Closed By", "Remarks"]
        data = [[r["location_code"], r["asset_code"], r["shuttle_number"], r["voyage_status"], r["ticket_count"], r["fso_receipt_bbl"],
                 r["fso_export_bbl"], r["water_in_bbl"], r["water_out_bbl"], r["shuttle_discharge_bbl"], r["variance_bbl"], r["variance_pct"],
                 r["last_closing_stock_bbl"], r["closed_at"], r["closed_by"], r["closure_remarks"]] for r in rows]
    module = VESSEL[kind][2]
    text_filters = _filter_text({**filters, "tab": tab})
    _audit(db, request, user, module, "Export", "OperationVoyage", category="Export", details_summary=f"{len(data)} voyages as {format}; {text_filters}")
    db.commit()
    return _export(format, f"{kind}-voyages", module, headers, data, text_filters)


def _scoped_voyage(db, user, kind, voyage_id, *, lock=False):
    q = _voyage_query(db, user, kind).filter(OperationVoyage.id == voyage_id)
    if lock:
        q = q.with_for_update()
    voyage = q.first()
    if not voyage:
        raise HTTPException(404, "Voyage not found")
    return voyage


def _voyage_detail(db, voyage, kind):
    tickets = sorted(_voyage_tickets(db, voyage), key=lambda e: (ot.entry_moment(e), e.id))
    detail = _voyage_row(db, voyage, kind, tickets)
    detail["tickets"] = [ot.shuttle_ticket(t) for t in tickets]
    detail["open_ticket_count"] = len(_voyage_tickets(db, voyage, ot.OPEN_STATUSES))
    return detail


@router.get("/{kind}/voyages/{voyage_id}")
def vessel_voyage(kind: Literal["shuttle", "fso"], voyage_id: int, db=Depends(get_db), user=Depends(vessel_read)):
    return _voyage_detail(db, _scoped_voyage(db, user, kind, voyage_id), kind)


@router.get("/{kind}/voyages/{voyage_id}/export")
def export_vessel_voyage(request: Request, kind: Literal["shuttle", "fso"], voyage_id: int, format: Format = "csv", db=Depends(get_db),
                         user=Depends(vessel_read)):
    detail = _voyage_detail(db, _scoped_voyage(db, user, kind, voyage_id), kind)
    headers = ["Ticket", "Date", "Time", "Operation", "Sign", "Opening Stock", "Opening Water", "Closing Stock", "Closing Water",
               "Net Stock", "Net Water", "Reference / Vessel"]
    rows = [[t["ticket_number"], t["operation_date"], t["event_time"], t["operation_label"], t["operation_sign"], t["opening_stock_bbl"],
             t["opening_water_bbl"], t["closing_stock_bbl"], t["closing_water_bbl"], t["net_stock_bbl"], t["net_water_bbl"],
             t.get("barge_reference") or t.get("vessel_name") or ""] for t in detail["tickets"]]
    summary_keys = ("net_receipt_bbl", "net_discharge_bbl", "transfer_in_bbl", "transfer_out_bbl", "tov_bbl", "fw_bbl", "nsv_bbl") if kind == "shuttle" \
        else ("fso_receipt_bbl", "fso_export_bbl", "water_in_bbl", "water_out_bbl", "shuttle_discharge_bbl", "variance_bbl", "variance_pct")
    rows += [["TOTAL", "", "", key.replace("_bbl", "").replace("_", " ").upper(), "", "", "", "", "", "", "", detail[key]] for key in summary_keys]
    module = VESSEL[kind][2]
    _audit(db, request, user, module, "Export Voyage MTR", "OperationVoyage", detail["id"], detail["group_key"], category="Export",
           details_summary=f"{len(detail['tickets'])} tickets as {format}")
    db.commit()
    return _export(format, f"{kind}-voyage-mtr", f"{module} MTR {detail['group_key']}", headers, rows, detail["group_key"])


@router.post("/{kind}/voyages/{voyage_id}/{action}")
def change_vessel_voyage(kind: Literal["shuttle", "fso"], voyage_id: int, action: Literal["close", "reopen"], body: RemarksBody, request: Request,
                         db=Depends(get_db), user=Depends(vessel_read)):
    require_capability(db, user, "operation_voyages:update")
    voyage = _scoped_voyage(db, user, kind, voyage_id, lock=True)
    if action == "close":
        if voyage.status == "CLOSED":
            raise HTTPException(400, "Voyage is already CLOSED")
        if _voyage_tickets(db, voyage, ot.OPEN_STATUSES):
            raise HTTPException(400, "Finish or cancel open (Draft/Submitted/Rejected) tickets before closing the voyage")
        voyage.status, voyage.closed_at, voyage.closed_by_user_id = "CLOSED", utcnow(), user.id
    else:
        if voyage.status != "CLOSED":
            raise HTTPException(400, "Voyage is not CLOSED")
        voyage.status, voyage.closed_at, voyage.closed_by_user_id = "OPEN", None, None
    voyage.closure_remarks = body.remarks
    db.flush()
    module = VESSEL[kind][2]
    label = "Shuttle" if kind == "shuttle" else "FSO"
    _audit(db, request, user, module, f"{'Close' if action == 'close' else 'Reopen'} {label} Voyage", "OperationVoyage", voyage.id,
           f"{voyage.location.location_code}|{voyage.reference}|{voyage.asset.asset_code}", remarks=body.remarks,
           old_status="OPEN" if action == "close" else "CLOSED", new_status="CLOSED" if action == "close" else "OPEN")
    _commit(db, request)
    return _voyage_detail(db, voyage, kind)


# ---------------------------------------------------------------------------
# FSO reports: OTR, Material Balance, Outturn
# ---------------------------------------------------------------------------


def _fso_entries(db, user, location_id, asset_id, date_from, date_to, shuttle_number=None):
    require_capability(db, user, "fso_tracking:read")
    _date_range(date_from, date_to)
    ensure_location(db, user, location_id)
    q = scoped_entries(db, user).filter(OperationEntry.operation_type_code == FSO, OperationEntry.payload_code == "fso_payload",
        OperationEntry.status == ot.APPROVED, OperationEntry.location_id == location_id, OperationEntry.asset_id == asset_id,
        OperationEntry.operation_date >= date_from, OperationEntry.operation_date <= date_to)
    if shuttle_number:
        q = q.filter(OperationEntry.convoy_number == shuttle_number)
    if q.count() > MAX_EXPORT_ROWS:
        raise HTTPException(400, "Narrow the date range for this FSO report")
    return q.all()


def fso_report_filters(location_id: int = Query(ge=1), asset_id: int = Query(ge=1), date_from: date = Query(), date_to: date = Query(),
                       shuttle_number: str | None = Query(None, max_length=50)):
    return locals()


def _fso_report(db, user, kind, filters):
    entries = _fso_entries(db, user, **filters)
    if kind == "otr":
        rows, totals = ot.fso_otr_rows(entries)
    elif kind == "material-balance":
        rows, totals = ot.fso_material_balance(entries), {}
    else:
        rows, totals = ot.fso_outturn(entries)
    return {"kind": kind, "rows": rows, "totals": totals,
            "accounting_day_note": "Accounting date = operation date (Location Accounting Day Setting is Planned)."}


@router.get("/fso/reports/{kind}")
def fso_report(kind: Literal["otr", "material-balance", "outturn"], filters=Depends(fso_report_filters), db=Depends(get_db),
               user=Depends(require_permission("fso_tracking:read"))):
    return _fso_report(db, user, kind, filters)


@router.get("/fso/reports/{kind}/export")
def export_fso_report(request: Request, kind: Literal["otr", "material-balance", "outturn"], format: Format = "csv",
                      filters=Depends(fso_report_filters), db=Depends(get_db), user=Depends(require_permission("fso_tracking:read"))):
    report = _fso_report(db, user, kind, filters)
    rows = report["rows"]
    if kind == "otr":
        headers = ["Ticket", "Acc Date", "Operation", "Sign", "Shuttle", "Vessel", "Vessel Qty", "Move Qty", "Variance", "Shuttle Discharge", "Compare Variance"]
        data = [[r["ticket_number"], r["accounting_date"], r["operation_label"], r["operation_sign"], r["shuttle_number"], r["vessel_name"],
                 r["vessel_quantity_bbl"], r["movement_qty_bbl"], r["variance_bbl"], r["source_shuttle_discharge_bbl"], r["compare_variance_bbl"]] for r in rows]
    elif kind == "material-balance":
        headers = ["Acc Date", "Opening", "Receipt", "Export", "Book Close", "Physical Close", "Close Water", "Loss/Gain"]
        data = [[r["accounting_date"], r["opening_stock_bbl"], r["receipt_bbl"], r["export_bbl"], r["book_closing_bbl"], r["physical_closing_bbl"],
                 r["physical_closing_water_bbl"], r["loss_gain_bbl"]] for r in rows]
    else:
        headers = ["Acc Date", "Shuttle", "Shuttle Discharge", "FSO Receipt", "Variance", "Variance %"]
        data = [[r["accounting_date"], r["shuttle_number"], r["shuttle_discharge_bbl"], r["fso_receipt_bbl"], r["variance_bbl"], r["variance_pct"]] for r in rows]
    title = {"otr": "FSO OTR", "material-balance": "FSO Material Balance", "outturn": "FSO Outturn"}[kind]
    text_filters = _filter_text(filters)
    _audit(db, request, user, "FSO Tracking", f"Export {title}", "OperationEntry", category="Export", details_summary=f"{len(data)} rows as {format}; {text_filters}")
    db.commit()
    return _export(format, "fso-" + kind, title, headers, data, text_filters)
