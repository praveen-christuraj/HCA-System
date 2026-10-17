"""Authentication dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import TokenBlacklist, User
from app.utils.jwt import decode_access_token
from app.utils.time import utcnow

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = decode_access_token(credentials.credentials)

    jti = payload.get("jti")
    if jti:
        revoked = (
            db.query(TokenBlacklist.id)
            .filter(TokenBlacklist.jti == jti, TokenBlacklist.expires_at > utcnow())
            .first()
        )
        if revoked:
            raise HTTPException(status_code=401, detail="Token has been revoked")

    user_id = payload.get("user_id")
    user = db.query(User).filter(User.id == user_id).first() if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    if user.status != "Active":
        raise HTTPException(status_code=403, detail="User account is not active")

    # Stored for audit writers and middleware fallback.
    request.state.auth_user = user
    request.state.auth_claims = payload
    return user


def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        return get_current_user(request, credentials, db)
    except HTTPException:
        return None
