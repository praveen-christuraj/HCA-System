"""Comprehensive integration tests for all OTMS modules ported into HCA System."""

from __future__ import annotations

import hmac
import hashlib
import struct
import time

from app.database import Base


def _compute_totp(secret_b32: str) -> str:
    import base64

    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad, casefold=True)
    counter = int(time.time() // 30)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000
    return f"{code:06d}"


def test_zero_json_columns_across_all_models():
    for table_name, table in Base.metadata.tables.items():
        for col in table.columns:
            col_type = col.type.__class__.__name__.upper()
            assert "JSON" not in col_type, f"Forbidden JSON column {table_name}.{col.name}"


def test_permissions_export_and_user_locations_and_access_summary(client, admin_headers):
    # Permission Master filters & exports
    r = client.get("/api/permissions?action=read", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] > 10
    assert "read" in body["actions"]

    for fmt in ("csv", "xlsx", "pdf"):
        exp = client.get(f"/api/permissions/export?format={fmt}", headers=admin_headers)
        assert exp.status_code == 200
        assert len(exp.content) > 50

    # Create a test location
    loc_res = client.post(
        "/api/locations",
        json={"location_code": "ULOC-01", "location_name": "User Loc Terminal", "location_type": "Terminal", "status": "Active"},
        headers=admin_headers,
    )
    assert loc_res.status_code in (200, 201), loc_res.text
    loc_id = loc_res.json()["id"]

    # List user locations
    ul_list = client.get("/api/user-locations", headers=admin_headers)
    assert ul_list.status_code == 200
    items = ul_list.json()["items"]
    assert len(items) >= 1
    uid = items[0]["user_id"]

    # Update user location assignment
    put_res = client.put(
        f"/api/user-locations/{uid}",
        json={"location_ids": [loc_id], "all_locations_access": True},
        headers=admin_headers,
    )
    assert put_res.status_code == 200
    assert loc_id in put_res.json()["direct_location_ids"]
    assert put_res.json()["all_locations_access"] is True

    # Access Summary & export
    acc = client.get("/api/access-summary", headers=admin_headers)
    assert acc.status_code == 200
    assert acc.json()["total"] >= 1
    assert client.get("/api/access-summary/export?format=csv", headers=admin_headers).status_code == 200


def test_profile_2fa_and_password_reset_requests(client, admin_headers):
    setup = client.post("/api/auth/2fa/setup", json={}, headers=admin_headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert secret

    code = _compute_totp(secret)
    en = client.post("/api/auth/2fa/enable", json={"code": code}, headers=admin_headers)
    assert en.status_code == 200
    assert en.json()["totp_enabled"] is True
    assert len(en.json()["backup_codes"]) == 8

    dis = client.post(
        "/api/auth/2fa/disable",
        json={"current_password": "Admin@12345", "code": code},
        headers=admin_headers,
    )
    assert dis.status_code == 200
    assert dis.json()["totp_enabled"] is False

    # Password reset request queue
    client.post("/api/auth/forgot-password", json={"username": "admin", "reason": "Test reset"})
    reqs = client.get("/api/auth/password-reset-requests", headers=admin_headers)
    assert reqs.status_code == 200
    assert reqs.json()["total"] >= 1
    req_id = reqs.json()["items"][0]["id"]
    res = client.post(
        f"/api/auth/password-reset-requests/{req_id}/resolve",
        json={"status": "Resolved", "resolution_notes": "Handled"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["status"] == "Resolved"


def test_asset_assignments_and_summary(client, admin_headers):
    loc = client.post(
        "/api/locations",
        json={"location_code": "AALOC-01", "location_name": "Assignment Terminal", "location_type": "Terminal", "status": "Active"},
        headers=admin_headers,
    ).json()
    asset = client.post(
        "/api/assets",
        json={
            "asset_code": "AA-TNK-01",
            "asset_name": "Assignment Tank 01",
            "asset_type_code": "STORAGE_TANK",
            "asset_scope": "Local",
            "location_id": loc["id"],
            "status": "Active",
            "tanks": [{"tank_name": "Tank 1"}],
        },
        headers=admin_headers,
    ).json()

    created = client.post(
        "/api/asset-assignments",
        json={
            "asset_code": asset["asset_code"],
            "assignment_location_code": loc["location_code"],
            "assigned_to_type": "Location",
            "assigned_to": "Terminal Operations Team",
            "assignment_date": "2026-10-18",
            "status": "Active",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    aid = created.json()["id"]

    summary = client.get("/api/asset-assignments/summary", headers=admin_headers)
    assert summary.status_code == 200
    assert summary.json()["kpis"]["assigned_assets"] >= 1

    assert client.get("/api/asset-assignments/export?format=csv", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/asset-assignments/{aid}", headers=admin_headers).status_code == 200


def test_configurations_extended_endpoints(client, admin_headers):
    loc = client.post(
        "/api/locations",
        json={"location_code": "CFGLOC-01", "location_name": "Config Terminal", "location_type": "Terminal", "status": "Active"},
        headers=admin_headers,
    ).json()

    # Location Operation Availability & Summary
    avail = client.post(
        "/api/location-operation-availability",
        json={
            "location_code": loc["location_code"],
            "operation_type_code": "TANK_OPERATIONS",
            "status": "Active",
            "remarks": "Tank ops enabled",
        },
        headers=admin_headers,
    )
    assert avail.status_code == 201
    assert client.get("/api/location-operation-availability/summary", headers=admin_headers).status_code == 200

    # Location Accounting Day Setting
    acct = client.post(
        "/api/location-accounting-day-settings",
        json={
            "location_code": loc["location_code"],
            "day_start_time": "06:00",
            "day_end_time": "05:59",
            "effective_from": "2026-01-01",
            "timezone_name": "Africa/Lagos",
            "status": "Active",
        },
        headers=admin_headers,
    )
    assert acct.status_code == 201

    # Company Report Profile
    prof = client.post(
        "/api/company-report-profiles",
        json={
            "profile_code": "CRP-TEST-01",
            "company_name": "HCA Test Operations Ltd",
            "is_default": True,
            "status": "Active",
        },
        headers=admin_headers,
    )
    assert prof.status_code == 201
    assert client.get("/api/company-report-profiles/active", headers=admin_headers).status_code == 200

    # Material Balance Template Master
    mbt = client.post(
        "/api/material-balance-templates",
        json={
            "template_code": "MBT-TEST-01",
            "template_name": "Test Balance Template",
            "location_code": loc["location_code"],
            "basis": "NSV",
            "reporting_unit": "BBL",
            "is_default": False,
            "status": "Active",
            "columns": [
                {
                    "column_code": "OPENING_STOCK",
                    "column_label": "Opening Stock",
                    "column_group": "STOCK",
                    "column_type": "OPENING_STOCK",
                    "display_order": 1,
                },
                {
                    "column_code": "CLOSING_STOCK",
                    "column_label": "Closing Stock",
                    "column_group": "STOCK",
                    "column_type": "CLOSING_STOCK",
                    "display_order": 2,
                },
            ],
        },
        headers=admin_headers,
    )
    assert mbt.status_code == 201


def test_flowmeter_records_and_meter_history(client, admin_headers):
    loc = client.post(
        "/api/locations",
        json={"location_code": "FMLOC-01", "location_name": "Flowmeter Terminal", "location_type": "Terminal", "status": "Active"},
        headers=admin_headers,
    ).json()
    fm_asset = client.post(
        "/api/assets",
        json={
            "asset_code": "FM-AST-01",
            "asset_name": "Flowmeter Skid 01",
            "asset_type_code": "FLOWMETER",
            "asset_scope": "Local",
            "location_id": loc["id"],
            "calibration_required": False,
            "status": "Active",
        },
        headers=admin_headers,
    ).json()

    # Create FlowmeterConfig in operation-references -> triggers FlowmeterConfigHistory
    cfg = client.post(
        "/api/operation-references/meters",
        json={
            "location_id": loc["id"],
            "asset_id": fm_asset["id"],
            "stream_name": "Export Stream 1",
            "meter_label": "Meter Run 1",
            "meter_factor": 1.0015,
            "meter_unit": "bbls",
            "status": "Active",
        },
        headers=admin_headers,
    )
    assert cfg.status_code == 201
    hist = client.get("/api/flowmeter-configs/history", headers=admin_headers)
    assert hist.status_code == 200
    assert hist.json()["total"] >= 1

    # Flowmeter Record Entry
    calc = client.post(
        "/api/flowmeter-records/calculate",
        json={
            "opening_reading": 1000,
            "closing_reading": 1500,
            "meter_factor": 1.002,
            "ctl": 0.998,
            "cpl": 1.001,
            "bsw_pct": 0.5,
            "api60": 35.0,
        },
        headers=admin_headers,
    )
    assert calc.status_code == 200
    assert calc.json()["gross_volume"] == 500.0

    rec = client.post(
        "/api/flowmeter-records",
        json={
            "location_code": loc["location_code"],
            "flowmeter_asset_code": fm_asset["asset_code"],
            "stream_name": "Export Stream 1",
            "meter_label": "Meter Run 1",
            "record_date": "2026-10-18",
            "opening_reading": 1000,
            "closing_reading": 1500,
            "meter_factor": 1.002,
            "ctl": 0.998,
            "cpl": 1.001,
            "bsw_pct": 0.5,
            "api60": 35.0,
            "status": "Approved",
        },
        headers=admin_headers,
    )
    assert rec.status_code == 201


def test_export_operations_suite(client, admin_headers):
    assert client.post(
        "/api/export-operations/blocks",
        json={"block_code": "OML-99", "block_name": "Block 99", "status": "Active"},
        headers=admin_headers,
    ).status_code == 201

    assert client.post(
        "/api/export-operations/entities",
        json={"entity_code": "ENT-99", "entity_name": "Entity 99", "block_codes": ["OML-99"], "status": "Active"},
        headers=admin_headers,
    ).status_code == 201

    assert client.post(
        "/api/export-operations/locations",
        json={"location_code": "EXPLOC-99", "location_name": "Export Terminal 99", "entity_codes": ["ENT-99"], "status": "Active"},
        headers=admin_headers,
    ).status_code == 201

    assert client.post(
        "/api/export-operations/consignees",
        json={"consignee_code": "CNS-99", "consignee_name": "Global Refinery Ltd", "country": "Netherlands", "status": "Active"},
        headers=admin_headers,
    ).status_code == 201

    permit = client.post(
        "/api/export-operations/permits",
        json={
            "permit_number": "PRM-2026-Q4-99",
            "location_code": "EXPLOC-99",
            "entity_code": "ENT-99",
            "block_codes": ["OML-99"],
            "quarter": "Q4_2026",
            "permit_volume": 100000,
            "status": "Active",
        },
        headers=admin_headers,
    )
    assert permit.status_code == 201

    tx = client.post(
        "/api/export-operations/transactions",
        json={
            "bl_date": "2026-10-18",
            "location_code": "EXPLOC-99",
            "entity_code": "ENT-99",
            "block_code": "OML-99",
            "permit_number": "PRM-2026-Q4-99",
            "quarter": "Q4_2026",
            "vessel_name": "MT Atlantic Star",
            "consignee": "Global Refinery Ltd",
            "country": "Netherlands",
            "volume": 40000,
            "status": "Active",
        },
        headers=admin_headers,
    )
    assert tx.status_code == 201

    dash = client.get("/api/export-operations/dashboard", headers=admin_headers)
    assert dash.status_code == 200
    assert dash.json()["total_export_volume"] >= 40000

    rep = client.get("/api/export-operations/report", headers=admin_headers)
    assert rep.status_code == 200
    assert rep.json()["total_rows"] >= 1


def test_reports_backup_notifications_and_db_browser(client, admin_headers):
    # Reports endpoints
    loc = client.get("/api/locations", headers=admin_headers).json()["items"][0]
    loc_code = loc["location_code"]

    assert client.get(f"/api/reports/tank-operation-summary?location_code={loc_code}", headers=admin_headers).status_code == 200
    assert client.get(f"/api/reports/out-turn-summary?location_code={loc_code}", headers=admin_headers).status_code == 200
    assert client.get(f"/api/reports/material-balance?location_code={loc_code}", headers=admin_headers).status_code == 200

    # Backup & Recovery full lifecycle
    bkp = client.post("/api/backup/jobs/manual", json={"description": "Pytest backup"}, headers=admin_headers)
    assert bkp.status_code == 201
    job_id = bkp.json()["id"]

    ver = client.post(f"/api/backup/jobs/{job_id}/verify", json={}, headers=admin_headers)
    assert ver.status_code == 200
    assert ver.json()["matched"] is True

    rreq = client.post(
        "/api/backup/restore-requests",
        json={"backup_job_id": job_id, "reason": "Testing disaster recovery restore workflow"},
        headers=admin_headers,
    )
    assert rreq.status_code == 201
    req_id = rreq.json()["id"]
    req_num = rreq.json()["request_number"]

    assert client.post(f"/api/backup/restore-requests/{req_id}/approve", json={"remarks": "Approved"}, headers=admin_headers).status_code == 200
    assert client.post(f"/api/backup/restore-requests/{req_id}/validate", json={}, headers=admin_headers).status_code == 200
    exec_res = client.post(
        f"/api/backup/restore-requests/{req_id}/execute",
        json={"confirmation_text": f"EXECUTE RESTORE {req_num}", "remarks": "Executed"},
        headers=admin_headers,
    )
    assert exec_res.status_code == 200
    assert exec_res.json()["status"] == "Restored"
    assert exec_res.json()["pre_restore_backup_number"].startswith("BKP-")

    # System Notifications
    notif = client.post(
        "/api/system-notifications",
        json={
            "title": "Scheduled Custody Closing Window",
            "message": "Please complete all tank gauging tickets before 06:00.",
            "priority": "High",
            "target_scope": "All Users",
            "requires_acknowledgement": True,
            "status": "Published",
        },
        headers=admin_headers,
    )
    assert notif.status_code == 201
    nid = notif.json()["id"]
    assert client.get("/api/system-notifications/my", headers=admin_headers).status_code == 200
    assert client.post(f"/api/system-notifications/{nid}/acknowledge", json={}, headers=admin_headers).status_code == 200
    assert client.get(f"/api/system-notifications/delivery-report?notification_id={nid}", headers=admin_headers).status_code == 200

    # Database Browser with sensitive field masking
    tables = client.get("/api/database-browser/tables", headers=admin_headers)
    assert tables.status_code == 200
    assert tables.json()["total_tables"] >= 40

    users_browse = client.get("/api/database-browser/tables/users", headers=admin_headers)
    assert users_browse.status_code == 200
    assert users_browse.json()["items"][0]["password_hash"] == "********"
