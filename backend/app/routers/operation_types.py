"""Operation types and categories (Configurations, read-only catalogue).

The operation types, their asset types, the operation categories and the stock
sign of each category are hard coded in ``app.utils.operation_types``. This
router only reports them, with live counts of how many Operation Master records
sit under each type, so the page shows the rules the system is actually using.
There is deliberately no create, update or delete here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import get_user_location_ids, require_permission
from app.models import Operation, User
from app.utils.operation_types import (
    operation_category_catalog,
    operation_sign_catalog,
    operation_type_catalog,
)

router = APIRouter(prefix="/operation-types", tags=["Operation Types"])


def _operation_counts(db: Session, user: User) -> dict[str, tuple[int, int]]:
    """{type_code: (total, active)} for the Operation Master rows the user can see."""
    query = db.query(
        Operation.operation_type_code,
        func.count(Operation.id),
        func.sum(case((Operation.status == "Active", 1), else_=0)),
    )
    allowed = get_user_location_ids(db, user)
    if allowed is not None:
        if not allowed:
            return {}
        query = query.filter(Operation.location_id.in_(sorted(allowed)))
    rows = query.group_by(Operation.operation_type_code).all()
    return {code: (int(total), int(active or 0)) for code, total, active in rows}


@router.get("")
def list_operation_types(
    user: User = Depends(require_permission("operation_types:read")),
    db: Session = Depends(get_db),
):
    """Fixed operation types with their asset type, plus the category and sign catalogue.

    The catalogue is small and fixed, so it is returned in one response rather
    than paginated. ``total`` and the page metadata keep the shape the list pages
    expect.
    """
    counts = _operation_counts(db, user)
    items = []
    for item in operation_type_catalog():
        total, active = counts.get(item["code"], (0, 0))
        items.append({**item, "operation_count": total, "active_operation_count": active})
    return {
        "items": items,
        "total": len(items),
        "page": 1,
        "page_size": len(items),
        "pages": 1,
        "has_more": False,
        "categories": operation_category_catalog(),
        "signs": operation_sign_catalog(),
    }


@router.get("/categories")
def list_operation_categories(
    user: User = Depends(require_permission("operation_types:read")),
):
    """Fixed categories and their stock signs, for dropdowns and help text."""
    return {
        "items": operation_category_catalog(),
        "signs": operation_sign_catalog(),
        "total": len(operation_category_catalog()),
        "page": 1,
        "page_size": len(operation_category_catalog()),
        "pages": 1,
        "has_more": False,
    }
