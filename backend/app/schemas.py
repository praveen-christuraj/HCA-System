"""Pydantic request/response schemas.

Output shapes for nested resources are assembled in ``app.services.serializers``
so that every router returns the same field names.
"""

from __future__ import annotations

from datetime import datetime
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
