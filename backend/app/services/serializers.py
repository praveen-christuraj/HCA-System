"""Consistent API representations for shared entities."""

from __future__ import annotations

from app.models import AuditLog, Permission, Role, User


def role_to_dict(role: Role) -> dict:
    return {
        "id": role.id,
        "role_name": role.role_name,
        "description": role.description or "",
        "status": role.status,
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
