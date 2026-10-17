"""SQLAlchemy models.

Owner rule 4: no JSON/JSONB/document columns. Every business attribute is a
typed column; collections are child tables. Audit details are typed columns
plus a human-readable summary, never a serialized payload.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
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
