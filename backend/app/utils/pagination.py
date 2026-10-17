"""Pagination helpers (owner rule 5).

Every list endpoint uses the same page/page_size contract and the standard
20/50/100/200 page sizes. Date filters are applied by the routers separately
from general filters (owner rule 6).
"""

from __future__ import annotations

from math import ceil

from app.config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PAGE_SIZE_OPTIONS


def clamp_page(value) -> int:
    try:
        return max(int(value or 1), 1)
    except (TypeError, ValueError):
        return 1


def clamp_page_size(value, *, allow_export_sizes: bool = False) -> int:
    try:
        size = int(value or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE

    size = max(size, 1)
    if size in PAGE_SIZE_OPTIONS:
        return size
    # Snap to a supported size. Standard lists use 20/50/100/200 exactly;
    # export/large-list callers may go up to MAX_PAGE_SIZE.
    if allow_export_sizes and size > max(PAGE_SIZE_OPTIONS):
        return min(size, MAX_PAGE_SIZE)
    supported = sorted(PAGE_SIZE_OPTIONS)
    smaller = [option for option in supported if option <= size]
    return smaller[-1] if smaller else DEFAULT_PAGE_SIZE


def paginate_query(query, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
    page = clamp_page(page)
    page_size = clamp_page_size(page_size)
    total = query.order_by(None).count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    pages = ceil(total / page_size) if page_size else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "has_more": page < pages,
    }


def pagination_payload(items, total: int, page: int, page_size: int) -> dict:
    page = clamp_page(page)
    page_size = clamp_page_size(page_size)
    pages = ceil(total / page_size) if page_size else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "has_more": page < pages,
    }
