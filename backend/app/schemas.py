"""Pydantic request/response schemas.

Output shapes for nested resources are assembled in ``app.services.serializers``
so that every router returns the same field names.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class TwoFAVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=8, max_length=120)
    code: str = Field(min_length=1, max_length=40)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    reason: Optional[str] = Field(default=None, max_length=500)
    reset_2fa: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
class RoleCreate(BaseModel):
    role_name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    status: Literal["Active", "Inactive"] = "Active"


class PermissionCreate(BaseModel):
    permission_name: str = Field(min_length=2, max_length=120)
    module_name: str = Field(min_length=2, max_length=120)
    category: str = Field(default="General", max_length=120)
    action: str = Field(default="Other", max_length=40)
    description: Optional[str] = Field(default=None, max_length=500)


class RolePermissionUpdate(BaseModel):
    permission_ids: list[int] = Field(default_factory=list)


class UserRolesUpdate(BaseModel):
    role_ids: list[int] = Field(default_factory=list)


class RoleLocationsUpdate(BaseModel):
    location_ids: list[int] = Field(default_factory=list)


class LocationCreate(BaseModel):
    location_name: str = Field(min_length=2, max_length=150)
    location_code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9._-]+$")
    location_type: str = Field(min_length=2, max_length=100)
    parent_location_id: Optional[int] = None
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Literal["Active", "Inactive"] = "Active"


class LocationUpdate(BaseModel):
    location_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    location_code: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=50,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    location_type: Optional[str] = Field(default=None, min_length=2, max_length=100)
    parent_location_id: Optional[int] = None
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[Literal["Active", "Inactive"]] = None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9._-]+$")
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=50)
    department: Optional[str] = Field(default=None, max_length=100)
    designation: Optional[str] = Field(default=None, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    status: Literal["Active", "Inactive"] = "Active"
    force_password_change: bool = True
    role_ids: list[int] = Field(default_factory=list)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    department: Optional[str] = Field(default=None, max_length=100)
    designation: Optional[str] = Field(default=None, max_length=100)
    status: Optional[Literal["Active", "Inactive"]] = None
    force_password_change: Optional[bool] = None
    role_ids: Optional[list[int]] = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=200)
    force_password_change: bool = True


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
class AuditUiEventRequest(BaseModel):
    module: str = Field(min_length=1, max_length=120)
    action: str = Field(min_length=1, max_length=120)
    route: Optional[str] = Field(default=None, max_length=250)
    details: Optional[dict[str, Any]] = None


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    module_name: str
    action: str
    category: str
    outcome: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    entity_label: Optional[str] = None
    actor_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    actor_full_name: Optional[str] = None
    http_method: Optional[str] = None
    request_path: Optional[str] = None
    status_code: Optional[int] = None
    ip_address: Optional[str] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    remarks: Optional[str] = None
    details_summary: Optional[str] = None
    created_at: datetime


class PageMeta(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    has_more: bool


# ---------------------------------------------------------------------------
# Master data — assets, tanks and calibration
#
# ``asset_type_code`` accepts any catalog spelling ("Storage Tank",
# "STORAGE_TANK", "storage-tank") and is folded onto the hard-coded catalog code
# by the router, so an import file never has to know the internal key.
# ---------------------------------------------------------------------------
class AssetTankInput(BaseModel):
    tank_name: str = Field(min_length=1, max_length=120)
    tank_code: Optional[str] = Field(default=None, max_length=50)
    sort_order: Optional[int] = Field(default=None, ge=1, le=9999)
    description: Optional[str] = Field(default=None, max_length=2000)


class AssetCreate(BaseModel):
    asset_name: str = Field(min_length=2, max_length=150)
    asset_code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._/-]+$")
    asset_type_code: str = Field(min_length=1, max_length=50)
    asset_scope: Literal["Local", "Global"] = "Local"
    location_id: Optional[int] = None
    calibration_required: bool = True
    dip_unit: Literal["cm", "mm", "m"] = "cm"
    volume_unit: Literal["l", "kl", "bbl"] = "bbl"
    serial_number: Optional[str] = Field(default=None, max_length=100)
    manufacturer: Optional[str] = Field(default=None, max_length=150)
    model: Optional[str] = Field(default=None, max_length=150)
    commission_date: Optional[date] = None
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Literal["Active", "Inactive"] = "Active"
    tanks: list[AssetTankInput] = Field(default_factory=list)


class AssetUpdate(BaseModel):
    asset_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    asset_code: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9._/-]+$",
    )
    asset_type_code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    asset_scope: Optional[Literal["Local", "Global"]] = None
    location_id: Optional[int] = None
    calibration_required: Optional[bool] = None
    dip_unit: Optional[Literal["cm", "mm", "m"]] = None
    volume_unit: Optional[Literal["l", "kl", "bbl"]] = None
    serial_number: Optional[str] = Field(default=None, max_length=100)
    manufacturer: Optional[str] = Field(default=None, max_length=150)
    model: Optional[str] = Field(default=None, max_length=150)
    commission_date: Optional[date] = None
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[Literal["Active", "Inactive"]] = None
    tanks: Optional[list[AssetTankInput]] = None


class VolumeLookupRequest(BaseModel):
    """Dip -> volume lookup against an asset's active calibration chart."""

    tank_name: str = Field(min_length=1, max_length=120)
    dip_value: float = Field(ge=0)
    dip_unit: Optional[Literal["cm", "mm", "m"]] = None
    volume_unit: Optional[Literal["l", "kl", "bbl"]] = None
    allow_clamping: bool = False


class VolumeLookupBatchRequest(BaseModel):
    """Several readings for one tank in a single round trip."""

    tank_name: str = Field(min_length=1, max_length=120)
    dip_values: list[float] = Field(min_length=1, max_length=200)
    dip_unit: Optional[Literal["cm", "mm", "m"]] = None
    volume_unit: Optional[Literal["l", "kl", "bbl"]] = None
    allow_clamping: bool = False
