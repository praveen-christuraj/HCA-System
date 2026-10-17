"""HTTP middleware.

AuditMiddleware provides the second layer of owner rule 1: any mutating API
request or denied request that a router did not explicitly audit is written to
the audit trail with its actor, path, status, IP and user agent. Requests that
were explicitly audited set ``request.state.audit_written`` and are skipped.
"""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import SessionLocal
from app.models import AuditLog
from app.utils.helpers import client_ip, user_agent
from app.utils.jwt import decode_token
from app.utils.time import utcnow

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

PATH_MODULES = [
    ("/api/auth", "Authentication", "Authentication"),
    ("/api/users", "User Master", "Data Change"),
    ("/api/roles", "Role Master", "Data Change"),
    ("/api/locations", "Location Master", "Data Change"),
    ("/api/role-locations", "Role Location Assignment", "Administration"),
    ("/api/user-roles", "User Role Assignment", "Administration"),
    ("/api/permissions", "Permission Master", "Data Change"),
    ("/api/permission-presets", "Permission Presets", "Administration"),
    ("/api/prime-mover-tanker-links", "Prime Mover-Tanker Link", "Data Change"),
    ("/api/operation-types", "Operation Types", "Data Change"),
    ("/api/operations", "Operation Master", "Data Change"),
    ("/api/audit-logs", "Audit Trail", "Auditing"),
    ("/api/audit/ui-events", "UI Activity", "Navigation"),
    ("/api/dashboard", "Dashboard", "Navigation"),
    ("/api/system", "System Administration", "Administration"),
]

ACTION_BY_METHOD = {
    "POST": "Create",
    "PUT": "Update",
    "PATCH": "Update",
    "DELETE": "Delete",
}


def _resolve_module(path: str) -> tuple[str, str]:
    for prefix, module, category in PATH_MODULES:
        if path.startswith(prefix):
            return module, category
    return "Application", "General"


def _actor_from_request(request: Request) -> tuple[int | None, str | None]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None, None
    token = header.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except Exception:
        return None, None
    return payload.get("user_id"), payload.get("username")


def _entity_id_from_path(path: str) -> int | None:
    for segment in reversed(path.rstrip("/").split("/")):
        if segment.isdigit():
            return int(segment)
    return None


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        should_consider = path.startswith("/api/") and path not in {
            "/api/health",
            "/api/openapi.json",
        }

        response = await call_next(request)

        if not should_consider:
            return response

        # A router/endpoint already wrote a detailed audit row for this request.
        if getattr(request.state, "audit_written", False):
            return response

        method = request.method.upper()
        is_denied = response.status_code in {401, 403}
        if method not in MUTATING_METHODS and not is_denied:
            return response

        module_name, category = _resolve_module(path)
        actor_user_id, actor_username = _actor_from_request(request)

        if is_denied:
            action = "Access Denied"
            category = "Security"
            outcome = "Failure"
        else:
            base_action = ACTION_BY_METHOD.get(method, "Action")
            if method == "POST" and path.rstrip("/").endswith("/import"):
                base_action = "Import Users"
            elif method == "POST" and path.rstrip("/").endswith("/export"):
                base_action = "Export"
            action = base_action if response.status_code < 400 else f"{base_action} Failed"
            outcome = "Success" if response.status_code < 400 else "Failure"

        entity_id = _entity_id_from_path(path)
        summary = (
            f"{method} {path} returned {response.status_code}. "
            "Recorded by the audit fallback middleware."
        )

        db = SessionLocal()
        try:
            db.add(
                AuditLog(
                    module_name=module_name,
                    action=action,
                    category=category,
                    outcome=outcome,
                    entity_type=None,
                    entity_id=entity_id,
                    entity_label=None,
                    actor_user_id=actor_user_id,
                    actor_username=actor_username,
                    actor_full_name=None,
                    http_method=method,
                    request_path=path[:250],
                    status_code=response.status_code,
                    ip_address=client_ip(request),
                    user_agent=user_agent(request),
                    remarks=None,
                    details_summary=summary,
                    created_at=utcnow(),
                )
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Conservative response hardening that keeps previews embeddable."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        return response
