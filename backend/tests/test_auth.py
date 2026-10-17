"""Authentication, lockout and session tests."""

from __future__ import annotations


def test_health_reports_admin_seeded(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["admin_seeded"] is True
    assert body["version"]


def test_admin_login_returns_permissions(client, admin_tokens):
    assert admin_tokens["access_token"]
    assert admin_tokens["refresh_token"]
    user = admin_tokens["user"]
    assert user["username"] == "admin"
    assert user["is_admin"] is True
    assert len(user["permissions"]) >= 20
    permission_names = {permission["permission_name"] for permission in user["permissions"]}
    assert "audit:read" in permission_names
    assert all(":" in name for name in permission_names)


def test_me_requires_a_valid_token(client, admin_headers):
    assert client.get("/api/auth/me").status_code == 401
    response = client.get("/api/auth/me", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_failed_login_is_audited(client, admin_headers):
    response = client.post(
        "/api/auth/login",
        json={"username": "ghost_user", "password": "Whatever@123"},
    )
    assert response.status_code == 401

    audit = client.get(
        "/api/audit-logs",
        params={"search": "ghost_user", "page_size": 20},
        headers=admin_headers,
    )
    assert audit.status_code == 200
    actions = [item["action"] for item in audit.json()["items"]]
    assert "Login Failed" in actions


def test_account_lockout_after_five_failures(client, admin_headers):
    create = client.post(
        "/api/users",
        json={
            "full_name": "Lockout Tester",
            "username": "lockout.tester",
            "email": "lockout.tester@example.com",
            "password": "Lock@12345",
            "role_ids": [],
            "force_password_change": False,
        },
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text

    for _ in range(5):
        failed = client.post(
            "/api/auth/login",
            json={"username": "lockout.tester", "password": "Wrong@12345"},
        )
        assert failed.status_code == 401

    locked = client.post(
        "/api/auth/login",
        json={"username": "lockout.tester", "password": "Lock@12345"},
    )
    assert locked.status_code == 423
    assert "locked" in locked.json()["detail"].lower()


def test_logout_revokes_access_token(client):
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Admin@12345"},
    )
    access_token = login.json()["access_token"]
    refresh_token = login.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    assert client.get("/api/auth/me", headers=headers).status_code == 200
    logout = client.post(
        "/api/auth/logout",
        json={"refresh_token": refresh_token},
        headers=headers,
    )
    assert logout.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_refresh_rotates_tokens(client):
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Admin@12345"},
    ).json()
    refreshed = client.post(
        "/api/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    assert refreshed.status_code == 200
    new_access = refreshed.json()["access_token"]
    assert new_access != login["access_token"]

    # The rotated refresh token is revoked.
    reused = client.post(
        "/api/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    assert reused.status_code == 401


def test_password_reset_request_creates_auditable_record(client, admin_headers):
    response = client.post(
        "/api/auth/forgot-password",
        json={"username": "admin", "reason": "Testing reset flow", "reset_2fa": False},
    )
    assert response.status_code == 200
    assert "request" in response.json()["message"].lower()

    audit = client.get(
        "/api/audit-logs",
        params={"action": "Password Reset Requested", "page_size": 20},
        headers=admin_headers,
    )
    assert audit.status_code == 200
    assert audit.json()["total"] >= 1
