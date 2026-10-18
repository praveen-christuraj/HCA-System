"""Operation Tracking calculations ported from OTMS ``tracking_helpers`` /
``tanker_tracking`` / ``shuttle_fso_voyages`` / ``reports`` (FSO).

Every view is computed on read from Approved tickets through
``payload_from_entry`` (the OTMS-shaped payload rebuilt from typed tables), so
there is no stored copy of quantities or comparisons and nothing can drift from
the immutable approved snapshots. Only non-ticket facts (receipt
acknowledgements, timeline corrections, voyage status) are persisted.
"""
from __future__ import annotations

from datetime import datetime, time

from app.services.operation_entry_service import payload_from_entry

APPROVED = "Approved"
OPEN_STATUSES = ("Draft", "Rejected", "Submitted")

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def num(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result else 0.0  # NaN guard


def rnd(value, digits=3):
    return round(num(value), digits)


def text(value) -> str:
    return str(value or "").strip()


def entry_moment(entry) -> datetime:
    """Chronological key of a ticket (OTMS orders by operation date/time then id)."""
    return entry.operation_end_datetime or entry.operation_start_datetime or datetime.combine(entry.operation_date, time.min)


def ticket_ref(entry) -> dict:
    return {
        "id": entry.id, "ticket_number": entry.ticket_number, "status": entry.status,
        "operation_date": entry.operation_date, "operation_code": entry.operation_code_snapshot,
        "operation_label": entry.operation_label_snapshot, "operation_category": entry.operation_category_snapshot,
        "operation_sign": entry.operation_sign_snapshot, "asset_id": entry.asset_id,
        "asset_code": entry.asset_code_snapshot, "asset_name": entry.asset_name_snapshot,
        "location_id": entry.location_id, "location_code": entry.location.location_code if entry.location else "",
        "destination_location_code": entry.destination_location.location_code if entry.destination_location else "",
        "receiver_location_code": entry.receiver_location.location_code if entry.receiver_location else "",
        "convoy_number": entry.convoy_number, "linked_ticket_id": entry.linked_ticket_id,
        "product_name": entry.product_name, "barge_event_type": entry.barge_event_type,
        "approved_at": entry.approved_at, "created_by": entry.created_by.username if entry.created_by else "",
        "approved_by": entry.approved_by.username if getattr(entry, "approved_by", None) else "",
    }


# ---------------------------------------------------------------------------
# Barge: timeline events and LOAD_AFTER vs UNLOAD_BEFORE comparison (OTMS v2)
# ---------------------------------------------------------------------------
BARGE_TICKET_EVENTS = ("LOAD_1", "LOAD_2_TOPUP", "UNLOAD", "STS")
BARGE_MANUAL_EVENTS = ("RECEIVED", "RECEIPT_REVOKED", "STS_OUT", "STS_IN", "SHUTTLE_RECEIPT", "OTHER")
LOAD_EVENTS = ("LOAD_1", "LOAD_2_TOPUP")
COMPARISON_TYPE = "LOAD_AFTER_vs_UNLOAD_BEFORE"
TEMP_SEAL_KEYS = ("portManifoldSeal", "stbdManifoldSeal", "pumproomSeal", "otherSeal")
TEMP_SEAL_LABELS = {"portManifoldSeal": "Port Manifold", "stbdManifoldSeal": "Stbd Manifold",
                    "pumproomSeal": "Pumproom", "otherSeal": "Other"}
PERMANENT_SEAL_POSITIONS = ("MH1", "MH2", "LOCK", "DIPHATCH")
TOTAL_KEYS = ("TOV", "FW", "GOV", "GSV", "BSW", "NSV", "LT", "MT")


def is_barge_receiver(entry) -> bool:
    return bool(entry.linked_ticket_id) or entry.operation_category_snapshot == "RECEIPT"


def resolve_barge_events(tickets, overrides):
    """Event type per Approved barge ticket (OTMS timeline self-heal rules).

    Order of precedence: an administrator correction, a linked/RECEIPT ticket
    is UNLOAD, an explicit UNLOAD/STS ticket field, otherwise the first load of
    a barge in the convoy is LOAD_1 and later loads are LOAD_2_TOPUP.
    """
    events, seen_load = {}, set()
    for entry in sorted(tickets, key=lambda e: (entry_moment(e), e.id)):
        override = overrides.get(entry.id)
        if override:
            kind, source = override.event_type, "CORRECTED"
        elif is_barge_receiver(entry):
            kind, source = "UNLOAD", "DERIVED"
        elif entry.barge_event_type in ("UNLOAD", "STS"):
            kind, source = entry.barge_event_type, "TICKET"
        else:
            kind = "LOAD_2_TOPUP" if entry.asset_id in seen_load else "LOAD_1"
            source = "TICKET" if entry.barge_event_type == kind else "DERIVED"
        if kind in LOAD_EVENTS:
            seen_load.add(entry.asset_id)
        events[entry.id] = (kind, source)
    return events


def _stage(payload, stage):
    calculated = (payload.get("calculated") or {}).get(stage) or {}
    per_tank = (payload.get("perTank") or {}).get(stage) or {}
    inputs = (payload.get("inputs") or {}).get(stage) or {}
    return calculated, per_tank, inputs


def compare_barge(left, right):
    """OTMS comparison v2: left ticket AFTER stage vs right ticket BEFORE stage.

    ``delta = left - right`` for every total and per-tank figure. Temporary
    seals: sender AFTER vs receiver BEFORE/AFTER; permanent tank seals: master
    vs sender and receiver observed numbers.
    """
    lp, rp = payload_from_entry(left), payload_from_entry(right)
    lc, lt, li = _stage(lp, "after")
    rc, rt, ri = _stage(rp, "before")
    totals = [{"parameter": key, "left": rnd(lc.get(key)), "right": rnd(rc.get(key)),
               "delta": rnd(num(lc.get(key)) - num(rc.get(key)))} for key in TOTAL_KEYS]
    quality = [{"parameter": key, "left": lc.get(key), "right": rc.get(key)} for key in ("API60", "VCF")]
    quality += [{"parameter": label, "left": li.get(key), "right": ri.get(key)} for key, label in
                (("bswPct", "BS&W %"), ("tankTemp", "Tank Temp"), ("sampleTemp", "Sample Temp"), ("obsApi", "Observed API"))]
    tanks = list(dict.fromkeys(list(lt.keys()) + list(rt.keys())))
    per_tank = []
    for tank in tanks:
        a, b = lt.get(tank) or {}, rt.get(tank) or {}
        row = {"tank": tank}
        for key in ("totalDip", "waterDip", "tovCorrected", "fwCorrected"):
            row[key] = {"left": rnd(a.get(key)), "right": rnd(b.get(key)), "delta": rnd(num(a.get(key)) - num(b.get(key)))}
        per_tank.append(row)
    left_seals = ((lp.get("seals") or {}).get("after") or {})
    right_seals = ((rp.get("seals") or {}).get("after") or {})
    temp_checks = []
    for key in TEMP_SEAL_KEYS:
        sender = text((left_seals.get("temporary") or {}).get(key))
        receiver = text((right_seals.get("temporary") or {}).get(key))
        if not sender and not receiver:
            status = "MISSING_BOTH"
        elif not sender:
            status = "MISSING_SENDER"
        elif not receiver:
            status = "MISSING_RECEIVER"
        else:
            status = "MATCH" if sender.upper() == receiver.upper() else "MISMATCH"
        temp_checks.append({"seal": TEMP_SEAL_LABELS[key], "key": key, "sender": sender, "receiver": receiver, "status": status})
    permanent = []
    left_tank_seals, right_tank_seals = left_seals.get("tankSeals") or {}, right_seals.get("tankSeals") or {}
    for tank in sorted(set(left_tank_seals) | set(right_tank_seals)):
        for position in PERMANENT_SEAL_POSITIONS:
            a = (left_tank_seals.get(tank) or {}).get(position) or {}
            b = (right_tank_seals.get(tank) or {}).get(position) or {}
            master = text(a.get("master") or b.get("master"))
            if not master and not a.get("observed") and not b.get("observed"):
                continue
            sender, receiver = text(a.get("observed")), text(b.get("observed"))
            ok = bool(master) and sender == master and receiver == master
            permanent.append({"tank": tank, "position": position, "master": master, "sender": sender,
                              "receiver": receiver, "status": "MATCH" if ok else "MISMATCH"})
    nsv = next(t for t in totals if t["parameter"] == "NSV")
    return {
        "comparison_type": COMPARISON_TYPE, "asset_id": left.asset_id, "asset_code": left.asset_code_snapshot,
        "asset_name": left.asset_name_snapshot, "left_ticket": ticket_ref(left), "right_ticket": ticket_ref(right),
        "left_stage": "AFTER", "right_stage": "BEFORE", "totals": totals, "quality": quality, "per_tank": per_tank,
        "temporary_seal_checks": temp_checks, "permanent_seal_checks": permanent,
        "nsv_delta_bbl": nsv["delta"],
        "nsv_delta_pct": rnd(nsv["delta"] / nsv["left"] * 100, 4) if nsv["left"] else 0.0,
        "seal_issue_count": sum(1 for c in temp_checks if c["status"] not in ("MATCH", "MISSING_BOTH"))
        + sum(1 for c in permanent if c["status"] != "MATCH"),
    }


# ---------------------------------------------------------------------------
# Tanker: role, seals and quantity comparison (OTMS tanker_tracking)
# ---------------------------------------------------------------------------
TANKER_SEALS = (("C1", "seal_c1"), ("C2", "seal_c2"), ("M1", "seal_m1"), ("M2", "seal_m2"))
RECEIVER_KEYWORDS = ("RECEIPT", "RECEIVE", "UNLOAD", "DISCHARGE")


def tanker_role(entry) -> str:
    if entry.linked_ticket_id or entry.operation_category_snapshot == "RECEIPT":
        return "RECEIVER"
    words = f"{entry.operation_code_snapshot} {entry.operation_label_snapshot}".upper()
    return "RECEIVER" if any(k in words for k in RECEIVER_KEYWORDS) else "SENDER"


def tanker_ticket(entry):
    if not entry:
        return None
    row = entry.tanker
    data = ticket_ref(entry)
    data.update(
        prime_mover_code=row.prime_mover_number if row else None, prime_mover_name=row.prime_mover_name if row else None,
        chassis_number=row.chassis_number if row else None, compartment=row.compartment if row else None,
        total_dip_cm=num(row.total_dip_cm) if row else 0, water_dip_cm=num(row.water_dip_cm) if row else 0,
        tank_temperature=num(row.tank_temperature) if row else 0, sample_temperature=num(row.sample_temperature) if row else 0,
        observed_api=num(row.observed_api) if row and row.observed_api is not None else None,
        api60=num(row.api60) if row else 0, vcf=num(row.vcf) if row else 0, bsw_percent=num(row.bsw_percent) if row else 0,
        tov_bbl=num(row.tov_bbl) if row else 0, free_water_bbl=num(row.free_water_bbl) if row else 0,
        gov_bbl=num(row.gov_bbl) if row else 0, gsv_bbl=num(row.gsv_bbl) if row else 0,
        bsw_bbl=num(row.bsw_bbl) if row else 0, nsv_bbl=num(row.nsv_bbl) if row else 0,
        lt=num(row.lt) if row else 0, mt=num(row.mt) if row else 0,
        **{f"seal_{name.lower()}": (getattr(row, attr) or "") if row else "" for name, attr in TANKER_SEALS},
    )
    return data


def tanker_seal_checks(sender, receiver):
    checks = []
    for name, _attr in TANKER_SEALS:
        a = text((sender or {}).get(f"seal_{name.lower()}"))
        b = text((receiver or {}).get(f"seal_{name.lower()}"))
        if not a and not b:
            status = "NOT_ENTERED"
        elif a and not b:
            status = "RECEIVER_MISSING"
        elif b and not a:
            status = "SENDER_MISSING"
        else:
            status = "MATCHED" if a.upper() == b.upper() else "MISMATCH"
        checks.append({"seal_name": name, "sender_value": a, "receiver_value": b, "status": status})
    return checks


def tanker_quantity(sender, receiver):
    if not sender or not receiver:
        return None
    result = {}
    for key, label in (("gov_bbl", "gov"), ("gsv_bbl", "gsv"), ("nsv_bbl", "nsv"), ("lt", "lt"), ("mt", "mt")):
        result[f"sender_{label}"] = rnd(sender[key])
        result[f"receiver_{label}"] = rnd(receiver[key])
        result[f"{label}_variance"] = rnd(num(receiver[key]) - num(sender[key]))  # receiver - sender (OTMS)
    result["nsv_variance_pct"] = rnd(result["nsv_variance"] / sender["nsv_bbl"] * 100, 4) if num(sender["nsv_bbl"]) else 0.0
    return result


def tanker_status(sender, receiver, seal_checks, quantity, acknowledgement):
    if acknowledgement is not None and acknowledgement.status == "Closed":
        return "CLOSED"
    if not sender:
        return "NO_SENDER"
    if not receiver:
        return "ACKNOWLEDGED" if acknowledgement is not None and acknowledgement.status == "Acknowledged" else "PENDING_RECEIPT"
    if any(c["status"] in ("MISMATCH", "RECEIVER_MISSING", "SENDER_MISSING") for c in seal_checks):
        return "SEAL_MISMATCH"
    if quantity:
        return "QUANTITY_VARIANCE" if abs(quantity["nsv_variance"]) > 0 else "MATCHED"
    return "RECEIVED"


TANKER_STATUSES = ("PENDING_RECEIPT", "ACKNOWLEDGED", "SEAL_MISMATCH", "QUANTITY_VARIANCE", "MATCHED", "RECEIVED", "NO_SENDER", "CLOSED")


def tanker_summary(rows):
    counts = {status: 0 for status in TANKER_STATUSES}
    for row in rows:
        counts[row["tracking_status"]] = counts.get(row["tracking_status"], 0) + 1
    return {
        "all": len(rows), "pending_receipt": counts["PENDING_RECEIPT"], "acknowledged": counts["ACKNOWLEDGED"],
        "seal_mismatch": counts["SEAL_MISMATCH"], "quantity_variance": counts["QUANTITY_VARIANCE"],
        "matched": counts["MATCHED"], "received": counts["RECEIVED"], "no_sender": counts["NO_SENDER"], "closed": counts["CLOSED"],
        "compared": sum(1 for row in rows if row["quantity_comparison"]),
    }


# ---------------------------------------------------------------------------
# Shuttle / FSO (OTMS shuttle_movement_totals and FSO reports)
# ---------------------------------------------------------------------------


def _words(entry):
    return f"{entry.operation_code_snapshot} {entry.operation_label_snapshot}".upper().replace("_", " ")


def shuttle_ticket(entry):
    row = entry.shuttle or entry.fso
    data = ticket_ref(entry)
    data.update(
        event_time=row.event_time if row else None,
        opening_stock_bbl=num(row.opening_stock_bbl) if row else 0, opening_water_bbl=num(row.opening_water_bbl) if row else 0,
        closing_stock_bbl=num(row.closing_stock_bbl) if row else 0, closing_water_bbl=num(row.closing_water_bbl) if row else 0,
        net_stock_bbl=num(row.net_stock_bbl) if row else 0, net_water_bbl=num(row.net_water_bbl) if row else 0,
        remarks=row.remarks if row else None,
    )
    if entry.shuttle:
        data["barge_reference"] = entry.shuttle.barge_reference
    if entry.fso:
        data.update(shuttle_number=entry.fso.shuttle_number, vessel_name=entry.fso.vessel_name,
                    vessel_quantity_bbl=num(entry.fso.vessel_quantity_bbl),
                    source_shuttle_discharge_bbl=num(entry.fso.source_shuttle_discharge_bbl) if entry.fso.source_shuttle_discharge_bbl is not None else None,
                    variance_bbl=num(entry.fso.variance_bbl))
    return data


def shuttle_movement_totals(entries):
    """OTMS ``shuttle_movement_totals``: receipts are loading / STS-in / top-up;
    discharge is unloading that is not STS-out; transfers are reported apart.
    Quantities are ``abs(net stock) + abs(net water)`` (never netted)."""
    totals = {"net_receipt_bbl": 0.0, "net_discharge_bbl": 0.0, "transfer_in_bbl": 0.0, "transfer_out_bbl": 0.0,
              "tov_bbl": 0.0, "fw_bbl": 0.0, "nsv_bbl": 0.0}
    for entry in entries:
        row = entry.shuttle
        if not row:
            continue
        stock, water = num(row.net_stock_bbl), num(row.net_water_bbl)
        qty = abs(stock) + abs(water)
        totals["tov_bbl"] += stock + water
        totals["fw_bbl"] += water
        totals["nsv_bbl"] += stock
        words = _words(entry)
        sts_out = "STS OUT" in words
        sts_in = "STS IN" in words
        if sts_out:
            totals["transfer_out_bbl"] += qty
        elif sts_in:
            totals["transfer_in_bbl"] += qty
            totals["net_receipt_bbl"] += qty
        elif "UNLOAD" in words or "DISCHARGE" in words:
            totals["net_discharge_bbl"] += qty
        elif "LOAD" in words or "TOP UP" in words or "TOPUP" in words or "RECEIPT" in words:
            totals["net_receipt_bbl"] += qty
    return {k: rnd(v) for k, v in totals.items()}


def fso_movement(entry):
    row = entry.fso
    return abs(num(row.net_stock_bbl)) + abs(num(row.net_water_bbl)) if row else 0.0


def fso_voyage_totals(entries):
    """OTMS ``fso-tracking`` group figures: receipts, exports and the shuttle
    discharge vs FSO receipt variance (discharge - receipt)."""
    receipt = export = water_in = water_out = discharge = 0.0
    for entry in entries:
        row = entry.fso
        if not row:
            continue
        qty = fso_movement(entry)
        if entry.operation_sign_snapshot == "IN":
            receipt += qty
            water_in += abs(num(row.net_water_bbl))
        elif entry.operation_sign_snapshot == "OUT":
            export += qty
            water_out += abs(num(row.net_water_bbl))
        if row.source_shuttle_discharge_bbl is not None:
            discharge = max(discharge, num(row.source_shuttle_discharge_bbl))
    variance = discharge - receipt if discharge else 0.0
    return {"fso_receipt_bbl": rnd(receipt), "fso_export_bbl": rnd(export), "water_in_bbl": rnd(water_in),
            "water_out_bbl": rnd(water_out), "shuttle_discharge_bbl": rnd(discharge), "variance_bbl": rnd(variance),
            "variance_pct": rnd(variance / discharge * 100, 4) if discharge else 0.0}


def fso_otr_rows(entries):
    """FSO OTR (transaction-wise). HCA has no Location Accounting Day Setting
    yet, so the accounting date is the operation date."""
    rows, totals = [], {"receipt": 0.0, "export": 0.0, "movement": 0.0, "variance": 0.0, "compare_variance": 0.0}
    for entry in sorted(entries, key=lambda e: (e.operation_date, e.fso.event_time if e.fso else "", e.id)):
        row = entry.fso
        if not row:
            continue
        sign = entry.operation_sign_snapshot
        qty = fso_movement(entry)
        vessel = num(row.vessel_quantity_bbl)
        variance = vessel - qty if sign == "IN" else 0.0
        source = num(row.source_shuttle_discharge_bbl)
        compare = source - qty if sign == "IN" and source > 0 else 0.0
        rows.append({
            "transaction_id": entry.id, "ticket_number": entry.ticket_number, "accounting_date": entry.operation_date,
            "event_time": row.event_time, "location_code": entry.location.location_code, "fso_asset_code": entry.asset_code_snapshot,
            "shuttle_number": row.shuttle_number or entry.convoy_number, "operation_label": entry.operation_label_snapshot,
            "operation_sign": sign, "vessel_name": row.vessel_name, "vessel_quantity_bbl": rnd(vessel),
            "opening_stock_bbl": num(row.opening_stock_bbl), "closing_stock_bbl": num(row.closing_stock_bbl),
            "net_stock_bbl": num(row.net_stock_bbl), "net_water_bbl": num(row.net_water_bbl),
            "movement_qty_bbl": rnd(qty), "variance_bbl": rnd(variance), "source_shuttle_discharge_bbl": rnd(source),
            "compare_variance_bbl": rnd(compare), "remarks": row.remarks,
        })
        totals["movement"] += qty
        totals["variance"] += variance
        totals["compare_variance"] += compare
        if sign == "IN":
            totals["receipt"] += qty
        elif sign == "OUT":
            totals["export"] += qty
    return rows, {f"total_{k}_bbl": rnd(v) for k, v in totals.items()}


def fso_material_balance(entries):
    buckets = {}
    for entry in entries:
        if entry.fso:
            buckets.setdefault(entry.operation_date, []).append(entry)
    rows, previous_close = [], None
    for day in sorted(buckets):
        items = sorted(buckets[day], key=lambda e: (e.fso.event_time or "00:00", e.id))
        opening = num(items[0].fso.opening_stock_bbl) if previous_close is None else previous_close
        receipt = sum(fso_movement(e) for e in items if e.operation_sign_snapshot == "IN")
        export = sum(fso_movement(e) for e in items if e.operation_sign_snapshot == "OUT")
        book = opening + receipt - export
        physical = num(items[-1].fso.closing_stock_bbl)
        rows.append({"accounting_date": day, "opening_stock_bbl": rnd(opening), "receipt_bbl": rnd(receipt),
                     "export_bbl": rnd(export), "book_closing_bbl": rnd(book), "physical_closing_bbl": rnd(physical),
                     "physical_closing_water_bbl": rnd(items[-1].fso.closing_water_bbl), "loss_gain_bbl": rnd(physical - book)})
        previous_close = physical
    return rows


def fso_outturn(entries):
    buckets = {}
    for entry in entries:
        row = entry.fso
        if not row:
            continue
        shuttle = text(row.shuttle_number or entry.convoy_number)
        if not shuttle:
            continue
        bucket = buckets.setdefault((entry.operation_date, shuttle), {"receipt": 0.0, "discharge": 0.0})
        if entry.operation_sign_snapshot == "IN":
            bucket["receipt"] += fso_movement(entry)
        if row.source_shuttle_discharge_bbl is not None:
            bucket["discharge"] = max(bucket["discharge"], num(row.source_shuttle_discharge_bbl))
    rows, totals = [], {"discharge": 0.0, "receipt": 0.0, "variance": 0.0}
    for (day, shuttle) in sorted(buckets):
        b = buckets[(day, shuttle)]
        variance = b["discharge"] - b["receipt"]
        rows.append({"accounting_date": day, "shuttle_number": shuttle, "shuttle_discharge_bbl": rnd(b["discharge"]),
                     "fso_receipt_bbl": rnd(b["receipt"]), "variance_bbl": rnd(variance),
                     "variance_pct": rnd(variance / b["discharge"] * 100, 4) if b["discharge"] else 0.0})
        totals["discharge"] += b["discharge"]
        totals["receipt"] += b["receipt"]
        totals["variance"] += variance
    return rows, {"total_shuttle_discharge_bbl": rnd(totals["discharge"]), "total_fso_receipt_bbl": rnd(totals["receipt"]),
                  "total_variance_bbl": rnd(totals["variance"]),
                  "total_variance_pct": rnd(totals["variance"] / totals["discharge"] * 100, 4) if totals["discharge"] else 0.0}
