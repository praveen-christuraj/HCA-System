"""XLSX/CSV user import: preview, row errors and commit (owner rule 7)."""

from __future__ import annotations

import io

from openpyxl import Workbook


def _csv_bytes(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    for row in rows:
        buffer.write(",".join(row) + "\n")
    return buffer.getvalue().encode("utf-8")


def test_import_preview_reports_row_errors(client, admin_headers):
    content = _csv_bytes(
        [
            ["username", "full_name", "email", "password", "department", "status"],
            ["import.one", "Import One", "import.one@example.com", "Strong@12345", "Operations", "Active"],
            ["import.two", "Import Two", "not-an-email", "Strong@12345", "Operations", "Active"],
            ["import.three", "Import Three", "import.three@example.com", "weak", "Finance", "Active"],
        ]
    )
    response = client.post(
        "/api/users/import",
        files={"file": ("users.csv", content, "text/csv")},
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_rows"] == 3
    assert payload["valid_rows"] == 1
    assert payload["invalid_rows"] == 2
    errors = {row["username"]: row["errors"] for row in payload["rows"]}
    assert any("Invalid email" in error for error in errors["import.two"])
    assert any("Password must contain" in error for error in errors["import.three"])

    # Confirm is refused while any row is invalid.
    refused = client.post(
        "/api/users/import",
        files={"file": ("users.csv", content, "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert refused.status_code == 422


def test_import_commit_creates_users_and_is_audited(client, admin_headers):
    content = _csv_bytes(
        [
            ["username", "full_name", "email", "password", "department", "status"],
            ["import.ok1", "Import Okay One", "import.ok1@example.com", "Strong@12345", "Operations", "Active"],
            ["import.ok2", "Import Okay Two", "import.ok2@example.com", "Strong@12345", "Finance", "Inactive"],
        ]
    )
    response = client.post(
        "/api/users/import",
        files={"file": ("users.csv", content, "text/csv")},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["imported"] == 2

    imported = client.post(
        "/api/auth/login",
        json={"username": "import.ok1", "password": "Strong@12345"},
    )
    assert imported.status_code == 200
    assert imported.json()["permissions"] == []

    audit = client.get(
        "/api/audit-logs",
        params={"action": "Import Users", "page_size": 20},
        headers=admin_headers,
    ).json()
    assert audit["total"] >= 1
    assert "imported=2" in audit["items"][0]["details_summary"]


def test_import_accepts_xlsx(client, admin_headers):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["username", "full_name", "email", "password", "status"])
    sheet.append(["import.xlsx", "Import XLSX", "import.xlsx@example.com", "Strong@12345", "Active"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    preview = client.post(
        "/api/users/import",
        files={
            "file": (
                "users.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"confirm": "false"},
        headers=admin_headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["format"] == "xlsx"
    assert preview.json()["valid_rows"] == 1
