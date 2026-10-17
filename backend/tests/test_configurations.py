"""Configurations module coverage: operation types, categories and the Operation Master.

Checks the hard-coded catalogue (each type's asset type, each category's stock
sign), the Operation Master rules (fixed type and category, derived sign,
case-insensitive uniqueness per location and type, active-location rule,
deactivation), location scope, read-only types, import preview and commit,
exports, RBAC, the audit trail and the Configurations dashboard.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func

from app.database import SessionLocal
from app.models import AuditLog
from app.utils.asset_types import (
    BARGE,
    FLOWMETER,
    FSO,
    SHUTTLE_VESSEL,
    STORAGE_TANK,
    TANKER_TRAILER,
)
from app.utils.operation_types import (
    OPERATION_CATEGORY_CODES,
    OPERATION_TYPE_CODES,
    resolve_operation_category_code,
    resolve_operation_type_code,
    sign_for_category,
)


def _csv(rows: list[list[str]]) -> bytes:
    return ("\ufeff" + "\n".join(",".join(row) for row in rows) + "\n").encode("utf-8")


def _tag(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:6].upper()}"


def _location(client, headers, prefix: str = "OPS-LOC", status: str | None = None) -> dict:
    code = _tag(prefix)
    response = client.post(
        "/api/locations",
        json={"location_name": f"Ops {code}", "location_code": code, "location_type": "Terminal"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    location = response.json()
    if status:
        client.put(f"/api/locations/{location['id']}", json={"status": status}, headers=headers)
        location["status"] = status
    return location


def _operation(client, headers, location_id: int, **overrides) -> object:
    payload = {
        "location_id": location_id,
        "operation_type_code": "TANK_OPERATIONS",
        "operation_category": "RECEIPT",
        "operation_code": _tag("OP-"),
        "operation_label": f"Receipt {uuid.uuid4().hex[:4]}",
        "sort_order": 1,
        "status": "Active",
    }
    payload.update(overrides)
    return client.post("/api/operations", json=payload, headers=headers)


# ---------------------------------------------------------------------------
# Hard-coded catalogue
# ---------------------------------------------------------------------------
def test_operation_types_map_to_the_required_asset_types():
    expected = {
        "TANK_OPERATIONS": STORAGE_TANK,
        "BARGE_OPERATIONS": BARGE,
        "SHUTTLE_OPERATIONS": SHUTTLE_VESSEL,
        "FSO_OPERATIONS": FSO,
        "TANKER_OPERATIONS": TANKER_TRAILER,
        "FLOWMETER_OPERATIONS": FLOWMETER,
    }
    assert set(OPERATION_TYPE_CODES) == set(expected)
    from app.utils.operation_types import get_operation_type

    for code, asset_type in expected.items():
        assert get_operation_type(code)["asset_type_code"] == asset_type
    # A prime mover carries no operation of its own.
    assert "PRIME_MOVER" not in {get_operation_type(c)["asset_type_code"] for c in OPERATION_TYPE_CODES}


def test_categories_carry_the_required_stock_signs():
    expected = {
        "OPENING_STOCK": "SET",
        "RECEIPT": "IN",
        "DISPATCH": "OUT",
        "EXPORT": "OUT",
        "CLOSING_STOCK": "SET",
        "DRAINING": "OUT",
        "DECANTING": "OUT",
        "ITT": "NEUTRAL",
    }
    assert set(OPERATION_CATEGORY_CODES) == set(expected)
    for category, sign in expected.items():
        assert sign_for_category(category) == sign


def test_spelling_variants_fold_onto_the_catalogue_codes():
    assert resolve_operation_type_code("Tank Operations") == "TANK_OPERATIONS"
    assert resolve_operation_type_code("tank-operations") == "TANK_OPERATIONS"
    assert resolve_operation_type_code("FSO Operations") == "FSO_OPERATIONS"
    assert resolve_operation_type_code("FSO") is None
    assert resolve_operation_type_code("Mystery") is None
    assert resolve_operation_category_code("OPENING STOCK") == "OPENING_STOCK"
    assert resolve_operation_category_code("opening_stock") == "OPENING_STOCK"
    assert resolve_operation_category_code("Neutral") is None


def test_operation_types_endpoint_is_the_fixed_reference(client, admin_headers):
    response = client.get("/api/operation-types", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 6
    by_code = {item["code"]: item for item in body["items"]}
    assert by_code["TANKER_OPERATIONS"]["asset_type_code"] == TANKER_TRAILER
    assert by_code["TANKER_OPERATIONS"]["asset_type_name"] == "Tanker Trailer"
    assert by_code["FLOWMETER_OPERATIONS"]["asset_type_name"] == "Flowmeter"
    assert {item["code"]: item["sign"] for item in body["categories"]}["ITT"] == "NEUTRAL"
    assert [sign["code"] for sign in body["signs"]] == ["SET", "IN", "OUT", "NEUTRAL"]

    categories = client.get("/api/operation-types/categories", headers=admin_headers)
    assert categories.status_code == 200
    assert categories.json()["total"] == 8


def test_operation_types_are_read_only(client, admin_headers):
    """There is no route that creates, edits or deletes a catalogue entry."""
    assert client.post("/api/operation-types", json={"code": "X"}, headers=admin_headers).status_code == 405
    assert client.put("/api/operation-types/1", json={}, headers=admin_headers).status_code in (404, 405)
    assert client.delete("/api/operation-types/1", headers=admin_headers).status_code in (404, 405)


# ---------------------------------------------------------------------------
# Operation Master
# ---------------------------------------------------------------------------
def test_operation_takes_its_sign_from_the_category(client, admin_headers):
    location = _location(client, admin_headers)
    created = _operation(
        client, admin_headers, location["id"],
        operation_category="OPENING_STOCK", operation_type_code="Tank Operations",
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["operation_sign"] == "SET"
    assert body["operation_type_code"] == "TANK_OPERATIONS"
    assert body["operation_type_name"] == "Tank Operations"
    assert body["asset_type_name"] == "Storage Tank"
    assert body["operation_category_label"] == "OPENING STOCK"
    assert body["location_code"] == location["location_code"]

    # Changing the category changes the sign; the sign is never set on its own.
    changed = client.put(
        f"/api/operations/{body['id']}",
        json={"operation_category": "ITT"},
        headers=admin_headers,
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["operation_sign"] == "NEUTRAL"


def test_operation_rejects_unknown_type_and_category(client, admin_headers):
    location = _location(client, admin_headers)
    bad_type = _operation(client, admin_headers, location["id"], operation_type_code="Pipeline Operations")
    assert bad_type.status_code == 422
    assert "Operation types are fixed" in bad_type.json()["detail"]
    bad_category = _operation(client, admin_headers, location["id"], operation_category="TRANSFER")
    assert bad_category.status_code == 422
    assert "Categories are fixed" in bad_category.json()["detail"]


def test_code_and_name_are_unique_per_location_and_type_ignoring_case(client, admin_headers):
    location = _location(client, admin_headers)
    first = _operation(
        client, admin_headers, location["id"],
        operation_code="RCV-01", operation_label="Receipt From Vessel",
    )
    assert first.status_code == 201, first.text

    same_code = _operation(
        client, admin_headers, location["id"],
        operation_code="rcv-01", operation_label="Something Else",
    )
    assert same_code.status_code == 409
    assert "code already exists" in same_code.json()["detail"]

    same_name = _operation(
        client, admin_headers, location["id"],
        operation_code="RCV-02", operation_label="  receipt from vessel ",
    )
    assert same_name.status_code == 409
    assert "name already exists" in same_name.json()["detail"]

    # The same code and name are allowed under another operation type...
    other_type = _operation(
        client, admin_headers, location["id"],
        operation_type_code="BARGE_OPERATIONS",
        operation_code="RCV-01", operation_label="Receipt From Vessel",
    )
    assert other_type.status_code == 201, other_type.text

    # ...and at another location.
    elsewhere = _location(client, admin_headers, "OPS-OTHER")
    other_location = _operation(
        client, admin_headers, elsewhere["id"],
        operation_code="RCV-01", operation_label="Receipt From Vessel",
    )
    assert other_location.status_code == 201, other_location.text


def test_location_must_be_active_for_an_active_operation(client, admin_headers):
    inactive = _location(client, admin_headers, "OPS-OFF", status="Inactive")
    refused = _operation(client, admin_headers, inactive["id"], status="Active")
    assert refused.status_code == 422
    assert "Active location" in refused.json()["detail"]
    kept = _operation(client, admin_headers, inactive["id"], status="Inactive")
    assert kept.status_code == 201, kept.text


def test_update_detects_clashes_and_ignores_itself(client, admin_headers):
    location = _location(client, admin_headers)
    first = _operation(client, admin_headers, location["id"], operation_code="DSP-01",
                       operation_label="Dispatch One", operation_category="DISPATCH").json()
    second = _operation(client, admin_headers, location["id"], operation_code="DSP-02",
                        operation_label="Dispatch Two", operation_category="DISPATCH").json()

    clash = client.put(
        f"/api/operations/{second['id']}",
        json={"operation_code": "DSP-01"},
        headers=admin_headers,
    )
    assert clash.status_code == 409

    resave = client.put(
        f"/api/operations/{first['id']}",
        json={"operation_label": "Dispatch One", "description": "Still the same"},
        headers=admin_headers,
    )
    assert resave.status_code == 200, resave.text
    assert resave.json()["description"] == "Still the same"


def test_deactivation_keeps_the_record_and_is_not_repeatable(client, admin_headers):
    location = _location(client, admin_headers)
    created = _operation(client, admin_headers, location["id"]).json()
    deactivated = client.delete(f"/api/operations/{created['id']}", headers=admin_headers)
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["status"] == "Inactive"
    again = client.delete(f"/api/operations/{created['id']}", headers=admin_headers)
    assert again.status_code == 409
    fetched = client.get(f"/api/operations/{created['id']}", headers=admin_headers)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "Inactive"


def test_operation_list_filters_pagination_and_reference_data(client, admin_headers):
    location = _location(client, admin_headers)
    _operation(client, admin_headers, location["id"], operation_category="RECEIPT",
               operation_label="Filter Receipt", operation_code="FLT-RCV")
    _operation(client, admin_headers, location["id"], operation_type_code="FSO_OPERATIONS",
               operation_category="DISPATCH", operation_label="Filter FSO Dispatch",
               operation_code="FLT-FSO")

    by_type = client.get(
        "/api/operations",
        params={"location_id": location["id"], "operation_type_code": "FSO Operations"},
        headers=admin_headers,
    )
    assert by_type.status_code == 200, by_type.text
    assert by_type.json()["total"] == 1
    assert by_type.json()["items"][0]["operation_code"] == "FLT-FSO"

    by_category = client.get(
        "/api/operations",
        params={"location_id": location["id"], "operation_category": "RECEIPT"},
        headers=admin_headers,
    )
    assert by_category.json()["total"] == 1
    assert by_category.json()["items"][0]["operation_sign"] == "IN"

    search = client.get(
        "/api/operations", params={"search": "FLT-"}, headers=admin_headers
    ).json()
    assert search["total"] >= 2

    body = client.get("/api/operations", params={"page_size": 50}, headers=admin_headers).json()
    assert body["page_size"] == 50
    assert {item["code"] for item in body["operation_types"]} == set(OPERATION_TYPE_CODES)
    assert len(body["operation_categories"]) == 8
    assert any(location_row["id"] == location["id"] for location_row in body["locations"])

    dated = client.get(
        "/api/operations",
        params={"location_id": location["id"], "date_from": "2000-01-01", "date_to": "2000-01-02"},
        headers=admin_headers,
    )
    assert dated.json()["total"] == 0


def test_operations_are_location_scoped_for_non_admin_users(client, admin_headers):
    home = _location(client, admin_headers, "OPS-HOME")
    far = _location(client, admin_headers, "OPS-FAR")
    role = client.post(
        "/api/roles",
        json={"role_name": f"Ops Scoped {_tag('R')}", "description": "Operations at one location"},
        headers=admin_headers,
    ).json()
    catalog = client.get("/api/permissions/catalog", headers=admin_headers).json()
    wanted = {"operations:read", "operations:create", "operations:update", "operations:delete"}
    ids = [
        permission["id"]
        for category in catalog["categories"]
        for module in category["modules"]
        for permission in module["permissions"]
        if permission["permission_name"] in wanted
    ]
    client.put(f"/api/roles/{role['id']}/permissions", json={"permission_ids": ids}, headers=admin_headers)
    client.put(f"/api/role-locations/{role['id']}", json={"location_ids": [home["id"]]}, headers=admin_headers)

    username = _tag("opsscoped").lower()
    client.post(
        "/api/users",
        json={
            "full_name": "Scoped Ops",
            "username": username,
            "email": f"{username}@example.com",
            "password": "ScopedOps@123",
            "role_ids": [role["id"]],
            "force_password_change": False,
        },
        headers=admin_headers,
    )
    tokens = client.post("/api/auth/login", json={"username": username, "password": "ScopedOps@123"}).json()
    scoped = {"Authorization": f"Bearer {tokens['access_token']}"}

    mine = _operation(client, scoped, home["id"], operation_code="SCO-MINE", operation_label="Scoped mine")
    assert mine.status_code == 201, mine.text
    theirs = _operation(client, admin_headers, far["id"], operation_code="SCO-THEIRS",
                        operation_label="Scoped theirs")
    assert theirs.status_code == 201, theirs.text

    refused = _operation(client, scoped, far["id"], operation_code="SCO-NOPE", operation_label="Nope")
    assert refused.status_code == 403

    listing = client.get("/api/operations", params={"page_size": 200}, headers=scoped).json()
    codes = {item["operation_code"] for item in listing["items"]}
    assert "SCO-MINE" in codes
    assert "SCO-THEIRS" not in codes
    assert client.get(f"/api/operations/{theirs.json()['id']}", headers=scoped).status_code == 404


def test_operation_import_previews_then_commits(client, admin_headers):
    location = _location(client, admin_headers, "OPS-IMP")
    code = _tag("IMP")
    rows = [
        ["location_code", "operation_type", "operation_category", "operation_code", "operation_label",
         "sort_order", "description", "status"],
        [location["location_code"], "Barge Operations", "RECEIPT", f"{code}-1", "Import receipt", "1", "", "Active"],
        [location["location_code"], "BARGE_OPERATIONS", "ITT", f"{code}-2", "Import ITT", "2", "Between tanks", "Active"],
    ]
    preview = client.post(
        "/api/operations/import",
        files={"file": ("operations.csv", _csv(rows), "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid_rows"] == 2
    assert preview.json()["rows"][1]["operation_sign"] == "NEUTRAL"

    committed = client.post(
        "/api/operations/import",
        files={"file": ("operations.csv", _csv(rows), "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["imported"] == 2

    listing = client.get(
        "/api/operations", params={"search": code}, headers=admin_headers
    ).json()
    assert listing["total"] == 2
    signs = {item["operation_code"]: item["operation_sign"] for item in listing["items"]}
    assert signs[f"{code}-1"] == "IN"
    assert signs[f"{code}-2"] == "NEUTRAL"

    # A second import of the same codes is refused, so configured rows are never rewritten.
    again = client.post(
        "/api/operations/import",
        files={"file": ("operations.csv", _csv(rows), "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert again.status_code == 200
    assert again.json()["invalid_rows"] == 2
    assert any("already exists" in error for row in again.json()["rows"] for error in row["errors"])


def test_operation_import_rejects_unknown_type_category_and_location(client, admin_headers):
    location = _location(client, admin_headers, "OPS-BAD")
    rows = [
        ["location_code", "operation_type", "operation_category", "operation_code", "operation_label"],
        [location["location_code"], "Pipeline", "RECEIPT", "BAD-1", "Bad type"],
        [location["location_code"], "TANK_OPERATIONS", "TRANSFER", "BAD-2", "Bad category"],
        ["NO-SUCH-LOC", "TANK_OPERATIONS", "RECEIPT", "BAD-3", "Bad location"],
    ]
    rejected = client.post(
        "/api/operations/import",
        files={"file": ("bad.csv", _csv(rows), "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert rejected.status_code == 422
    errors = [error for row in rejected.json()["rows"] for error in row["errors"]]
    assert any("Unknown operation type" in error for error in errors)
    assert any("Unknown operation category" in error for error in errors)
    assert any("Location code not found" in error for error in errors)


def test_operation_exports_and_audit_trail(client, admin_headers):
    location = _location(client, admin_headers, "OPS-EXP")
    created = _operation(client, admin_headers, location["id"], operation_label="Export me",
                         operation_code=_tag("EXP")).json()

    csv_response = client.get(
        "/api/operations/export", params={"format": "csv", "location_id": location["id"]},
        headers=admin_headers,
    )
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    assert created["operation_code"] in csv_response.text

    xlsx = client.get("/api/operations/export", params={"format": "xlsx"}, headers=admin_headers)
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    pdf = client.get("/api/operations/export", params={"format": "pdf"}, headers=admin_headers)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    client.put(f"/api/operations/{created['id']}", json={"operation_label": "Export renamed"},
               headers=admin_headers)
    client.delete(f"/api/operations/{created['id']}", headers=admin_headers)
    with SessionLocal() as db:
        actions = {
            row.action
            for row in db.query(AuditLog.action).filter(
                AuditLog.module_name == "Operation Master", AuditLog.entity_id == created["id"]
            )
        }
        exports = (
            db.query(func.count(AuditLog.id))
            .filter(AuditLog.module_name == "Operation Master", AuditLog.category == "Export")
            .scalar()
        )
    assert {"Create Operation", "Update Operation", "Deactivate Operation"} <= actions
    assert exports >= 3


def test_operation_master_is_permission_gated(client, admin_headers):
    role = client.post(
        "/api/roles",
        json={"role_name": f"Ops Viewer {_tag('V')}", "description": "Types only"},
        headers=admin_headers,
    ).json()
    catalog = client.get("/api/permissions/catalog", headers=admin_headers).json()
    types_only = [
        permission["id"]
        for category in catalog["categories"]
        for module in category["modules"]
        for permission in module["permissions"]
        if permission["permission_name"] == "operation_types:read"
    ]
    client.put(f"/api/roles/{role['id']}/permissions", json={"permission_ids": types_only}, headers=admin_headers)
    username = _tag("opsviewer").lower()
    client.post(
        "/api/users",
        json={
            "full_name": "Ops Viewer",
            "username": username,
            "email": f"{username}@example.com",
            "password": "OpsViewer@123",
            "role_ids": [role["id"]],
            "force_password_change": False,
        },
        headers=admin_headers,
    )
    tokens = client.post("/api/auth/login", json={"username": username, "password": "OpsViewer@123"}).json()
    viewer = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert client.get("/api/operation-types", headers=viewer).status_code == 200
    assert client.get("/api/operations", headers=viewer).status_code == 403
    assert client.post("/api/operations", json={}, headers=viewer).status_code == 403


def test_configurations_dashboard_reports_live_kpis(client, admin_headers):
    location = _location(client, admin_headers, "OPS-DASH")
    _operation(client, admin_headers, location["id"], operation_label="Dashboard op",
               operation_code=_tag("DSH"))
    response = client.get("/api/dashboard/modules/configurations", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["module"]["name"] == "Configurations"
    labels = {kpi["label"]: kpi["value"] for kpi in body["kpis"]}
    assert labels["Operation types"] == 6
    assert labels["Categories"] == 8
    assert labels["Active operations"] >= 1
    assert {row["label"] for row in body["breakdown"]} == {
        "Tank Operations", "Barge Operations", "Shuttle Operations",
        "FSO Operations", "Tanker Operations", "Flowmeter Operations",
    }
    assert {link["path"] for link in body["quick_links"]} >= {"/operation-types", "/operations"}
    portfolio = client.get("/api/dashboard/summary", headers=admin_headers).json()
    modules = {module["key"]: module for module in portfolio["modules"]}
    assert modules["configurations"]["name"] == "Configurations"
    assert modules["configurations"]["path"] == "/modules/configurations"
