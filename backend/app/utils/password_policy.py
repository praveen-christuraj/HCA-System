"""Password policy.

Enterprise baseline: at least 8 characters with upper case, lower case, digit
and special character. Kept in one place so seeding, user creation, admin
reset and self-service password change all enforce the same rule.
"""

from __future__ import annotations

SPECIAL_CHARACTERS = "!@#$%^&*()_+-=[]{};:'\",.<>/?\\|`~"

MIN_LENGTH = 8
MAX_LENGTH = 200


def password_policy_errors(password: str) -> list[str]:
    errors: list[str] = []
    if len(password or "") < MIN_LENGTH:
        errors.append(f"Password must be at least {MIN_LENGTH} characters long")
    if len(password or "") > MAX_LENGTH:
        errors.append(f"Password must be at most {MAX_LENGTH} characters long")
    if not any(char.islower() for char in password or ""):
        errors.append("Password must contain a lower-case letter")
    if not any(char.isupper() for char in password or ""):
        errors.append("Password must contain an upper-case letter")
    if not any(char.isdigit() for char in password or ""):
        errors.append("Password must contain a digit")
    if not any(char in SPECIAL_CHARACTERS for char in password or ""):
        errors.append("Password must contain a special character")
    return errors


def validate_password_policy(password: str) -> None:
    from fastapi import HTTPException

    errors = password_policy_errors(password)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
