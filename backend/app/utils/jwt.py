"""JWT creation and decoding (access + refresh tokens).

Identity claims only: user id, username, token type, expiry and jti.
Permissions are never trusted from the token — they are read from the
database on every request.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException

from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    REFRESH_TOKEN_EXPIRE_DAYS,
)


def _encode(data: dict, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **data,
        "exp": now + expires_delta,
        "iat": now,
        "token_type": token_type,
        "jti": secrets.token_urlsafe(24),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    return _encode(
        data,
        "access",
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(data: dict, expires_delta: timedelta | None = None) -> str:
    return _encode(
        data,
        "refresh",
        expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: str | None = None) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    if expected_type and payload.get("token_type") != expected_type:
        raise HTTPException(status_code=401, detail="Invalid token type")
    return payload


def decode_access_token(token: str) -> dict:
    return decode_token(token, "access")


def decode_refresh_token(token: str) -> dict:
    return decode_token(token, "refresh")
