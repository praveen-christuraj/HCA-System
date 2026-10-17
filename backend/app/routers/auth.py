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
from app.utils.password_policy import validate_password_policy
from app.utils.security import (
    decrypt_security_value,
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
