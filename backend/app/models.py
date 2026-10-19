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
    Time,
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
    all_locations_access = Column(Boolean, nullable=False, default=False)

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


class PermissionPreset(Base):
    """A named, reusable set of standard permissions.

    Presets exist so an administrator can maintain many roles without ticking
    permissions one by one: the preset is built once and then applied to a role
    (replacing or adding to its current grants). The catalog is deliberately
    capped (``MAX_PERMISSION_PRESETS``, default 20) so the list stays a short,
    curated set of named templates instead of a second permission table.

    Permissions are stored one row per grant in ``permission_preset_items``
    (owner rule 4: no JSON arrays).
    """

    __tablename__ = "permission_presets"

    id = Column(Integer, primary_key=True, index=True)
    preset_name = Column(String(120), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)

    times_applied = Column(Integer, nullable=False, default=0)
    last_applied_at = Column(DateTime, nullable=True)

    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    created_by = relationship("User", foreign_keys=[created_by_user_id])
    updated_by = relationship("User", foreign_keys=[updated_by_user_id])
    items = relationship(
        "PermissionPresetItem",
        back_populates="preset",
        cascade="all, delete-orphan",
    )


class PermissionPresetItem(Base):
    """One permission inside one preset (typed child table, never a JSON list)."""

    __tablename__ = "permission_preset_items"

    id = Column(Integer, primary_key=True, index=True)
    preset_id = Column(
        Integer,
        ForeignKey("permission_presets.id", ondelete="CASCADE"),
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

    preset = relationship("PermissionPreset", back_populates="items")
    permission = relationship("Permission")

    __table_args__ = (
        UniqueConstraint(
            "preset_id",
            "permission_id",
            name="unique_preset_permission",
        ),
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
    task_id = Column(Integer, ForeignKey("operation_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    acted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    acted_at = Column(DateTime, nullable=True)
    action_notes = Column(Text, nullable=True)

    task = relationship("OperationTask")


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


# ---------------------------------------------------------------------------
# Master Data: Prime Mover-Tanker Link
# ---------------------------------------------------------------------------
class PrimeMoverTankerLink(Base):
    """Which tanker trailer a prime mover is hauling, and for which dates.

    Both sides are references to the asset register (ids, not text codes), so a
    renamed asset keeps its links. The link is validated against the exact
    hard-coded asset types (PRIME_MOVER, TANKER_TRAILER). At most one link per
    prime mover and at most one per tanker may be ``Active`` at a time; closing
    a link sets its end date and makes it ``Inactive``.
    """

    __tablename__ = "prime_mover_tanker_links"

    id = Column(Integer, primary_key=True, index=True)
    prime_mover_asset_id = Column(
        Integer,
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    tanker_asset_id = Column(
        Integer,
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    linked_from = Column(Date, nullable=False, index=True)
    linked_to = Column(Date, nullable=True, index=True)
    remarks = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)

    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    prime_mover_asset = relationship("Asset", foreign_keys=[prime_mover_asset_id])
    tanker_asset = relationship("Asset", foreign_keys=[tanker_asset_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    updated_by = relationship("User", foreign_keys=[updated_by_user_id])


# ---------------------------------------------------------------------------
# Configurations: Operation Master (location-scoped operations)
# ---------------------------------------------------------------------------
class Operation(Base):
    """A named operation a location performs, under a fixed type and category.

    The operation type and category come from the hard-coded catalogue in
    ``app.utils.operation_types``. ``operation_sign`` is written from the
    category on every save, so the stored sign can never disagree with the
    category. Operation Entry reads these rows to fill its dropdowns.
    """

    __tablename__ = "operations"

    id = Column(Integer, primary_key=True, index=True)
    location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operation_type_code = Column(String(40), nullable=False, index=True)
    operation_category = Column(String(40), nullable=False, index=True)
    operation_sign = Column(String(10), nullable=False)
    operation_code = Column(String(40), nullable=False, index=True)
    operation_label = Column(String(150), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    location = relationship("Location")

    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "operation_type_code",
            "operation_code",
            name="uq_operation_location_type_code",
        ),
        UniqueConstraint(
            "location_id",
            "operation_type_code",
            "operation_label",
            name="uq_operation_location_type_label",
        ),
    )


# ---------------------------------------------------------------------------
# Business: Operation Entry
#
# One ticket per operation, for every operation type and asset type on a single
# page. The payload shapes are the fixed OTMS module payloads (owner decision
# 2026-10-17: no Operation Template Master customisation); persistence is typed
# columns and child tables per rule 4, and serializers rebuild the payload
# objects for transport.
# ---------------------------------------------------------------------------
class OperationEntry(Base):
    """One operation ticket header (OTMS ``OperationTransaction`` header fields)."""

    __tablename__ = "operation_entries"

    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(200), nullable=False, unique=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    payload_code = Column(String(40), nullable=False)
    operation_id = Column(Integer, ForeignKey("operations.id", ondelete="RESTRICT"), nullable=False)
    linked_ticket_id = Column(Integer, ForeignKey("operation_entries.id", ondelete="RESTRICT"), nullable=True, index=True)
    # Non-null only for a live receiving ticket; unique constraint protects concurrent creation.
    receiver_link_key = Column(Integer, unique=True, nullable=True)
    barge_event_type = Column(String(30), nullable=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    asset_code_snapshot = Column(String(80), nullable=False)
    asset_name_snapshot = Column(String(150), nullable=False)
    operation_code_snapshot = Column(String(40), nullable=False)
    operation_label_snapshot = Column(String(150), nullable=False)
    operation_category_snapshot = Column(String(40), nullable=False)
    operation_sign_snapshot = Column(String(10), nullable=False)
    __mapper_args__ = {"version_id_col": version}
    operation_type_code = Column(String(40), nullable=False, index=True)
    asset_type_code = Column(String(50), nullable=False, index=True)

    asset_id = Column(
        Integer,
        ForeignKey("assets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    destination_location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    sender_location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    receiver_location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    convoy_number = Column(String(50), nullable=True, index=True)
    operation_date = Column(Date, nullable=False, index=True)
    operation_start_datetime = Column(DateTime, nullable=True)
    operation_end_datetime = Column(DateTime, nullable=True)
    product_name = Column(String(150), nullable=True, index=True)
    remarks = Column(Text, nullable=True)

    status = Column(String(20), nullable=False, default="Draft", index=True)
    status_remarks = Column(Text, nullable=True)

    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    asset = relationship("Asset", foreign_keys=[asset_id])
    operation = relationship("Operation", foreign_keys=[operation_id])
    linked_ticket = relationship("OperationEntry", remote_side=[id], foreign_keys=[linked_ticket_id])
    location = relationship("Location", foreign_keys=[location_id])
    destination_location = relationship("Location", foreign_keys=[destination_location_id])
    sender_location = relationship("Location", foreign_keys=[sender_location_id])
    receiver_location = relationship("Location", foreign_keys=[receiver_location_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    updated_by = relationship("User", foreign_keys=[updated_by_user_id])
    submitted_by = relationship("User", foreign_keys=[submitted_by_user_id])
    approved_by = relationship("User", foreign_keys=[approved_by_user_id])

    tank_gauging = relationship(
        "OperationEntryTankGauging",
        back_populates="entry",
        cascade="all, delete-orphan",
        uselist=False,
    )
    multi_tank = relationship(
        "OperationEntryMultiTank",
        back_populates="entry",
        cascade="all, delete-orphan",
        uselist=False,
    )
    tanker = relationship(
        "OperationEntryTanker",
        back_populates="entry",
        cascade="all, delete-orphan",
        uselist=False,
    )
    shuttle = relationship(
        "OperationEntryShuttle",
        back_populates="entry",
        cascade="all, delete-orphan",
        uselist=False,
    )
    fso = relationship(
        "OperationEntryFso",
        back_populates="entry",
        cascade="all, delete-orphan",
        uselist=False,
    )
    flowmeter = relationship(
        "OperationEntryFlowmeter",
        back_populates="entry",
        cascade="all, delete-orphan",
        uselist=False,
    )
    status_history = relationship(
        "OperationEntryStatusHistory",
        back_populates="entry",
        cascade="all, delete-orphan",
        order_by="OperationEntryStatusHistory.id",
    )


class OperationEntryStatusHistory(Base):
    """Append-only workflow history of one ticket."""

    __tablename__ = "operation_entry_status_history"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(
        Integer,
        ForeignKey("operation_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status = Column(String(20), nullable=True)
    to_status = Column(String(20), nullable=False)
    action = Column(String(40), nullable=False)
    remarks = Column(Text, nullable=True)
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=utcnow)

    entry = relationship("OperationEntry", back_populates="status_history")
    actor = relationship("User", foreign_keys=[actor_user_id])


class OperationEntryTankGauging(Base):
    """``tank_gauging_payload``: one row per tank operations ticket."""

    __tablename__ = "operation_entry_tank_gauging"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(
        Integer,
        ForeignKey("operation_entries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Operation selection (Operation Master row, snapshot of its identity)
    operation_code = Column(String(40), nullable=False)
    operation_label = Column(String(150), nullable=False)
    operation_category = Column(String(40), nullable=False)
    operation_sign = Column(String(10), nullable=False)

    # inputs (OTMS emptyTankInput)
    gauging_date = Column(Date, nullable=False)
    gauging_time = Column(String(5), nullable=False)
    dip_cm = Column(Numeric(14, 4), nullable=False)
    water_level_cm = Column(Numeric(14, 4), nullable=False)
    tank_temperature_unit = Column(String(2), nullable=False, default="C")
    tank_temperature = Column(Numeric(8, 3), nullable=False)
    observed_input_type = Column(String(30), nullable=False, default="Observed API")
    observed_api = Column(Numeric(10, 4), nullable=True)
    observed_density = Column(Numeric(12, 4), nullable=True)
    sample_temperature_unit = Column(String(2), nullable=False, default="F")
    sample_temperature = Column(Numeric(8, 3), nullable=False)
    bsw_percent = Column(Numeric(8, 4), nullable=False)
    remarks = Column(Text, nullable=True)

    calibration_table_id_at_save = Column(Integer, nullable=True)
    calibration_name = Column(String(150), nullable=True)
    calibration_effective_date = Column(Date, nullable=True)
    calibration_basis = Column(String(10), nullable=True)
    calibration_max_dip_cm = Column(Numeric(14, 4), nullable=True)
    calibration_table_id = Column(
        Integer,
        ForeignKey("asset_calibration_tables.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # calculated (OTMS tank payload.calculated, keys camelCase in transport)
    tov_bbl = Column(Numeric(16, 4), nullable=True)
    free_water_bbl = Column(Numeric(16, 4), nullable=True)
    gov_bbl = Column(Numeric(16, 4), nullable=True)
    calc_observed_api = Column(Numeric(10, 4), nullable=True)
    calc_observed_density = Column(Numeric(12, 4), nullable=True)
    api60 = Column(Numeric(10, 4), nullable=True)
    density15 = Column(Numeric(12, 4), nullable=True)
    vcf = Column(Numeric(12, 8), nullable=True)
    gsv_bbl = Column(Numeric(16, 4), nullable=True)
    bsw_bbl = Column(Numeric(16, 4), nullable=True)
    nsv_bbl = Column(Numeric(16, 4), nullable=True)
    lt_factor = Column(Numeric(16, 10), nullable=True)
    lt = Column(Numeric(16, 4), nullable=True)
    mt = Column(Numeric(16, 4), nullable=True)
    mass_method = Column(String(120), nullable=True)
    table11_method = Column(String(120), nullable=True)
    table11_lower_api60 = Column(Numeric(10, 4), nullable=True)
    table11_upper_api60 = Column(Numeric(10, 4), nullable=True)

    entry = relationship("OperationEntry", back_populates="tank_gauging")
    calibration_table = relationship("AssetCalibrationTable")


class OperationEntryMultiTank(Base):
    """``multi_tank_payload`` header: barge before/after across compartments."""

    __tablename__ = "operation_entry_multi_tank"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(
        Integer,
        ForeignKey("operation_entries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    calibration_table_id_at_save = Column(Integer, nullable=True)
    calibration_name = Column(String(150), nullable=True)
    calibration_effective_date = Column(Date, nullable=True)
    calibration_basis = Column(String(10), nullable=True)
    calibration_max_dip_cm = Column(Numeric(14, 4), nullable=True)
    calibration_table_id = Column(
        Integer,
        ForeignKey("asset_calibration_tables.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ccf = Column(Numeric(10, 6), nullable=True)

    # Net movement (After − Before)
    net_tov_bbl = Column(Numeric(16, 4), nullable=True)
    net_free_water_bbl = Column(Numeric(16, 4), nullable=True)
    net_gov_bbl = Column(Numeric(16, 4), nullable=True)
    net_gsv_bbl = Column(Numeric(16, 4), nullable=True)
    net_bsw_bbl = Column(Numeric(16, 4), nullable=True)
    net_nsv_bbl = Column(Numeric(16, 4), nullable=True)
    net_lt = Column(Numeric(16, 4), nullable=True)
    net_mt = Column(Numeric(16, 4), nullable=True)

    entry = relationship("OperationEntry", back_populates="multi_tank")
    calibration_table = relationship("AssetCalibrationTable")
    stages = relationship(
        "OperationEntryMultiTankStage",
        back_populates="multi_tank",
        cascade="all, delete-orphan",
        order_by="OperationEntryMultiTankStage.id",
    )
    seals = relationship(
        "OperationEntryMultiTankSeal",
        back_populates="multi_tank",
        cascade="all, delete-orphan",
        order_by="OperationEntryMultiTankSeal.id",
    )


class OperationEntryMultiTankStage(Base):
    """One Before/After stage of a multi-tank ticket, with its totals."""

    __tablename__ = "operation_entry_multi_tank_stages"

    id = Column(Integer, primary_key=True, index=True)
    multi_tank_id = Column(
        Integer,
        ForeignKey("operation_entry_multi_tank.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage = Column(String(10), nullable=False)  # Before | After
    stage_date = Column(Date, nullable=True)
    stage_time = Column(String(5), nullable=True)

    ccf = Column(Numeric(10, 6), nullable=True)
    obs_mode = Column(String(30), nullable=False, default="Observed API")
    obs_api = Column(Numeric(10, 4), nullable=True)
    obs_density = Column(Numeric(12, 4), nullable=True)
    sample_temp_unit = Column(String(2), nullable=False, default="F")
    sample_temp = Column(Numeric(8, 3), nullable=False)
    tank_temp_unit = Column(String(2), nullable=False, default="C")
    tank_temp = Column(Numeric(8, 3), nullable=False)
    bsw_pct = Column(Numeric(8, 4), nullable=False)

    tov_bbl = Column(Numeric(16, 4), nullable=True)
    free_water_bbl = Column(Numeric(16, 4), nullable=True)
    gov_bbl = Column(Numeric(16, 4), nullable=True)
    api60 = Column(Numeric(10, 4), nullable=True)
    vcf = Column(Numeric(12, 8), nullable=True)
    gsv_bbl = Column(Numeric(16, 4), nullable=True)
    bsw_bbl = Column(Numeric(16, 4), nullable=True)
    nsv_bbl = Column(Numeric(16, 4), nullable=True)
    lt_factor = Column(Numeric(16, 10), nullable=True)
    lt = Column(Numeric(16, 4), nullable=True)
    mt = Column(Numeric(16, 4), nullable=True)
    table11_method = Column(String(120), nullable=True)
    table11_lower_api60 = Column(Numeric(10, 4), nullable=True)
    table11_upper_api60 = Column(Numeric(10, 4), nullable=True)

    multi_tank = relationship("OperationEntryMultiTank", back_populates="stages")
    dips = relationship(
        "OperationEntryMultiTankDip",
        back_populates="stage",
        cascade="all, delete-orphan",
        order_by="OperationEntryMultiTankDip.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("multi_tank_id", "stage", name="uq_multi_tank_stage"),
    )


class OperationEntryMultiTankDip(Base):
    """One compartment's dip pair in one stage."""

    __tablename__ = "operation_entry_multi_tank_dips"

    id = Column(Integer, primary_key=True, index=True)
    stage_id = Column(
        Integer,
        ForeignKey("operation_entry_multi_tank_stages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tank_name = Column(String(120), nullable=False)
    sort_order = Column(Integer, nullable=False, default=1)
    total_dip_cm = Column(Numeric(14, 4), nullable=True)
    water_dip_cm = Column(Numeric(14, 4), nullable=True)
    tov_bbl = Column(Numeric(16, 4), nullable=True)
    free_water_bbl = Column(Numeric(16, 4), nullable=True)
    gov_bbl = Column(Numeric(16, 4), nullable=True)

    stage = relationship("OperationEntryMultiTankStage", back_populates="dips")

    __table_args__ = (
        UniqueConstraint("stage_id", "tank_name", name="uq_multi_tank_dip_tank"),
    )


class OperationEntryMultiTankSeal(Base):
    """Permanent tank seal or temporary seal captured on the After stage."""

    __tablename__ = "operation_entry_multi_tank_seals"

    id = Column(Integer, primary_key=True, index=True)
    multi_tank_id = Column(
        Integer,
        ForeignKey("operation_entry_multi_tank.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seal_group = Column(String(20), nullable=False)  # Tank | Temporary
    tank_name = Column(String(120), nullable=True)
    position = Column(String(40), nullable=False)  # MH1, MH2, LOCK, ... | portManifoldSeal ...
    master_number = Column(String(120), nullable=True)
    observed_number = Column(String(120), nullable=True)
    remarks = Column(Text, nullable=True)

    multi_tank = relationship("OperationEntryMultiTank", back_populates="seals")


class OperationEntryTanker(Base):
    """``tanker_payload``: one row per tanker ticket."""

    __tablename__ = "operation_entry_tanker"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(
        Integer,
        ForeignKey("operation_entries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    operation_code = Column(String(40), nullable=True)
    operation_label = Column(String(150), nullable=True)
    operation_category = Column(String(40), nullable=True)
    operation_sign = Column(String(10), nullable=True)

    operation_text = Column(String(150), nullable=True)
    tanker_transaction_date = Column(Date, nullable=False)
    tanker_transaction_time = Column(String(5), nullable=False)
    tanker_name = Column(String(150), nullable=True)
    prime_mover_number = Column(String(80), nullable=True)
    chassis_number = Column(String(100), nullable=True)
    compartment = Column(String(120), nullable=False, default="C1")
    prime_mover_asset_id = Column(Integer, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True)
    prime_mover_name = Column(String(150), nullable=True)
    total_dip_cm = Column(Numeric(14, 4), nullable=False)
    water_dip_cm = Column(Numeric(14, 4), nullable=False)
    bsw_percent = Column(Numeric(8, 4), nullable=False)
    tank_temperature_unit = Column(String(2), nullable=False, default="C")
    tank_temperature = Column(Numeric(8, 3), nullable=False)
    observed_input_type = Column(String(30), nullable=False, default="Observed API")
    observed_api = Column(Numeric(10, 4), nullable=True)
    observed_density = Column(Numeric(12, 4), nullable=True)
    sample_temperature_unit = Column(String(2), nullable=False, default="F")
    sample_temperature = Column(Numeric(8, 3), nullable=False)
    seal_c1 = Column(String(120), nullable=True)
    seal_c2 = Column(String(120), nullable=True)
    seal_m1 = Column(String(120), nullable=True)
    seal_m2 = Column(String(120), nullable=True)
    remarks = Column(Text, nullable=True)

    calibration_table_id_at_save = Column(Integer, nullable=True)
    calibration_name = Column(String(150), nullable=True)
    calibration_effective_date = Column(Date, nullable=True)
    calibration_basis = Column(String(10), nullable=True)
    calibration_max_dip_cm = Column(Numeric(14, 4), nullable=True)
    calibration_table_id = Column(
        Integer,
        ForeignKey("asset_calibration_tables.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    tov_bbl = Column(Numeric(16, 4), nullable=True)
    free_water_bbl = Column(Numeric(16, 4), nullable=True)
    gov_bbl = Column(Numeric(16, 4), nullable=True)
    calc_observed_api = Column(Numeric(10, 4), nullable=True)
    calc_observed_density = Column(Numeric(12, 4), nullable=True)
    api60 = Column(Numeric(10, 4), nullable=True)
    density15 = Column(Numeric(12, 4), nullable=True)
    vcf = Column(Numeric(12, 8), nullable=True)
    gsv_bbl = Column(Numeric(16, 4), nullable=True)
    bsw_bbl = Column(Numeric(16, 4), nullable=True)
    nsv_bbl = Column(Numeric(16, 4), nullable=True)
    lt_factor = Column(Numeric(16, 10), nullable=True)
    lt = Column(Numeric(16, 4), nullable=True)
    mt = Column(Numeric(16, 4), nullable=True)
    mass_method = Column(String(120), nullable=True)
    table11_method = Column(String(120), nullable=True)
    table11_lower_api60 = Column(Numeric(10, 4), nullable=True)
    table11_upper_api60 = Column(Numeric(10, 4), nullable=True)

    entry = relationship("OperationEntry", back_populates="tanker")
    calibration_table = relationship("AssetCalibrationTable")


class OperationEntryShuttle(Base):
    """``shuttle_payload``: one row per shuttle voyage event."""

    __tablename__ = "operation_entry_shuttle"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(
        Integer,
        ForeignKey("operation_entries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    operation_code = Column(String(40), nullable=False)
    operation_label = Column(String(150), nullable=False)
    operation_category = Column(String(40), nullable=False)
    operation_sign = Column(String(10), nullable=False)

    event_time = Column(String(5), nullable=True)
    opening_stock_bbl = Column(Numeric(16, 4), nullable=False, default=0)
    opening_water_bbl = Column(Numeric(16, 4), nullable=False, default=0)
    closing_stock_bbl = Column(Numeric(16, 4), nullable=False, default=0)
    closing_water_bbl = Column(Numeric(16, 4), nullable=False, default=0)
    barge_reference = Column(String(120), nullable=True)
    remarks = Column(Text, nullable=True)

    net_stock_bbl = Column(Numeric(16, 4), nullable=True)
    net_water_bbl = Column(Numeric(16, 4), nullable=True)

    entry = relationship("OperationEntry", back_populates="shuttle")


class OperationEntryFso(Base):
    """``fso_payload``: one row per FSO event."""

    __tablename__ = "operation_entry_fso"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(
        Integer,
        ForeignKey("operation_entries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    operation_code = Column(String(40), nullable=False)
    operation_label = Column(String(150), nullable=False)
    operation_category = Column(String(40), nullable=False)
    operation_sign = Column(String(10), nullable=False)

    event_time = Column(String(5), nullable=True)
    shuttle_number = Column(String(50), nullable=True)
    vessel_name = Column(String(150), nullable=True)
    vessel_quantity_bbl = Column(Numeric(20, 8), nullable=True)
    source_shuttle_discharge_bbl = Column(Numeric(20, 8), nullable=True)
    source_voyage_id = Column(Integer, ForeignKey("operation_voyages.id", ondelete="RESTRICT"), nullable=True)
    opening_stock_bbl = Column(Numeric(16, 4), nullable=False, default=0)
    opening_water_bbl = Column(Numeric(16, 4), nullable=False, default=0)
    closing_stock_bbl = Column(Numeric(16, 4), nullable=False, default=0)
    closing_water_bbl = Column(Numeric(16, 4), nullable=False, default=0)
    remarks = Column(Text, nullable=True)

    net_stock_bbl = Column(Numeric(16, 4), nullable=True)
    net_water_bbl = Column(Numeric(16, 4), nullable=True)
    variance_bbl = Column(Numeric(16, 4), nullable=True)

    entry = relationship("OperationEntry", back_populates="fso")


class OperationEntryFlowmeter(Base):
    """``flowmeter_payload`` header: one row per meter-reading ticket."""

    __tablename__ = "operation_entry_flowmeter"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(
        Integer,
        ForeignKey("operation_entries.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    stream_name = Column(String(150), nullable=False)
    reading_date = Column(Date, nullable=False)
    event_time = Column(String(5), nullable=True)
    tank_temperature_unit = Column(String(2), nullable=False, default="C")
    tank_temperature = Column(Numeric(8, 3), nullable=False)
    observed_input_type = Column(String(30), nullable=False, default="Observed API")
    observed_api = Column(Numeric(10, 4), nullable=True)
    observed_density = Column(Numeric(12, 4), nullable=True)
    sample_temperature_unit = Column(String(2), nullable=False, default="F")
    sample_temperature = Column(Numeric(8, 3), nullable=False)
    bsw_percent = Column(Numeric(8, 4), nullable=False)
    remarks = Column(Text, nullable=True)

    stream_gross_observed = Column(Numeric(26, 12), nullable=True)
    stream_gross_observed_bbl = Column(Numeric(26, 12), nullable=True)
    api60 = Column(Numeric(10, 4), nullable=True)
    vcf = Column(Numeric(12, 8), nullable=True)
    gsv_bbl = Column(Numeric(26, 12), nullable=True)
    bsw_bbl = Column(Numeric(26, 12), nullable=True)
    nsv_bbl = Column(Numeric(26, 12), nullable=True)

    entry = relationship("OperationEntry", back_populates="flowmeter")
    meters = relationship(
        "OperationEntryFlowmeterMeter",
        back_populates="flowmeter",
        cascade="all, delete-orphan",
        order_by="OperationEntryFlowmeterMeter.sort_order",
    )


class OperationEntryFlowmeterMeter(Base):
    """One meter's opening/closing readings in a flowmeter ticket."""

    __tablename__ = "operation_entry_flowmeter_meters"

    id = Column(Integer, primary_key=True, index=True)
    flowmeter_id = Column(
        Integer,
        ForeignKey("operation_entry_flowmeter.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sort_order = Column(Integer, nullable=False, default=1)
    config_id = Column(Integer, ForeignKey("flowmeter_configs.id", ondelete="RESTRICT"), nullable=False)
    meter_asset_code = Column(String(80), nullable=True)
    meter_asset_name = Column(String(150), nullable=True)
    meter_label = Column(String(150), nullable=False)
    opening_reading = Column(Numeric(26, 12), nullable=False, default=0)
    closing_reading = Column(Numeric(26, 12), nullable=False, default=0)
    meter_factor = Column(Numeric(16, 10), nullable=False, default=1)
    meter_unit = Column(String(10), nullable=False, default="m3")
    gross_observed = Column(Numeric(26, 12), nullable=True)
    gross_observed_bbl = Column(Numeric(26, 12), nullable=True)

    flowmeter = relationship("OperationEntryFlowmeter", back_populates="meters")

    __table_args__ = (
        UniqueConstraint("flowmeter_id", "meter_label", name="uq_flowmeter_meter_label"),
    )


class Table11Factor(Base):
    """Operator-supplied Table 11 reference factors. Never generated or labelled certified."""
    __tablename__ = "table11_factors"
    id = Column(Integer, primary_key=True)
    api60 = Column(Numeric(10, 4), nullable=False, unique=True, index=True)
    lt_factor = Column(Numeric(16, 10), nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class FlowmeterConfig(Base):
    __tablename__ = "flowmeter_configs"
    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    meter_asset_id = Column(Integer, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True)
    stream_name = Column(String(150), nullable=False)
    meter_label = Column(String(150), nullable=False)
    meter_factor = Column(Numeric(16, 10), nullable=False, default=1)
    meter_unit = Column(String(10), nullable=False, default="bbls")
    calibration_date = Column(Date, nullable=True)
    remarks = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active")
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    asset = relationship("Asset", foreign_keys=[asset_id])
    meter_asset = relationship("Asset", foreign_keys=[meter_asset_id])
    location = relationship("Location")
    __table_args__ = (UniqueConstraint("location_id", "asset_id", "meter_label", name="uq_entry_meter_config"),)


class BargeSealMaster(Base):
    __tablename__ = "barge_seal_master"
    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    tank_id = Column(Integer, ForeignKey("asset_tanks.id", ondelete="RESTRICT"), nullable=False)
    seal_position = Column(String(20), nullable=False)
    seal_number = Column(String(120), nullable=False)
    effective_date = Column(Date, nullable=True)
    remarks = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active")
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    asset = relationship("Asset")
    tank = relationship("AssetTank")
    __table_args__ = (UniqueConstraint("asset_id", "tank_id", "seal_position", name="uq_entry_barge_seal"),)


class OperationWorkflowPolicy(Base):
    """Additional role/user gate, never a substitute for the capability + location gates."""
    __tablename__ = "operation_workflow_policies"
    id = Column(Integer, primary_key=True)
    policy_name = Column(String(150), nullable=False, unique=True)
    action_code = Column(String(30), nullable=False)
    operation_type_code = Column(String(40), nullable=True)
    asset_type_code = Column(String(50), nullable=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True)
    payload_code = Column(String(40), nullable=True)
    priority = Column(Integer, nullable=False, default=100)
    roles = relationship("OperationWorkflowPolicyRole", cascade="all, delete-orphan")
    users = relationship("OperationWorkflowPolicyUser", cascade="all, delete-orphan")
    status = Column(String(20), nullable=False, default="Active")
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class OperationVoyage(Base):
    """Entry-side trip guard and closed-shuttle discharge source. Tracking reports are separate."""
    __tablename__ = "operation_voyages"
    id = Column(Integer, primary_key=True)
    reference = Column(String(50), nullable=False, index=True)
    operation_type_code = Column(String(40), nullable=False)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(20), nullable=False, default="OPEN")
    closed_at = Column(DateTime, nullable=True)
    closed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    closure_remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    asset = relationship("Asset")
    location = relationship("Location")
    closed_by = relationship("User")
    __table_args__ = (UniqueConstraint("operation_type_code", "reference", "asset_id", "location_id", name="uq_operation_voyage_key"),)


class OperationPosting(Base):
    """Exactly one immutable stock/event posting per approved ticket, in the same transaction."""
    __tablename__ = "operation_postings"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("operation_entries.id", ondelete="RESTRICT"), nullable=False, unique=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True)
    operation_date = Column(Date, nullable=False, index=True)
    operation_category = Column(String(40), nullable=False)
    operation_sign = Column(String(10), nullable=False)
    quantity_bbl = Column(Numeric(26, 12), nullable=False)
    water_bbl = Column(Numeric(26, 12), nullable=False, default=0)
    event_type = Column(String(30), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class OperationEntryManualMovement(Base):
    """OTMS scalar fields used by Stock Movement and Vessel Cycle (no EAV/JSON storage)."""
    __tablename__ = "operation_entry_manual_movements"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("operation_entries.id", ondelete="CASCADE"), nullable=False, unique=True)
    movement_reference = Column(String(120), nullable=True)
    counterparty_asset_code = Column(String(80), nullable=True)
    opening_stock = Column(Numeric(24, 8), nullable=True)
    opening_water = Column(Numeric(24, 8), nullable=True)
    closing_stock = Column(Numeric(24, 8), nullable=True)
    closing_water = Column(Numeric(24, 8), nullable=True)
    quantity_bbl = Column(Numeric(24, 8), nullable=True)
    water_bbl = Column(Numeric(24, 8), nullable=True)
    net_stock = Column(Numeric(24, 8), nullable=True)
    net_water = Column(Numeric(24, 8), nullable=True)
    net_nsv = Column(Numeric(24, 8), nullable=True)
    entry = relationship("OperationEntry", backref="manual_movement_rows")


class OperationEntryWarning(Base):
    __tablename__ = "operation_entry_warnings"
    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("operation_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    message = Column(Text, nullable=False)
    entry = relationship("OperationEntry", backref="warnings")


class OperationWorkflowPolicyRole(Base):
    __tablename__ = "operation_workflow_policy_roles"
    policy_id = Column(Integer, ForeignKey("operation_workflow_policies.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True)


class OperationWorkflowPolicyUser(Base):
    __tablename__ = "operation_workflow_policy_users"
    policy_id = Column(Integer, ForeignKey("operation_workflow_policies.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    mode = Column(String(10), nullable=False, default="ALLOW")


# ---------------------------------------------------------------------------
# Operation Tracking (OTMS Barge / Tanker tracking facts)
# ---------------------------------------------------------------------------
class BargeTimelineEvent(Base):
    """Manually recorded barge timeline facts.

    Ticket events (LOAD_1, LOAD_2_TOPUP, UNLOAD, STS) are derived from Approved
    tickets on read. Only facts that are not tickets are stored here: receipt
    acknowledgements (RECEIVED / RECEIPT_REVOKED) and administrator corrections
    of a ticket's event type (``entry_id`` set, one correction per ticket).
    """

    __tablename__ = "barge_timeline_events"

    id = Column(Integer, primary_key=True)
    convoy_number = Column(String(50), nullable=False, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    entry_id = Column(Integer, ForeignKey("operation_entries.id", ondelete="RESTRICT"), nullable=True, unique=True)
    event_type = Column(String(30), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True)
    event_datetime = Column(DateTime, nullable=False, default=utcnow)
    remarks = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    asset = relationship("Asset")
    location = relationship("Location")
    created_by = relationship("User")


class TankerReceiptAcknowledgement(Base):
    """Receiver acknowledgement and closure of one Approved tanker sender ticket."""

    __tablename__ = "tanker_receipt_acknowledgements"

    id = Column(Integer, primary_key=True)
    sender_entry_id = Column(Integer, ForeignKey("operation_entries.id", ondelete="RESTRICT"), nullable=False, unique=True)
    convoy_number = Column(String(50), nullable=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    receiver_location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(20), nullable=False, default="Acknowledged")  # Acknowledged | Revoked | Closed
    remarks = Column(Text, nullable=True)
    acknowledged_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=False, default=utcnow)
    revoked_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoke_remarks = Column(Text, nullable=True)
    closed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    closure_remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    receiver_location = relationship("Location")
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_user_id])
    closed_by = relationship("User", foreign_keys=[closed_by_user_id])


# ---------------------------------------------------------------------------
# User Location Assignment (direct user-location scope alongside RoleLocation)
# ---------------------------------------------------------------------------
class UserLocation(Base):
    __tablename__ = "user_locations"
    __table_args__ = (
        UniqueConstraint("user_id", "location_id", name="uq_user_locations_pair"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    user = relationship("User", backref="user_location_assignments")
    location = relationship("Location")


# ---------------------------------------------------------------------------
# Asset Assignment Master
# ---------------------------------------------------------------------------
class AssetAssignment(Base):
    __tablename__ = "asset_assignments"

    id = Column(Integer, primary_key=True, index=True)
    asset_id = Column(Integer, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    asset_code = Column(String(50), nullable=False, index=True)
    asset_scope = Column(String(30), nullable=False)
    assignment_location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True)
    assignment_location_code = Column(String(50), nullable=False, index=True)
    assigned_to_type = Column(String(30), nullable=False)  # User | Location | External
    assigned_to = Column(String(150), nullable=False)
    assignment_date = Column(Date, nullable=False)
    return_date = Column(Date, nullable=True)
    remarks = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    asset = relationship("Asset")
    assignment_location = relationship("Location")


# ---------------------------------------------------------------------------
# Configurations: Location Operation Availability, Accounting Day, Report Profile, Material Balance
# ---------------------------------------------------------------------------
class LocationOperationAvailability(Base):
    __tablename__ = "location_operation_availability"
    __table_args__ = (
        UniqueConstraint("location_id", "operation_type_code", name="uq_loc_op_avail_pair"),
    )

    id = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)
    location_code = Column(String(50), nullable=False, index=True)
    operation_type_code = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    location = relationship("Location")


class LocationAccountingDaySetting(Base):
    __tablename__ = "location_accounting_day_settings"

    id = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)
    location_code = Column(String(50), nullable=False, index=True)
    day_start_time = Column(Time, nullable=False)
    day_end_time = Column(Time, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    timezone_name = Column(String(100), nullable=False, default="Africa/Lagos")
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    location = relationship("Location")


class CompanyReportProfile(Base):
    __tablename__ = "company_report_profiles"

    id = Column(Integer, primary_key=True, index=True)
    profile_code = Column(String(50), nullable=False, unique=True, index=True)
    company_name = Column(String(200), nullable=False)
    company_short_name = Column(String(100), nullable=True)
    report_header_line_1 = Column(String(250), nullable=True)
    report_header_line_2 = Column(String(250), nullable=True)
    address_line = Column(String(300), nullable=True)
    email = Column(String(150), nullable=True)
    phone = Column(String(80), nullable=True)
    website = Column(String(200), nullable=True)
    tax_registration_number = Column(String(100), nullable=True)
    logo_url = Column(Text, nullable=True)
    primary_color = Column(String(30), nullable=False, default="#0B3B66")
    accent_color = Column(String(30), nullable=False, default="#1F5F99")
    footer_text = Column(String(300), nullable=True)
    prepared_by_label = Column(String(100), nullable=False, default="Prepared By")
    checked_by_label = Column(String(100), nullable=False, default="Checked By")
    approved_by_label = Column(String(100), nullable=False, default="Approved By")
    show_signature_block = Column(Boolean, nullable=False, default=True)
    show_generated_timestamp = Column(Boolean, nullable=False, default=True)
    show_page_number = Column(Boolean, nullable=False, default=True)
    is_default = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class MaterialBalanceTemplate(Base):
    __tablename__ = "material_balance_templates"

    id = Column(Integer, primary_key=True, index=True)
    template_name = Column(String(150), nullable=False)
    template_code = Column(String(80), nullable=False, unique=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True, index=True)
    location_code = Column(String(50), nullable=False, index=True)
    basis = Column(String(20), nullable=False, default="NSV")
    reporting_unit = Column(String(20), nullable=False, default="BBL")
    auto_carry_opening_stock = Column(Boolean, nullable=False, default=True)
    opening_operation_code = Column(String(80), nullable=False, default="OPENING_STOCK")
    closing_operation_code = Column(String(80), nullable=False, default="CLOSING_STOCK")
    is_default = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="Active", index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    location = relationship("Location")
    columns = relationship(
        "MaterialBalanceTemplateColumn",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="MaterialBalanceTemplateColumn.display_order",
    )


class MaterialBalanceTemplateColumn(Base):
    __tablename__ = "material_balance_template_columns"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("material_balance_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    column_code = Column(String(80), nullable=False)
    column_label = Column(String(150), nullable=False)
    column_group = Column(String(80), nullable=False, default="MOVEMENTS")
    column_type = Column(String(40), nullable=False)
    unit = Column(String(30), nullable=True)
    display_order = Column(Integer, nullable=False, default=1)
    source_metric = Column(String(30), nullable=False, default="NSV")
    direction_filter = Column(String(20), nullable=True)
    category_filter = Column(String(40), nullable=True)
    sign_multiplier = Column(Integer, nullable=False, default=1)
    formula_expression = Column(String(500), nullable=True)
    visible = Column(Boolean, nullable=False, default=True)
    is_system_column = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="Active")
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    template = relationship("MaterialBalanceTemplate", back_populates="columns")
    operation_mappings = relationship(
        "MaterialBalanceTemplateColumnOperation",
        back_populates="column",
        cascade="all, delete-orphan",
    )


class MaterialBalanceTemplateColumnOperation(Base):
    __tablename__ = "material_balance_template_column_operations"

    id = Column(Integer, primary_key=True, index=True)
    column_id = Column(Integer, ForeignKey("material_balance_template_columns.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_code = Column(String(80), nullable=False)
    mapping_mode = Column(String(20), nullable=False, default="INCLUDE")  # INCLUDE | EXCLUDE

    column = relationship("MaterialBalanceTemplateColumn", back_populates="operation_mappings")


class OutTurnSummaryConfig(Base):
    __tablename__ = "out_turn_summary_configs"

    id = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=True, index=True)
    location_code = Column(String(50), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="Active")
    updated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    columns = relationship(
        "OutTurnSummaryConfigColumn",
        back_populates="config",
        cascade="all, delete-orphan",
        order_by="OutTurnSummaryConfigColumn.sort_order",
    )


class OutTurnSummaryConfigColumn(Base):
    __tablename__ = "out_turn_summary_config_columns"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey("out_turn_summary_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    column_key = Column(String(80), nullable=False)
    operation_code = Column(String(80), nullable=False)
    column_label = Column(String(150), nullable=False)
    sign = Column(String(10), nullable=False, default="+")
    visible = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=1)

    config = relationship("OutTurnSummaryConfig", back_populates="columns")


# ---------------------------------------------------------------------------
# Flowmeter History & Standalone Records, Movement Mapping, Operation Tasks, Corrections
# ---------------------------------------------------------------------------
class FlowmeterConfigHistory(Base):
    __tablename__ = "flowmeter_config_history"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey("flowmeter_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(40), nullable=False)
    changed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_by = Column(String(150), nullable=True)
    old_meter_factor = Column(Numeric(18, 6), nullable=True)
    new_meter_factor = Column(Numeric(18, 6), nullable=True)
    old_status = Column(String(30), nullable=True)
    new_status = Column(String(30), nullable=True)
    change_summary = Column(Text, nullable=True)
    changed_at = Column(DateTime, nullable=False, default=utcnow)


class FlowmeterRecord(Base):
    __tablename__ = "flowmeter_records"

    id = Column(Integer, primary_key=True, index=True)
    record_number = Column(String(60), nullable=False, unique=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False, index=True)
    location_code = Column(String(50), nullable=False, index=True)
    flowmeter_asset_id = Column(Integer, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, index=True)
    flowmeter_asset_code = Column(String(50), nullable=False, index=True)
    stream_name = Column(String(150), nullable=False)
    meter_label = Column(String(150), nullable=False)
    record_date = Column(Date, nullable=False, index=True)
    start_time = Column(String(20), nullable=True)
    end_time = Column(String(20), nullable=True)
    opening_reading = Column(Numeric(18, 4), nullable=False, default=0)
    closing_reading = Column(Numeric(18, 4), nullable=False, default=0)
    gross_volume = Column(Numeric(18, 4), nullable=False, default=0)
    meter_factor = Column(Numeric(18, 6), nullable=False, default=1)
    ctl = Column(Numeric(18, 6), nullable=False, default=1)
    cpl = Column(Numeric(18, 6), nullable=False, default=1)
    bsw_pct = Column(Numeric(18, 4), nullable=False, default=0)
    gsv_bbl = Column(Numeric(18, 4), nullable=False, default=0)
    bsw_bbl = Column(Numeric(18, 4), nullable=False, default=0)
    nsv_bbl = Column(Numeric(18, 4), nullable=False, default=0)
    mt = Column(Numeric(18, 4), nullable=False, default=0)
    lt = Column(Numeric(18, 4), nullable=False, default=0)
    temperature_deg = Column(Numeric(18, 4), nullable=True)
    pressure_psig = Column(Numeric(18, 4), nullable=True)
    api60 = Column(Numeric(18, 4), nullable=True)
    remarks = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Approved", index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    location = relationship("Location")
    flowmeter_asset = relationship("Asset")
    created_by = relationship("User")


class MovementMapping(Base):
    __tablename__ = "movement_mappings"

    id = Column(Integer, primary_key=True, index=True)
    mapping_number = Column(String(60), nullable=False, unique=True, index=True)
    mapping_type = Column(String(40), nullable=False, default="TANK_TO_BARGE")
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True, index=True)
    location_code = Column(String(50), nullable=False, index=True)
    mapping_date = Column(Date, nullable=False, index=True)
    sender_total_gov = Column(Numeric(18, 4), nullable=False, default=0)
    sender_total_gsv = Column(Numeric(18, 4), nullable=False, default=0)
    sender_total_nsv = Column(Numeric(18, 4), nullable=False, default=0)
    receiver_total_gov = Column(Numeric(18, 4), nullable=False, default=0)
    receiver_total_gsv = Column(Numeric(18, 4), nullable=False, default=0)
    receiver_total_nsv = Column(Numeric(18, 4), nullable=False, default=0)
    variance_gov = Column(Numeric(18, 4), nullable=False, default=0)
    variance_gsv = Column(Numeric(18, 4), nullable=False, default=0)
    variance_nsv = Column(Numeric(18, 4), nullable=False, default=0)
    variance_nsv_pct = Column(Numeric(18, 4), nullable=False, default=0)
    remarks = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Open", index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(String(150), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    items = relationship("MovementMappingItem", back_populates="mapping", cascade="all, delete-orphan")


class MovementMappingItem(Base):
    __tablename__ = "movement_mapping_items"

    id = Column(Integer, primary_key=True, index=True)
    mapping_id = Column(Integer, ForeignKey("movement_mappings.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_id = Column(Integer, ForeignKey("operation_entries.id", ondelete="RESTRICT"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # SENDER | RECEIVER
    allocated_gov = Column(Numeric(18, 4), nullable=True)
    allocated_gsv = Column(Numeric(18, 4), nullable=True)
    allocated_nsv = Column(Numeric(18, 4), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    mapping = relationship("MovementMapping", back_populates="items")
    entry = relationship("OperationEntry")


class OperationTask(Base):
    __tablename__ = "operation_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_number = Column(String(60), nullable=False, unique=True, index=True)
    task_type = Column(String(60), nullable=False, index=True)
    entry_id = Column(Integer, ForeignKey("operation_entries.id", ondelete="CASCADE"), nullable=True, index=True)
    ticket_number = Column(String(80), nullable=True, index=True)
    operation_code = Column(String(80), nullable=True)
    operation_type_code = Column(String(50), nullable=True, index=True)
    asset_type_code = Column(String(50), nullable=True)
    primary_asset_code = Column(String(50), nullable=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True, index=True)
    location_code = Column(String(50), nullable=True, index=True)
    raised_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_policy_id = Column(Integer, ForeignKey("operation_workflow_policies.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), nullable=False, default="Pending", index=True)
    priority = Column(String(20), nullable=False, default="Normal")
    due_at = Column(DateTime, nullable=True)
    taken_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    taken_at = Column(DateTime, nullable=True)
    acted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acted_at = Column(DateTime, nullable=True)
    action_taken = Column(String(60), nullable=True)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    entry = relationship("OperationEntry")
    assigned_roles = relationship("OperationTaskRole", back_populates="task", cascade="all, delete-orphan")
    assigned_users = relationship("OperationTaskUser", back_populates="task", cascade="all, delete-orphan")
    events = relationship(
        "OperationTaskEvent",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="OperationTaskEvent.id",
    )


class OperationTaskRole(Base):
    __tablename__ = "operation_task_roles"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)

    task = relationship("OperationTask", back_populates="assigned_roles")


class OperationTaskUser(Base):
    __tablename__ = "operation_task_users"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    task = relationship("OperationTask", back_populates="assigned_users")


class OperationTaskEvent(Base):
    __tablename__ = "operation_task_events"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("operation_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(60), nullable=False)
    old_status = Column(String(30), nullable=True)
    new_status = Column(String(30), nullable=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_display = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    details_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    task = relationship("OperationTask", back_populates="events")


class ApprovedTransactionCorrectionRequest(Base):
    __tablename__ = "approved_transaction_correction_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_number = Column(String(60), nullable=False, unique=True, index=True)
    entry_id = Column(Integer, ForeignKey("operation_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("operation_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    ticket_number = Column(String(80), nullable=False, index=True)
    operation_code = Column(String(80), nullable=True)
    request_type = Column(String(80), nullable=False)
    suggested_action = Column(String(80), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(40), nullable=False, default="Pending Admin Review", index=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_by_display = Column(String(200), nullable=False)
    requested_at = Column(DateTime, nullable=False, default=utcnow)
    admin_action = Column(String(40), nullable=True)
    admin_remarks = Column(Text, nullable=True)
    admin_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    admin_action_at = Column(DateTime, nullable=True)
    previous_status_before_revoke = Column(String(30), nullable=True)
    new_status_after_revoke = Column(String(30), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    entry = relationship("OperationEntry")
    task = relationship("OperationTask")


# ---------------------------------------------------------------------------
# Export Operations
# ---------------------------------------------------------------------------
class ExportLocation(Base):
    __tablename__ = "export_locations"

    id = Column(Integer, primary_key=True, index=True)
    location_code = Column(String(50), nullable=False, unique=True, index=True)
    location_name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ExportEntity(Base):
    __tablename__ = "export_entities"

    id = Column(Integer, primary_key=True, index=True)
    entity_code = Column(String(50), nullable=False, unique=True, index=True)
    entity_name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ExportLocationEntity(Base):
    __tablename__ = "export_location_entities"
    __table_args__ = (
        UniqueConstraint("location_code", "entity_code", name="uq_export_loc_entity"),
    )

    id = Column(Integer, primary_key=True, index=True)
    location_code = Column(String(50), nullable=False, index=True)
    entity_code = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="Active")
    created_at = Column(DateTime, nullable=False, default=utcnow)


class ExportBlock(Base):
    __tablename__ = "export_blocks"

    id = Column(Integer, primary_key=True, index=True)
    block_code = Column(String(50), nullable=False, unique=True, index=True)
    block_name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ExportEntityBlock(Base):
    __tablename__ = "export_entity_blocks"
    __table_args__ = (
        UniqueConstraint("entity_code", "block_code", name="uq_export_entity_block"),
    )

    id = Column(Integer, primary_key=True, index=True)
    entity_code = Column(String(50), nullable=False, index=True)
    block_code = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="Active")
    created_at = Column(DateTime, nullable=False, default=utcnow)


class ExportConsignee(Base):
    __tablename__ = "export_consignees"

    id = Column(Integer, primary_key=True, index=True)
    consignee_code = Column(String(50), nullable=False, unique=True, index=True)
    consignee_name = Column(String(150), nullable=False)
    country = Column(String(100), nullable=True)
    contact_info = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ExportPermit(Base):
    __tablename__ = "export_permits"

    id = Column(Integer, primary_key=True, index=True)
    permit_number = Column(String(80), nullable=False, unique=True, index=True)
    location_code = Column(String(50), nullable=False, index=True)
    entity_code = Column(String(50), nullable=False, index=True)
    block_code = Column(String(50), nullable=True, index=True)
    quarter = Column(String(20), nullable=False, index=True)
    permit_volume = Column(Numeric(18, 4), nullable=False, default=0)
    issue_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    remarks = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    block_assignments = relationship(
        "ExportPermitBlockAssignment",
        back_populates="permit",
        cascade="all, delete-orphan",
    )


class ExportPermitBlockAssignment(Base):
    __tablename__ = "export_permit_block_assignments"

    id = Column(Integer, primary_key=True, index=True)
    permit_id = Column(Integer, ForeignKey("export_permits.id", ondelete="CASCADE"), nullable=False, index=True)
    block_code = Column(String(50), nullable=False, index=True)

    permit = relationship("ExportPermit", back_populates="block_assignments")


class ExportTransaction(Base):
    __tablename__ = "export_transactions"

    id = Column(Integer, primary_key=True, index=True)
    bl_date = Column(Date, nullable=False, index=True)
    location_code = Column(String(50), nullable=False, index=True)
    entity_code = Column(String(50), nullable=False, index=True)
    block_code = Column(String(50), nullable=False, index=True)
    permit_number = Column(String(80), nullable=True, index=True)
    quarter = Column(String(20), nullable=False, index=True)
    vessel_name = Column(String(150), nullable=True)
    consignee = Column(String(150), nullable=True)
    country = Column(String(100), nullable=True, index=True)
    volume = Column(Numeric(18, 4), nullable=False, default=0)
    override_permit_limit = Column(Boolean, nullable=False, default=False)
    remarks = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class ExportConfig(Base):
    __tablename__ = "export_configs"

    id = Column(Integer, primary_key=True, index=True)
    config_key = Column(String(100), nullable=False, unique=True, index=True)
    config_value = Column(String(250), nullable=False)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------------------
# Backup & Recovery (typed scalar columns only — no JSON)
# ---------------------------------------------------------------------------
class BackupSettings(Base):
    __tablename__ = "backup_settings"

    id = Column(Integer, primary_key=True, index=True)
    enabled = Column(Boolean, nullable=False, default=False)
    schedule_mode = Column(String(20), nullable=False, default="Daily")
    interval_value = Column(Integer, nullable=False, default=24)
    run_time = Column(String(10), nullable=False, default="02:00")
    retention_days = Column(Integer, nullable=False, default=30)
    keep_minimum = Column(Integer, nullable=False, default=5)
    backup_directory = Column(String(300), nullable=False, default="backups")
    compression_enabled = Column(Boolean, nullable=False, default=True)
    status = Column(String(20), nullable=False, default="Active")
    next_run_at = Column(DateTime, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class BackupJob(Base):
    __tablename__ = "backup_jobs"

    id = Column(Integer, primary_key=True, index=True)
    backup_number = Column(String(60), nullable=False, unique=True, index=True)
    backup_type = Column(String(30), nullable=False, default="Manual")
    trigger_source = Column(String(30), nullable=False, default="User")
    status = Column(String(20), nullable=False, default="Completed", index=True)
    description = Column(Text, nullable=True)
    file_name = Column(String(200), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    checksum_sha256 = Column(String(128), nullable=True)
    database_name = Column(String(100), nullable=True)
    backup_format = Column(String(40), nullable=False, default="SQLite Snapshot")
    requested_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_by_display = Column(String(200), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    table_count = Column(Integer, nullable=True)
    row_count = Column(Integer, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    verified_checksum_matched = Column(Boolean, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class BackupRestoreRequest(Base):
    __tablename__ = "backup_restore_requests"

    id = Column(Integer, primary_key=True, index=True)
    request_number = Column(String(60), nullable=False, unique=True, index=True)
    backup_job_id = Column(Integer, ForeignKey("backup_jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    backup_number = Column(String(60), nullable=False)
    status = Column(String(30), nullable=False, default="Pending Approval", index=True)
    reason = Column(Text, nullable=False)
    business_impact = Column(Text, nullable=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_by_display = Column(String(200), nullable=True)
    requested_at = Column(DateTime, nullable=False, default=utcnow)
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_display = Column(String(200), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    rejected_by_display = Column(String(200), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    cancelled_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancelled_by_display = Column(String(200), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    action_remarks = Column(Text, nullable=True)
    pre_restore_backup_number = Column(String(60), nullable=True)
    executed_by_display = Column(String(200), nullable=True)
    executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    backup_job = relationship("BackupJob")
    validations = relationship(
        "BackupRestoreValidation",
        back_populates="restore_request",
        cascade="all, delete-orphan",
        order_by="BackupRestoreValidation.id.desc()",
    )


class BackupRestoreValidation(Base):
    __tablename__ = "backup_restore_validations"

    id = Column(Integer, primary_key=True, index=True)
    validation_number = Column(String(60), nullable=False, unique=True, index=True)
    restore_request_id = Column(Integer, ForeignKey("backup_restore_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    backup_job_id = Column(Integer, ForeignKey("backup_jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    backup_number = Column(String(60), nullable=False)
    status = Column(String(30), nullable=False, default="Validated", index=True)
    validation_database_name = Column(String(120), nullable=True)
    started_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_by_display = Column(String(200), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    table_count = Column(Integer, nullable=True)
    total_rows = Column(Integer, nullable=True)
    validation_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    restore_request = relationship("BackupRestoreRequest", back_populates="validations")


# ---------------------------------------------------------------------------
# System Notifications (typed child tables for targets — no JSON)
# ---------------------------------------------------------------------------
class SystemNotification(Base):
    __tablename__ = "system_notifications"

    id = Column(Integer, primary_key=True, index=True)
    notification_number = Column(String(60), nullable=False, unique=True, index=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String(30), nullable=False, default="Info")
    priority = Column(String(20), nullable=False, default="Normal")
    delivery_mode = Column(String(30), nullable=False, default="Banner + Inbox")
    target_scope = Column(String(30), nullable=False, default="All Users")
    display_from = Column(DateTime, nullable=True)
    display_until = Column(DateTime, nullable=True)
    requires_acknowledgement = Column(Boolean, nullable=False, default=False)
    popup_enabled = Column(Boolean, nullable=False, default=False)
    banner_enabled = Column(Boolean, nullable=False, default=True)
    auto_dismiss_seconds = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="Draft", index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_display = Column(String(200), nullable=True)
    published_at = Column(DateTime, nullable=True)
    published_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deactivated_at = Column(DateTime, nullable=True)
    deactivated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deactivation_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    target_roles = relationship("SystemNotificationTargetRole", back_populates="notification", cascade="all, delete-orphan")
    target_users = relationship("SystemNotificationTargetUser", back_populates="notification", cascade="all, delete-orphan")
    target_locations = relationship("SystemNotificationTargetLocation", back_populates="notification", cascade="all, delete-orphan")
    receipts = relationship("SystemNotificationReceipt", back_populates="notification", cascade="all, delete-orphan")


class SystemNotificationTargetRole(Base):
    __tablename__ = "system_notification_target_roles"

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(Integer, ForeignKey("system_notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)

    notification = relationship("SystemNotification", back_populates="target_roles")


class SystemNotificationTargetUser(Base):
    __tablename__ = "system_notification_target_users"

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(Integer, ForeignKey("system_notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    notification = relationship("SystemNotification", back_populates="target_users")


class SystemNotificationTargetLocation(Base):
    __tablename__ = "system_notification_target_locations"

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(Integer, ForeignKey("system_notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    location_code = Column(String(50), nullable=False, index=True)

    notification = relationship("SystemNotification", back_populates="target_locations")


class SystemNotificationReceipt(Base):
    __tablename__ = "system_notification_receipts"
    __table_args__ = (
        UniqueConstraint("notification_id", "user_id", name="uq_sys_notif_receipt_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(Integer, ForeignKey("system_notifications.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String(80), nullable=False)
    status = Column(String(20), nullable=False, default="Unread", index=True)
    delivered_at = Column(DateTime, nullable=False, default=utcnow)
    first_seen_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    dismissed_at = Column(DateTime, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledgement_remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    notification = relationship("SystemNotification", back_populates="receipts")

