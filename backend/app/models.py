"""SQLAlchemy models.

Owner rule 4: no JSON/JSONB/document columns. Every business attribute is a
typed column; collections are child tables. Audit details are typed columns
plus a human-readable summary, never a serialized payload.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utcnow


# ---------------------------------------------------------------------------
# Identity and access
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(150), nullable=False)
    username = Column(String(80), nullable=False, unique=True, index=True)
    email = Column(String(150), nullable=False, index=True)
    phone = Column(String(50), nullable=True)
    department = Column(String(100), nullable=True, index=True)
    designation = Column(String(100), nullable=True)

    password_hash = Column(Text, nullable=False)
    password_changed_at = Column(DateTime, nullable=True)
    force_password_change = Column(Boolean, nullable=False, default=False)

    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(80), nullable=True)

    totp_enabled = Column(Boolean, nullable=False, default=False)
    totp_secret = Column(Text, nullable=True)
    totp_confirmed_at = Column(DateTime, nullable=True)
    force_2fa = Column(Boolean, nullable=False, default=False)

    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    roles = relationship(
        "Role",
        secondary="user_roles",
        back_populates="users",
        lazy="selectin",
    )
    backup_codes = relationship(
        "UserBackupCode",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserBackupCode(Base):
    """One row per backup code (owner rule 4: no JSON arrays)."""

    __tablename__ = "user_backup_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash = Column(String(255), nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    user = relationship("User", back_populates="backup_codes")


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    role_name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    users = relationship(
        "User",
        secondary="user_roles",
        back_populates="roles",
    )
    permissions = relationship(
        "Permission",
        secondary="role_permissions",
        back_populates="roles",
    )
    location_assignments = relationship(
        "RoleLocation",
        back_populates="role",
        cascade="all, delete-orphan",
    )


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    permission_name = Column(String(120), nullable=False, index=True)
    module_name = Column(String(120), nullable=False, index=True)
    category = Column(String(120), nullable=False, default="General", index=True)
    action = Column(String(40), nullable=False, default="Other")
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    roles = relationship(
        "Role",
        secondary="role_permissions",
        back_populates="permissions",
    )

    __table_args__ = (
        UniqueConstraint(
            "permission_name",
            "module_name",
            name="unique_permission_per_module",
        ),
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id = Column(Integer, primary_key=True, index=True)
    role_id = Column(
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    permission_id = Column(
        Integer,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="unique_role_permission"),
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id = Column(
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="unique_user_role_pair"),
    )


class Location(Base):
    """Soft-coded operational location and optional hierarchy node."""

    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    location_name = Column(String(150), nullable=False, index=True)
    location_code = Column(String(50), nullable=False, unique=True, index=True)
    location_type = Column(String(100), nullable=False, index=True)
    parent_location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    parent_location = relationship(
        "Location",
        remote_side=[id],
        back_populates="children",
    )
    children = relationship("Location", back_populates="parent_location")
    role_assignments = relationship(
        "RoleLocation",
        back_populates="location",
        cascade="all, delete-orphan",
    )


class RoleLocation(Base):
    """Typed role-to-location assignment child table."""

    __tablename__ = "role_locations"

    id = Column(Integer, primary_key=True, index=True)
    role_id = Column(
        Integer,
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, default=utcnow)

    role = relationship("Role", back_populates="location_assignments")
    location = relationship("Location", back_populates="role_assignments")

    __table_args__ = (
        UniqueConstraint("role_id", "location_id", name="unique_role_location"),
    )


# ---------------------------------------------------------------------------
# Authentication and security
# ---------------------------------------------------------------------------
class AuthLoginChallenge(Base):
    __tablename__ = "auth_login_challenges"

    id = Column(Integer, primary_key=True, index=True)
    challenge_id = Column(String(120), nullable=False, unique=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(30), nullable=False, default="Pending", index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    ip_address = Column(String(80), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    verified_at = Column(DateTime, nullable=True)


class PasswordResetRequest(Base):
    __tablename__ = "password_reset_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_number = Column(String(120), nullable=False, unique=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    username = Column(String(80), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="Pending", index=True)
    reason = Column(Text, nullable=True)
    reset_2fa = Column(Boolean, nullable=False, default=False)
    requested_at = Column(DateTime, nullable=False, default=utcnow)
    requested_by_ip = Column(String(80), nullable=True)
    acted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    acted_at = Column(DateTime, nullable=True)
    action_notes = Column(Text, nullable=True)


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    token_type = Column(String(20), nullable=False, default="access")
    expires_at = Column(DateTime, nullable=False, index=True)
    reason = Column(String(120), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


# ---------------------------------------------------------------------------
# Audit trail (typed columns only — owner rule 4)
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)

    module_name = Column(String(120), nullable=False, index=True)
    action = Column(String(120), nullable=False, index=True)
    category = Column(String(60), nullable=False, default="General", index=True)
    outcome = Column(String(20), nullable=False, default="Success", index=True)

    entity_type = Column(String(120), nullable=True, index=True)
    entity_id = Column(Integer, nullable=True, index=True)
    entity_label = Column(String(200), nullable=True)

    actor_user_id = Column(Integer, nullable=True, index=True)
    actor_username = Column(String(80), nullable=True, index=True)
    actor_full_name = Column(String(150), nullable=True)

    http_method = Column(String(10), nullable=True)
    request_path = Column(String(250), nullable=True, index=True)
    status_code = Column(Integer, nullable=True)
    ip_address = Column(String(80), nullable=True)
    user_agent = Column(Text, nullable=True)

    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=True)

    remarks = Column(Text, nullable=True)
    details_summary = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)


# ---------------------------------------------------------------------------
# Master data — assets, tanks and calibration
#
# Asset types are hard coded in ``app.utils.asset_types`` (owner decision
# 2026-10-17): there is deliberately no ``asset_types`` table, so the seven
# hydrocarbon asset classes cannot be renamed or deleted at runtime.
#
# Calibration rows are typed columns, never a JSON document (owner rule 4).
# OTMS stored each row as ``row_data JSONB`` keyed by user-invented template
# column names, so nothing downstream could rely on a field existing. HCA
# fixes the chart shape at three columns — tank name, dip/ullage, volume — and
# stores the canonical cm/bbl value next to the value as it was supplied.
# ---------------------------------------------------------------------------
class Asset(Base):
    """A physical asset, scoped to a hard-coded asset type and a location."""

    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    asset_name = Column(String(150), nullable=False, index=True)
    asset_code = Column(String(80), nullable=False, unique=True, index=True)
    asset_type_code = Column(String(50), nullable=False, index=True)
    asset_scope = Column(String(10), nullable=False, default="Local", index=True)
    location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    calibration_required = Column(Boolean, nullable=False, default=True)
    dip_unit = Column(String(10), nullable=False, default="cm")
    volume_unit = Column(String(10), nullable=False, default="bbl")

    serial_number = Column(String(100), nullable=True)
    manufacturer = Column(String(150), nullable=True)
    model = Column(String(150), nullable=True)
    commission_date = Column(Date, nullable=True)
    description = Column(Text, nullable=True)

    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    location = relationship("Location")
    tanks = relationship(
        "AssetTank",
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="AssetTank.sort_order",
    )
    calibration_table = relationship(
        "AssetCalibrationTable",
        back_populates="asset",
        uselist=False,
        cascade="all, delete-orphan",
    )


class AssetTank(Base):
    """A tank or compartment belonging to an asset.

    Tanks are declared while the asset is created, because a barge or FSO
    carries several and the calibration chart is keyed by these exact names.
    """

    __tablename__ = "asset_tanks"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(
        Integer,
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tank_name = Column(String(120), nullable=False)
    tank_code = Column(String(50), nullable=True)
    sort_order = Column(Integer, nullable=False, default=1)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    asset = relationship("Asset", back_populates="tanks")

    __table_args__ = (
        UniqueConstraint("asset_id", "tank_name", name="unique_tank_name_per_asset"),
    )


class AssetCalibrationTable(Base):
    """The single active calibration chart of an asset.

    One chart per asset (owner decision 2026-10-17): uploading a new chart
    replaces the rows of the previous one. The chart covers every tank of the
    asset, which is what makes the tank name the third interpolation axis.
    """

    __tablename__ = "asset_calibration_tables"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(
        Integer,
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    chart_name = Column(String(150), nullable=False)
    measurement_basis = Column(String(10), nullable=False, default="Dip")
    source_dip_unit = Column(String(10), nullable=False, default="cm")
    source_volume_unit = Column(String(10), nullable=False, default="bbl")
    source_file_name = Column(String(255), nullable=True)
    effective_date = Column(Date, nullable=True)
    remarks = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    asset = relationship("Asset", back_populates="calibration_table")
    rows = relationship(
        "AssetCalibrationRow",
        back_populates="calibration_table",
        cascade="all, delete-orphan",
        order_by="AssetCalibrationRow.tank_id, AssetCalibrationRow.dip_cm",
    )


class AssetCalibrationRow(Base):
    """One dip/volume point of one tank, stored in canonical cm and bbl.

    ``dip_cm`` holds dip *or* ullage in centimetres, following the parent
    chart's ``measurement_basis``; every payload that exposes it also exposes
    the basis so the value can never be misread. ``source_dip_value`` and
    ``source_volume_value`` keep the numbers exactly as the calibration chart
    supplied them, so an auditor can verify the conversion.
    """

    __tablename__ = "asset_calibration_rows"

    id = Column(Integer, primary_key=True, index=True)
    calibration_table_id = Column(
        Integer,
        ForeignKey("asset_calibration_tables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tank_id = Column(
        Integer,
        ForeignKey("asset_tanks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_number = Column(Integer, nullable=False, default=1)
    dip_cm = Column(Numeric(14, 4), nullable=False)
    volume_bbl = Column(Numeric(16, 6), nullable=False)
    source_dip_value = Column(Numeric(14, 4), nullable=True)
    source_volume_value = Column(Numeric(16, 6), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    calibration_table = relationship("AssetCalibrationTable", back_populates="rows")
    tank = relationship("AssetTank")

    __table_args__ = (
        UniqueConstraint(
            "calibration_table_id",
            "tank_id",
            "dip_cm",
            name="unique_calibration_point_per_tank",
        ),
    )
