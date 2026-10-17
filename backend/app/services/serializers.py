"""Consistent API representations for shared entities."""

from __future__ import annotations

from app.models import (
    Asset,
    AssetCalibrationRow,
    AssetCalibrationTable,
    AssetTank,
    AuditLog,
    Location,
    Permission,
    Role,
    User,
)
from app.utils.asset_types import get_asset_type
from app.utils.units import DIP_UNIT_LABELS, VOLUME_UNIT_LABELS


def role_to_dict(role: Role) -> dict:
    return {
        "id": role.id,
        "role_name": role.role_name,
        "description": role.description or "",
        "status": role.status,
        "created_at": role.created_at,
        "updated_at": role.updated_at,
    }


def location_to_dict(location: Location) -> dict:
    parent = location.parent_location
    return {
        "id": location.id,
        "location_name": location.location_name,
        "location_code": location.location_code,
        "location_type": location.location_type,
        "parent_location_id": location.parent_location_id,
        "parent_location_name": parent.location_name if parent else "",
        "parent_location_code": parent.location_code if parent else "",
        "description": location.description or "",
        "status": location.status,
        "created_at": location.created_at,
        "updated_at": location.updated_at,
    }


def permission_to_dict(permission: Permission) -> dict:
    return {
        "id": permission.id,
        "permission_name": permission.permission_name,
        "module_name": permission.module_name,
        "category": permission.category,
        "action": permission.action,
        "description": permission.description or "",
        "status": permission.status,
    }


def user_to_dict(user: User, include_roles: bool = True) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "phone": user.phone or "",
        "department": user.department or "",
        "designation": user.designation or "",
        "status": user.status,
        "force_password_change": bool(user.force_password_change),
        "force_2fa": bool(user.force_2fa),
        "totp_enabled": bool(user.totp_enabled),
        "failed_login_count": int(user.failed_login_count or 0),
        "locked_until": user.locked_until,
        "last_login_at": user.last_login_at,
        "last_login_ip": user.last_login_ip or "",
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "roles": [role_to_dict(role) for role in user.roles] if include_roles else [],
    }


def audit_to_dict(entry: AuditLog) -> dict:
    return {
        "id": entry.id,
        "module_name": entry.module_name,
        "action": entry.action,
        "category": entry.category,
        "outcome": entry.outcome,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "entity_label": entry.entity_label,
        "actor_user_id": entry.actor_user_id,
        "actor_username": entry.actor_username,
        "actor_full_name": entry.actor_full_name,
        "http_method": entry.http_method,
        "request_path": entry.request_path,
        "status_code": entry.status_code,
        "ip_address": entry.ip_address,
        "old_status": entry.old_status,
        "new_status": entry.new_status,
        "remarks": entry.remarks,
        "details_summary": entry.details_summary,
        "created_at": entry.created_at,
    }


# ---------------------------------------------------------------------------
# Master data — assets, tanks and calibration
#
# Numeric calibration columns are ``Numeric`` in the database and are emitted as
# floats here so the SPA can render them without string coercion.
# ---------------------------------------------------------------------------
def _number(value) -> float | None:
    if value is None:
        return None
    return float(value)


def asset_tank_to_dict(tank: AssetTank) -> dict:
    return {
        "id": tank.id,
        "asset_id": tank.asset_id,
        "tank_name": tank.tank_name,
        "tank_code": tank.tank_code or "",
        "sort_order": int(tank.sort_order or 1),
        "description": tank.description or "",
    }


def asset_to_dict(asset: Asset, *, include_tanks: bool = True) -> dict:
    asset_type = get_asset_type(asset.asset_type_code) or {}
    location = asset.location
    tanks = sorted(asset.tanks, key=lambda item: (item.sort_order or 0, item.tank_name))
    return {
        "id": asset.id,
        "asset_name": asset.asset_name,
        "asset_code": asset.asset_code,
        "asset_type_code": asset.asset_type_code,
        "asset_type_name": asset_type.get("name", asset.asset_type_code),
        "asset_type_supports_tanks": bool(asset_type.get("supports_tanks", False)),
        "asset_type_supports_calibration": bool(asset_type.get("calibration_supported", False)),
        "asset_scope": asset.asset_scope,
        "location_id": asset.location_id,
        "location_name": location.location_name if location else "",
        "location_code": location.location_code if location else "",
        "calibration_required": bool(asset.calibration_required),
        "dip_unit": asset.dip_unit,
        "dip_unit_label": DIP_UNIT_LABELS.get(asset.dip_unit, asset.dip_unit),
        "volume_unit": asset.volume_unit,
        "volume_unit_label": VOLUME_UNIT_LABELS.get(asset.volume_unit, asset.volume_unit),
        "serial_number": asset.serial_number or "",
        "manufacturer": asset.manufacturer or "",
        "model": asset.model or "",
        "commission_date": asset.commission_date,
        "description": asset.description or "",
        "status": asset.status,
        "created_at": asset.created_at,
        "updated_at": asset.updated_at,
        "tanks": [asset_tank_to_dict(tank) for tank in tanks] if include_tanks else [],
        "tank_count": len(tanks),
        "has_calibration": bool(
            asset.calibration_table and asset.calibration_table.status == "Active"
        ),
    }


def calibration_row_to_dict(row: AssetCalibrationRow) -> dict:
    return {
        "id": row.id,
        "tank_id": row.tank_id,
        "tank_name": row.tank.tank_name if row.tank else "",
        "row_number": int(row.row_number or 0),
        "dip_cm": _number(row.dip_cm),
        "volume_bbl": _number(row.volume_bbl),
        "source_dip_value": _number(row.source_dip_value),
        "source_volume_value": _number(row.source_volume_value),
    }


def calibration_table_to_dict(
    table: AssetCalibrationTable | None,
    *,
    include_rows: bool = False,
    row_limit: int | None = None,
) -> dict | None:
    if table is None:
        return None
    rows = sorted(
        table.rows,
        key=lambda row: (row.tank.tank_name if row.tank else "", float(row.dip_cm or 0)),
    )
    selected = rows if row_limit is None else rows[:row_limit]
    tanks: dict[str, int] = {}
    for row in rows:
        name = row.tank.tank_name if row.tank else ""
        tanks[name] = tanks.get(name, 0) + 1
    payload = {
        "id": table.id,
        "asset_id": table.asset_id,
        "chart_name": table.chart_name,
        "measurement_basis": table.measurement_basis,
        "source_dip_unit": table.source_dip_unit,
        "source_volume_unit": table.source_volume_unit,
        "source_file_name": table.source_file_name or "",
        "effective_date": table.effective_date,
        "remarks": table.remarks or "",
        "status": table.status,
        "created_at": table.created_at,
        "updated_at": table.updated_at,
        "row_count": len(rows),
        "tank_point_counts": [
            {"tank_name": name, "points": count} for name, count in sorted(tanks.items())
        ],
    }
    if include_rows:
        payload["rows"] = [calibration_row_to_dict(row) for row in selected]
        payload["rows_returned"] = len(selected)
    return payload
