"""Asset Master and calibration coverage.

Exercises the hard-coded asset type catalog, scope rules, tank declaration and
the full calibration path: upload, unit conversion, validation and dip-to-volume
interpolation in both 2D and 3D.
"""

from __future__ import annotations

import io

import pytest

from app.utils.asset_types import (
    ASSET_TYPE_CODES,
    asset_type_catalog,
    asset_type_supports_calibration,
    resolve_asset_type_code,
)
from app.utils.units import (
    CANONICAL_DIP_UNIT,
    CANONICAL_VOLUME_UNIT,
    from_canonical_volume,
    to_canonical_dip,
    to_canonical_volume,
)


def _csv(rows: list[list[str]]) -> bytes:
    return ("\ufeff" + "\n".join(",".join(row) for row in rows) + "\n").encode("utf-8")


@pytest.fixture(scope="module")
def location_id(client, admin_headers):
    response = client.post(
        "/api/locations",
        json={
            "location_name": "Asset Test Terminal",
            "location_code": "ASSET-TERM-01",
            "location_type": "Terminal",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture(scope="module")
def barge_id(client, admin_headers, location_id):
    """A multi-tank barge that requires calibration."""
    response = client.post(
        "/api/assets",
        json={
            "asset_name": "Barge Test Vessel",
            "asset_code": "BRG-TEST-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "dip_unit": "cm",
            "volume_unit": "bbl",
            "tanks": [
                {"tank_name": "1P"},
                {"tank_name": "1S"},
                {"tank_name": "2P"},
            ],
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------------------------------------------------------------------------
# Hard-coded asset type catalog
# ---------------------------------------------------------------------------
def test_asset_type_catalog_is_the_seven_fixed_types():
    assert ASSET_TYPE_CODES == (
        "STORAGE_TANK",
        "BARGE",
        "SHUTTLE_VESSEL",
        "FSO",
        "PRIME_MOVER",
        "TANKER_TRAILER",
        "FLOWMETER",
    )
    names = [item["name"] for item in asset_type_catalog()]
    assert names == [
        "Storage Tank",
        "Barge",
        "Shuttle Vessel",
        "FSO",
        "Prime Mover",
        "Tanker Trailer",
        "Flowmeter",
    ]


def test_asset_type_aliases_fold_onto_catalog_codes():
    assert resolve_asset_type_code("Storage Tank") == "STORAGE_TANK"
    assert resolve_asset_type_code("storage-tank") == "STORAGE_TANK"
    assert resolve_asset_type_code("SHUTTLE VESSEL") == "SHUTTLE_VESSEL"
    # OTMS installations that called a barge class "YADE" still resolve.
    assert resolve_asset_type_code("YADE") == "BARGE"
    assert resolve_asset_type_code("Prime Mover") == "PRIME_MOVER"
    assert resolve_asset_type_code("Not A Type") is None


def test_flowmeter_and_prime_mover_are_not_calibrated():
    assert asset_type_supports_calibration("FLOWMETER") is False
    assert asset_type_supports_calibration("PRIME_MOVER") is False
    assert asset_type_supports_calibration("BARGE") is True


def test_asset_reference_endpoint_exposes_catalog_and_units(client, admin_headers):
    response = client.get("/api/assets/reference", headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert [item["code"] for item in payload["asset_types"]] == list(ASSET_TYPE_CODES)
    assert payload["canonical_dip_unit"] == CANONICAL_DIP_UNIT == "cm"
    assert payload["canonical_volume_unit"] == CANONICAL_VOLUME_UNIT == "bbl"
    assert payload["units"]["measurement_bases"] == ["Dip", "Ullage"]
    assert [unit["code"] for unit in payload["units"]["dip_units"]] == ["cm", "mm", "m"]
    assert [unit["code"] for unit in payload["units"]["volume_units"]] == ["l", "kl", "bbl"]
    assert payload["chart_template_headers"] == ["tank_name", "dip_ullage", "volume"]


# ---------------------------------------------------------------------------
# Unit conversion factors
# ---------------------------------------------------------------------------
def test_depth_conversion_factors():
    assert to_canonical_dip(1, "cm") == 1.0
    assert to_canonical_dip(10, "mm") == pytest.approx(1.0)
    assert to_canonical_dip(1, "m") == 100.0
    assert to_canonical_dip(2.5, "m") == 250.0


def test_volume_conversion_factors():
    # 1 US petroleum barrel is exactly 158.987294928 litres.
    assert to_canonical_volume(158.987294928, "l") == pytest.approx(1.0)
    assert to_canonical_volume(1, "bbl") == 1.0
    assert to_canonical_volume(1, "kl") == pytest.approx(6.289810770432105)
    # Round trip back to the supplied unit is lossless to display precision.
    assert from_canonical_volume(to_canonical_volume(1234.5, "l"), "l") == pytest.approx(1234.5)


# ---------------------------------------------------------------------------
# Asset scope and tank rules
# ---------------------------------------------------------------------------
def test_local_asset_requires_a_location(client, admin_headers):
    response = client.post(
        "/api/assets",
        json={
            "asset_name": "No Location Tank",
            "asset_code": "TNK-NOLOC-01",
            "asset_type_code": "STORAGE_TANK",
            "asset_scope": "Local",
            "calibration_required": False,
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "location is required" in response.json()["detail"].lower()


def test_global_asset_must_not_carry_a_location(client, admin_headers, location_id):
    response = client.post(
        "/api/assets",
        json={
            "asset_name": "Bad Global Tank",
            "asset_code": "TNK-BADGLOB-01",
            "asset_type_code": "STORAGE_TANK",
            "asset_scope": "Global",
            "location_id": location_id,
            "calibration_required": False,
        },
        headers=admin_headers,
    )
    # The location is ignored for a Global asset rather than stored.
    assert response.status_code == 201, response.text
    assert response.json()["location_id"] is None


def test_unknown_asset_type_is_rejected(client, admin_headers):
    response = client.post(
        "/api/assets",
        json={
            "asset_name": "Mystery Asset",
            "asset_code": "MYS-01",
            "asset_type_code": "HELICOPTER",
            "asset_scope": "Global",
            "calibration_required": False,
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "Unknown asset type" in response.json()["detail"]


def test_uncalibrated_asset_type_cannot_require_calibration(client, admin_headers):
    response = client.post(
        "/api/assets",
        json={
            "asset_name": "Flowmeter With Chart",
            "asset_code": "FM-BAD-01",
            "asset_type_code": "FLOWMETER",
            "asset_scope": "Global",
            "calibration_required": True,
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "not calibrated" in response.json()["detail"]


def test_calibrated_asset_must_declare_a_tank(client, admin_headers, location_id):
    response = client.post(
        "/api/assets",
        json={
            "asset_name": "Tankless Storage Tank",
            "asset_code": "TNK-NOTANK-01",
            "asset_type_code": "STORAGE_TANK",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [],
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "at least one tank" in response.json()["detail"].lower()


def test_duplicate_tank_names_are_rejected(client, admin_headers, location_id):
    response = client.post(
        "/api/assets",
        json={
            "asset_name": "Duplicate Tank Barge",
            "asset_code": "BRG-DUP-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": False,
            "tanks": [{"tank_name": "1P"}, {"tank_name": "1P"}],
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "declared twice" in response.json()["detail"]


def test_asset_code_must_be_unique(client, admin_headers, location_id, barge_id):
    response = client.post(
        "/api/assets",
        json={
            "asset_name": "Duplicate Code Barge",
            "asset_code": "BRG-TEST-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": False,
        },
        headers=admin_headers,
    )
    assert response.status_code == 409


def test_barge_carries_its_declared_tanks(client, admin_headers, barge_id):
    response = client.get(f"/api/assets/{barge_id}", headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_type_name"] == "Barge"
    assert payload["asset_type_supports_tanks"] is True
    assert payload["tank_count"] == 3
    assert [tank["tank_name"] for tank in payload["tanks"]] == ["1P", "1S", "2P"]


# ---------------------------------------------------------------------------
# Calibration upload, conversion and validation
# ---------------------------------------------------------------------------
def test_calibration_upload_requires_a_declared_tank(client, admin_headers, barge_id):
    upload = _csv(
        [
            ["tank_name", "dip_ullage", "volume"],
            ["3C", "0", "0"],
            ["3C", "100", "10"],
        ]
    )
    response = client.post(
        f"/api/assets/{barge_id}/calibration/upload",
        files={"file": ("chart.csv", io.BytesIO(upload), "text/csv")},
        data={"measurement_basis": "Dip", "dip_unit": "cm", "volume_unit": "bbl"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["invalid_rows"] == 2
    assert "not declared on this asset" in payload["rows"][0]["errors"][0]


def test_calibration_upload_converts_mm_and_litres_to_canonical(client, admin_headers, barge_id):
    """A chart in mm and litres is stored as cm and bbl."""
    upload = _csv(
        [
            ["Tank Name", "Dip/Ullage", "Volume"],
            ["1P", "0", "0"],
            ["1P", "1000", "1589.87294928"],
            ["1P", "2000", "3179.74589856"],
            ["1S", "0", "0"],
            ["1S", "1000", "1589.87294928"],
            ["1S", "2000", "3179.74589856"],
        ]
    )
    preview = client.post(
        f"/api/assets/{barge_id}/calibration/upload",
        files={"file": ("barge-chart.csv", io.BytesIO(upload), "text/csv")},
        data={
            "chart_name": "Barge Test Vessel strapping table",
            "measurement_basis": "Dip",
            "dip_unit": "mm",
            "volume_unit": "l",
        },
        headers=admin_headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["layout"] == "long"
    assert body["valid_rows"] == 6
    assert body["invalid_rows"] == 0
    assert body["declared_units"] == {
        "measurement_basis": "Dip",
        "dip_unit": "mm",
        "volume_unit": "l",
    }
    # 1000 mm -> 100 cm, and 1589.87294928 L -> 10 bbl.
    first_point = next(row for row in body["rows"] if row["dip_value"] == 1000.0)
    assert first_point["dip_cm"] == 100.0
    assert first_point["volume_bbl"] == pytest.approx(10.0)

    commit = client.post(
        f"/api/assets/{barge_id}/calibration/upload",
        files={"file": ("barge-chart.csv", io.BytesIO(upload), "text/csv")},
        data={
            "chart_name": "Barge Test Vessel strapping table",
            "measurement_basis": "Dip",
            "dip_unit": "mm",
            "volume_unit": "l",
            "confirm": "true",
        },
        headers=admin_headers,
    )
    assert commit.status_code == 200, commit.text
    assert commit.json()["imported"] == 6

    stored = client.get(f"/api/assets/{barge_id}/calibration", headers=admin_headers).json()
    assert stored["chart"]["row_count"] == 6
    assert stored["chart"]["measurement_basis"] == "Dip"
    assert stored["chart"]["source_dip_unit"] == "mm"
    assert stored["chart"]["source_volume_unit"] == "l"
    assert stored["chart"]["source_file_name"] == "barge-chart.csv"
    # 2P was declared on the asset but this chart has no rows for it, and the
    # page must report that rather than leaving the gap to be discovered.
    assert stored["tanks_without_rows"] == ["2P"]

    rows = stored["chart"]["rows"]
    point = next(row for row in rows if row["tank_name"] == "1P" and row["dip_cm"] == 100.0)
    assert point["volume_bbl"] == pytest.approx(10.0)
    # The values as supplied are kept for audit.
    assert point["source_dip_value"] == pytest.approx(1000.0)
    assert point["source_volume_value"] == pytest.approx(1589.87294928)


def test_wide_layout_chart_is_normalised(client, admin_headers, location_id):
    """A printed calibration book (depths down, tanks across) is accepted."""
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Wide Chart Barge",
            "asset_code": "BRG-WIDE-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "1P"}, {"tank_name": "1S"}],
        },
        headers=admin_headers,
    ).json()

    upload = _csv(
        [
            ["Dip", "1P", "1S"],
            ["0", "0", "0"],
            ["100", "10", "11"],
            ["200", "21", "22"],
        ]
    )
    response = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("book.csv", io.BytesIO(upload), "text/csv")},
        data={
            "measurement_basis": "Dip",
            "dip_unit": "cm",
            "volume_unit": "bbl",
            "confirm": "true",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["layout"] == "wide"
    assert body["imported"] == 6
    assert body["tanks_found"] == ["1P", "1S"]


def test_chart_with_a_single_point_per_tank_is_rejected(client, admin_headers, location_id):
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Thin Chart Tank",
            "asset_code": "TNK-THIN-01",
            "asset_type_code": "STORAGE_TANK",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "T1"}],
        },
        headers=admin_headers,
    ).json()

    upload = _csv([["tank_name", "dip_ullage", "volume"], ["T1", "50", "5"]])
    response = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("thin.csv", io.BytesIO(upload), "text/csv")},
        data={"measurement_basis": "Dip", "dip_unit": "cm", "volume_unit": "bbl"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["invalid_rows"] == 1
    messages = " ".join(str(error) for row in body["rows"] for error in row["errors"])
    assert "at least 2 are needed" in messages


def test_repeated_depth_within_a_tank_is_rejected(client, admin_headers, location_id):
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Duplicate Depth Tank",
            "asset_code": "TNK-DUPDEPTH-01",
            "asset_type_code": "STORAGE_TANK",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "T1"}],
        },
        headers=admin_headers,
    ).json()

    upload = _csv(
        [
            ["tank_name", "dip_ullage", "volume"],
            ["T1", "50", "5"],
            ["T1", "50", "9"],
            ["T1", "100", "10"],
        ]
    )
    response = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("dup.csv", io.BytesIO(upload), "text/csv")},
        data={"measurement_basis": "Dip", "dip_unit": "cm", "volume_unit": "bbl"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["invalid_rows"] > 0
    messages = " ".join(str(error) for row in body["rows"] for error in row["errors"])
    assert "repeated" in messages or "appears twice" in messages


def test_upload_is_refused_for_an_asset_that_needs_no_calibration(
    client, admin_headers, location_id
):
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Prime Mover No Chart",
            "asset_code": "PM-NOCHART-01",
            "asset_type_code": "PRIME_MOVER",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": False,
        },
        headers=admin_headers,
    ).json()

    upload = _csv([["tank_name", "dip_ullage", "volume"], ["T1", "0", "0"], ["T1", "10", "1"]])
    response = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("x.csv", io.BytesIO(upload), "text/csv")},
        data={"measurement_basis": "Dip", "dip_unit": "cm", "volume_unit": "bbl"},
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "not requiring calibration" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Interpolation — 2D within a tank, 3D across the asset's tanks
# ---------------------------------------------------------------------------
def test_lookup_interpolates_midpoint_exactly(client, admin_headers, barge_id):
    """100 cm -> 10 bbl and 200 cm -> 20 bbl, so 150 cm must give 15 bbl."""
    response = client.post(
        f"/api/assets/{barge_id}/calibration/lookup",
        json={"tank_name": "1P", "dip_value": 150, "dip_unit": "cm", "volume_unit": "bbl"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["volume_bbl"] == pytest.approx(15.0)
    assert payload["method"] == "interpolated"
    assert payload["in_range"] is True
    assert payload["lower_point"]["dip_cm"] == 100.0
    assert payload["upper_point"]["dip_cm"] == 200.0
    assert payload["measurement_basis"] == "Dip"


def test_lookup_returns_exact_chart_point(client, admin_headers, barge_id):
    response = client.post(
        f"/api/assets/{barge_id}/calibration/lookup",
        json={"tank_name": "1P", "dip_value": 100},
        headers=admin_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "exact"
    assert payload["volume_bbl"] == pytest.approx(10.0)


def test_3d_lookup_resolves_the_tank_axis(client, admin_headers, location_id):
    """Two tanks with different tables must never return each other's volume."""
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Two Tank Barge",
            "asset_code": "BRG-3D-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "2P"}, {"tank_name": "2S"}],
        },
        headers=admin_headers,
    ).json()

    upload = _csv(
        [
            ["tank_name", "dip_ullage", "volume"],
            ["2P", "0", "0"],
            ["2P", "100", "10"],
            ["2S", "0", "0"],
            ["2S", "100", "40"],
        ]
    )
    committed = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("3d.csv", io.BytesIO(upload), "text/csv")},
        data={
            "measurement_basis": "Dip",
            "dip_unit": "cm",
            "volume_unit": "bbl",
            "confirm": "true",
        },
        headers=admin_headers,
    )
    assert committed.status_code == 200, committed.text

    port = client.post(
        f"/api/assets/{asset['id']}/calibration/lookup",
        json={"tank_name": "2P", "dip_value": 50},
        headers=admin_headers,
    ).json()
    starboard = client.post(
        f"/api/assets/{asset['id']}/calibration/lookup",
        json={"tank_name": "2S", "dip_value": 50},
        headers=admin_headers,
    ).json()
    assert port["volume_bbl"] == pytest.approx(5.0)
    assert starboard["volume_bbl"] == pytest.approx(20.0)

    # Tank name matching tolerates case and surrounding space only.
    case_insensitive = client.post(
        f"/api/assets/{asset['id']}/calibration/lookup",
        json={"tank_name": " 2p ", "dip_value": 50},
        headers=admin_headers,
    ).json()
    assert case_insensitive["volume_bbl"] == pytest.approx(5.0)


def test_lookup_refuses_an_undeclared_tank(client, admin_headers, barge_id):
    response = client.post(
        f"/api/assets/{barge_id}/calibration/lookup",
        json={"tank_name": "9Z", "dip_value": 50},
        headers=admin_headers,
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "not on this calibration chart" in detail
    assert "1P" in detail


def test_lookup_accepts_readings_in_any_depth_unit(client, admin_headers, barge_id):
    """1.5 m, 1500 mm and 150 cm are the same reading."""
    results = []
    for value, unit in ((150, "cm"), (1500, "mm"), (1.5, "m")):
        payload = client.post(
            f"/api/assets/{barge_id}/calibration/lookup",
            json={"tank_name": "1P", "dip_value": value, "dip_unit": unit},
            headers=admin_headers,
        ).json()
        results.append(payload["volume_bbl"])
    assert results[0] == pytest.approx(15.0)
    assert results[1] == pytest.approx(15.0)
    assert results[2] == pytest.approx(15.0)


def test_lookup_returns_volume_in_the_requested_unit(client, admin_headers, barge_id):
    payload = client.post(
        f"/api/assets/{barge_id}/calibration/lookup",
        json={"tank_name": "1P", "dip_value": 100, "volume_unit": "l"},
        headers=admin_headers,
    ).json()
    assert payload["volume_bbl"] == pytest.approx(10.0)
    assert payload["volume_display"] == pytest.approx(1589.872949, rel=1e-6)
    assert payload["volume_unit"] == "l"

    kilolitres = client.post(
        f"/api/assets/{barge_id}/calibration/lookup",
        json={"tank_name": "1P", "dip_value": 100, "volume_unit": "kl"},
        headers=admin_headers,
    ).json()
    # Display values are rounded to the engine's 4-decimal volume precision,
    # so 10 bbl shows as 1.5899 kL rather than the full 1.58987294928.
    assert kilolitres["volume_display"] == pytest.approx(1.58987294928, abs=1e-4)


def test_out_of_range_reading_is_refused_not_silently_clamped(client, admin_headers, barge_id):
    response = client.post(
        f"/api/assets/{barge_id}/calibration/lookup",
        json={"tank_name": "1P", "dip_value": 5000, "allow_clamping": False},
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "above the certified range" in response.json()["detail"]


def test_out_of_range_reading_is_flagged_when_clamping_is_allowed(
    client, admin_headers, barge_id
):
    response = client.post(
        f"/api/assets/{barge_id}/calibration/lookup",
        json={"tank_name": "1P", "dip_value": 202, "allow_clamping": True},
        headers=admin_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "clamped_high"
    assert payload["in_range"] is False
    assert payload["volume_bbl"] == pytest.approx(20.0)
    assert payload["warnings"]


def test_batch_lookup_resolves_many_readings_and_reports_failures(
    client, admin_headers, barge_id
):
    response = client.post(
        f"/api/assets/{barge_id}/calibration/lookup-batch",
        json={
            "tank_name": "1P",
            "dip_values": [0, 50, 100, 150, 5000],
            "dip_unit": "cm",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requested"] == 5
    assert payload["resolved"] == 4
    assert payload["failed"] == 1
    volumes = [item.get("volume_bbl") for item in payload["results"][:4]]
    assert volumes[0] == pytest.approx(0.0)
    assert volumes[1] == pytest.approx(5.0)
    assert volumes[2] == pytest.approx(10.0)
    assert volumes[3] == pytest.approx(15.0)
    assert "error" in payload["results"][4]


def test_ullage_chart_is_interpreted_on_its_declared_basis(client, admin_headers, location_id):
    """Ullage counts down from the reference point, so volume falls as it grows."""
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Ullage Basis Tank",
            "asset_code": "TNK-ULLAGE-01",
            "asset_type_code": "STORAGE_TANK",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "T1"}],
        },
        headers=admin_headers,
    ).json()

    upload = _csv(
        [
            ["tank_name", "dip_ullage", "volume"],
            ["T1", "0", "100"],
            ["T1", "100", "50"],
            ["T1", "200", "0"],
        ]
    )
    committed = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("ullage.csv", io.BytesIO(upload), "text/csv")},
        data={
            "measurement_basis": "Ullage",
            "dip_unit": "cm",
            "volume_unit": "bbl",
            "confirm": "true",
        },
        headers=admin_headers,
    )
    assert committed.status_code == 200, committed.text

    chart = client.get(f"/api/assets/{asset['id']}/calibration", headers=admin_headers).json()
    assert chart["chart"]["measurement_basis"] == "Ullage"

    lookup = client.post(
        f"/api/assets/{asset['id']}/calibration/lookup",
        json={"tank_name": "T1", "dip_value": 50},
        headers=admin_headers,
    ).json()
    assert lookup["volume_bbl"] == pytest.approx(75.0)
    assert lookup["measurement_basis"] == "Ullage"


def test_non_monotonic_chart_raises_a_warning(client, admin_headers, location_id):
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Reversing Chart Tank",
            "asset_code": "TNK-REVERSE-01",
            "asset_type_code": "STORAGE_TANK",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "T1"}],
        },
        headers=admin_headers,
    ).json()

    upload = _csv(
        [
            ["tank_name", "dip_ullage", "volume"],
            ["T1", "0", "0"],
            ["T1", "100", "10"],
            ["T1", "200", "8"],
        ]
    )
    response = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("reverse.csv", io.BytesIO(upload), "text/csv")},
        data={
            "measurement_basis": "Dip",
            "dip_unit": "cm",
            "volume_unit": "bbl",
            "confirm": "true",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert any("Volume falls" in warning for warning in body["warnings"])


# ---------------------------------------------------------------------------
# Re-upload, export and audit
# ---------------------------------------------------------------------------
def test_reupload_replaces_the_previous_chart(client, admin_headers, location_id):
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Reupload Tank",
            "asset_code": "TNK-REUPLOAD-01",
            "asset_type_code": "STORAGE_TANK",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "T1"}],
        },
        headers=admin_headers,
    ).json()

    first = _csv(
        [
            ["tank_name", "dip_ullage", "volume"],
            ["T1", "0", "0"],
            ["T1", "100", "10"],
        ]
    )
    client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("first.csv", io.BytesIO(first), "text/csv")},
        data={
            "measurement_basis": "Dip",
            "dip_unit": "cm",
            "volume_unit": "bbl",
            "confirm": "true",
        },
        headers=admin_headers,
    )

    second = _csv(
        [
            ["tank_name", "dip_ullage", "volume"],
            ["T1", "0", "0"],
            ["T1", "100", "12"],
            ["T1", "200", "24"],
        ]
    )
    replaced = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("second.csv", io.BytesIO(second), "text/csv")},
        data={
            "chart_name": "Recalibrated table",
            "measurement_basis": "Dip",
            "dip_unit": "cm",
            "volume_unit": "bbl",
            "confirm": "true",
        },
        headers=admin_headers,
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["imported"] == 3

    chart = client.get(f"/api/assets/{asset['id']}/calibration", headers=admin_headers).json()
    assert chart["chart"]["row_count"] == 3
    assert chart["chart"]["chart_name"] == "Recalibrated table"
    assert chart["chart"]["source_file_name"] == "second.csv"

    # The replacement is recorded rather than silent.
    audit = client.get(
        "/api/audit-logs",
        params={"action": "Upload Calibration Chart", "page_size": 20},
        headers=admin_headers,
    ).json()
    assert audit["total"] >= 1
    summaries = " ".join(str(item.get("details_summary") or "") for item in audit["items"])
    assert "previous_rows=2" in summaries


def test_calibration_export_round_trips_in_all_three_formats(client, admin_headers, barge_id):
    for format_name, media in (
        ("csv", "text/csv"),
        ("xlsx", "spreadsheetml"),
        ("pdf", "application/pdf"),
    ):
        response = client.get(
            f"/api/assets/{barge_id}/calibration/export",
            params={"format": format_name},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        assert media in response.headers["content-type"]
        assert len(response.content) > 100

    csv_text = client.get(
        f"/api/assets/{barge_id}/calibration/export",
        params={"format": "csv"},
        headers=admin_headers,
    ).content.decode("utf-8-sig")
    assert "Tank name" in csv_text
    assert "Depth (cm)" in csv_text
    assert "1P" in csv_text


def test_asset_register_export_and_audit_trail(client, admin_headers):
    response = client.get(
        "/api/assets/export",
        params={"format": "csv"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    assert "Asset code" in text
    assert "BRG-TEST-01" in text
    assert "Barge" in text

    audit = client.get(
        "/api/audit-logs",
        params={"module_name": "Asset Master", "page_size": 20},
        headers=admin_headers,
    ).json()
    actions = {item["action"] for item in audit["items"]}
    assert "Create Asset" in actions
    assert "Export Assets" in actions


def test_calibration_rows_are_blocked_from_removing_a_tank_in_use(
    client, admin_headers, location_id
):
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Tank Guard Barge",
            "asset_code": "BRG-GUARD-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "1P"}, {"tank_name": "1S"}],
        },
        headers=admin_headers,
    ).json()

    upload = _csv(
        [
            ["tank_name", "dip_ullage", "volume"],
            ["1P", "0", "0"],
            ["1P", "100", "10"],
            ["1S", "0", "0"],
            ["1S", "100", "10"],
        ]
    )
    client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("guard.csv", io.BytesIO(upload), "text/csv")},
        data={
            "measurement_basis": "Dip",
            "dip_unit": "cm",
            "volume_unit": "bbl",
            "confirm": "true",
        },
        headers=admin_headers,
    )

    response = client.put(
        f"/api/assets/{asset['id']}",
        json={"tanks": [{"tank_name": "1P"}]},
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "calibration rows" in response.json()["detail"]


def test_asset_master_is_permission_gated(client, admin_headers):
    role = client.post(
        "/api/roles",
        json={"role_name": "Asset Viewer", "description": "Read-only asset access"},
        headers=admin_headers,
    ).json()

    catalog = client.get("/api/permissions/catalog", headers=admin_headers).json()
    read_id = next(
        permission["id"]
        for category in catalog["categories"]
        for module in category["modules"]
        for permission in module["permissions"]
        if permission["permission_name"] == "assets:read"
    )
    client.put(
        f"/api/roles/{role['id']}/permissions",
        json={"permission_ids": [read_id]},
        headers=admin_headers,
    )

    user = client.post(
        "/api/users",
        json={
            "full_name": "Asset Viewer User",
            "username": "assetviewer",
            "email": "assetviewer@example.com",
            "password": "AssetView@123",
            "role_ids": [role["id"]],
        },
        headers=admin_headers,
    ).json()

    tokens = client.post(
        "/api/auth/login",
        json={"username": "assetviewer", "password": "AssetView@123"},
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert client.get("/api/assets", headers=headers).status_code == 200
    assert client.get("/api/assets/reference", headers=headers).status_code == 200

    create = client.post(
        "/api/assets",
        json={
            "asset_name": "Denied Asset",
            "asset_code": "DENIED-01",
            "asset_type_code": "STORAGE_TANK",
            "asset_scope": "Global",
            "calibration_required": False,
        },
        headers=headers,
    )
    assert create.status_code == 403
    assert user["username"] == "assetviewer"


def test_asset_list_pagination_contract(client, admin_headers):
    response = client.get("/api/assets", params={"page": 1, "page_size": 20}, headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()
    for key in ("items", "total", "page", "page_size", "pages", "has_more"):
        assert key in payload
    assert payload["page_size"] == 20
    assert payload["asset_types"]


# ---------------------------------------------------------------------------
# XLSX uploads (the same parser path as CSV, through openpyxl)
# ---------------------------------------------------------------------------
def _xlsx(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_xlsx_chart_in_metres_and_kilolitres_is_converted(client, admin_headers, location_id):
    """A real Excel workbook in m and kL lands as canonical cm and bbl."""
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Excel Chart Barge",
            "asset_code": "BRG-XLSX-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "1P"}, {"tank_name": "1S"}],
        },
        headers=admin_headers,
    ).json()

    workbook = _xlsx(
        [
            ["Tank Name", "Dip/Ullage", "Volume"],
            ["1P", 0, 0],
            ["1P", 1, 6.289810770432105],
            ["1P", 2, 12.57962154086421],
            ["1S", 0, 0],
            ["1S", 1, 6.289810770432105],
            ["1S", 2, 12.57962154086421],
        ]
    )
    response = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("chart.xlsx", io.BytesIO(workbook), XLSX_MIMETYPE)},
        data={
            "measurement_basis": "Dip",
            "dip_unit": "m",
            "volume_unit": "kl",
            "confirm": "true",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "xlsx"
    assert body["layout"] == "long"
    assert body["imported"] == 6

    chart = client.get(f"/api/assets/{asset['id']}/calibration", headers=admin_headers).json()
    assert chart["chart"]["source_file_name"] == "chart.xlsx"
    point = next(
        row for row in chart["chart"]["rows"] if row["tank_name"] == "1P" and row["dip_cm"] == 100.0
    )
    # 1 m -> 100 cm, and 6.289810770432105 kL -> 39.56171952... bbl, because
    # 1 kL = 6.289810770432105 bbl. volume_bbl is stored to six decimals, so the
    # tolerance has to allow for that rounding rather than exact float equality.
    expected_bbl = 6.289810770432105 * 6.289810770432105
    assert point["volume_bbl"] == pytest.approx(expected_bbl, abs=1e-6)
    assert point["source_dip_value"] == pytest.approx(1.0)


def test_wide_xlsx_workbook_is_normalised(client, admin_headers, location_id):
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Excel Wide Barge",
            "asset_code": "BRG-XLSXWIDE-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "1P"}, {"tank_name": "1S"}],
        },
        headers=admin_headers,
    ).json()

    workbook = _xlsx([["Dip", "1P", "1S"], [0, 0, 0], [100, 10, 11], [200, 21, 22]])
    response = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("book.xlsx", io.BytesIO(workbook), XLSX_MIMETYPE)},
        data={
            "measurement_basis": "Dip",
            "dip_unit": "cm",
            "volume_unit": "bbl",
            "confirm": "true",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["layout"] == "wide"
    assert body["imported"] == 6
    assert body["tanks_found"] == ["1P", "1S"]


def test_xlsx_validation_rejects_an_undeclared_tank(client, admin_headers, location_id):
    asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Excel Bad Tank Barge",
            "asset_code": "BRG-XLSXBAD-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location_id,
            "calibration_required": True,
            "tanks": [{"tank_name": "1P"}],
        },
        headers=admin_headers,
    ).json()

    workbook = _xlsx(
        [["Tank Name", "Dip/Ullage", "Volume"], ["9Z", 0, 0], ["9Z", 100, 10]]
    )
    response = client.post(
        f"/api/assets/{asset['id']}/calibration/upload",
        files={"file": ("bad.xlsx", io.BytesIO(workbook), XLSX_MIMETYPE)},
        data={"measurement_basis": "Dip", "dip_unit": "cm", "volume_unit": "bbl"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["invalid_rows"] == 2
    assert "not declared on this asset" in body["rows"][0]["errors"][0]


def test_asset_register_xlsx_import(client, admin_headers, location_id):
    workbook = _xlsx(
        [
            [
                "asset_code",
                "asset_name",
                "asset_type",
                "asset_scope",
                "location_code",
                "tank_names",
                "calibration_required",
            ],
            ["BRG-XLSXIMP-01", "Imported Excel Barge", "Barge", "Local", "ASSET-TERM-01", "1P;1S", "Yes"],
        ]
    )
    response = client.post(
        "/api/assets/import",
        files={"file": ("register.xlsx", io.BytesIO(workbook), XLSX_MIMETYPE)},
        data={"confirm": "true"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 1

    created = client.get(
        "/api/assets",
        params={"search": "BRG-XLSXIMP-01"},
        headers=admin_headers,
    ).json()
    assert created["total"] == 1
    asset = created["items"][0]
    # The alias "Barge" folded onto the fixed catalog code.
    assert asset["asset_type_code"] == "BARGE"
    assert asset["tank_count"] == 2
    assert asset["location_code"] == "ASSET-TERM-01"


def test_location_scoped_user_sees_only_global_and_own_locations(client, admin_headers):
    """A user whose role has location assignments is restricted; admin is not.

    This is the behaviour ``get_user_location_ids`` exists for: once a role is
    given locations, its members see those locations plus Global assets, and
    assets at any other location are not merely filtered out of the list but
    are absent from single-asset reads too.
    """
    home = client.post(
        "/api/locations",
        json={"location_name": "Scoped Home", "location_code": "ASSET-HOME-01", "location_type": "Terminal"},
        headers=admin_headers,
    ).json()
    elsewhere = client.post(
        "/api/locations",
        json={"location_name": "Scoped Elsewhere", "location_code": "ASSET-FAR-01", "location_type": "Terminal"},
        headers=admin_headers,
    ).json()

    role = client.post(
        "/api/roles",
        json={"role_name": "Scoped Asset Operator", "description": "One location only"},
        headers=admin_headers,
    ).json()
    catalog = client.get("/api/permissions/catalog", headers=admin_headers).json()
    read_id = next(
        permission["id"]
        for category in catalog["categories"]
        for module in category["modules"]
        for permission in module["permissions"]
        if permission["permission_name"] == "assets:read"
    )
    client.put(
        f"/api/roles/{role['id']}/permissions",
        json={"permission_ids": [read_id]},
        headers=admin_headers,
    )
    location_response = client.put(
        f"/api/role-locations/{role['id']}",
        json={"location_ids": [home["id"]]},
        headers=admin_headers,
    )
    assert location_response.status_code == 200, location_response.text
    client.post(
        "/api/users",
        json={
            "full_name": "Scoped Operator",
            "username": "scopedoperator",
            "email": "scopedoperator@example.com",
            "password": "ScopedOp@123",
            "role_ids": [role["id"]],
        },
        headers=admin_headers,
    )
    tokens = client.post(
        "/api/auth/login",
        json={"username": "scopedoperator", "password": "ScopedOp@123"},
    ).json()
    scoped = {"Authorization": f"Bearer {tokens['access_token']}"}

    at_home = client.post(
        "/api/assets",
        json={
            "asset_name": "Scoped Home Barge",
            "asset_code": "BRG-SCOPED-HOME-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": home["id"],
            "calibration_required": False,
        },
        headers=admin_headers,
    ).json()
    far_away = client.post(
        "/api/assets",
        json={
            "asset_name": "Scoped Far Barge",
            "asset_code": "BRG-SCOPED-FAR-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": elsewhere["id"],
            "calibration_required": False,
        },
        headers=admin_headers,
    ).json()
    shared = client.post(
        "/api/assets",
        json={
            "asset_name": "Scoped Global Flowmeter",
            "asset_code": "FLW-SCOPED-GLOBAL-01",
            "asset_type_code": "FLOWMETER",
            "asset_scope": "Global",
            "calibration_required": False,
        },
        headers=admin_headers,
    ).json()

    # Admin sees all three.
    admin_view = client.get("/api/assets", headers=admin_headers).json()
    admin_codes = {item["asset_code"] for item in admin_view["items"]}
    assert {"BRG-SCOPED-HOME-01", "BRG-SCOPED-FAR-01", "FLW-SCOPED-GLOBAL-01"} <= admin_codes

    # The scoped user sees their own location plus every Global asset. Other
    # tests in this module also create Global assets against the same shared
    # fixture, so assert on membership rather than an exact set.
    scoped_view = client.get("/api/assets", headers=scoped).json()
    scoped_codes = {item["asset_code"] for item in scoped_view["items"]}
    assert "BRG-SCOPED-HOME-01" in scoped_codes
    assert "FLW-SCOPED-GLOBAL-01" in scoped_codes
    # The asset at a location the role was not given must be absent, while
    # Global assets created elsewhere in the suite are still visible.
    assert "BRG-SCOPED-FAR-01" not in scoped_codes
    assert all(
        item["asset_scope"] == "Global" or item["asset_code"] == "BRG-SCOPED-HOME-01"
        for item in scoped_view["items"]
    )
    assert scoped_view["total"] == len(scoped_view["items"])

    # The reference data the filter bar needs is still complete, so the UI is
    # not left showing a location the user cannot see assets for.
    reference = client.get("/api/assets/reference", headers=scoped).json()
    assert len(reference["asset_types"]) == len(asset_type_catalog())
    assert reference["canonical_dip_unit"] == "cm"
    assert reference["canonical_volume_unit"] == "bbl"

    # Single reads and lookups are scoped the same way as the list.
    assert client.get(f"/api/assets/{at_home['id']}", headers=scoped).status_code == 200
    assert client.get(f"/api/assets/{shared['id']}", headers=scoped).status_code == 200
    assert client.get(f"/api/assets/{far_away['id']}", headers=scoped).status_code == 404


# ---------------------------------------------------------------------------
# Location lifecycle interacts with assets
# ---------------------------------------------------------------------------
def test_location_holding_an_active_asset_cannot_be_deactivated(client, admin_headers):
    """A Local asset may only sit on an Active location.

    The asset router enforces that on create and on update, so deactivating the
    location underneath a live asset would leave a record the API refuses to
    create and refuses to edit. The location endpoint has to hold the same line.
    """
    location_response = client.post(
        "/api/locations",
        json={
            "location_name": "Guarded Terminal",
            "location_code": "ASSET-LOCGUARD-01",
            "location_type": "Terminal",
        },
        headers=admin_headers,
    )
    assert location_response.status_code == 201, location_response.text
    location = location_response.json()

    asset_response = client.post(
        "/api/assets",
        json={
            "asset_name": "Guarded Barge",
            "asset_code": "BRG-LOCGUARD-01",
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location["id"],
            "calibration_required": False,
        },
        headers=admin_headers,
    )
    assert asset_response.status_code == 201, asset_response.text
    asset = asset_response.json()
    assert asset["status"] == "Active"
    assert asset["location_id"] == location["id"]

    blocked = client.delete(f"/api/locations/{location['id']}", headers=admin_headers)
    assert blocked.status_code == 409
    assert "active assets" in blocked.json()["detail"]

    # The location must be untouched, not half-deactivated.
    listed = client.get(
        "/api/locations",
        params={"search": "ASSET-LOCGUARD-01", "page_size": 50},
        headers=admin_headers,
    ).json()
    current = next(item for item in listed["items"] if item["id"] == location["id"])
    assert current["status"] == "Active"

    # Once the asset is retired the location is free to go.
    retired = client.put(
        f"/api/assets/{asset['id']}",
        json={
            "asset_name": asset["asset_name"],
            "asset_code": asset["asset_code"],
            "asset_type_code": "BARGE",
            "asset_scope": "Local",
            "location_id": location["id"],
            "calibration_required": False,
            "status": "Inactive",
        },
        headers=admin_headers,
    )
    assert retired.status_code == 200, retired.text

    allowed = client.delete(f"/api/locations/{location['id']}", headers=admin_headers)
    assert allowed.status_code == 200, allowed.text

    listed_after = client.get(
        "/api/locations",
        params={"search": "ASSET-LOCGUARD-01", "page_size": 50},
        headers=admin_headers,
    ).json()
    after = next(item for item in listed_after["items"] if item["id"] == location["id"])
    assert after["status"] == "Inactive"


def test_global_asset_does_not_block_location_deactivation(client, admin_headers):
    """A Global asset holds no location, so it cannot pin one down."""
    location = client.post(
        "/api/locations",
        json={
            "location_name": "Free Terminal",
            "location_code": "ASSET-FREE-01",
            "location_type": "Terminal",
        },
        headers=admin_headers,
    ).json()
    global_asset = client.post(
        "/api/assets",
        json={
            "asset_name": "Free Global Flowmeter",
            "asset_code": "FLW-FREE-01",
            "asset_type_code": "FLOWMETER",
            "asset_scope": "Global",
            "calibration_required": False,
        },
        headers=admin_headers,
    )
    assert global_asset.status_code == 201, global_asset.text

    response = client.delete(f"/api/locations/{location['id']}", headers=admin_headers)
    assert response.status_code == 200, response.text
