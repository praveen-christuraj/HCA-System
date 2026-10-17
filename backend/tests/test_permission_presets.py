"""Permission Preset Master coverage.

Capped catalog (20 presets), CRUD with soft deactivation and permanent delete,
replace/add application to one or many roles, RBAC enforcement, import
preview/commit, three-format export and the audit trail every action writes.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta

from openpyxl import Workbook

from app.config import MAX_PERMISSION_PRESETS

PREFIX = "Preset Test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _csv(rows: list[list[str]]) -> bytes:
    return ("\ufeff" + "\n".join(",".join(row) for row in rows) + "\n").encode("utf-8")


def _xlsx(rows: list[list[str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _catalog_ids(client, headers) -> dict[str, int]:
    response = client.get("/api/permissions/catalog", headers=headers)
    assert response.status_code == 200, response.text
    ids: dict[str, int] = {}
    for category in response.json()["categories"]:
        for module in category["modules"]:
            for permission in module["permissions"]:
                ids[permission["permission_name"]] = permission["id"]
    return ids


def _ids(client, headers, *names: str) -> list[int]:
    catalog = _catalog_ids(client, headers)
    missing = [name for name in names if name not in catalog]
    assert not missing, f"permissions missing from the catalog: {missing}"
    return [catalog[name] for name in names]


def _create_preset(client, headers, name: str, permission_ids: list[int], **extra) -> dict:
    payload = {"preset_name": name, "permission_ids": permission_ids, **extra}
    response = client.post("/api/permission-presets", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _create_role(client, headers, name: str) -> int:
    response = client.post(
        "/api/roles",
        json={"role_name": name, "description": "Permission preset test role"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _role_permission_names(client, headers, role_id: int) -> set[str]:
    response = client.get(f"/api/roles/{role_id}/permissions", headers=headers)
    assert response.status_code == 200, response.text
    return {item["permission_name"] for item in response.json()["items"]}


def _purge_test_presets(client, headers) -> None:
    """Remove every preset this suite created, straight from the database.

    Application code refuses to erase a preset that has been applied, which is
    the behaviour under test; test isolation still needs the rows gone.
    """
    from app.database import SessionLocal
    from app.models import PermissionPreset, PermissionPresetItem

    db = SessionLocal()
    try:
        presets = (
            db.query(PermissionPreset)
            .filter(PermissionPreset.preset_name.ilike(f"{PREFIX}%"))
            .all()
        )
        for preset in presets:
            db.query(PermissionPresetItem).filter(
                PermissionPresetItem.preset_id == preset.id
            ).delete(synchronize_session=False)
            db.delete(preset)
        db.commit()
    finally:
        db.close()
    listed = client.get("/api/permission-presets", headers=headers, params={"page_size": 200})
    assert listed.status_code == 200
    assert not [
        item for item in listed.json()["items"] if item["preset_name"].startswith(PREFIX)
    ]


def _audit_rows(client, headers, *, action: str, module_name: str | None = None) -> list[dict]:
    params = {"action": action, "page_size": 200}
    if module_name:
        params["module_name"] = module_name
    response = client.get("/api/audit-logs", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


# ---------------------------------------------------------------------------
# CRUD, validation and the capped catalog
# ---------------------------------------------------------------------------
def test_preset_crud_validation_and_soft_delete(client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    name = f"{PREFIX} Operations Read {suffix}"
    permission_ids = _ids(client, admin_headers, "users:read", "roles:read")

    created = _create_preset(
        client,
        admin_headers,
        name,
        permission_ids,
        description="Read-only operations preset",
    )
    assert created["preset_name"] == name
    assert created["status"] == "Active"
    assert created["permission_count"] == 2
    assert created["module_count"] == 2
    assert created["times_applied"] == 0
    assert created["preset_limit"] == MAX_PERMISSION_PRESETS
    assert created["presets_used"] >= 1
    assert sorted(created["permission_ids"]) == sorted(permission_ids)

    other_name = f"{PREFIX} Operations Other {suffix}"
    try:
        _create_preset(client, admin_headers, other_name, permission_ids)

        duplicate = client.post(
            "/api/permission-presets",
            json={"preset_name": f"  {name.upper()} ", "permission_ids": permission_ids},
            headers=admin_headers,
        )
        assert duplicate.status_code == 409

        too_short = client.post(
            "/api/permission-presets",
            json={"preset_name": "A", "permission_ids": permission_ids},
            headers=admin_headers,
        )
        assert too_short.status_code == 422

        empty = client.post(
            "/api/permission-presets",
            json={"preset_name": f"{PREFIX} Empty {suffix}", "permission_ids": []},
            headers=admin_headers,
        )
        assert empty.status_code == 422

        unknown = client.post(
            "/api/permission-presets",
            json={"preset_name": f"{PREFIX} Unknown {suffix}", "permission_ids": [987654]},
            headers=admin_headers,
        )
        assert unknown.status_code == 422

        duplicated_ids = client.post(
            "/api/permission-presets",
            json={
                "preset_name": f"{PREFIX} Duplicated {suffix}",
                "permission_ids": permission_ids + permission_ids[:1],
            },
            headers=admin_headers,
        )
        assert duplicated_ids.status_code == 422

        detail = client.get(f"/api/permission-presets/{created['id']}", headers=admin_headers)
        assert detail.status_code == 200
        payload = detail.json()
        assert {item["permission_name"] for item in payload["permissions"]} == {
            "users:read",
            "roles:read",
        }
        assert payload["presets_remaining"] == MAX_PERMISSION_PRESETS - payload["presets_used"]

        missing = client.get("/api/permission-presets/424242", headers=admin_headers)
        assert missing.status_code == 404

        location_id = _ids(client, admin_headers, "locations:read")[0]
        updated = client.put(
            f"/api/permission-presets/{created['id']}",
            json={
                "preset_name": f"{name} v2",
                "description": "Extended read preset",
                "permission_ids": [permission_ids[0], location_id],
            },
            headers=admin_headers,
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["preset_name"] == f"{name} v2"
        assert body["description"] == "Extended read preset"
        assert body["added"] == 1
        assert body["removed"] == 1
        assert body["permission_count"] == 2
        assert set(body["active_permission_ids"]) == {permission_ids[0], location_id}

        rename_conflict = client.put(
            f"/api/permission-presets/{created['id']}",
            json={"preset_name": other_name.upper()},
            headers=admin_headers,
        )
        assert rename_conflict.status_code == 409

        # Renaming a preset to a case variant of its own name is allowed.
        own_case = client.put(
            f"/api/permission-presets/{created['id']}",
            json={"preset_name": body["preset_name"].upper()},
            headers=admin_headers,
        )
        assert own_case.status_code == 200, own_case.text
        assert own_case.json()["preset_name"] == body["preset_name"].upper()

        deactivated = client.delete(
            f"/api/permission-presets/{created['id']}", headers=admin_headers
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["preset"]["status"] == "Inactive"
        # A deactivated preset still occupies a slot in the capped catalog.
        assert deactivated.json()["presets_used"] == body["presets_used"]

        reactivated = client.put(
            f"/api/permission-presets/{created['id']}",
            json={"status": "Active"},
            headers=admin_headers,
        )
        assert reactivated.status_code == 200
        assert reactivated.json()["status"] == "Active"

        assert _audit_rows(client, admin_headers, action="Create Permission Preset")
        assert _audit_rows(client, admin_headers, action="Update Permission Preset")
        assert _audit_rows(client, admin_headers, action="Deactivate Permission Preset")
    finally:
        _purge_test_presets(client, admin_headers)


def test_preset_permanent_delete_rules(client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    permission_ids = _ids(client, admin_headers, "users:read")
    preset = _create_preset(client, admin_headers, f"{PREFIX} Deletable {suffix}", permission_ids)

    used_before = preset["presets_used"]
    deleted = client.delete(
        f"/api/permission-presets/{preset['id']}",
        params={"permanent": "true"},
        headers=admin_headers,
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["permanent"] is True
    assert deleted.json()["presets_used"] == used_before - 1

    assert client.get(f"/api/permission-presets/{preset['id']}", headers=admin_headers).status_code == 404
    assert _audit_rows(client, admin_headers, action="Delete Permission Preset")

    # Once a preset has shaped live roles it may only be deactivated.
    applied = _create_preset(client, admin_headers, f"{PREFIX} Applied {suffix}", permission_ids)
    role_id = _create_role(client, admin_headers, f"{PREFIX} Role {suffix}")
    response = client.post(
        f"/api/permission-presets/{applied['id']}/apply",
        json={"role_ids": [role_id], "mode": "replace"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    blocked = client.delete(
        f"/api/permission-presets/{applied['id']}",
        params={"permanent": "true"},
        headers=admin_headers,
    )
    assert blocked.status_code == 409
    soft = client.delete(f"/api/permission-presets/{applied['id']}", headers=admin_headers)
    assert soft.status_code == 200
    assert soft.json()["preset"]["status"] == "Inactive"
    _purge_test_presets(client, admin_headers)


def test_preset_cap_is_enforced_at_twenty(client, admin_headers):
    assert MAX_PERMISSION_PRESETS == 20
    suffix = uuid.uuid4().hex[:8]
    permission_ids = _ids(client, admin_headers, "users:read")

    listing = client.get("/api/permission-presets", headers=admin_headers)
    remaining = listing.json()["presets_remaining"]
    assert 0 < remaining <= MAX_PERMISSION_PRESETS

    try:
        for index in range(remaining):
            _create_preset(
                client, admin_headers, f"{PREFIX} Cap {suffix} {index:02d}", permission_ids
            )

        full = client.get("/api/permission-presets", headers=admin_headers).json()
        assert full["presets_used"] == MAX_PERMISSION_PRESETS
        assert full["presets_remaining"] == 0

        refused = client.post(
            "/api/permission-presets",
            json={"preset_name": f"{PREFIX} Over Cap {suffix}", "permission_ids": permission_ids},
            headers=admin_headers,
        )
        assert refused.status_code == 409
        assert "Preset limit reached" in refused.json()["detail"]

        over_cap_csv = _csv(
            [
                ["preset_name", "permission_names"],
                [f"{PREFIX} Import Over Cap {suffix}", "users:read"],
            ]
        )
        preview = client.post(
            "/api/permission-presets/import",
            files={"file": ("over-cap.csv", over_cap_csv, "text/csv")},
            data={"confirm": "false"},
            headers=admin_headers,
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["invalid_rows"] == 1
        assert "Preset limit" in preview.json()["rows"][0]["errors"][0]

        freed = client.delete(
            f"/api/permission-presets/{full['items'][0]['id']}",
            params={"permanent": "true"},
            headers=admin_headers,
        )
        assert freed.status_code == 200
        assert freed.json()["presets_remaining"] == 1
        _create_preset(
            client, admin_headers, f"{PREFIX} Reuses Slot {suffix}", permission_ids
        )
    finally:
        _purge_test_presets(client, admin_headers)


def test_preset_list_filters_and_pagination(client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    user_ids = _ids(client, admin_headers, "users:read", "users:create")
    asset_ids = _ids(client, admin_headers, "assets:read")
    first = _create_preset(client, admin_headers, f"{PREFIX} Filter Users {suffix}", user_ids)
    second = _create_preset(client, admin_headers, f"{PREFIX} Filter Assets {suffix}", asset_ids)

    try:
        search = client.get(
            "/api/permission-presets",
            params={"search": f"Filter Users {suffix}", "page_size": 20},
            headers=admin_headers,
        ).json()
        assert search["total"] == 1
        assert search["items"][0]["id"] == first["id"]

        by_module = client.get(
            "/api/permission-presets",
            params={"module_name": "Asset Master", "search": PREFIX, "page_size": 20},
            headers=admin_headers,
        ).json()
        assert {item["id"] for item in by_module["items"]} == {second["id"]}

        by_permission = client.get(
            "/api/permission-presets",
            params={"permission_id": user_ids[1], "page_size": 20},
            headers=admin_headers,
        ).json()
        assert {item["id"] for item in by_permission["items"]} == {first["id"]}

        client.delete(f"/api/permission-presets/{second['id']}", headers=admin_headers)
        inactive = client.get(
            "/api/permission-presets",
            params={"status": "Inactive", "search": PREFIX, "page_size": 20},
            headers=admin_headers,
        ).json()
        assert {item["id"] for item in inactive["items"]} == {second["id"]}
        active = client.get(
            "/api/permission-presets",
            params={"status": "Active", "search": PREFIX, "page_size": 20},
            headers=admin_headers,
        ).json()
        assert {item["id"] for item in active["items"]} == {first["id"]}

        today = date.today()
        in_range = client.get(
            "/api/permission-presets",
            params={"search": PREFIX, "date_from": today.isoformat(), "page_size": 20},
            headers=admin_headers,
        ).json()
        assert in_range["total"] == 2
        out_of_range = client.get(
            "/api/permission-presets",
            params={
                "search": PREFIX,
                "date_from": (today - timedelta(days=2)).isoformat(),
                "date_to": (today - timedelta(days=1)).isoformat(),
                "page_size": 20,
            },
            headers=admin_headers,
        ).json()
        assert out_of_range["total"] == 0

        snapped = client.get(
            "/api/permission-presets", params={"page_size": 30}, headers=admin_headers
        ).json()
        assert snapped["page_size"] == 20
        assert snapped["page"] == 1
        paged = client.get(
            "/api/permission-presets", params={"page": 99, "page_size": 20}, headers=admin_headers
        ).json()
        assert paged["items"] == []
        assert paged["has_more"] is False

        options = client.get("/api/permission-presets/options", headers=admin_headers).json()
        option_ids = {item["id"] for item in options["items"]}
        assert first["id"] in option_ids
        assert second["id"] not in option_ids
        assert options["preset_limit"] == MAX_PERMISSION_PRESETS
    finally:
        _purge_test_presets(client, admin_headers)


# ---------------------------------------------------------------------------
# Applying presets to roles
# ---------------------------------------------------------------------------
def test_preset_apply_replace_and_add_modes(client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    read_ids = _ids(client, admin_headers, "users:read", "roles:read")
    extra_ids = _ids(client, admin_headers, "locations:read")

    preset = _create_preset(client, admin_headers, f"{PREFIX} Apply Read {suffix}", read_ids)
    addition = _create_preset(client, admin_headers, f"{PREFIX} Apply Extra {suffix}", extra_ids)
    first_role = _create_role(client, admin_headers, f"{PREFIX} Apply One {suffix}")
    second_role = _create_role(client, admin_headers, f"{PREFIX} Apply Two {suffix}")

    try:
        seeded = client.put(
            f"/api/roles/{first_role}/permissions",
            json={"permission_ids": extra_ids},
            headers=admin_headers,
        )
        assert seeded.status_code == 200, seeded.text

        replaced = client.post(
            f"/api/permission-presets/{preset['id']}/apply",
            json={"role_ids": [first_role, second_role], "mode": "replace"},
            headers=admin_headers,
        )
        assert replaced.status_code == 200, replaced.text
        body = replaced.json()
        assert body["mode"] == "replace"
        assert body["roles_updated"] == 2
        assert body["preset"]["times_applied"] == 2
        assert body["preset"]["last_applied_at"]
        per_role = {row["role_id"]: row for row in body["roles"]}
        assert per_role[first_role]["added"] == 2
        assert per_role[first_role]["removed"] == 1
        assert per_role[second_role]["added"] == 2
        assert per_role[second_role]["removed"] == 0
        assert _role_permission_names(client, admin_headers, first_role) == {
            "users:read",
            "roles:read",
        }
        assert _role_permission_names(client, admin_headers, second_role) == {
            "users:read",
            "roles:read",
        }

        merged = client.post(
            f"/api/permission-presets/{addition['id']}/apply",
            json={"role_ids": [first_role], "mode": "add"},
            headers=admin_headers,
        )
        assert merged.status_code == 200, merged.text
        assert merged.json()["roles"][0]["added"] == 1
        assert merged.json()["roles"][0]["removed"] == 0
        assert _role_permission_names(client, admin_headers, first_role) == {
            "users:read",
            "roles:read",
            "locations:read",
        }

        # Re-applying the same preset in add mode is a no-op, never a duplicate.
        idempotent = client.post(
            f"/api/permission-presets/{addition['id']}/apply",
            json={"role_ids": [first_role], "mode": "add"},
            headers=admin_headers,
        )
        assert idempotent.status_code == 200
        assert idempotent.json()["roles"][0]["added"] == 0
        assert idempotent.json()["roles"][0]["total"] == 3

        grants = client.get(f"/api/roles/{first_role}/permissions", headers=admin_headers).json()
        assert len(grants["permission_ids"]) == len(set(grants["permission_ids"])) == 3

        rows = _audit_rows(
            client, admin_headers, action="Apply Permission Preset",
            module_name="Role Permission Assignment",
        )
        assert len([row for row in rows if row["entity_id"] == first_role]) >= 3
        summary = next(row for row in rows if row["entity_id"] == second_role)
        assert summary["details_summary"].startswith(f"preset_id={preset['id']}")
        assert "mode=replace" in summary["details_summary"]
        assert summary["outcome"] == "Success"
    finally:
        _purge_test_presets(client, admin_headers)


def test_preset_apply_guards(client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    permission_ids = _ids(client, admin_headers, "users:read")
    preset = _create_preset(client, admin_headers, f"{PREFIX} Guards {suffix}", permission_ids)
    role_id = _create_role(client, admin_headers, f"{PREFIX} Guard Role {suffix}")

    try:
        admin_role = next(
            role
            for role in client.get("/api/roles", headers=admin_headers, params={"page_size": 200}).json()["items"]
            if role["is_reserved"]
        )
        reserved = client.post(
            f"/api/permission-presets/{preset['id']}/apply",
            json={"role_ids": [admin_role["id"]], "mode": "replace"},
            headers=admin_headers,
        )
        assert reserved.status_code == 403
        assert "reserved Admin role" in reserved.json()["detail"]

        role_name = f"{PREFIX} Guard Role {suffix}"
        inactive_role = client.put(
            f"/api/roles/{role_id}",
            json={"role_name": role_name, "status": "Inactive"},
            headers=admin_headers,
        )
        assert inactive_role.status_code == 200, inactive_role.text
        refused = client.post(
            f"/api/permission-presets/{preset['id']}/apply",
            json={"role_ids": [role_id], "mode": "replace"},
            headers=admin_headers,
        )
        assert refused.status_code == 422
        assert "Only active roles" in refused.json()["detail"]
        client.put(
            f"/api/roles/{role_id}",
            json={"role_name": role_name, "status": "Active"},
            headers=admin_headers,
        )

        unknown = client.post(
            f"/api/permission-presets/{preset['id']}/apply",
            json={"role_ids": [role_id, 424242], "mode": "replace"},
            headers=admin_headers,
        )
        assert unknown.status_code == 422
        assert "424242" in unknown.json()["detail"]

        duplicated = client.post(
            f"/api/permission-presets/{preset['id']}/apply",
            json={"role_ids": [role_id, role_id], "mode": "replace"},
            headers=admin_headers,
        )
        assert duplicated.status_code == 422

        empty = client.post(
            f"/api/permission-presets/{preset['id']}/apply",
            json={"role_ids": [], "mode": "replace"},
            headers=admin_headers,
        )
        assert empty.status_code == 422

        bad_mode = client.post(
            f"/api/permission-presets/{preset['id']}/apply",
            json={"role_ids": [role_id], "mode": "merge"},
            headers=admin_headers,
        )
        assert bad_mode.status_code == 422

        client.delete(f"/api/permission-presets/{preset['id']}", headers=admin_headers)
        inactive_preset = client.post(
            f"/api/permission-presets/{preset['id']}/apply",
            json={"role_ids": [role_id], "mode": "replace"},
            headers=admin_headers,
        )
        assert inactive_preset.status_code == 422
        assert "Only active presets" in inactive_preset.json()["detail"]

        missing_preset = client.post(
            "/api/permission-presets/424242/apply",
            json={"role_ids": [role_id], "mode": "replace"},
            headers=admin_headers,
        )
        assert missing_preset.status_code == 404
    finally:
        _purge_test_presets(client, admin_headers)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def _login(client, username: str, password: str) -> dict:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_preset_rbac_enforcement(client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    catalog = _catalog_ids(client, admin_headers)

    viewer_role = _create_role(client, admin_headers, f"{PREFIX} Viewer {suffix}")
    client.put(
        f"/api/roles/{viewer_role}/permissions",
        json={
            "permission_ids": [
                catalog["permission_presets:read"],
                catalog["roles:read"],
                catalog["permissions:read"],
            ]
        },
        headers=admin_headers,
    )
    editor_role = _create_role(client, admin_headers, f"{PREFIX} Editor {suffix}")
    client.put(
        f"/api/roles/{editor_role}/permissions",
        json={
            "permission_ids": [
                catalog["permission_presets:read"],
                catalog["permission_presets:create"],
                catalog["permission_presets:update"],
                catalog["permission_presets:delete"],
                catalog["assignments:write"],
                catalog["roles:read"],
                catalog["permissions:read"],
                catalog["users:read"],
            ]
        },
        headers=admin_headers,
    )

    viewer = client.post(
        "/api/users",
        json={
            "full_name": "Preset Viewer",
            "username": f"preset.viewer.{suffix}",
            "email": f"preset.viewer.{suffix}@example.com",
            "password": "Preset@12345",
            "force_password_change": False,
            "role_ids": [viewer_role],
        },
        headers=admin_headers,
    )
    assert viewer.status_code == 201, viewer.text
    editor = client.post(
        "/api/users",
        json={
            "full_name": "Preset Editor",
            "username": f"preset.editor.{suffix}",
            "email": f"preset.editor.{suffix}@example.com",
            "password": "Preset@12345",
            "force_password_change": False,
            "role_ids": [editor_role],
        },
        headers=admin_headers,
    )
    assert editor.status_code == 201, editor.text

    viewer_headers = _login(client, f"preset.viewer.{suffix}", "Preset@12345")
    editor_headers = _login(client, f"preset.editor.{suffix}", "Preset@12345")

    assert client.get("/api/permission-presets").status_code in {401, 403}
    assert client.get("/api/permission-presets", headers=viewer_headers).status_code == 200

    forbidden_create = client.post(
        "/api/permission-presets",
        json={
            "preset_name": f"{PREFIX} Viewer Create {suffix}",
            "permission_ids": [catalog["users:read"]],
        },
        headers=viewer_headers,
    )
    assert forbidden_create.status_code == 403
    assert "permission_presets:create" in forbidden_create.json()["detail"]

    viewer_preset = _create_preset(
        client, admin_headers, f"{PREFIX} Viewer Target {suffix}", [catalog["users:read"]]
    )
    forbidden_apply = client.post(
        f"/api/permission-presets/{viewer_preset['id']}/apply",
        json={"role_ids": [viewer_role], "mode": "add"},
        headers=viewer_headers,
    )
    assert forbidden_apply.status_code == 403
    assert "assignments:write" in forbidden_apply.json()["detail"]

    forbidden_update = client.put(
        f"/api/permission-presets/{viewer_preset['id']}",
        json={"description": "viewer edit"},
        headers=viewer_headers,
    )
    assert forbidden_update.status_code == 403
    forbidden_delete = client.delete(
        f"/api/permission-presets/{viewer_preset['id']}", headers=viewer_headers
    )
    assert forbidden_delete.status_code == 403

    # The editor holds the preset capabilities and assignments:write, but not
    # audit:read, so a preset containing it must be refused.
    beyond_access = client.post(
        "/api/permission-presets",
        json={
            "preset_name": f"{PREFIX} Editor Beyond {suffix}",
            "permission_ids": [catalog["audit:read"]],
        },
        headers=editor_headers,
    )
    assert beyond_access.status_code == 403
    assert "permissions you do not hold" in beyond_access.json()["detail"]

    editor_preset = _create_preset(
        client,
        editor_headers,
        f"{PREFIX} Editor Own {suffix}",
        [catalog["users:read"], catalog["roles:read"]],
    )
    assert editor_preset["created_by_name"] == "Preset Editor"

    editor_role_target = _create_role(client, admin_headers, f"{PREFIX} Editor Target {suffix}")
    applied = client.post(
        f"/api/permission-presets/{editor_preset['id']}/apply",
        json={"role_ids": [editor_role_target], "mode": "replace"},
        headers=editor_headers,
    )
    assert applied.status_code == 200, applied.text
    assert _role_permission_names(client, admin_headers, editor_role_target) == {
        "users:read",
        "roles:read",
    }

    # Replacing a role that holds access the editor does not is refused.
    client.put(
        f"/api/roles/{editor_role_target}/permissions",
        json={"permission_ids": [catalog["users:read"], catalog["audit:read"]]},
        headers=admin_headers,
    )
    blocked_replace = client.post(
        f"/api/permission-presets/{editor_preset['id']}/apply",
        json={"role_ids": [editor_role_target], "mode": "replace"},
        headers=editor_headers,
    )
    assert blocked_replace.status_code == 403
    # Adding is still allowed: nothing outside the editor's access is removed.
    allowed_add = client.post(
        f"/api/permission-presets/{editor_preset['id']}/apply",
        json={"role_ids": [editor_role_target], "mode": "add"},
        headers=editor_headers,
    )
    assert allowed_add.status_code == 200, allowed_add.text
    assert "audit:read" in _role_permission_names(client, admin_headers, editor_role_target)

    # The reserved Admin role keeps every catalog permission, including the new ones.
    me = client.get("/api/auth/me", headers=admin_headers).json()
    held = {permission["permission_name"] for permission in me["permissions"]}
    assert {
        "permission_presets:read",
        "permission_presets:create",
        "permission_presets:update",
        "permission_presets:delete",
    } <= held

    _purge_test_presets(client, admin_headers)


# ---------------------------------------------------------------------------
# Import and export
# ---------------------------------------------------------------------------
def test_preset_import_preview_and_commit(client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    existing = _create_preset(
        client, admin_headers, f"{PREFIX} Import Existing {suffix}", _ids(client, admin_headers, "users:read")
    )

    try:
        payload = _csv(
            [
                ["preset_name", "permission_names", "description", "status"],
                [f"{PREFIX} Import Valid {suffix}", "users:read; roles:read", "Valid row", "Active"],
                [f"{PREFIX} Import Unknown {suffix}", "users:read; not:a:permission", "Unknown key", "Active"],
                [f"{PREFIX} Import Existing {suffix}", "users:read", "Duplicate name", "Active"],
                [f"{PREFIX} Import Empty {suffix}", "", "No permissions", "Active"],
                ["", "users:read", "No name", "Active"],
                [f"{PREFIX} Import Status {suffix}", "users:read", "Bad status", "Deleted"],
            ]
        )
        preview = client.post(
            "/api/permission-presets/import",
            files={"file": ("presets.csv", payload, "text/csv")},
            data={"confirm": "false"},
            headers=admin_headers,
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["total_rows"] == 6
        assert body["valid_rows"] == 1
        assert body["invalid_rows"] == 5
        assert body["preset_limit"] == MAX_PERMISSION_PRESETS
        errors = {row["preset_name"]: row["errors"] for row in body["rows"]}
        assert errors[f"{PREFIX} Import Valid {suffix}"] == []
        assert any("Unknown or inactive" in error for error in errors[f"{PREFIX} Import Unknown {suffix}"])
        assert "Preset name already exists" in errors[f"{PREFIX} Import Existing {suffix}"]
        assert "At least one permission key is required" in errors[f"{PREFIX} Import Empty {suffix}"]
        assert "Preset name is required" in errors[""]
        assert "Status must be Active or Inactive" in errors[f"{PREFIX} Import Status {suffix}"]

        blocked_commit = client.post(
            "/api/permission-presets/import",
            files={"file": ("presets.csv", payload, "text/csv")},
            data={"confirm": "true"},
            headers=admin_headers,
        )
        assert blocked_commit.status_code == 422

        clean = _csv(
            [
                ["preset_name", "permission_names", "description", "status"],
                [f"{PREFIX} Import Clean {suffix}", "users:read; locations:read", "Clean row", "Active"],
            ]
        )
        committed = client.post(
            "/api/permission-presets/import",
            files={"file": ("presets-clean.csv", clean, "text/csv")},
            data={"confirm": "true"},
            headers=admin_headers,
        )
        assert committed.status_code == 200, committed.text
        assert committed.json()["imported"] == 1

        imported = client.get(
            "/api/permission-presets",
            params={"search": f"Import Clean {suffix}", "page_size": 20},
            headers=admin_headers,
        ).json()["items"][0]
        assert imported["permission_count"] == 2
        assert imported["description"] == "Clean row"

        workbook = _xlsx(
            [
                ["preset_name", "permission_names", "description"],
                [f"{PREFIX} Import Sheet {suffix}", "roles:read;assets:read", "From XLSX"],
            ]
        )
        xlsx_commit = client.post(
            "/api/permission-presets/import",
            files={
                "file": (
                    "presets.xlsx",
                    workbook,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={"confirm": "true"},
            headers=admin_headers,
        )
        assert xlsx_commit.status_code == 200, xlsx_commit.text
        assert xlsx_commit.json()["imported"] == 1
        sheet_preset = client.get(
            "/api/permission-presets",
            params={"search": f"Import Sheet {suffix}", "page_size": 20},
            headers=admin_headers,
        ).json()["items"][0]
        assert sheet_preset["permission_count"] == 2
        assert sheet_preset["status"] == "Active"

        rejected_type = client.post(
            "/api/permission-presets/import",
            files={"file": ("presets.txt", b"preset_name,permission_names", "text/plain")},
            data={"confirm": "false"},
            headers=admin_headers,
        )
        assert rejected_type.status_code == 422

        missing_columns = client.post(
            "/api/permission-presets/import",
            files={"file": ("short.csv", _csv([["preset_name"], ["No permissions"]]), "text/csv")},
            data={"confirm": "false"},
            headers=admin_headers,
        )
        assert missing_columns.status_code == 422
        assert "permission_names" in missing_columns.json()["missing_columns"]

        assert _audit_rows(client, admin_headers, action="Import Permission Presets")
        assert _audit_rows(client, admin_headers, action="Preview Permission Preset Import")
    finally:
        assert existing["id"]
        _purge_test_presets(client, admin_headers)


def test_preset_export_formats(client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    preset = _create_preset(
        client,
        admin_headers,
        f"{PREFIX} Export {suffix}",
        _ids(client, admin_headers, "users:read", "roles:read"),
        description="Exported preset",
    )

    try:
        csv_response = client.get(
            "/api/permission-presets/export",
            params={"format": "csv", "search": f"Export {suffix}"},
            headers=admin_headers,
        )
        assert csv_response.status_code == 200
        assert csv_response.headers["content-type"].startswith("text/csv")
        text = csv_response.text
        assert preset["preset_name"] in text
        assert "roles:read; users:read" in text
        assert 'content-disposition' in {key.lower() for key in csv_response.headers}

        xlsx_response = client.get(
            "/api/permission-presets/export",
            params={"format": "xlsx"},
            headers=admin_headers,
        )
        assert xlsx_response.status_code == 200
        assert "spreadsheetml" in xlsx_response.headers["content-type"]

        pdf_response = client.get(
            "/api/permission-presets/export",
            params={"format": "pdf", "status": "Active"},
            headers=admin_headers,
        )
        assert pdf_response.status_code == 200
        assert pdf_response.headers["content-type"] == "application/pdf"

        bad_format = client.get(
            "/api/permission-presets/export", params={"format": "json"}, headers=admin_headers
        )
        assert bad_format.status_code == 422

        assert _audit_rows(client, admin_headers, action="Export Permission Presets")
    finally:
        _purge_test_presets(client, admin_headers)


def test_preset_module_dashboard_and_navigation_metadata(client, admin_headers):
    suffix = uuid.uuid4().hex[:8]
    preset = _create_preset(
        client, admin_headers, f"{PREFIX} Dashboard {suffix}", _ids(client, admin_headers, "users:read")
    )
    try:
        dashboard = client.get("/api/dashboard/modules/user-management", headers=admin_headers)
        assert dashboard.status_code == 200, dashboard.text
        body = dashboard.json()
        kpi = next(item for item in body["kpis"] if item["label"] == "Permission presets")
        assert kpi["value"].endswith(f"/ {MAX_PERMISSION_PRESETS}")
        assert {link["path"] for link in body["quick_links"]} >= {"/permission-presets"}

        summary = client.get("/api/dashboard/summary", headers=admin_headers).json()
        user_module = next(
            module for module in summary["modules"] if module["key"] == "user-management"
        )
        assert any(metric["label"] == "Permission presets" for metric in user_module["metrics"])
    finally:
        assert preset["id"]
        _purge_test_presets(client, admin_headers)
