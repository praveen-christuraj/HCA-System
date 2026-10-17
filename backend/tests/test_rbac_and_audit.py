"""RBAC enforcement, audit coverage, pagination and database-shape tests."""

from __future__ import annotations

from sqlalchemy import JSON

from app.database import Base


def test_no_json_database_columns():
    """Owner rule 4: persistence must not use JSON/JSONB columns."""
    offenders = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            column_type = column.type
            if isinstance(column_type, JSON):
                offenders.append(f"{table.name}.{column.name}")
            elif "JSON" in type(column_type).__name__.upper():
                offenders.append(f"{table.name}.{column.name}")
    assert offenders == [], f"JSON columns are not allowed: {offenders}"


def test_user_without_permission_is_denied(client, admin_headers):
    role = client.post(
        "/api/roles",
        json={"role_name": "No Access Role", "description": "Used by RBAC tests"},
        headers=admin_headers,
    )
    assert role.status_code == 201, role.text
    role_id = role.json()["id"]

    user = client.post(
        "/api/users",
        json={
            "full_name": "Denied Tester",
            "username": "denied.tester",
            "email": "denied.tester@example.com",
            "password": "Denied@12345",
            "role_ids": [role_id],
            "force_password_change": False,
        },
        headers=admin_headers,
    )
    assert user.status_code == 201, user.text

    login = client.post(
        "/api/auth/login",
        json={"username": "denied.tester", "password": "Denied@12345"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["is_admin"] is False
    assert login.json()["permissions"] == []

    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/users", headers=headers).status_code == 403
    assert client.get("/api/dashboard/summary", headers=headers).status_code == 403
    assert client.get("/api/audit-logs", headers=headers).status_code == 403

    # The denied request is captured by the audit fallback layer.
    audit = client.get(
        "/api/audit-logs",
        params={"actor_username": "denied.tester", "category": "Security", "page_size": 20},
        headers=admin_headers,
    )
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1
    assert audit.json()["items"][0]["outcome"] == "Failure"


def test_role_creation_is_audited(client, admin_headers):
    role = client.post(
        "/api/roles",
        json={"role_name": "Audited Role", "description": "Audit coverage"},
        headers=admin_headers,
    )
    assert role.status_code == 201

    audit = client.get(
        "/api/audit-logs",
        params={"action": "Create Role", "search": "Audited Role", "page_size": 20},
        headers=admin_headers,
    )
    payload = audit.json()
    assert payload["total"] >= 1
    entry = payload["items"][0]
    assert entry["actor_username"] == "admin"
    assert entry["module_name"] == "Role Master"
    assert entry["entity_label"] == "Audited Role"


def test_ui_events_are_persisted(client, admin_headers):
    response = client.post(
        "/api/audit/ui-events",
        json={
            "module": "Portfolio Dashboard",
            "action": "Change Theme",
            "route": "/",
            "details": {"theme": "dark"},
        },
        headers=admin_headers,
    )
    assert response.status_code == 201

    audit = client.get(
        "/api/audit-logs",
        params={"action": "Change Theme", "page_size": 20},
        headers=admin_headers,
    )
    payload = audit.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["category"] == "UI Activity"
    assert "theme=dark" in payload["items"][0]["details_summary"]


def test_pagination_contract_and_page_size_options(client, admin_headers):
    response = client.get(
        "/api/audit-logs",
        params={"page": 1, "page_size": 20},
        headers=admin_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    for key in ("items", "total", "page", "page_size", "pages", "has_more"):
        assert key in payload
    assert payload["page_size"] == 20
    assert len(payload["items"]) <= 20

    # Unsupported sizes snap to a supported option (20/50/100/200).
    for requested, expected in ((37, 20), (75, 50), (150, 100), (500, 200)):
        page = client.get(
            "/api/audit-logs",
            params={"page_size": requested},
            headers=admin_headers,
        ).json()
        assert page["page_size"] == expected


def test_audit_export_is_audited_and_supports_three_formats(client, admin_headers):
    for file_format, media in (
        ("csv", "text/csv"),
        (
            "xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ("pdf", "application/pdf"),
    ):
        response = client.get(
            f"/api/audit-logs/export?format={file_format}",
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert media in response.headers["content-type"]
        assert len(response.content) > 100

    audit = client.get(
        "/api/audit-logs",
        params={"action": "Export Audit Log", "page_size": 20},
        headers=admin_headers,
    ).json()
    assert audit["total"] >= 3


def test_user_export_contains_headers(client, admin_headers):
    response = client.get("/api/users/export?format=csv", headers=admin_headers)
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    assert "Username" in text
    assert "admin" in text


def test_module_dashboard_reports_master_data_asset_module(client, admin_headers):
    """Master Data is now the asset module; locations moved to User Management."""
    response = client.get("/api/dashboard/modules/master-data", headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["module"]["permission"] == "assets:read"
    assert payload["kpis"]
    assert payload["quick_links"]
    labels = [kpi["label"] for kpi in payload["kpis"]]
    assert "Total assets" in labels
    assert "Calibration charts" in labels
    # Every hard-coded asset type is reported, even with no assets yet.
    breakdown_labels = [item["label"] for item in payload["breakdown"]]
    for expected in (
        "Storage Tank",
        "Barge",
        "Shuttle Vessel",
        "FSO",
        "Prime Mover",
        "Tanker Trailer",
        "Flowmeter",
    ):
        assert expected in breakdown_labels


def test_user_management_dashboard_includes_locations(client, admin_headers):
    """Location Master and Role Location now live under User Management."""
    response = client.get("/api/dashboard/modules/user-management", headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()
    labels = [kpi["label"] for kpi in payload["kpis"]]
    assert "Locations" in labels
    paths = [link["path"] for link in payload["quick_links"]]
    assert "/locations" in paths
    assert "/role-locations" in paths
    # The ordering the owner specified for the User Management group.
    assert paths.index("/users") < paths.index("/roles") < paths.index("/locations")
    assert paths.index("/locations") < paths.index("/role-permissions")
    assert paths.index("/role-permissions") < paths.index("/role-locations")
    assert paths.index("/role-locations") < paths.index("/user-roles")


def test_location_permission_is_catalogued_under_user_management(client, admin_headers):
    """Location Master moved to User Management; Asset Master owns Master Data."""
    response = client.get("/api/permissions/catalog", headers=admin_headers)
    assert response.status_code == 200
    categories = response.json()["categories"]

    modules_by_category = {
        category["category"]: [module["module_name"] for module in category["modules"]]
        for category in categories
    }
    assert "Location Master" in modules_by_category["User Management"]
    assert "Asset Master" in modules_by_category["Master Data Management"]
    assert "Location Master" not in modules_by_category["Master Data Management"]

    asset_modules = next(
        module
        for category in categories
        if category["category"] == "Master Data Management"
        for module in category["modules"]
        if module["module_name"] == "Asset Master"
    )
    actions = {permission["action"] for permission in asset_modules["permissions"]}
    assert actions == {"read", "create", "update", "delete"}
