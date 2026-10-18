"""Operation Tracking: register, barge / tanker / shuttle / FSO tracking and reports."""
from copy import deepcopy

from app.database import SessionLocal
from app.models import AuditLog, OperationVoyage

from test_operation_entries import (  # noqa: F401 - fixtures are registered by import
    create, empty_table11, location, make_case, person, post, tag, transition,
)

API = "/api/operation-tracking"


def approve(client, headers, ticket):
    ticket = transition(client, headers, ticket, "submit")
    return transition(client, headers, ticket, "approve")


def audited(action, module):
    with SessionLocal() as db:
        return db.query(AuditLog).filter_by(action=action, module_name=module).count()


def test_register_status_counts_filters_and_export(client, admin_headers, make_case):
    case = make_case("TANK_OPERATIONS")
    loc = case["loc"]
    first = create(client, admin_headers, case)
    second_body = deepcopy(case["body"]); second_body["convoy_number"] = tag("VOY")
    second = post(client, admin_headers, "/api/operation-entries", second_body)
    transition(client, admin_headers, second, "submit")
    r = client.get(f"{API}/transactions", params={"location_id": loc["id"]}, headers=admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status_counts"]["All"] == 2 and data["status_counts"]["Draft"] == 1 and data["status_counts"]["Submitted"] == 1
    only = client.get(f"{API}/transactions", params={"location_id": loc["id"], "status": "Submitted"}, headers=admin_headers).json()
    assert [i["id"] for i in only["items"]] == [second["id"]]
    assert only["status_counts"]["All"] == 2  # tab counts ignore the status filter
    assert only["items"][0]["payload"] is None
    for fmt in ("csv", "xlsx", "pdf"):
        e = client.get(f"{API}/transactions/export", params={"location_id": loc["id"], "format": fmt}, headers=admin_headers)
        assert e.status_code == 200, e.text
    assert first["ticket_number"].encode() in client.get(f"{API}/transactions/export", params={"location_id": loc["id"]}, headers=admin_headers).content
    assert audited("Export", "Operation Transaction Register") >= 4


def test_register_permission_is_separate_from_entry_page(client, admin_headers, make_case):
    case = make_case("TANK_OPERATIONS")
    ticket = create(client, admin_headers, case)
    viewer, _, _ = person(client, admin_headers, ["operation_transactions:read"], [case["loc"]["id"]])
    assert client.get(f"{API}/transactions", headers=viewer).status_code == 200
    assert client.get(f"/api/operation-entries/{ticket['id']}", headers=viewer).status_code == 200
    assert client.get(f"/api/operation-entries/{ticket['id']}/history", headers=viewer).status_code == 200
    assert client.get("/api/operation-entries", headers=viewer).status_code == 403  # Operation Entry page stays separate
    denied = client.post(f"/api/operation-entries/{ticket['id']}/submit", json={"version": ticket["version"], "review_confirmed": True}, headers=viewer)
    assert denied.status_code == 403
    approver, _, _ = person(client, admin_headers, ["operation_transactions:read", "operation_submissions:create", "operation_reviews:create"], [case["loc"]["id"]])
    ok = client.post(f"/api/operation-entries/{ticket['id']}/submit", json={"version": ticket["version"], "review_confirmed": True}, headers=approver)
    assert ok.status_code == 200, ok.text
    outsider, _, _ = person(client, admin_headers, ["operation_transactions:read"], [location(client, admin_headers)["id"]])
    assert client.get(f"/api/operation-entries/{ticket['id']}", headers=outsider).status_code == 404
    nobody, _, _ = person(client, admin_headers, ["operation_entries:read"], [case["loc"]["id"]])
    for path in ("/transactions", "/barge/voyages", "/tanker", "/shuttle/voyages", "/fso/voyages", "/tanker/report"):
        assert client.get(API + path, headers=nobody).status_code == 403, path


def _barge_sender(client, admin_headers, make_case):
    case = make_case("BARGE_OPERATIONS", category="DISPATCH", scope="Global")
    dest = location(client, admin_headers)
    case["body"].update(receiver_location_id=dest["id"], destination_location_id=dest["id"])
    sender = approve(client, admin_headers, create(client, admin_headers, case))
    return case, dest, sender


def _barge_receiver(client, admin_headers, case, dest, sender):
    op = post(client, admin_headers, "/api/operations", dict(location_id=dest["id"], operation_type_code="BARGE_OPERATIONS",
              operation_category="RECEIPT", operation_code=tag("UNL"), operation_label=tag("Unloading")))
    body = deepcopy(case["body"])
    body.update(operation_id=op["id"], location_id=dest["id"], sender_location_id=case["loc"]["id"], linked_ticket_id=sender["id"])
    body.pop("barge_event_type", None)
    return approve(client, admin_headers, post(client, admin_headers, "/api/operation-entries", body))


def test_barge_tracking_receipt_comparison_timeline_and_closure(client, admin_headers, make_case):
    case, dest, sender = _barge_sender(client, admin_headers, make_case)
    convoy = sender["convoy_number"]
    listing = client.get(f"{API}/barge/voyages", params={"search": convoy}, headers=admin_headers).json()
    assert listing["open_count"] == 1 and listing["items"][0]["convoy_number"] == convoy
    assert listing["items"][0]["destination_location_codes"] == [dest["location_code"]]
    state = client.get(f"{API}/barge/convoy", params={"convoy_number": convoy}, headers=admin_headers).json()
    barge = state["barges"][0]
    assert barge["pending_sender_ticket"]["id"] == sender["id"] and not barge["received"]
    assert barge["timeline"][0]["event_type"] == "LOAD_1"
    assert not state["can_close"] and any("two Approved" in b for b in state["close_blockers"])
    asset_id = case["asset"]["id"]
    assert client.post(f"{API}/barge/receipts/revoke", json={"convoy_number": convoy, "asset_id": asset_id, "remarks": "x" * 5}, headers=admin_headers).status_code == 400
    r = client.post(f"{API}/barge/receipts", json={"convoy_number": convoy, "asset_id": asset_id, "remarks": "Arrived"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    barge = r.json()["barges"][0]
    assert barge["received"] and barge["receipt_location_code"] == dest["location_code"]
    assert [e["event_type"] for e in barge["timeline"]] == ["LOAD_1", "RECEIVED"]
    assert client.post(f"{API}/barge/receipts", json={"convoy_number": convoy, "asset_id": asset_id}, headers=admin_headers).status_code == 400

    receiver = _barge_receiver(client, admin_headers, case, dest, sender)
    state = client.get(f"{API}/barge/convoy", params={"convoy_number": convoy}, headers=admin_headers).json()
    barge = state["barges"][0]
    assert barge["receiver_ticket_exists"] and barge["pending_sender_ticket"] is None
    comparison = barge["comparisons"][0]
    assert comparison["left_ticket"]["id"] == sender["id"] and comparison["right_ticket"]["id"] == receiver["id"]
    tov = next(t for t in comparison["totals"] if t["parameter"] == "TOV")
    assert tov["left"] == round(sender["payload"]["calculated"]["after"]["TOV"], 3)
    assert tov["right"] == round(receiver["payload"]["calculated"]["before"]["TOV"], 3)
    assert tov["delta"] == round(tov["left"] - tov["right"], 3)
    assert {c["status"] for c in comparison["temporary_seal_checks"]} == {"MATCH"}
    assert {t["tank"] for t in comparison["per_tank"]} == {"1P", "1S"}
    assert state["can_close"], state["close_blockers"]
    revoke = client.post(f"{API}/barge/receipts/revoke", json={"convoy_number": convoy, "asset_id": asset_id, "remarks": "Wrong barge"}, headers=admin_headers)
    assert revoke.status_code == 400 and "receiving ticket" in revoke.text

    fix = client.put(f"{API}/barge/timeline", json={"convoy_number": convoy, "entry_id": sender["id"], "event_type": "LOAD_2_TOPUP", "remarks": "Top-up load"}, headers=admin_headers)
    assert fix.status_code == 200, fix.text
    event = next(e for e in fix.json()["barges"][0]["timeline"] if e["ticket_id"] == sender["id"])
    assert event["event_type"] == "LOAD_2_TOPUP" and event["source"] == "CORRECTED"
    fix = client.put(f"{API}/barge/timeline", json={"convoy_number": convoy, "entry_id": sender["id"], "event_type": "LOAD_1", "remarks": "Restore first load"}, headers=admin_headers)
    assert fix.status_code == 200
    assert audited("Fix Timeline", "Barge Tracking") >= 2

    exported = client.get(f"{API}/barge/convoy/export", params={"convoy_number": convoy, "format": "csv"}, headers=admin_headers)
    assert exported.status_code == 200 and b"Temporary Seal" in exported.content
    assert client.post(f"{API}/barge/close", json={"convoy_number": convoy, "remarks": "ok"}, headers=admin_headers).status_code == 422
    closed = client.post(f"{API}/barge/close", json={"convoy_number": convoy, "remarks": "Movement reconciled"}, headers=admin_headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"
    with SessionLocal() as db:
        assert {v.status for v in db.query(OperationVoyage).filter_by(reference=convoy, operation_type_code="BARGE_OPERATIONS")} == {"CLOSED"}
    blocked = client.post("/api/operation-entries", json={**case["body"], "operation_date": "2026-10-18"}, headers=admin_headers)
    assert blocked.status_code == 400 and "CLOSED" in blocked.text
    assert client.get(f"{API}/barge/voyages", params={"search": convoy, "tab": "CLOSED"}, headers=admin_headers).json()["closed_count"] == 1
    assert client.post(f"{API}/barge/receipts", json={"convoy_number": convoy, "asset_id": asset_id}, headers=admin_headers).status_code == 400
    reopened = client.post(f"{API}/barge/reopen", json={"convoy_number": convoy, "remarks": "Late correction"}, headers=admin_headers)
    assert reopened.status_code == 200 and reopened.json()["status"] == "OPEN"
    assert audited("Close Barge Movement", "Barge Tracking") >= 1 and audited("Reopen Barge Movement", "Barge Tracking") >= 1


def test_barge_tracking_permissions(client, admin_headers, make_case):
    case, dest, sender = _barge_sender(client, admin_headers, make_case)
    convoy = sender["convoy_number"]
    viewer, _, _ = person(client, admin_headers, ["barge_tracking:read"], [dest["id"]])
    assert client.get(f"{API}/barge/convoy", params={"convoy_number": convoy}, headers=viewer).status_code == 200
    body = {"convoy_number": convoy, "asset_id": case["asset"]["id"], "remarks": "Arrived"}
    assert client.post(f"{API}/barge/receipts", json=body, headers=viewer).status_code == 403
    assert client.post(f"{API}/barge/close", json={"convoy_number": convoy, "remarks": "Close it"}, headers=viewer).status_code == 403
    assert client.put(f"{API}/barge/timeline", json={"convoy_number": convoy, "entry_id": sender["id"], "event_type": "UNLOAD", "remarks": "nope"}, headers=viewer).status_code == 403
    receiver_clerk, _, _ = person(client, admin_headers, ["barge_tracking:read", "shipment_receipts:create"], [dest["id"]])
    assert client.post(f"{API}/barge/receipts", json=body, headers=receiver_clerk).status_code == 200
    assert client.post(f"{API}/barge/receipts/revoke", json=body, headers=receiver_clerk).status_code == 403
    stranger, _, _ = person(client, admin_headers, ["barge_tracking:read"], [location(client, admin_headers)["id"]])
    assert client.get(f"{API}/barge/convoy", params={"convoy_number": convoy}, headers=stranger).status_code == 404


def test_tanker_tracking_acknowledge_compare_close_and_report(client, admin_headers, make_case):
    case = make_case("TANKER_OPERATIONS", category="DISPATCH", scope="Global")
    dest = location(client, admin_headers)
    case["body"].update(receiver_location_id=dest["id"], destination_location_id=dest["id"])
    sender = approve(client, admin_headers, create(client, admin_headers, case))
    params = {"convoy_number": sender["convoy_number"]}
    rows = client.get(f"{API}/tanker", params=params, headers=admin_headers).json()
    assert rows["summary"]["pending_receipt"] == 1
    row = rows["items"][0]
    assert row["tracking_status"] == "PENDING_RECEIPT" and row["sender_ticket"]["seal_c1"] == "C-1"
    wrong = client.post(f"{API}/tanker/acknowledgements", json={"sender_entry_id": sender["id"], "receiver_location_id": case["loc"]["id"]}, headers=admin_headers)
    assert wrong.status_code == 400
    ack = client.post(f"{API}/tanker/acknowledgements", json={"sender_entry_id": sender["id"], "receiver_location_id": dest["id"], "remarks": "Arrived"}, headers=admin_headers)
    assert ack.status_code == 201, ack.text
    ack = ack.json()
    assert client.post(f"{API}/tanker/acknowledgements", json={"sender_entry_id": sender["id"], "receiver_location_id": dest["id"]}, headers=admin_headers).status_code == 409
    row = client.get(f"{API}/tanker", params=params, headers=admin_headers).json()["items"][0]
    assert row["tracking_status"] == "ACKNOWLEDGED" and row["can_create_receiver"]
    assert client.post(f"{API}/tanker/acknowledgements/{ack['id']}/close", json={"remarks": "Too early"}, headers=admin_headers).status_code == 400

    op = post(client, admin_headers, "/api/operations", dict(location_id=dest["id"], operation_type_code="TANKER_OPERATIONS",
              operation_category="RECEIPT", operation_code=tag("REC"), operation_label=tag("Receipt")))
    body = deepcopy(case["body"])
    body.update(operation_id=op["id"], location_id=dest["id"], sender_location_id=case["loc"]["id"], linked_ticket_id=sender["id"])
    body["payload"]["inputs"].update(sealC2="BROKEN", totalDipCm=99)
    receiver = approve(client, admin_headers, post(client, admin_headers, "/api/operation-entries", body))
    assert client.post(f"{API}/tanker/acknowledgements/{ack['id']}/revoke", json={"remarks": "Wrong tanker"}, headers=admin_headers).status_code == 400
    data = client.get(f"{API}/tanker", params=params, headers=admin_headers).json()
    row = data["items"][0]
    assert row["tracking_status"] == "SEAL_MISMATCH" and data["summary"]["compared"] == 1
    assert next(c for c in row["seal_checks"] if c["seal_name"] == "C2")["status"] == "MISMATCH"
    q = row["quantity_comparison"]
    assert q["nsv_variance"] == round(receiver["payload"]["calculated"]["nsvBbl"] - sender["payload"]["calculated"]["nsvBbl"], 3)
    filtered = client.get(f"{API}/tanker", params={**params, "status": "MATCHED"}, headers=admin_headers).json()
    assert filtered["total"] == 0 and filtered["summary"]["all"] == 1
    closed = client.post(f"{API}/tanker/acknowledgements/{ack['id']}/close", json={"remarks": "Variance accepted"}, headers=admin_headers)
    assert closed.status_code == 200 and closed.json()["status"] == "Closed"
    assert client.get(f"{API}/tanker", params=params, headers=admin_headers).json()["items"][0]["tracking_status"] == "CLOSED"
    for fmt in ("csv", "xlsx", "pdf"):
        assert client.get(f"{API}/tanker/export", params={**params, "format": fmt}, headers=admin_headers).status_code == 200
    report = client.get(f"{API}/tanker/report", params=params, headers=admin_headers).json()
    assert report["total"] == 2
    assert report["totals"]["nsv_bbl"] == round(sender["payload"]["calculated"]["nsvBbl"] + receiver["payload"]["calculated"]["nsvBbl"], 3)
    export = client.get(f"{API}/tanker/report/export", params={**params, "format": "csv"}, headers=admin_headers)
    assert export.status_code == 200 and b"BROKEN" in export.content
    assert audited("Acknowledge Receipt", "Tanker Tracking") >= 1 and audited("Close Tanker Movement", "Tanker Tracking") >= 1


def test_shuttle_and_fso_tracking(client, admin_headers, make_case):
    case = make_case("SHUTTLE_OPERATIONS", category="DISPATCH")
    client.put(f"/api/operations/{case['op']['id']}", headers=admin_headers, json={"operation_label": tag("UNLOADING")})
    shuttle = approve(client, admin_headers, create(client, admin_headers, case))
    number = shuttle["convoy_number"]
    data = client.get(f"{API}/shuttle/voyages", params={"shuttle_number": number}, headers=admin_headers).json()
    assert data["open_count"] == 1 and data["closed_count"] == 0
    voyage = data["items"][0]
    assert voyage["net_discharge_bbl"] == 52 and voyage["ticket_count"] == 1  # abs(50) + abs(2)
    detail = client.get(f"{API}/shuttle/voyages/{voyage['id']}", headers=admin_headers).json()
    assert detail["tickets"][0]["ticket_number"] == shuttle["ticket_number"]
    assert client.get(f"{API}/fso/voyages/{voyage['id']}", headers=admin_headers).status_code == 404  # wrong kind
    closed = client.post(f"{API}/shuttle/voyages/{voyage['id']}/close", json={"remarks": "Discharged to FSO"}, headers=admin_headers)
    assert closed.status_code == 200 and closed.json()["voyage_status"] == "CLOSED"
    assert client.get(f"{API}/shuttle/voyages", params={"shuttle_number": number, "tab": "CLOSED"}, headers=admin_headers).json()["total"] == 1
    assert client.get("/api/operation-entries/closed-shuttle", params={"shuttle_number": number}, headers=admin_headers).json()["rows"][0]["netDischargeBbl"] == 52
    assert client.get(f"{API}/shuttle/voyages/{voyage['id']}/export", params={"format": "pdf"}, headers=admin_headers).status_code == 200
    assert client.post(f"{API}/shuttle/voyages/{voyage['id']}/reopen", json={"remarks": "Reopen for correction"}, headers=admin_headers).json()["voyage_status"] == "OPEN"
    assert audited("Close Shuttle Voyage", "Shuttle Tracking") >= 1

    fso_case = make_case("FSO_OPERATIONS", category="RECEIPT")
    fso = approve(client, admin_headers, create(client, admin_headers, fso_case))
    filters = dict(location_id=fso_case["loc"]["id"], asset_id=fso_case["asset"]["id"], date_from="2026-10-01", date_to="2026-10-31")
    otr = client.get(f"{API}/fso/reports/otr", params=filters, headers=admin_headers).json()
    assert otr["rows"][0]["ticket_number"] == fso["ticket_number"]
    assert otr["rows"][0]["movement_qty_bbl"] == 52 and otr["rows"][0]["variance_bbl"] == 8  # 60 vessel qty - 52
    assert otr["totals"]["total_receipt_bbl"] == 52
    mb = client.get(f"{API}/fso/reports/material-balance", params=filters, headers=admin_headers).json()["rows"][0]
    assert mb["opening_stock_bbl"] == 100 and mb["receipt_bbl"] == 52 and mb["book_closing_bbl"] == 152 and mb["loss_gain_bbl"] == -2
    outturn = client.get(f"{API}/fso/reports/outturn", params=filters, headers=admin_headers).json()
    assert outturn["rows"][0]["fso_receipt_bbl"] == 52
    assert client.get(f"{API}/fso/reports/otr/export", params={**filters, "format": "xlsx"}, headers=admin_headers).status_code == 200
    fso_voyages = client.get(f"{API}/fso/voyages", params={"location_id": fso_case["loc"]["id"]}, headers=admin_headers).json()
    assert fso_voyages["items"][0]["fso_receipt_bbl"] == 52
    shuttle_only, _, _ = person(client, admin_headers, ["shuttle_tracking:read"], [fso_case["loc"]["id"]])
    assert client.get(f"{API}/fso/voyages", headers=shuttle_only).status_code == 403
    assert client.get(f"{API}/fso/reports/otr", params=filters, headers=shuttle_only).status_code == 403
    no_close, _, _ = person(client, admin_headers, ["shuttle_tracking:read"], [case["loc"]["id"]])
    assert client.post(f"{API}/shuttle/voyages/{voyage['id']}/close", json={"remarks": "Discharged"}, headers=no_close).status_code == 403


def test_operation_tracking_module_dashboard(client, admin_headers):
    r = client.get("/api/dashboard/modules/operation-tracking", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert {link["path"] for link in r.json()["quick_links"]} >= {"/operation-transactions", "/barge-tracking", "/tanker-tracking",
                                                                  "/shuttle-tracking", "/fso-tracking", "/tanker-transaction-report"}
    summary = client.get("/api/dashboard/summary", headers=admin_headers)
    assert summary.status_code == 200, summary.text
    module = next(m for m in summary.json()["modules"] if m["key"] == "operation-tracking")
    assert module["status"] == "Available" and "barge_tracking:read" in module["any_permissions"]
    loc = location(client, admin_headers)
    tracker, _, _ = person(client, admin_headers, ["barge_tracking:read"], [loc["id"]])
    assert client.get("/api/dashboard/modules/operation-tracking", headers=tracker).status_code == 200
    # Tracking-only users can use the bounded location / asset filter lookups.
    lookup = client.get("/api/operation-entries/lookups/locations", headers=tracker)
    assert lookup.status_code == 200 and [x["id"] for x in lookup.json()["items"]] == [loc["id"]]
    entry_only, _, _ = person(client, admin_headers, ["operation_entries:read"], [loc["id"]])
    assert client.get("/api/dashboard/modules/operation-tracking", headers=entry_only).status_code == 403
