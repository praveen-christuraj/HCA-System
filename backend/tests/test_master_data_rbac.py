"""Location masters and role/user assignment RBAC integration coverage."""

from __future__ import annotations

import io
import uuid

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Permission, Role, RolePermission, UserRole
from app.services.bootstrap import _migrate_legacy_permission_grants, seed_permission_catalog


def _csv(rows: list[list[str]]) -> bytes:
    return ("\ufeff" + "\n".join(",".join(row) for row in rows) + "\n").encode("utf-8")


def _create_role(client, headers, name: str) -> int:
    response = client.post(
        "/api/roles",
        json={"role_name": name, "description": "Assignment integration test"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_location_hierarchy_and_role_location_assignment(client, admin_headers):
    root = client.post(
        "/api/locations",
        json={
            "location_name": "Integration Root",
            "location_code": "TEST-ROOT-01",
            "location_type": "Terminal",
        },
        headers=admin_headers,
    )
    assert root.status_code == 201, root.text
    root_item = root.json()

    child = client.post(
        "/api/locations",
        json={
            "location_name": "Integration Child",
            "location_code": "TEST-CHILD-01",
            "location_type": "Tank Farm",
            "parent_location_id": root_item["id"],
        },
        headers=admin_headers,
    )
    assert child.status_code == 201, child.text
    child_item = child.json()
    assert child_item["parent_location_code"] == "TEST-ROOT-01"

    cycle = client.put(
        f"/api/locations/{root_item['id']}",
        json={"parent_location_id": child_item["id"]},
        headers=admin_headers,
    )
    assert cycle.status_code == 422

    role_id = _create_role(client, admin_headers, "Location Assignment Integration")
    assigned = client.put(
        f"/api/role-locations/{role_id}",
        json={"location_ids": [root_item["id"], child_item["id"]]},
        headers=admin_headers,
    )
    assert assigned.status_code == 200, assigned.text
    assert set(assigned.json()["location_ids"]) == {root_item["id"], child_item["id"]}

    parent_deactivate = client.delete(f"/api/locations/{root_item['id']}", headers=admin_headers)
    assert parent_deactivate.status_code == 409
    assigned_deactivate = client.delete(f"/api/locations/{child_item['id']}", headers=admin_headers)
    assert assigned_deactivate.status_code == 409

    cleared = client.put(
        f"/api/role-locations/{role_id}",
        json={"location_ids": []},
        headers=admin_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["location_ids"] == []

    deactivated = client.delete(f"/api/locations/{child_item['id']}", headers=admin_headers)
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["location"]["status"] == "Inactive"

    filtered = client.get(
        "/api/locations",
        params={"search": "TEST-CHILD-01", "status": "Inactive", "page_size": 20},
        headers=admin_headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == child_item["id"]


def test_user_role_assignment_and_reserved_admin_protection(client, admin_headers):
    role_id = _create_role(client, admin_headers, "User Role Integration")
    user = client.post(
        "/api/users",
        json={
            "full_name": "Assignment Integration User",
            "username": "assignment.integration",
            "email": "assignment.integration@example.com",
            "password": "Integration@123",
            "force_password_change": False,
        },
        headers=admin_headers,
    )
    assert user.status_code == 201, user.text
    user_id = user.json()["id"]

    assigned = client.put(
        f"/api/user-roles/{user_id}",
        json={"role_ids": [role_id]},
        headers=admin_headers,
    )
    assert assigned.status_code == 200, assigned.text
    assert [role["id"] for role in assigned.json()["roles"]] == [role_id]

    register = client.get("/api/user-roles", headers=admin_headers)
    assert register.status_code == 200
    found = next(item for item in register.json()["items"] if item["id"] == user_id)
    assert found["role_count"] == 1

    admin_role = next(
        role for role in client.get("/api/roles?page_size=200", headers=admin_headers).json()["items"]
        if role["is_reserved"]
    )
    forbidden = client.put(
        f"/api/user-roles/{user_id}",
        json={"role_ids": [admin_role["id"]]},
        headers=admin_headers,
    )
    assert forbidden.status_code == 403

    forbidden_create = client.post(
        "/api/users",
        json={
            "full_name": "Must Not Be Admin",
            "username": "must.not.be.admin",
            "email": "must.not.be.admin@example.com",
            "password": "Integration@123",
            "role_ids": [admin_role["id"]],
        },
        headers=admin_headers,
    )
    assert forbidden_create.status_code == 403


def test_assignment_imports_preview_and_commit(client, admin_headers):
    role_id = _create_role(client, admin_headers, "Bulk Assignment Import")
    location = client.post(
        "/api/locations",
        json={"location_name": "Bulk Location", "location_code": "BULK-LOC-01", "location_type": "Terminal"},
        headers=admin_headers,
    )
    assert location.status_code == 201, location.text

    role_location_csv = _csv([
        ["role_name", "location_codes"],
        ["Bulk Assignment Import", "BULK-LOC-01"],
    ])
    preview = client.post(
        "/api/role-locations/import",
        files={"file": ("role-locations.csv", role_location_csv, "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid_rows"] == 1
    committed = client.post(
        "/api/role-locations/import",
        files={"file": ("role-locations.csv", role_location_csv, "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["imported"] == 1
    assignment = client.get(f"/api/role-locations/{role_id}", headers=admin_headers)
    assert assignment.status_code == 200
    assert assignment.json()["location_ids"] == [location.json()["id"]]

    permission_csv = _csv([
        ["role_name", "permission_names"],
        ["Bulk Assignment Import", "users:read; locations:read"],
    ])
    permission_preview = client.post(
        "/api/roles/permissions/import",
        files={"file": ("role-permissions.csv", permission_csv, "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert permission_preview.status_code == 200, permission_preview.text
    assert permission_preview.json()["valid_rows"] == 1
    permission_commit = client.post(
        "/api/roles/permissions/import",
        files={"file": ("role-permissions.csv", permission_csv, "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert permission_commit.status_code == 200, permission_commit.text
    assigned_permissions = client.get(f"/api/roles/{role_id}/permissions", headers=admin_headers)
    assert assigned_permissions.status_code == 200
    assert {item["permission_name"] for item in assigned_permissions.json()["items"]} == {"users:read", "locations:read"}

    user = client.post(
        "/api/users",
        json={
            "full_name": "Bulk Assignment User",
            "username": "bulk.assignment.user",
            "email": "bulk.assignment.user@example.com",
            "password": "Bulk@12345",
            "force_password_change": False,
        },
        headers=admin_headers,
    )
    assert user.status_code == 201, user.text
    user_role_csv = _csv([
        ["username", "role_names"],
        ["bulk.assignment.user", "Bulk Assignment Import"],
    ])
    user_preview = client.post(
        "/api/user-roles/import",
        files={"file": ("user-roles.csv", user_role_csv, "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert user_preview.status_code == 200, user_preview.text
    assert user_preview.json()["valid_rows"] == 1
    user_commit = client.post(
        "/api/user-roles/import",
        files={"file": ("user-roles.csv", user_role_csv, "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert user_commit.status_code == 200, user_commit.text
    assigned_roles = client.get(
        "/api/user-roles",
        params={"search": "bulk.assignment.user"},
        headers=admin_headers,
    )
    assert assigned_roles.status_code == 200
    matching_user = next(item for item in assigned_roles.json()["items"] if item["id"] == user.json()["id"])
    assert [item["id"] for item in matching_user["roles"]] == [role_id]

    rejected = client.post(
        "/api/user-roles/import",
        files={"file": ("reserved.csv", _csv([["username", "role_names"], ["bulk.assignment.user", "Admin"]]), "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert rejected.status_code == 422
    assert rejected.json()["invalid_rows"] == 1


def test_location_import_preview_commit_and_hierarchy(client, admin_headers):
    payload = _csv([
        ["location_name", "location_code", "location_type", "parent_location_code", "description", "status"],
        ["Import Root", "TEST-IMP-ROOT", "Terminal", "", "Imported parent", "Active"],
        ["Import Child", "TEST-IMP-CHILD", "Tank Farm", "TEST-IMP-ROOT", "Imported child", "Active"],
    ])
    preview = client.post(
        "/api/locations/import",
        files={"file": ("locations.csv", payload, "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid_rows"] == 2
    assert preview.json()["invalid_rows"] == 0

    committed = client.post(
        "/api/locations/import",
        files={"file": ("locations.csv", payload, "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["imported"] == 2

    child = client.get(
        "/api/locations",
        params={"search": "TEST-IMP-CHILD", "page_size": 20},
        headers=admin_headers,
    ).json()["items"][0]
    assert child["parent_location_code"] == "TEST-IMP-ROOT"

    cyclic = _csv([
        ["location_name", "location_code", "location_type", "parent_location_code"],
        ["Cycle A", "TEST-CYCLE-A", "Terminal", "TEST-CYCLE-B"],
        ["Cycle B", "TEST-CYCLE-B", "Tank Farm", "TEST-CYCLE-A"],
    ])
    invalid = client.post(
        "/api/locations/import",
        files={"file": ("cycle.csv", cyclic, "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert invalid.status_code == 200
    assert invalid.json()["invalid_rows"] == 2
    rejected = client.post(
        "/api/locations/import",
        files={"file": ("cycle.csv", cyclic, "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert rejected.status_code == 422


def test_standard_permissions_are_auto_seeded_and_enforced(client, admin_headers):
    catalog = client.get("/api/permissions/catalog", headers=admin_headers)
    assert catalog.status_code == 200
    names = {
        permission["permission_name"]
        for category in catalog.json()["categories"]
        for module in category["modules"]
        for permission in module["permissions"]
    }
    assert {"users:read", "roles:create", "permissions:read", "assignments:write", "locations:read"} <= names

    role_id = _create_role(client, admin_headers, "Location Read Only Integration")
    permission = client.get(
        "/api/permissions",
        params={"search": "locations:read", "page_size": 20},
        headers=admin_headers,
    ).json()["items"][0]
    grant = client.put(
        f"/api/roles/{role_id}/permissions",
        json={"permission_ids": [permission["id"]]},
        headers=admin_headers,
    )
    assert grant.status_code == 200, grant.text

    user = client.post(
        "/api/users",
        json={
            "full_name": "Location Read User",
            "username": "location.read.user",
            "email": "location.read.user@example.com",
            "password": "Location@123",
            "role_ids": [role_id],
            "force_password_change": False,
        },
        headers=admin_headers,
    )
    assert user.status_code == 201, user.text
    login = client.post("/api/auth/login", json={"username": "location.read.user", "password": "Location@123"})
    assert login.status_code == 200, login.text
    user_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/locations", headers=user_headers).status_code == 200
    assert client.get("/api/roles", headers=user_headers).status_code == 403
    assert client.post(
        "/api/locations",
        json={"location_name": "Not Allowed", "location_code": "NO-LOCATION-CREATE", "location_type": "Terminal"},
        headers=user_headers,
    ).status_code == 403


def test_bootstrap_keeps_active_catalog_standard_only():
    db: Session = SessionLocal()
    suffix = uuid.uuid4().hex[:10]
    custom = Permission(
        permission_name=f"Custom Permission {suffix}",
        module_name="Legacy Custom Module",
        category="Legacy",
        action="Other",
        status="Active",
    )
    db.add(custom)
    db.commit()
    try:
        seed_permission_catalog(db)
        db.refresh(custom)
        assert custom.status == "Inactive"
        active_names = {
            permission.permission_name
            for permission in db.query(Permission).filter(Permission.status == "Active").all()
        }
        assert active_names
        assert all(":" in name for name in active_names)
    finally:
        db.close()


def test_legacy_permission_migration_preserves_role_grants():
    db: Session = SessionLocal()
    suffix = uuid.uuid4().hex[:10]
    role = Role(role_name=f"Legacy Migration {suffix}", status="Active")
    legacy = Permission(
        permission_name="View User",
        module_name="User Master",
        category="Legacy",
        action="Other",
        status="Active",
    )
    db.add_all([role, legacy])
    db.flush()
    db.add(RolePermission(role_id=role.id, permission_id=legacy.id))
    db.commit()
    try:
        added = _migrate_legacy_permission_grants(db)
        db.commit()
        assert added == 1
        assert legacy.status == "Inactive"
        target = db.query(Permission).filter_by(permission_name="users:read").one()
        assert db.query(RolePermission).filter_by(role_id=role.id, permission_id=target.id).count() == 1

        assert _migrate_legacy_permission_grants(db) == 0
        db.commit()
        assert db.query(RolePermission).filter_by(role_id=role.id, permission_id=target.id).count() == 1
    finally:
        db.close()
