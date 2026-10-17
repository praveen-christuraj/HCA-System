"""Small shared helpers."""

from __future__ import annotations

from datetime import date, datetime, time

from fastapi import HTTPException, Request


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def require_text(value: str | None, field_name: str) -> str:
    cleaned = clean_optional_text(value)
    if not cleaned:
        raise HTTPException(status_code=422, detail=f"{field_name} is required")
    return cleaned


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    agent = request.headers.get("user-agent")
    return agent[:1000] if agent else None


def display_name(user) -> str:
    if user is None:
        return "System"
    full_name = getattr(user, "full_name", None) or ""
    username = getattr(user, "username", None) or ""
    if full_name and username:
        return f"{full_name} ({username})"
    return full_name or username or "System"


def parse_date_bound(value: date | datetime | None, end: bool = False) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.max if end else time.min)


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")
