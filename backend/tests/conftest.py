"""Test configuration.

The environment is configured before importing the application so the engine
binds to a disposable SQLite database. The lifespan bootstraps the permission
catalog, Admin role and administrator exactly as Docker does.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

TEST_DB = Path(__file__).resolve().parent / ".pytest_hca.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key"
os.environ["SEED_ADMIN_USERNAME"] = "admin"
os.environ["SEED_ADMIN_EMAIL"] = "admin@hca.test"
os.environ["SEED_ADMIN_PASSWORD"] = "Admin@12345"
os.environ["BOOTSTRAP_ADMIN_ON_STARTUP"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_tokens(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Admin@12345"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="session")
def admin_headers(admin_tokens):
    return {"Authorization": f"Bearer {admin_tokens['access_token']}"}


@pytest.fixture(scope="session")
def admin_user(admin_tokens):
    return admin_tokens["user"]
