"""Authentication and session endpoints (mirrors the OTMS auth model)."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ACCOUNT_LOCK_MINUTES,
    LOGIN_CHALLENGE_MINUTES,
    MAX_FAILED_LOGINS,
)
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import (
    build_logged_in_user_response,
    require_permission,
)
from app.models import (
    AuthLoginChallenge,
    PasswordResetRequest,
    TokenBlacklist,
    User,
    UserBackupCode,
)
from app.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    TwoFAVerifyRequest,
)
from app.services.audit_service import create_audit_log
from app.services.serializers import user_to_dict
from app.utils.helpers import client_ip, display_name, user_agent
from app.utils.jwt import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from app.utils.pagination import paginate_query
from app.utils.password_policy import validate_password_policy
from app.utils.security import (
    decrypt_security_value,
    encrypt_security_value,
    hash_password,
    verify_password,
)
from app.utils.time import utcnow

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _token_expiry(token_payload: dict) -> datetime:
    exp = token_payload.get("exp")
    if exp is None:
        return utcnow() + timedelta(days=1)
    return datetime.fromtimestamp(int(exp), tz=timezone.utc).replace(tzinfo=None)


def _blacklist_token(db: Session, payload: dict, reason: str) -> None:
    jti = payload.get("jti")
    if not jti:
        return
    exists = db.query(TokenBlacklist.id).filter(TokenBlacklist.jti == jti).first()
    if exists:
        return
    db.add(
        TokenBlacklist(
            jti=jti,
            user_id=payload.get("user_id"),
            token_type=payload.get("token_type", "access"),
            expires_at=_token_expiry(payload),
            reason=reason,
            created_at=utcnow(),
        )
    )


def _issue_session(db: Session, user: User, request: Request, audit_action: str) -> dict:
    logged_in_user = build_logged_in_user_response(db, user)
    access_token = create_access_token(
        data={"user_id": user.id, "username": user.username}
    )
    refresh_token = create_refresh_token(
        data={"user_id": user.id, "username": user.username}
    )

    user.last_login_at = utcnow()
    user.last_login_ip = client_ip(request)
    user.failed_login_count = 0
    user.locked_until = None

    create_audit_log(
        db,
        module_name="Authentication",
        action=audit_action,
        category="Authentication",
        current_user=user,
        entity_type="User",
        entity_id=user.id,
        entity_label=display_name(user),
        request=request,
        remarks="User session established",
        details_summary=f"username={user.username}; ip={client_ip(request) or 'unknown'}",
    )
    db.commit()

    return {
        "message": "Login successful",
        "requires_2fa": False,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in_minutes": ACCESS_TOKEN_EXPIRE_MINUTES,
        "user": logged_in_user,
        "role": logged_in_user["role"],
        "roles": logged_in_user["roles"],
        "permissions": logged_in_user["permissions"],
    }


def _audit_login_failure(
    db: Session,
    request: Request,
    username: str,
    action: str,
    remark: str,
    user: User | None = None,
) -> None:
    create_audit_log(
        db,
        module_name="Authentication",
        action=action,
        category="Authentication",
        outcome="Failure",
        current_user=user,
        entity_type="User" if user else None,
        entity_id=user.id if user else None,
        entity_label=display_name(user) if user else username,
        request=request,
        remarks=remark,
        details_summary=f"username={username}; ip={client_ip(request) or 'unknown'}",
        status_code=401,
        actor_username=username if user is None else None,
        actor_full_name="Unknown user" if user is None else None,
    )


def _verify_totp_or_backup_code(db: Session, user: User, code: str) -> bool:
    secret = decrypt_security_value(user.totp_secret)
    if secret:
        try:
            if pyotp.TOTP(secret).verify(code.strip(), valid_window=1):
                return True
        except Exception:
            pass

    # Backup codes are separate rows, never a JSON array (owner rule 4).
    for backup in user.backup_codes:
        if backup.used_at is not None:
            continue
        if verify_password(code.strip(), backup.code_hash):
            backup.used_at = utcnow()
            return True
    return False


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if not payload.password.strip():
        raise HTTPException(status_code=400, detail="Password is required")

    user = (
        db.query(User)
        .filter(func.lower(User.username) == username.lower())
        .first()
    )

    if user is None:
        _audit_login_failure(
            db,
            request,
            username,
            "Login Failed",
            "Unknown username",
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user.status != "Active":
        _audit_login_failure(
            db,
            request,
            username,
            "Login Blocked",
            f"Account status is {user.status}",
            user=user,
        )
        db.commit()
        raise HTTPException(status_code=403, detail="User account is not active")

    if user.locked_until and user.locked_until > utcnow():
        _audit_login_failure(
            db,
            request,
            username,
            "Login Blocked",
            "Account temporarily locked after failed sign-in attempts",
            user=user,
        )
        db.commit()
        raise HTTPException(
            status_code=423,
            detail="Account is temporarily locked. Please try again later.",
        )

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count = int(user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = utcnow() + timedelta(minutes=ACCOUNT_LOCK_MINUTES)
        _audit_login_failure(
            db,
            request,
            username,
            "Login Failed",
            "Invalid password",
            user=user,
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user.failed_login_count = 0
    user.locked_until = None

    if user.totp_enabled:
        challenge = AuthLoginChallenge(
            challenge_id=secrets.token_urlsafe(32),
            user_id=user.id,
            status="Pending",
            expires_at=utcnow() + timedelta(minutes=LOGIN_CHALLENGE_MINUTES),
            ip_address=client_ip(request),
            user_agent=user_agent(request),
            created_at=utcnow(),
        )
        db.add(challenge)
        create_audit_log(
            db,
            module_name="Authentication",
            action="Login 2FA Required",
            category="Authentication",
            current_user=user,
            entity_type="User",
            entity_id=user.id,
            entity_label=display_name(user),
            request=request,
            remarks="Password verified; waiting for two-factor verification",
            details_summary=f"challenge_id={challenge.challenge_id}; username={user.username}",
        )
        db.commit()
        return {
            "message": "Two-factor authentication required",
            "requires_2fa": True,
            "challenge_id": challenge.challenge_id,
            "user_hint": {"full_name": user.full_name, "username": user.username},
        }

    return _issue_session(db, user, request, "Login Success")


@router.post("/2fa/verify")
def verify_login_2fa(
    payload: TwoFAVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    challenge = (
        db.query(AuthLoginChallenge)
        .filter(AuthLoginChallenge.challenge_id == payload.challenge_id)
        .first()
    )
    if (
        challenge is None
        or challenge.status != "Pending"
        or challenge.expires_at < utcnow()
    ):
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA challenge")

    user = db.query(User).filter(User.id == challenge.user_id).first()
    if user is None or user.status != "Active":
        raise HTTPException(status_code=401, detail="Invalid 2FA challenge")

    if not _verify_totp_or_backup_code(db, user, payload.code):
        create_audit_log(
            db,
            module_name="Authentication",
            action="2FA Failed",
            category="Authentication",
            outcome="Failure",
            current_user=user,
            entity_type="User",
            entity_id=user.id,
            entity_label=display_name(user),
            request=request,
            remarks="Invalid two-factor code",
            details_summary=f"challenge_id={challenge.challenge_id}",
            status_code=401,
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid authentication code")

    challenge.status = "Verified"
    challenge.verified_at = utcnow()
    db.commit()
    return _issue_session(db, user, request, "Login Success (2FA)")


@router.post("/refresh")
def refresh_session(
    payload: RefreshTokenRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    token_payload = decode_refresh_token(payload.refresh_token)

    jti = token_payload.get("jti")
    if jti:
        revoked = (
            db.query(TokenBlacklist.id)
            .filter(TokenBlacklist.jti == jti, TokenBlacklist.expires_at > utcnow())
            .first()
        )
        if revoked:
            raise HTTPException(status_code=401, detail="Refresh token has been revoked")

    user = db.query(User).filter(User.id == token_payload.get("user_id")).first()
    if user is None or user.status != "Active":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    _blacklist_token(db, token_payload, "Rotated on refresh")

    access_token = create_access_token(
        data={"user_id": user.id, "username": user.username}
    )
    refresh_token = create_refresh_token(
        data={"user_id": user.id, "username": user.username}
    )

    create_audit_log(
        db,
        module_name="Authentication",
        action="Refresh Token",
        category="Authentication",
        current_user=user,
        entity_type="User",
        entity_id=user.id,
        entity_label=display_name(user),
        request=request,
        remarks="Access token refreshed; previous refresh token rotated",
        details_summary=f"username={user.username}",
    )
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in_minutes": ACCESS_TOKEN_EXPIRE_MINUTES,
        "user": build_logged_in_user_response(db, user),
    }


@router.post("/logout")
def logout(
    request: Request,
    payload: LogoutRequest | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    claims = getattr(request.state, "auth_claims", {}) or {}
    _blacklist_token(db, claims, "Logout")

    if payload and payload.refresh_token:
        try:
            refresh_payload = decode_refresh_token(payload.refresh_token)
            if refresh_payload.get("user_id") == user.id:
                _blacklist_token(db, refresh_payload, "Logout")
        except HTTPException:
            pass

    create_audit_log(
        db,
        module_name="Authentication",
        action="Logout",
        category="Authentication",
        current_user=user,
        entity_type="User",
        entity_id=user.id,
        entity_label=display_name(user),
        request=request,
        remarks="User signed out",
        details_summary=f"username={user.username}",
    )
    db.commit()
    return {"message": "Signed out successfully"}


@router.get("/me")
def current_user_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return build_logged_in_user_response(db, user)


@router.get("/security")
def own_security_settings(
    user: User = Depends(require_permission("profile:read")),
    db: Session = Depends(get_db),
):
    return {
        "user": user_to_dict(user),
        "security": {
            "force_password_change": bool(user.force_password_change),
            "force_2fa": bool(user.force_2fa),
            "totp_enabled": bool(user.totp_enabled),
            "password_changed_at": user.password_changed_at,
            "last_login_at": user.last_login_at,
            "last_login_ip": user.last_login_ip,
            "failed_login_count": int(user.failed_login_count or 0),
            "locked_until": user.locked_until,
        },
        "backup_codes_remaining": sum(
            1 for code in user.backup_codes if code.used_at is None
        ),
    }


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(require_permission("profile:update")),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    validate_password_policy(payload.new_password)
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(
            status_code=422,
            detail="New password must be different from the current password",
        )

    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = utcnow()
    user.force_password_change = False
    user.updated_at = utcnow()

    create_audit_log(
        db,
        module_name="Profile & Security",
        action="Change Password",
        category="Security",
        current_user=user,
        entity_type="User",
        entity_id=user.id,
        entity_label=display_name(user),
        request=request,
        remarks="User changed own password",
        details_summary=f"username={user.username}",
    )
    db.commit()
    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
def request_password_reset(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    username = payload.username.strip()
    user = (
        db.query(User)
        .filter(func.lower(User.username) == username.lower())
        .first()
    )

    if user is not None:
        # Deduplicate pending requests for this user (OTMS parity)
        existing_pending = (
            db.query(PasswordResetRequest)
            .filter(PasswordResetRequest.user_id == user.id, PasswordResetRequest.status == "Pending")
            .first()
        )
        if existing_pending:
            db.commit()
            return {
                "message": (
                    "Password reset request submitted. An administrator will review it; "
                    "contact your administrator if you need urgent access."
                )
            }
        today = utcnow().strftime("%Y%m%d")
        prefix = f"PWR-{today}"
        count = (
            db.query(PasswordResetRequest)
            .filter(PasswordResetRequest.request_number.like(f"{prefix}%"))
            .count()
        )
        reset_request = PasswordResetRequest(
            request_number=f"{prefix}-{count + 1:04d}",
            user_id=user.id,
            username=user.username,
            status="Pending",
            reason=(payload.reason or "").strip()[:500] or None,
            reset_2fa=bool(payload.reset_2fa),
            requested_at=utcnow(),
            requested_by_ip=client_ip(request),
        )
        db.add(reset_request)
        db.flush()
        # Create linked Task Manager task (PASSWORD_RESET_REQUEST) so it appears in /operation-tasks
        try:
            from app.models import OperationTask, OperationTaskEvent
            from app.dependencies.permissions import get_user_role_ids

            # Assign to roles that can reset passwords (users:update or users:read)
            assigned_role_ids = []
            try:
                from app.models import Role
                from app.models import RolePermission
                from app.models import Permission
                # Roles with users:update
                q = (
                    db.query(Role.id)
                    .join(RolePermission, RolePermission.role_id == Role.id)
                    .join(Permission, Permission.id == RolePermission.permission_id)
                    .filter(Permission.permission_name == "users:update", Permission.status == "Active", Role.status == "Active")
                )
                assigned_role_ids = [r[0] for r in q.all()]
                if not assigned_role_ids:
                    # fallback to users:read
                    q2 = (
                        db.query(Role.id)
                        .join(RolePermission, RolePermission.role_id == Role.id)
                        .join(Permission, Permission.id == RolePermission.permission_id)
                        .filter(Permission.permission_name == "users:read", Permission.status == "Active", Role.status == "Active")
                    )
                    assigned_role_ids = [r[0] for r in q2.all()]
            except Exception:
                assigned_role_ids = []

            today_str = utcnow().strftime("%Y%m%d")
            t_prefix = f"TASK-{today_str}"
            t_count = db.query(OperationTask).filter(OperationTask.task_number.like(f"{t_prefix}%")).count()
            task_number = f"{t_prefix}-{t_count + 1:04d}"
            # OTMS uses PWR-derived ticket, HCA uses request_number
            task = OperationTask(
                task_number=task_number,
                task_type="PASSWORD_RESET_REQUEST",
                ticket_number=reset_request.request_number,
                operation_code="PASSWORD_RESET",
                operation_type_code="PASSWORD_RESET",
                location_code="",
                raised_by_user_id=user.id,
                status="Pending",
                priority="High",
                remarks=reset_request.reason or f"Password reset requested for {user.username}",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(task)
            db.flush()
            # link task to request
            reset_request.task_id = task.id
            # create assignment rows for visibility
            if assigned_role_ids:
                from app.models import OperationTaskRole
                for rid in assigned_role_ids:
                    db.add(OperationTaskRole(task_id=task.id, role_id=rid))
            # task event
            db.add(
                OperationTaskEvent(
                    task_id=task.id,
                    event_type="Created",
                    new_status="Pending",
                    actor_user_id=user.id,
                    actor_display=display_name(user),
                    notes=reset_request.reason or "Password reset requested",
                    created_at=utcnow(),
                )
            )
        except Exception:
            # Task creation is best-effort; don't fail the reset request if it errors
            pass
        create_audit_log(
            db,
            module_name="Authentication",
            action="Password Reset Requested",
            category="Security",
            current_user=user,
            entity_type="User",
            entity_id=user.id,
            entity_label=display_name(user),
            request=request,
            remarks="Password reset request submitted",
            details_summary=(
                f"request_number={reset_request.request_number}; "
                f"reset_2fa={payload.reset_2fa}"
            ),
        )
    else:
        create_audit_log(
            db,
            module_name="Authentication",
            action="Password Reset Requested",
            category="Security",
            outcome="Failure",
            request=request,
            entity_type=None,
            remarks="Password reset requested for an unknown username",
            details_summary=f"username={username}",
            actor_username=username,
            actor_full_name="Unknown user",
            status_code=202,
        )

    db.commit()
    return {
        "message": (
            "Password reset request submitted. An administrator will review it; "
            "contact your administrator if you need urgent access."
        )
    }


def _issue_backup_codes(db: Session, user: User, count: int = 8) -> list[str]:
    db.query(UserBackupCode).filter(UserBackupCode.user_id == user.id).delete()
    codes: list[str] = []
    for _ in range(count):
        raw = f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        codes.append(raw)
        db.add(
            UserBackupCode(
                user_id=user.id,
                code_hash=hash_password(raw),
                created_at=utcnow(),
            )
        )
    return codes


@router.post("/2fa/setup")
def setup_2fa(
    request: Request,
    user: User = Depends(require_permission("profile:update")),
    db: Session = Depends(get_db),
):
    secret = pyotp.random_base32()
    user.totp_secret = encrypt_security_value(secret)
    user.updated_at = utcnow()
    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
        name=user.username,
        issuer_name="HCA Enterprise",
    )
    create_audit_log(
        db,
        module_name="Profile & Security",
        action="2FA Setup Initiated",
        category="Security",
        current_user=user,
        entity_type="User",
        entity_id=user.id,
        entity_label=display_name(user),
        request=request,
        remarks="Generated new TOTP secret for two-factor enrolment",
        details_summary=f"username={user.username}",
    )
    db.commit()
    return {
        "secret": secret,
        "otpauth_url": provisioning_uri,
        "issuer": "HCA Enterprise",
        "account_name": user.username,
    }


@router.post("/2fa/enable")
def enable_2fa(
    payload: dict,
    request: Request,
    user: User = Depends(require_permission("profile:update")),
    db: Session = Depends(get_db),
):
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Verification code is required")
    secret = decrypt_security_value(user.totp_secret)
    if not secret:
        raise HTTPException(status_code=400, detail="Initiate 2FA setup first")
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid authenticator verification code")

    user.totp_enabled = True
    user.totp_confirmed_at = utcnow()
    user.force_2fa = False
    user.updated_at = utcnow()
    backup_codes = _issue_backup_codes(db, user)

    create_audit_log(
        db,
        module_name="Profile & Security",
        action="Enable 2FA",
        category="Security",
        current_user=user,
        entity_type="User",
        entity_id=user.id,
        entity_label=display_name(user),
        request=request,
        remarks="Two-factor authentication enabled and backup codes generated",
        details_summary=f"username={user.username}; backup_codes={len(backup_codes)}",
    )
    db.commit()
    return {
        "message": "Two-factor authentication enabled",
        "totp_enabled": True,
        "backup_codes": backup_codes,
    }


@router.post("/2fa/disable")
def disable_2fa(
    payload: dict,
    request: Request,
    user: User = Depends(require_permission("profile:update")),
    db: Session = Depends(get_db),
):
    password = str(payload.get("current_password") or payload.get("password") or "").strip()
    if not password or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is required to disable 2FA")

    user.totp_enabled = False
    user.totp_secret = None
    user.totp_confirmed_at = None
    user.updated_at = utcnow()
    db.query(UserBackupCode).filter(UserBackupCode.user_id == user.id).delete()

    create_audit_log(
        db,
        module_name="Profile & Security",
        action="Disable 2FA",
        category="Security",
        current_user=user,
        entity_type="User",
        entity_id=user.id,
        entity_label=display_name(user),
        request=request,
        remarks="Two-factor authentication disabled",
        details_summary=f"username={user.username}",
    )
    db.commit()
    return {"message": "Two-factor authentication disabled", "totp_enabled": False}


@router.post("/2fa/backup-codes/regenerate")
def regenerate_backup_codes(
    payload: dict | None = None,
    request: Request = None,
    user: User = Depends(require_permission("profile:update")),
    db: Session = Depends(get_db),
):
    if not user.totp_enabled:
        raise HTTPException(status_code=400, detail="Enable two-factor authentication before generating backup codes")
    backup_codes = _issue_backup_codes(db, user)
    create_audit_log(
        db,
        module_name="Profile & Security",
        action="Regenerate Backup Codes",
        category="Security",
        current_user=user,
        entity_type="User",
        entity_id=user.id,
        entity_label=display_name(user),
        request=request,
        remarks="Generated new single-use backup codes",
        details_summary=f"username={user.username}; count={len(backup_codes)}",
    )
    db.commit()
    return {"backup_codes": backup_codes, "backup_codes_remaining": len(backup_codes)}


@router.get("/password-reset-requests")
def list_password_reset_requests(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    search: str | None = None,
    user: User = Depends(require_permission("profile:read")),
    db: Session = Depends(get_db),
):
    from app.dependencies.permissions import user_has_permission

    can_manage_all = user_has_permission(db, user, "users:update") or user_has_permission(db, user, "users:read")
    query = db.query(PasswordResetRequest)
    if not can_manage_all:
        query = query.filter(PasswordResetRequest.user_id == user.id)
    if status:
        query = query.filter(PasswordResetRequest.status == status)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            (PasswordResetRequest.request_number.ilike(term))
            | (PasswordResetRequest.username.ilike(term))
            | (PasswordResetRequest.reason.ilike(term))
        )
    result = paginate_query(query.order_by(PasswordResetRequest.id.desc()), page=page, page_size=page_size)
    result["items"] = [
        {
            "id": r.id,
            "request_number": r.request_number,
            "user_id": r.user_id,
            "username": r.username,
            "status": r.status,
            "reason": r.reason or "",
            "notes": r.reason or "",
            "reset_2fa": bool(r.reset_2fa),
            "requested_at": r.requested_at,
            "requested_by_ip": r.requested_by_ip or "",
            "resolved_by_user_id": r.acted_by_user_id,
            "resolved_at": r.acted_at,
            "resolution_remarks": r.action_notes or "",
            "resolution_notes": r.action_notes or "",
        }
        for r in result["items"]
    ]
    return result


@router.post("/password-reset-requests/{request_id}/resolve")
def resolve_password_reset_request(
    request_id: int,
    payload: dict,
    request: Request,
    actor: User = Depends(require_permission("users:update")),
    db: Session = Depends(get_db),
):
    reset_req = db.get(PasswordResetRequest, request_id)
    if reset_req is None:
        raise HTTPException(status_code=404, detail="Password reset request not found")
    if reset_req.status != "Pending":
        raise HTTPException(status_code=400, detail="Password reset request is already resolved")

    decision = str(payload.get("action") or payload.get("status") or "Resolved").strip().title()
    if decision not in ("Approved", "Rejected", "Resolved"):
        raise HTTPException(status_code=400, detail="Action must be Approved, Resolved, or Rejected")

    remarks = str(payload.get("remarks") or payload.get("resolution_notes") or "").strip() or None
    target_user = db.get(User, reset_req.user_id)
    new_password = str(payload.get("new_password") or "").strip()
    if decision in ("Approved", "Resolved") and new_password:
        if target_user is None:
            raise HTTPException(status_code=404, detail="Target user no longer exists")
        validate_password_policy(new_password)
        target_user.password_hash = hash_password(new_password)
        target_user.password_changed_at = utcnow()
        target_user.force_password_change = True
        target_user.failed_login_count = 0
        target_user.locked_until = None
        if reset_req.reset_2fa or bool(payload.get("reset_2fa")):
            target_user.totp_enabled = False
            target_user.totp_secret = None
            target_user.totp_confirmed_at = None
            db.query(UserBackupCode).filter(UserBackupCode.user_id == target_user.id).delete()

    reset_req.status = decision
    reset_req.acted_by_user_id = actor.id
    reset_req.acted_at = utcnow()
    reset_req.action_notes = remarks

    create_audit_log(
        db,
        module_name="Profile & Security",
        action=f"{decision} Password Reset Request",
        category="Security",
        current_user=actor,
        entity_type="PasswordResetRequest",
        entity_id=reset_req.id,
        entity_label=reset_req.request_number,
        old_status="Pending",
        new_status=decision,
        request=request,
        remarks=remarks or f"Password reset request {decision.lower()}",
        details_summary=f"request_number={reset_req.request_number}; username={reset_req.username}; decision={decision}",
    )
    # Also close linked Task Manager task if present (OTMS parity)
    if reset_req.task_id:
        try:
            from app.models import OperationTask, OperationTaskEvent
            task = db.get(OperationTask, reset_req.task_id)
            if task and task.status in ("Pending", "In Progress"):
                old_status = task.status
                task.status = "Closed" if decision in ("Approved", "Resolved") else "Rejected"
                task.action_taken = "Password Reset Completed" if decision in ("Approved", "Resolved") else "Password Reset Rejected"
                task.acted_by_user_id = actor.id
                task.acted_at = utcnow()
                task.remarks = remarks or task.remarks
                task.updated_at = utcnow()
                db.add(
                    OperationTaskEvent(
                        task_id=task.id,
                        event_type=task.action_taken,
                        old_status=old_status,
                        new_status=task.status,
                        actor_user_id=actor.id,
                        actor_display=display_name(actor),
                        notes=remarks or f"Password reset {decision}",
                        created_at=utcnow(),
                    )
                )
        except Exception:
            pass
    db.commit()
    return {
        "id": reset_req.id,
        "request_number": reset_req.request_number,
        "status": reset_req.status,
        "resolved_at": reset_req.acted_at,
        "resolution_remarks": reset_req.action_notes or "",
        "resolution_notes": reset_req.action_notes or "",
    }


@router.post("/users/{user_id}/security/reset-password")
def admin_reset_user_password(
    user_id: int,
    payload: dict,
    request: Request,
    actor: User = Depends(require_permission("users:update")),
    db: Session = Depends(get_db),
):
    """
    OTMS-compatible admin password reset that closes the associated Task Manager task.
    Frontend Task Manager previously called /users/{id}/security/reset-password without the /auth prefix
    and received 404. This endpoint provides the correct /auth prefix and closes the PASSWORD_RESET_REQUEST task.
    """
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    new_password = str(payload.get("new_password") or "").strip()
    if not new_password:
        raise HTTPException(status_code=400, detail="new_password is required")
    validate_password_policy(new_password)
    target.password_hash = hash_password(new_password)
    target.password_changed_at = utcnow()
    force_change = bool(payload.get("force_password_change", True))
    target.force_password_change = True if force_change else False
    target.failed_login_count = 0
    target.locked_until = None
    reset_2fa = bool(payload.get("reset_2fa"))
    if reset_2fa:
        target.totp_enabled = False
        target.totp_secret = None
        target.totp_confirmed_at = None
        db.query(UserBackupCode).filter(UserBackupCode.user_id == target.id).delete()
    target.updated_at = utcnow()
    remarks = str(payload.get("remarks") or payload.get("reason") or "").strip() or "Password reset by administrator"
    # Close any pending password reset requests for this user
    pending_requests = (
        db.query(PasswordResetRequest)
        .filter(PasswordResetRequest.user_id == target.id, PasswordResetRequest.status == "Pending")
        .all()
    )
    for req in pending_requests:
        req.status = "Completed"
        req.acted_by_user_id = actor.id
        req.acted_at = utcnow()
        req.action_notes = remarks
        if req.task_id:
            try:
                from app.models import OperationTask, OperationTaskEvent
                task = db.get(OperationTask, req.task_id)
                if task and task.status in ("Pending", "In Progress"):
                    old_status = task.status
                    task.status = "Closed"
                    task.action_taken = "Password Reset Completed"
                    task.acted_by_user_id = actor.id
                    task.acted_at = utcnow()
                    task.remarks = remarks
                    task.updated_at = utcnow()
                    db.add(
                        OperationTaskEvent(
                            task_id=task.id,
                            event_type="Password Reset Completed",
                            old_status=old_status,
                            new_status=task.status,
                            actor_user_id=actor.id,
                            actor_display=display_name(actor),
                            notes=remarks,
                            created_at=utcnow(),
                        )
                    )
                    create_audit_log(
                        db,
                        module_name="Operation Task",
                        action="Close Password Reset Task",
                        category="Workflow",
                        current_user=actor,
                        entity_type="OperationTask",
                        entity_id=task.id,
                        entity_label=task.task_number,
                        old_status=old_status,
                        new_status=task.status,
                        request=request,
                        remarks=remarks,
                        details_summary=f"request_number={req.request_number}; target_user={target.username}",
                    )
            except Exception:
                pass
    create_audit_log(
        db,
        module_name="Profile & Security",
        action="Admin Reset User Password",
        category="Security",
        current_user=actor,
        entity_type="User",
        entity_id=target.id,
        entity_label=display_name(target),
        old_status=None,
        new_status=None,
        request=request,
        remarks=remarks,
        details_summary=f"username={target.username}; force_password_change={target.force_password_change}; reset_2fa={reset_2fa}",
        status_code=200,
    )
    db.commit()
    return {"message": "Password reset successfully", "user_id": target.id, "username": target.username}

