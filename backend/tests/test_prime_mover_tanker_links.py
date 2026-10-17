"""Prime Mover-Tanker Link (Master Data) coverage.

Covers the OTMS feature set on the HCA rules: exact asset types, one active
link per prime mover and per tanker, closing with remarks, the chassis and
asset enrichment, scope and Global-asset administration, import preview and
commit, the three export formats, the audit trail and the permission gate.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta

from sqlalchemy import func

from app.database import SessionLocal
from app.models import AuditLog


def _csv(rows: list[list[str]]) -> bytes:
    return ("\ufeff" + "\n".join(",".join(row) for row in rows) + "\n").encode("utf-8")


def _tag(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:6].upper()}"


def _location(client, headers, prefix: str = "PMT-LOC") -> dict:
    code = _tag(prefix)
    response = client.post(
        "/api/locations",
        json={"location_name": f"Location {code}", "location_code": code, "location_type": "Terminal"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _asset(client, headers, *, asset_type: str, code: str, scope: str = "Global", location_id=None,
           serial: str | None = None, status: str = "Active", name: str | None = None) -> dict:
    payload = {
        "asset_name": name or f"Asset {code}",
        "asset_code": code,
        "asset_type_code": asset_type,
        "asset_scope": scope,
        "location_id": location_id,
        "calibration_required": False,
        "serial_number": serial,
        "status": status,
        "tanks": [],
    }
    response = client.post("/api/assets", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _prime_mover(client, headers, **kwargs) -> dict:
    return _asset(client, headers, asset_type="PRIME_MOVER", code=_tag("PM-"), **kwargs)


def _tanker(client, headers, **kwargs) -> dict:
    return _asset(client, headers, asset_type="TANKER_TRAILER", code=_tag("TT-"), **kwargs)


def _link(client, headers, pm_id: int, tk_id: int, linked_from: date | None = None, **extra):
    payload = {
        "prime_mover_asset_id": pm_id,
        "tanker_asset_id": tk_id,
        "linked_from": (linked_from or date(2026, 1, 5)).isoformat(),
        **extra,
    }
    return client.post("/api/prime-mover-tanker-links", json=payload, headers=headers)


def test_link_requires_exact_prime_mover_and_tanker_types(client, admin_headers):
    pm = _prime_mover(client, admin_headers)
    tk = _tanker(client, admin_headers)
    storage = _asset(client, admin_headers, asset_type="STORAGE_TANK", code=_tag("TANK-"))

    tanker_as_prime = _link(client, admin_headers, tk["id"], pm["id"])
    assert tanker_as_prime.status_code == 422, tanker_as_prime.text
    assert "not a Prime Mover" in tanker_as_prime.json()["detail"]

    wrong_tanker = _link(client, admin_headers, pm["id"], storage["id"])
    assert wrong_tanker.status_code == 422, wrong_tanker.text
    assert "not a Tanker Trailer" in wrong_tanker.json()["detail"]

    same_asset = _link(client, admin_headers, pm["id"], pm["id"])
    assert same_asset.status_code == 422

    missing = _link(client, admin_headers, 99999999, tk["id"])
    assert missing.status_code == 422
    assert "not found" in missing.json()["detail"]


def test_active_link_needs_active_assets_but_inactive_links_do_not(client, admin_headers):
    pm = _prime_mover(client, admin_headers, status="Inactive")
    tk = _tanker(client, admin_headers)

    refused = _link(client, admin_headers, pm["id"], tk["id"])
    assert refused.status_code == 422
    assert "Inactive" in refused.json()["detail"]

    # A historical (Inactive) record can still be kept for an inactive asset.
    stored = _link(client, admin_headers, pm["id"], tk["id"], status="Inactive", remarks="Historic")
    assert stored.status_code == 201, stored.text
    assert stored.json()["is_current"] is False
    assert stored.json()["prime_mover_asset_status"] == "Inactive"


def test_one_active_link_per_prime_mover_and_per_tanker(client, admin_headers):
    pm = _prime_mover(client, admin_headers)
    tk = _tanker(client, admin_headers)
    other_pm = _prime_mover(client, admin_headers)
    other_tk = _tanker(client, admin_headers)

    first = _link(client, admin_headers, pm["id"], tk["id"], remarks="Initial hook-up")
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["status"] == "Active" and body["is_current"] is True
    assert body["prime_mover_asset_code"] == pm["asset_code"]
    assert body["tanker_asset_code"] == tk["asset_code"]

    second_for_pm = _link(client, admin_headers, pm["id"], other_tk["id"])
    assert second_for_pm.status_code == 409
    assert "prime mover already has an active link" in second_for_pm.json()["detail"]

    second_for_tanker = _link(client, admin_headers, other_pm["id"], tk["id"])
    assert second_for_tanker.status_code == 409
    assert "tanker already has an active link" in second_for_tanker.json()["detail"]

    current = client.get(
        f"/api/prime-mover-tanker-links/current-by-prime-mover/{pm['id']}", headers=admin_headers
    )
    assert current.status_code == 200
    assert current.json()["has_active_link"] is True
    assert current.json()["link"]["id"] == body["id"]

    current_tanker = client.get(
        f"/api/prime-mover-tanker-links/current-by-tanker/{tk['id']}", headers=admin_headers
    )
    assert current_tanker.json()["link"]["id"] == body["id"]

    no_link = client.get(
        f"/api/prime-mover-tanker-links/current-by-prime-mover/{other_pm['id']}",
        headers=admin_headers,
    )
    assert no_link.json() == {"has_active_link": False, "link": None}


def test_close_sets_end_date_appends_remarks_and_frees_the_asset(client, admin_headers):
    pm = _prime_mover(client, admin_headers)
    tk = _tanker(client, admin_headers)
    link = _link(client, admin_headers, pm["id"], tk["id"], remarks="Contract A").json()

    too_early = client.post(
        f"/api/prime-mover-tanker-links/{link['id']}/close",
        json={"linked_to": "2025-12-31", "remarks": "Wrong date"},
        headers=admin_headers,
    )
    assert too_early.status_code == 422

    closed = client.post(
        f"/api/prime-mover-tanker-links/{link['id']}/close",
        json={"linked_to": "2026-03-01", "remarks": "Tanker sold"},
        headers=admin_headers,
    )
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["status"] == "Inactive"
    assert body["linked_to"] == "2026-03-01"
    assert body["remarks"].endswith("Close Remarks: Tanker sold")
    assert body["remarks"].startswith("Contract A")

    again = client.post(
        f"/api/prime-mover-tanker-links/{link['id']}/close",
        json={},
        headers=admin_headers,
    )
    assert again.status_code == 409

    # Closing frees both assets, so a new link can be created for them.
    reused = _link(client, admin_headers, pm["id"], tk["id"], linked_from=date(2026, 3, 2))
    assert reused.status_code == 201, reused.text


def test_close_defaults_end_date_to_today(client, admin_headers):
    pm = _prime_mover(client, admin_headers)
    tk = _tanker(client, admin_headers)
    link = _link(client, admin_headers, pm["id"], tk["id"], linked_from=date(2020, 1, 1)).json()
    closed = client.post(
        f"/api/prime-mover-tanker-links/{link['id']}/close",
        json={},
        headers=admin_headers,
    ).json()
    assert closed["linked_to"] == date.today().isoformat()


def test_update_validates_the_merged_link_and_excludes_itself(client, admin_headers):
    pm = _prime_mover(client, admin_headers)
    tk = _tanker(client, admin_headers)
    link = _link(client, admin_headers, pm["id"], tk["id"]).json()

    # Re-saving the same active link must not conflict with itself.
    unchanged = client.put(
        f"/api/prime-mover-tanker-links/{link['id']}",
        json={"remarks": "Re-saved"},
        headers=admin_headers,
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["remarks"] == "Re-saved"

    backwards = client.put(
        f"/api/prime-mover-tanker-links/{link['id']}",
        json={"linked_to": "2025-01-01"},
        headers=admin_headers,
    )
    assert backwards.status_code == 422

    other_tk = _tanker(client, admin_headers)
    switched = client.put(
        f"/api/prime-mover-tanker-links/{link['id']}",
        json={"tanker_asset_id": other_tk["id"]},
        headers=admin_headers,
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["tanker_asset_code"] == other_tk["asset_code"]


def test_list_filters_pagination_and_chassis_enrichment(client, admin_headers):
    chassis = _tag("CHS")
    pm = _prime_mover(client, admin_headers, serial=f"{chassis}-PM")
    tk = _tanker(client, admin_headers, serial=chassis)
    created = _link(client, admin_headers, pm["id"], tk["id"], linked_from=date(2026, 6, 1)).json()

    listing = client.get(
        "/api/prime-mover-tanker-links",
        params={"search": chassis, "page_size": 20},
        headers=admin_headers,
    )
    assert listing.status_code == 200, listing.text
    payload = listing.json()
    assert payload["page_size"] == 20
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["id"] == created["id"]
    assert item["tanker_chassis_number"] == chassis
    assert item["prime_mover_chassis_number"] == f"{chassis}-PM"
    assert item["tanker_asset_type_code"] == "TANKER_TRAILER"
    assert item["prime_mover_asset_name"] == pm["asset_name"]

    by_status = client.get(
        "/api/prime-mover-tanker-links",
        params={"search": chassis, "status": "Inactive"},
        headers=admin_headers,
    )
    assert by_status.json()["total"] == 0

    by_date = client.get(
        "/api/prime-mover-tanker-links",
        params={"tanker_asset_id": tk["id"], "date_from": "2026-05-31", "date_to": "2026-06-01"},
        headers=admin_headers,
    )
    assert by_date.json()["total"] == 1
    outside = client.get(
        "/api/prime-mover-tanker-links",
        params={"tanker_asset_id": tk["id"], "date_from": "2026-06-02"},
        headers=admin_headers,
    )
    assert outside.json()["total"] == 0

    for size in (20, 50, 100, 200):
        response = client.get(
            "/api/prime-mover-tanker-links", params={"page_size": size}, headers=admin_headers
        )
        assert response.json()["page_size"] == size


def test_options_list_only_active_assets_of_the_right_type(client, admin_headers):
    active_pm = _prime_mover(client, admin_headers, serial=_tag("OPT"))
    inactive_pm = _prime_mover(client, admin_headers, status="Inactive")
    tk = _tanker(client, admin_headers, serial=_tag("OPTT"))

    options = client.get("/api/prime-mover-tanker-links/options", headers=admin_headers)
    assert options.status_code == 200, options.text
    pm_ids = {item["id"] for item in options.json()["prime_movers"]}
    tk_ids = {item["id"] for item in options.json()["tankers"]}
    assert active_pm["id"] in pm_ids
    assert inactive_pm["id"] not in pm_ids
    assert tk["id"] in tk_ids
    assert active_pm["id"] not in tk_ids


def test_delete_removes_the_link_and_is_audited(client, admin_headers):
    pm = _prime_mover(client, admin_headers)
    tk = _tanker(client, admin_headers)
    link = _link(client, admin_headers, pm["id"], tk["id"], remarks="To delete").json()

    deleted = client.delete(f"/api/prime-mover-tanker-links/{link['id']}", headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted": True, "id": link["id"]}
    assert client.get(f"/api/prime-mover-tanker-links/{link['id']}", headers=admin_headers).status_code == 404

    with SessionLocal() as db:
        entry = (
            db.query(AuditLog)
            .filter(
                AuditLog.module_name == "Prime Mover-Tanker Link",
                AuditLog.action == "Delete Prime Mover-Tanker Link",
                AuditLog.entity_id == link["id"],
            )
            .first()
        )
        assert entry is not None
        assert pm["asset_code"] in (entry.details_summary or "")


def test_every_mutation_is_audited_with_its_action(client, admin_headers):
    pm = _prime_mover(client, admin_headers)
    tk = _tanker(client, admin_headers)
    link = _link(client, admin_headers, pm["id"], tk["id"]).json()
    client.put(
        f"/api/prime-mover-tanker-links/{link['id']}",
        json={"remarks": "Edited"},
        headers=admin_headers,
    )
    client.post(
        f"/api/prime-mover-tanker-links/{link['id']}/close",
        json={"remarks": "Done"},
        headers=admin_headers,
    )
    with SessionLocal() as db:
        actions = {
            row.action
            for row in db.query(AuditLog.action).filter(
                AuditLog.module_name == "Prime Mover-Tanker Link",
                AuditLog.entity_id == link["id"],
            )
        }
    assert {"Create Prime Mover-Tanker Link", "Update Prime Mover-Tanker Link",
            "Close Prime Mover-Tanker Link"} <= actions


def test_export_is_available_in_three_formats_and_audited(client, admin_headers):
    pm = _prime_mover(client, admin_headers)
    tk = _tanker(client, admin_headers)
    _link(client, admin_headers, pm["id"], tk["id"])

    csv_response = client.get(
        "/api/prime-mover-tanker-links/export", params={"format": "csv", "search": pm["asset_code"]},
        headers=admin_headers,
    )
    assert csv_response.status_code == 200, csv_response.text
    assert "text/csv" in csv_response.headers["content-type"]
    assert pm["asset_code"] in csv_response.text

    xlsx = client.get(
        "/api/prime-mover-tanker-links/export", params={"format": "xlsx"}, headers=admin_headers
    )
    assert xlsx.status_code == 200
    assert xlsx.content[:2] == b"PK"

    pdf = client.get(
        "/api/prime-mover-tanker-links/export", params={"format": "pdf"}, headers=admin_headers
    )
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"

    with SessionLocal() as db:
        assert (
            db.query(func.count(AuditLog.id))
            .filter(AuditLog.module_name == "Prime Mover-Tanker Link", AuditLog.category == "Export")
            .scalar()
            >= 3
        )


def test_import_previews_then_commits_and_updates_matching_links(client, admin_headers):
    pm_code = _tag("IPM-")
    tk_code = _tag("ITT-")
    _asset(client, admin_headers, asset_type="PRIME_MOVER", code=pm_code)
    _asset(client, admin_headers, asset_type="TANKER_TRAILER", code=tk_code)

    rows = [
        ["prime_mover_code", "tanker_code", "linked_from", "linked_to", "status", "remarks"],
        [pm_code, tk_code, "2026-02-01", "", "Active", "Imported"],
    ]
    preview = client.post(
        "/api/prime-mover-tanker-links/import",
        files={"file": ("links.csv", _csv(rows), "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid_rows"] == 1
    assert preview.json()["rows"][0]["action"] == "Create"

    committed = client.post(
        "/api/prime-mover-tanker-links/import",
        files={"file": ("links.csv", _csv(rows), "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["created"] == 1

    listing = client.get(
        "/api/prime-mover-tanker-links",
        params={"search": pm_code},
        headers=admin_headers,
    ).json()
    assert listing["total"] == 1
    assert listing["items"][0]["remarks"] == "Imported"

    # Same prime mover + tanker + linked-from date updates the stored link.
    rows[1][5] = "Corrected"
    updated = client.post(
        "/api/prime-mover-tanker-links/import",
        files={"file": ("links.csv", _csv(rows), "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["updated"] == 1
    assert updated.json()["created"] == 0
    refreshed = client.get(
        "/api/prime-mover-tanker-links", params={"search": pm_code}, headers=admin_headers
    ).json()
    assert refreshed["total"] == 1
    assert refreshed["items"][0]["remarks"] == "Corrected"


def test_import_rejects_wrong_types_unknown_codes_and_active_conflicts(client, admin_headers):
    pm_code = _tag("RPM-")
    tk_code = _tag("RTT-")
    _asset(client, admin_headers, asset_type="PRIME_MOVER", code=pm_code)
    _asset(client, admin_headers, asset_type="TANKER_TRAILER", code=tk_code)
    other_tk = _tag("RTX-")
    _asset(client, admin_headers, asset_type="TANKER_TRAILER", code=other_tk)

    bad_rows = [
        ["prime_mover_code", "tanker_code", "linked_from", "linked_to", "status", "remarks"],
        [tk_code, pm_code, "2026-02-01", "", "Active", "Swapped types"],
        [pm_code, "NO-SUCH-CODE", "2026-02-01", "", "Active", "Unknown tanker"],
        [pm_code, other_tk, "2026-02-01", "2026-01-01", "Active", "Backwards dates"],
        [pm_code, tk_code, "not a date", "", "Active", "Bad date"],
        [pm_code, tk_code, "2026-02-01", "", "Maybe", "Bad status"],
    ]
    rejected = client.post(
        "/api/prime-mover-tanker-links/import",
        files={"file": ("bad.csv", _csv(bad_rows), "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert rejected.status_code == 422, rejected.text
    errors = [error for row in rejected.json()["rows"] for error in row["errors"]]
    assert any("is not a Prime Mover asset" in error for error in errors)
    assert any("Tanker code not found" in error for error in errors)
    assert any("cannot be before" in error for error in errors)
    assert any("valid date" in error for error in errors)
    assert any("Status must be" in error for error in errors)

    twice = [
        ["prime_mover_code", "tanker_code", "linked_from", "linked_to", "status", "remarks"],
        [pm_code, tk_code, "2026-03-01", "", "Active", "First"],
        [pm_code, other_tk, "2026-03-02", "", "Active", "Second for the same prime mover"],
    ]
    conflict = client.post(
        "/api/prime-mover-tanker-links/import",
        files={"file": ("twice.csv", _csv(twice), "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert conflict.status_code == 200, conflict.text
    assert conflict.json()["invalid_rows"] == 1
    assert any("linked Active twice" in error for row in conflict.json()["rows"]
               for error in row["errors"])

    missing_column = client.post(
        "/api/prime-mover-tanker-links/import",
        files={"file": ("missing.csv", _csv([["prime_mover_code", "tanker_code"], [pm_code, tk_code]]),
                        "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert missing_column.status_code == 422
    assert "linked_from" in missing_column.json()["missing_columns"]


def test_scoped_user_sees_only_links_whose_assets_are_in_scope(client, admin_headers):
    home = _location(client, admin_headers, "PMT-HOME")
    far = _location(client, admin_headers, "PMT-FAR")
    role = client.post(
        "/api/roles",
        json={"role_name": f"PMT Scoped {_tag('R')}", "description": "Scoped link operator"},
        headers=admin_headers,
    ).json()
    catalog = client.get("/api/permissions/catalog", headers=admin_headers).json()
    wanted = {
        "prime_mover_tanker_links:read",
        "prime_mover_tanker_links:create",
        "prime_mover_tanker_links:update",
        "prime_mover_tanker_links:delete",
    }
    permission_ids = [
        permission["id"]
        for category in catalog["categories"]
        for module in category["modules"]
        for permission in module["permissions"]
        if permission["permission_name"] in wanted
    ]
    assert client.put(
        f"/api/roles/{role['id']}/permissions",
        json={"permission_ids": permission_ids},
        headers=admin_headers,
    ).status_code == 200
    assert client.put(
        f"/api/role-locations/{role['id']}",
        json={"location_ids": [home["id"]]},
        headers=admin_headers,
    ).status_code == 200

    username = _tag("pmtscoped").lower()
    created_user = client.post(
        "/api/users",
        json={
            "full_name": "Scoped Link Operator",
            "username": username,
            "email": f"{username}@example.com",
            "password": "ScopedLink@123",
            "role_ids": [role["id"]],
            "force_password_change": False,
        },
        headers=admin_headers,
    )
    assert created_user.status_code == 201, created_user.text
    tokens = client.post(
        "/api/auth/login", json={"username": username, "password": "ScopedLink@123"}
    ).json()
    scoped = {"Authorization": f"Bearer {tokens['access_token']}"}

    pm_home = _asset(client, admin_headers, asset_type="PRIME_MOVER", code=_tag("SPM-H"),
                     scope="Local", location_id=home["id"])
    tk_home = _asset(client, admin_headers, asset_type="TANKER_TRAILER", code=_tag("STT-H"),
                     scope="Local", location_id=home["id"])
    pm_far = _asset(client, admin_headers, asset_type="PRIME_MOVER", code=_tag("SPM-F"),
                    scope="Local", location_id=far["id"])
    tk_far = _asset(client, admin_headers, asset_type="TANKER_TRAILER", code=_tag("STT-F"),
                    scope="Local", location_id=far["id"])
    global_tk = _asset(client, admin_headers, asset_type="TANKER_TRAILER", code=_tag("SGT-"),
                       scope="Global")

    admin_home = _link(client, admin_headers, pm_home["id"], tk_home["id"]).json()
    admin_far = _link(client, admin_headers, pm_far["id"], tk_far["id"]).json()
    assert admin_far["id"] and admin_home["id"]

    scoped_view = client.get("/api/prime-mover-tanker-links", params={"page_size": 200}, headers=scoped)
    assert scoped_view.status_code == 200, scoped_view.text
    visible_ids = {item["id"] for item in scoped_view.json()["items"]}
    assert admin_home["id"] in visible_ids
    assert admin_far["id"] not in visible_ids
    assert client.get(f"/api/prime-mover-tanker-links/{admin_far['id']}", headers=scoped).status_code == 404

    # Assets outside the scope cannot be linked, and the refusal does not reveal them.
    outside = _link(client, scoped, pm_far["id"], tk_home["id"])
    assert outside.status_code == 422
    assert "not found" in outside.json()["detail"]

    # A Global asset is visible to the scoped user, but only an administrator may
    # link it.
    global_refused = _link(client, scoped, pm_home["id"], global_tk["id"])
    assert global_refused.status_code == 403
    assert "administrator" in global_refused.json()["detail"]

    # Linking within scope works for the scoped user.
    pm_home_2 = _asset(client, admin_headers, asset_type="PRIME_MOVER", code=_tag("SPM-H2"),
                       scope="Local", location_id=home["id"])
    tk_home_2 = _asset(client, admin_headers, asset_type="TANKER_TRAILER", code=_tag("STT-H2"),
                       scope="Local", location_id=home["id"])
    within = _link(client, scoped, pm_home_2["id"], tk_home_2["id"])
    assert within.status_code == 201, within.text


def test_permission_gate_blocks_users_without_the_link_permission(client, admin_headers):
    role = client.post(
        "/api/roles",
        json={"role_name": f"PMT NoAccess {_tag('N')}", "description": "No link access"},
        headers=admin_headers,
    ).json()
    username = _tag("pmtnone").lower()
    client.post(
        "/api/users",
        json={
            "full_name": "No Link Access",
            "username": username,
            "email": f"{username}@example.com",
            "password": "NoLink@123",
            "role_ids": [role["id"]],
            "force_password_change": False,
        },
        headers=admin_headers,
    )
    tokens = client.post(
        "/api/auth/login", json={"username": username, "password": "NoLink@123"}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/api/prime-mover-tanker-links", headers=headers).status_code == 403
    assert client.post(
        "/api/prime-mover-tanker-links",
        json={"prime_mover_asset_id": 1, "tanker_asset_id": 2, "linked_from": "2026-01-01"},
        headers=headers,
    ).status_code == 403
    assert client.get("/api/prime-mover-tanker-links/export", headers=headers).status_code == 403


def test_permissions_are_registered_under_master_data(client, admin_headers):
    catalog = client.get("/api/permissions/catalog", headers=admin_headers).json()
    located = {
        permission["permission_name"]: category["category"]
        for category in catalog["categories"]
        for module in category["modules"]
        for permission in module["permissions"]
    }
    for action in ("read", "create", "update", "delete"):
        assert located[f"prime_mover_tanker_links:{action}"] == "Master Data Management"
    assert "operation_types:read" in located
    assert located["operation_types:read"] == "Configurations"


def test_module_dashboard_reports_live_link_kpis(client, admin_headers):
    pm = _prime_mover(client, admin_headers)
    tk = _tanker(client, admin_headers)
    _link(client, admin_headers, pm["id"], tk["id"])

    dashboard = client.get("/api/dashboard/modules/master-data", headers=admin_headers)
    assert dashboard.status_code == 200, dashboard.text
    labels = {kpi["label"]: kpi["value"] for kpi in dashboard.json()["kpis"]}
    assert labels["Active prime mover links"] >= 1
    assert "Prime movers without a link" in labels
    assert "Tankers without a link" in labels
    link_quick = [link["path"] for link in dashboard.json()["quick_links"]]
    assert "/prime-mover-tanker-links" in link_quick
    assert any(
        entry["module_name"] == "Prime Mover-Tanker Link"
        for entry in dashboard.json()["recent_activity"]
    )


def test_import_preview_file_keeps_the_original_rows_unchanged(client, admin_headers):
    """A preview never writes: the register size is identical before and after."""
    before = client.get("/api/prime-mover-tanker-links", headers=admin_headers).json()["total"]
    rows = [
        ["prime_mover_code", "tanker_code", "linked_from"],
        ["NO-SUCH-PM", "NO-SUCH-TK", (date.today() + timedelta(days=1)).isoformat()],
    ]
    response = client.post(
        "/api/prime-mover-tanker-links/import",
        files={"file": ("preview.csv", io.BytesIO(_csv(rows)).getvalue(), "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    # A preview reports the row problems with status 200; only a commit is refused.
    assert response.status_code == 200, response.text
    assert response.json()["invalid_rows"] == 1
    assert response.json()["rows"][0]["errors"]
    refused = client.post(
        "/api/prime-mover-tanker-links/import",
        files={"file": ("preview.csv", _csv(rows), "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert refused.status_code == 422
    assert client.get("/api/prime-mover-tanker-links", headers=admin_headers).json()["total"] == before
