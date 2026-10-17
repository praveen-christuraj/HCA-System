"""Audit trail writer (owner rules 1 and 11).

Audit records are append-only and use typed columns only (owner rule 4).
Routers pass ``request`` so the originating IP, user agent, method, path and
status are captured; doing so also marks the request as explicitly audited so
the fallback middleware does not duplicate the record.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.utils.helpers import client_ip, display_name, user_agent
from app.utils.time import utcnow


def create_audit_log(
    db: Session,
    module_name: str,
    action: str,
    *,
    current_user: User | None = None,
    category: str = "Data Change",
    outcome: str = "Success",
    entity_type: str | None = None,
    entity_id: int | None = None,
    entity_label: str | None = None,
    request: Request | None = None,
    remarks: str | None = None,
    details_summary: str | None = None,
    old_status: str | None = None,
    new_status: str | None = None,
    status_code: int = 200,
    actor_username: str | None = None,
    actor_user_id: int | None = None,
    actor_full_name: str | None = None,
) -> AuditLog:
    # The authenticated user is also stored on request.state by the auth
    # dependency, so callers that only have the request still get an actor.
    if current_user is None and request is not None:
        current_user = getattr(request.state, "auth_user", None)

    if current_user is not None:
        actor_user_id = getattr(current_user, "id", None)
        actor_username = getattr(current_user, "username", None)
        actor_full_name = getattr(current_user, "full_name", None)
    elif actor_username:
        actor_full_name = actor_full_name or "System"

    request_path = None
    http_method = None
    ip_address = None
    agent = None
    if request is not None:
        request.state.audit_written = True
        request_path = request.url.path
        http_method = request.method
        ip_address = client_ip(request)
        agent = user_agent(request)

    entry = AuditLog(
        module_name=(module_name or "Application")[:120],
        action=(action or "Action")[:120],
        category=(category or "General")[:60],
        outcome=(outcome or "Success")[:20],
        entity_type=(entity_type or "")[:120] or None,
        entity_id=entity_id,
        entity_label=(entity_label or "")[:200] or None,
        actor_user_id=actor_user_id,
        actor_username=(actor_username or "")[:80] or None,
        actor_full_name=(actor_full_name or "")[:150] or None,
        http_method=http_method,
        request_path=(request_path or "")[:250] or None,
        status_code=status_code,
        ip_address=ip_address,
        user_agent=agent,
        old_status=old_status,
        new_status=new_status,
        remarks=remarks,
        details_summary=details_summary,
        created_at=utcnow(),
    )
    db.add(entry)
    return entry


def audit_actor_label(user: User | None) -> str:
    return display_name(user) if user is not None else "System"
