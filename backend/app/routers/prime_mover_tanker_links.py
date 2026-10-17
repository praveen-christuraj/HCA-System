"""Prime Mover-Tanker Link (Master Data Management).

Records which tanker trailer a prime mover is hauling, and for which dates. It
is the OTMS "Prime Mover-Tanker Link Master" brought onto the HCA rules:

* **Exact asset types.** OTMS guessed whether an asset was a prime mover or a
  tanker from its name and code text. HCA checks the hard-coded
  ``PRIME_MOVER`` and ``TANKER_TRAILER`` types, so an alias can never link the
  wrong kind of asset.
* **Asset references, not text codes.** A link points at the asset register, so
  renaming an asset keeps its history.
* **One active link per side.** A prime mover and a tanker may each have at
  most one ``Active`` link. Closing a link sets its end date and makes it
  ``Inactive``. Only the Active link is the current one.
* **Location scope.** A link is visible only when both of its assets are
  visible to the user: Global assets, or assets at the user's assigned
  locations. Only an administrator may create or change a link that involves a
  Global asset, which matches the OTMS rule.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, aliased, joinedload

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import (
    get_user_location_ids,
    is_admin_user,
    require_permission,
)
from app.models import Asset, PrimeMoverTankerLink, User
from app.schemas import (
    PrimeMoverTankerLinkClose,
    PrimeMoverTankerLinkCreate,
    PrimeMoverTankerLinkUpdate,
)
from app.services.audit_service import create_audit_log
from app.services.serializers import prime_mover_tanker_link_to_dict
from app.utils.asset_types import PRIME_MOVER, TANKER_TRAILER, get_asset_type
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.helpers import clean_optional_text, parse_import_date
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/prime-mover-tanker-links", tags=["Prime Mover-Tanker Link"])

MODULE_NAME = "Prime Mover-Tanker Link"
STATUS_ACTIVE = "Active"
STATUS_INACTIVE = "Inactive"

IMPORT_TEMPLATE_HEADERS = [
    "prime_mover_code",
    "tanker_code",
    "linked_from",
    "linked_to",
    "status",
    "remarks",
]

_IMPORT_ALIASES = {
    "prime_mover": "prime_mover_code",
    "prime_mover_asset_code": "prime_mover_code",
    "tanker": "tanker_code",
    "tanker_asset_code": "tanker_code",
    "from": "linked_from",
    "to": "linked_to",
    "remark": "remarks",
}


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------
def _asset_visible_clause(asset_alias, allowed: set[int] | None):
    """SQL predicate: the asset is Global or sits at one of the allowed locations."""
    if allowed is None:
        return None
    if not allowed:
        return asset_alias.asset_scope == "Global"
    return or_(
        asset_alias.asset_scope == "Global",
        asset_alias.location_id.in_(sorted(allowed)),
    )


def _visible_asset_ids(db: Session, user: User) -> set[int] | None:
    """Ids of assets the user may see, or None when unrestricted."""
    allowed = get_user_location_ids(db, user)
    if allowed is None:
        return None
    query = db.query(Asset.id)
    clause = _asset_visible_clause(Asset, allowed)
    if clause is not None:
        query = query.filter(clause)
    return {asset_id for (asset_id,) in query.all()}


def _link_query(db: Session, user: User):
    """Links whose prime mover AND tanker are both visible to the user."""
    prime_alias = aliased(Asset)
    tanker_alias = aliased(Asset)
    query = (
        db.query(PrimeMoverTankerLink)
        .join(prime_alias, prime_alias.id == PrimeMoverTankerLink.prime_mover_asset_id)
        .join(tanker_alias, tanker_alias.id == PrimeMoverTankerLink.tanker_asset_id)
        .options(
            joinedload(PrimeMoverTankerLink.prime_mover_asset),
            joinedload(PrimeMoverTankerLink.tanker_asset),
            joinedload(PrimeMoverTankerLink.created_by),
            joinedload(PrimeMoverTankerLink.updated_by),
        )
    )
    allowed = get_user_location_ids(db, user)
    if allowed is not None:
        for alias in (prime_alias, tanker_alias):
            clause = _asset_visible_clause(alias, allowed)
            if clause is not None:
                query = query.filter(clause)
    return query, prime_alias, tanker_alias


def _get_link(db: Session, user: User, link_id: int) -> PrimeMoverTankerLink:
    query, _, _ = _link_query(db, user)
    link = query.filter(PrimeMoverTankerLink.id == link_id).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Prime mover-tanker link not found")
    return link


def _link_label(link: PrimeMoverTankerLink) -> str:
    pm = link.prime_mover_asset.asset_code if link.prime_mover_asset else str(link.prime_mover_asset_id)
    tk = link.tanker_asset.asset_code if link.tanker_asset else str(link.tanker_asset_id)
    return f"{pm} -> {tk}"


def _snapshot(link: PrimeMoverTankerLink) -> str:
    return (
        f"prime_mover={link.prime_mover_asset.asset_code if link.prime_mover_asset else ''}; "
        f"tanker={link.tanker_asset.asset_code if link.tanker_asset else ''}; "
        f"from={link.linked_from}; to={link.linked_to or 'open'}; status={link.status}"
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _validate_link(
    db: Session,
    actor: User,
    *,
    prime_mover_asset_id: int,
    tanker_asset_id: int,
    linked_from: date,
    linked_to: date | None,
    status: str,
    exclude_id: int | None = None,
) -> tuple[Asset, Asset]:
    """Raise HTTPException(422/403/409) unless the link may be stored.

    Assets outside the actor's scope are reported as "not found" so a user cannot
    probe the register for codes they cannot see.
    """
    if prime_mover_asset_id == tanker_asset_id:
        raise HTTPException(
            status_code=422,
            detail="A prime mover and a tanker trailer must be two different assets",
        )

    visible = _visible_asset_ids(db, actor)

    def _load(asset_id: int, label: str) -> Asset:
        asset = db.get(Asset, asset_id)
        if asset is None or (visible is not None and asset.id not in visible):
            raise HTTPException(status_code=422, detail=f"The {label} asset was not found")
        return asset

    prime_mover = _load(prime_mover_asset_id, "prime mover")
    tanker = _load(tanker_asset_id, "tanker")

    if prime_mover.asset_type_code != PRIME_MOVER:
        raise HTTPException(
            status_code=422,
            detail=f"{prime_mover.asset_code} is not a Prime Mover asset",
        )
    if tanker.asset_type_code != TANKER_TRAILER:
        raise HTTPException(
            status_code=422,
            detail=f"{tanker.asset_code} is not a Tanker Trailer asset",
        )
    if status == STATUS_ACTIVE:
        if prime_mover.status != STATUS_ACTIVE:
            raise HTTPException(
                status_code=422,
                detail=f"Prime mover {prime_mover.asset_code} is Inactive; activate it before linking",
            )
        if tanker.status != STATUS_ACTIVE:
            raise HTTPException(
                status_code=422,
                detail=f"Tanker {tanker.asset_code} is Inactive; activate it before linking",
            )

    if (
        prime_mover.asset_scope == "Global" or tanker.asset_scope == "Global"
    ) and not is_admin_user(actor, db):
        raise HTTPException(
            status_code=403,
            detail="Only an administrator can create or change a link that involves a Global asset",
        )

    if linked_to is not None and linked_to < linked_from:
        raise HTTPException(
            status_code=422,
            detail="The linked-to date cannot be before the linked-from date",
        )

    if status == STATUS_ACTIVE:
        _ensure_no_other_active(db, prime_mover_asset_id, tanker_asset_id, exclude_id)
    return prime_mover, tanker


def _ensure_no_other_active(
    db: Session,
    prime_mover_asset_id: int,
    tanker_asset_id: int,
    exclude_id: int | None,
) -> None:
    base = db.query(PrimeMoverTankerLink.id).filter(PrimeMoverTankerLink.status == STATUS_ACTIVE)
    if exclude_id is not None:
        base = base.filter(PrimeMoverTankerLink.id != exclude_id)
    if base.filter(PrimeMoverTankerLink.prime_mover_asset_id == prime_mover_asset_id).first():
        raise HTTPException(
            status_code=409,
            detail="This prime mover already has an active link. Close it before linking another tanker.",
        )
    if base.filter(PrimeMoverTankerLink.tanker_asset_id == tanker_asset_id).first():
        raise HTTPException(
            status_code=409,
            detail="This tanker already has an active link. Close it before linking another prime mover.",
        )


def _filtered_links(
    db: Session,
    user: User,
    *,
    search: str | None,
    status: str | None,
    prime_mover_asset_id: int | None,
    tanker_asset_id: int | None,
    date_from: date | None,
    date_to: date | None,
):
    query, prime_alias, tanker_alias = _link_query(db, user)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                prime_alias.asset_code.ilike(term),
                prime_alias.asset_name.ilike(term),
                prime_alias.serial_number.ilike(term),
                tanker_alias.asset_code.ilike(term),
                tanker_alias.asset_name.ilike(term),
                tanker_alias.serial_number.ilike(term),
                PrimeMoverTankerLink.remarks.ilike(term),
            )
        )
    if status:
        query = query.filter(PrimeMoverTankerLink.status == status)
    if prime_mover_asset_id is not None:
        query = query.filter(PrimeMoverTankerLink.prime_mover_asset_id == prime_mover_asset_id)
    if tanker_asset_id is not None:
        query = query.filter(PrimeMoverTankerLink.tanker_asset_id == tanker_asset_id)
    if date_from:
        query = query.filter(PrimeMoverTankerLink.linked_from >= date_from)
    if date_to:
        query = query.filter(PrimeMoverTankerLink.linked_from <= date_to)
    return query


def _apply_link_fields(link: PrimeMoverTankerLink, values: dict) -> None:
    link.prime_mover_asset_id = values["prime_mover_asset_id"]
    link.tanker_asset_id = values["tanker_asset_id"]
    link.linked_from = values["linked_from"]
    link.linked_to = values["linked_to"]
    link.remarks = values["remarks"]
    link.status = values["status"]


# ---------------------------------------------------------------------------
# Lists and lookups
# ---------------------------------------------------------------------------
@router.get("")
def list_links(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    prime_mover_asset_id: int | None = None,
    tanker_asset_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    user: User = Depends(require_permission("prime_mover_tanker_links:read")),
    db: Session = Depends(get_db),
):
    query = _filtered_links(
        db,
        user,
        search=search,
        status=status,
        prime_mover_asset_id=prime_mover_asset_id,
        tanker_asset_id=tanker_asset_id,
        date_from=date_from,
        date_to=date_to,
    ).order_by(
        PrimeMoverTankerLink.status.asc(),
        PrimeMoverTankerLink.linked_from.desc(),
        PrimeMoverTankerLink.id.desc(),
    )
    result = paginate_query(query, page=page, page_size=page_size)
    result["items"] = [prime_mover_tanker_link_to_dict(item) for item in result["items"]]
    return result


@router.get("/options")
def link_options(
    user: User = Depends(require_permission("prime_mover_tanker_links:read")),
    db: Session = Depends(get_db),
):
    """Assets offered by the link form: Active, visible, correct type."""
    visible = _visible_asset_ids(db, user)

    def _asset_rows(asset_type_code: str) -> list[dict]:
        query = db.query(Asset).filter(
            Asset.asset_type_code == asset_type_code,
            Asset.status == STATUS_ACTIVE,
        )
        if visible is not None:
            query = query.filter(Asset.id.in_(sorted(visible)) if visible else Asset.id.is_(None))
        return [
            {
                "id": asset.id,
                "asset_code": asset.asset_code,
                "asset_name": asset.asset_name,
                "chassis_number": asset.serial_number or "",
                "asset_scope": asset.asset_scope,
            }
            for asset in query.order_by(Asset.asset_code.asc()).all()
        ]

    return {
        "prime_movers": _asset_rows(PRIME_MOVER),
        "tankers": _asset_rows(TANKER_TRAILER),
        "statuses": [STATUS_ACTIVE, STATUS_INACTIVE],
        "prime_mover_type": get_asset_type(PRIME_MOVER),
        "tanker_type": get_asset_type(TANKER_TRAILER),
    }


def _current_link_response(db: Session, user: User, asset_id: int, asset_type_code: str, column):
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.asset_type_code == asset_type_code)
        .first()
    )
    visible = _visible_asset_ids(db, user)
    if asset is None or (visible is not None and asset.id not in visible):
        return {"has_active_link": False, "link": None}
    query, _, _ = _link_query(db, user)
    link = (
        query.filter(column == asset_id, PrimeMoverTankerLink.status == STATUS_ACTIVE)
        .order_by(PrimeMoverTankerLink.linked_from.desc(), PrimeMoverTankerLink.id.desc())
        .first()
    )
    return {
        "has_active_link": link is not None,
        "link": prime_mover_tanker_link_to_dict(link) if link else None,
    }


@router.get("/current-by-prime-mover/{asset_id}")
def current_by_prime_mover(
    asset_id: int,
    user: User = Depends(require_permission("prime_mover_tanker_links:read")),
    db: Session = Depends(get_db),
):
    return _current_link_response(
        db, user, asset_id, PRIME_MOVER, PrimeMoverTankerLink.prime_mover_asset_id
    )


@router.get("/current-by-tanker/{asset_id}")
def current_by_tanker(
    asset_id: int,
    user: User = Depends(require_permission("prime_mover_tanker_links:read")),
    db: Session = Depends(get_db),
):
    return _current_link_response(
        db, user, asset_id, TANKER_TRAILER, PrimeMoverTankerLink.tanker_asset_id
    )


@router.get("/export")
def export_links(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status: str | None = None,
    prime_mover_asset_id: int | None = None,
    tanker_asset_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("prime_mover_tanker_links:read")),
    db: Session = Depends(get_db),
):
    records = (
        _filtered_links(
            db,
            actor,
            search=search,
            status=status,
            prime_mover_asset_id=prime_mover_asset_id,
            tanker_asset_id=tanker_asset_id,
            date_from=date_from,
            date_to=date_to,
        )
        .order_by(
            PrimeMoverTankerLink.status.asc(),
            PrimeMoverTankerLink.linked_from.desc(),
            PrimeMoverTankerLink.id.desc(),
        )
        .limit(MAX_EXPORT_ROWS)
        .all()
    )
    headers = [
        "Prime mover code",
        "Prime mover chassis",
        "Tanker code",
        "Tanker chassis",
        "Linked from",
        "Linked to",
        "Status",
        "Remarks",
        "Created",
    ]
    rows = []
    for link in records:
        item = prime_mover_tanker_link_to_dict(link)
        rows.append(
            [
                item["prime_mover_asset_code"],
                item["prime_mover_chassis_number"],
                item["tanker_asset_code"],
                item["tanker_chassis_number"],
                item["linked_from"] or "",
                item["linked_to"] or "Open",
                item["status"],
                item["remarks"],
                item["created_at"],
            ]
        )
    filters_summary = "; ".join(
        part
        for part in (
            f"search={search}" if search else "",
            f"status={status}" if status else "",
            f"prime_mover_id={prime_mover_asset_id}" if prime_mover_asset_id is not None else "",
            f"tanker_id={tanker_asset_id}" if tanker_asset_id is not None else "",
            f"from={date_from}" if date_from else "",
            f"to={date_to}" if date_to else "",
        )
        if part
    ) or "no filters"
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Export Prime Mover-Tanker Links",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Prime mover-tanker links exported as {format.upper()}",
        details_summary=f"format={format}; rows={len(rows)}; {filters_summary}",
    )
    db.commit()
    if format == "xlsx":
        return xlsx_response(
            "prime-mover-tanker-links",
            "Prime Mover-Tanker Link",
            headers,
            rows,
            [18, 20, 18, 20, 16, 16, 12, 40, 22],
        )
    if format == "pdf":
        return pdf_response(
            "prime-mover-tanker-links",
            "Prime Mover-Tanker Link",
            headers,
            rows,
            [20, 22, 20, 22, 18, 18, 14, 40, 24],
            filters_summary=filters_summary,
        )
    return csv_response("prime-mover-tanker-links", headers, rows)


# ---------------------------------------------------------------------------
# Import (preview, then commit)
# ---------------------------------------------------------------------------
@router.post("/import")
def import_links(
    request: Request,
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    actor: User = Depends(require_permission("prime_mover_tanker_links:create")),
    db: Session = Depends(get_db),
):
    """Preview then commit a link register.

    A row matches an existing link on prime mover + tanker + linked-from date.
    A match is updated, otherwise the row creates a new link. Every row is
    validated against the same rules as the form, including the one-active-link
    rule across the whole file and the existing register.
    """
    from app.services.master_import import read_master_import

    try:
        table = read_master_import(file.file.read(), file.filename or "")
    except ValueError as exc:
        preview = {
            "filename": file.filename or "",
            "format": "",
            "total_rows": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "columns_detected": [],
            "missing_columns": [],
            "rows": [],
            "message": str(exc),
        }
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Preview Prime Mover-Tanker Link Import",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            remarks=f"Link import preview failed for {file.filename or 'upload'}",
            details_summary=str(exc),
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=preview)

    rows_source = []
    for raw in table["rows"]:
        row = dict(raw)
        for alias, canonical in _IMPORT_ALIASES.items():
            if canonical not in row and alias in row:
                row[canonical] = row[alias]
        rows_source.append(row)
    columns = set(table["columns"])
    for alias, canonical in _IMPORT_ALIASES.items():
        if alias in columns:
            columns.add(canonical)
    required = {"prime_mover_code", "tanker_code", "linked_from"}
    missing = sorted(required - columns)

    visible = _visible_asset_ids(db, actor)
    admin = is_admin_user(actor, db)
    assets_by_code = {}
    for asset in db.query(Asset).all():
        assets_by_code[asset.asset_code.strip().upper()] = asset

    existing_links = (
        db.query(PrimeMoverTankerLink)
        .order_by(PrimeMoverTankerLink.id.asc())
        .all()
    )
    existing_by_key = {}
    for link in existing_links:
        key = (link.prime_mover_asset_id, link.tanker_asset_id, link.linked_from)
        existing_by_key.setdefault(key, link)

    prepared = []
    for raw in rows_source:
        errors: list[str] = []
        pm_code = str(raw.get("prime_mover_code", "")).strip().upper()
        tk_code = str(raw.get("tanker_code", "")).strip().upper()
        status = str(raw.get("status", "") or "Active").strip().title() or "Active"
        remarks = str(raw.get("remarks", "") or "").strip()
        from_text = str(raw.get("linked_from", "") or "")
        to_text = str(raw.get("linked_to", "") or "")
        linked_from = parse_import_date(from_text)
        linked_to = parse_import_date(to_text) if to_text.strip() else None

        if not pm_code:
            errors.append("Prime mover code is required")
        if not tk_code:
            errors.append("Tanker code is required")
        if not from_text.strip():
            errors.append("Linked-from date is required")
        elif linked_from is None:
            errors.append("Linked-from date must be a valid date")
        if to_text.strip() and linked_to is None:
            errors.append("Linked-to date must be a valid date")
        if status not in {STATUS_ACTIVE, STATUS_INACTIVE}:
            errors.append("Status must be Active or Inactive")
        if linked_from and linked_to and linked_to < linked_from:
            errors.append("Linked-to date cannot be before the linked-from date")

        pm_asset = assets_by_code.get(pm_code) if pm_code else None
        tk_asset = assets_by_code.get(tk_code) if tk_code else None
        if pm_code and (pm_asset is None or (visible is not None and pm_asset.id not in visible)):
            errors.append(f"Prime mover code not found: {pm_code}")
            pm_asset = None
        elif pm_asset is not None and pm_asset.asset_type_code != PRIME_MOVER:
            errors.append(f"{pm_code} is not a Prime Mover asset")
        if tk_code and (tk_asset is None or (visible is not None and tk_asset.id not in visible)):
            errors.append(f"Tanker code not found: {tk_code}")
            tk_asset = None
        elif tk_asset is not None and tk_asset.asset_type_code != TANKER_TRAILER:
            errors.append(f"{tk_code} is not a Tanker Trailer asset")
        if pm_asset is not None and tk_asset is not None and pm_asset.id == tk_asset.id:
            errors.append("A prime mover and a tanker trailer must be two different assets")
        if status == STATUS_ACTIVE:
            if pm_asset is not None and pm_asset.status != STATUS_ACTIVE:
                errors.append(f"Prime mover {pm_code} is Inactive")
            if tk_asset is not None and tk_asset.status != STATUS_ACTIVE:
                errors.append(f"Tanker {tk_code} is Inactive")
        if (
            (pm_asset is not None and pm_asset.asset_scope == "Global")
            or (tk_asset is not None and tk_asset.asset_scope == "Global")
        ) and not admin:
            errors.append("Only an administrator can import a link involving a Global asset")

        match = None
        if pm_asset is not None and tk_asset is not None and linked_from is not None:
            match = existing_by_key.get((pm_asset.id, tk_asset.id, linked_from))
        action = "Update" if match is not None else "Create"

        prepared.append(
            {
                "row_number": raw["row_number"],
                "prime_mover_code": pm_code,
                "tanker_code": tk_code,
                "linked_from": linked_from,
                "linked_to": linked_to,
                "status": status,
                "remarks": remarks,
                "action": action,
                "prime_mover_asset_id": pm_asset.id if pm_asset else None,
                "tanker_asset_id": tk_asset.id if tk_asset else None,
                "match_id": match.id if match else None,
                "errors": errors,
            }
        )

    # Active-link rule across the file and the register. Only rows that end up
    # Active take part, and an updated row is compared with the other links, not
    # with its own stored copy.
    # Index the register's active links once, so each row is an O(1) lookup.
    register_active_pm: dict[int, set[int]] = {}
    register_active_tk: dict[int, set[int]] = {}
    for other in existing_links:
        if other.status != STATUS_ACTIVE:
            continue
        register_active_pm.setdefault(other.prime_mover_asset_id, set()).add(other.id)
        register_active_tk.setdefault(other.tanker_asset_id, set()).add(other.id)

    file_active_pm: set[int] = set()
    file_active_tk: set[int] = set()
    for row in prepared:
        if row["status"] != STATUS_ACTIVE or row["prime_mover_asset_id"] is None:
            continue
        pm_id = row["prime_mover_asset_id"]
        tk_id = row["tanker_asset_id"]
        if pm_id in file_active_pm:
            row["errors"].append(
                f"Prime mover {row['prime_mover_code']} is linked Active twice in this file"
            )
        if tk_id in file_active_tk:
            row["errors"].append(
                f"Tanker {row['tanker_code']} is linked Active twice in this file"
            )
        file_active_pm.add(pm_id)
        file_active_tk.add(tk_id)
        # A row that matches a stored link is compared with the other links only.
        others_pm = register_active_pm.get(pm_id, set()) - {row["match_id"]}
        others_tk = register_active_tk.get(tk_id, set()) - {row["match_id"]}
        if others_pm:
            row["errors"].append(
                f"Prime mover {row['prime_mover_code']} already has an active link"
            )
        if others_tk:
            row["errors"].append(f"Tanker {row['tanker_code']} already has an active link")

    preview_rows = [
        {
            "row_number": row["row_number"],
            "prime_mover_code": row["prime_mover_code"],
            "tanker_code": row["tanker_code"],
            "linked_from": row["linked_from"].isoformat() if row["linked_from"] else "",
            "linked_to": row["linked_to"].isoformat() if row["linked_to"] else "",
            "status": row["status"],
            "remarks": row["remarks"],
            "action": row["action"],
            "valid": not row["errors"],
            "errors": row["errors"],
        }
        for row in prepared
    ]
    total = len(prepared)
    valid = sum(1 for row in preview_rows if row["valid"])
    preview = {
        "filename": table["filename"],
        "format": table["format"],
        "total_rows": total,
        "valid_rows": valid,
        "invalid_rows": total - valid,
        "columns_detected": table["columns"],
        "missing_columns": missing,
        "rows": preview_rows,
        "message": (
            "Missing required columns: " + ", ".join(missing)
            if missing
            else f"{valid} row(s) ready to import" if valid
            else "No valid rows to import"
        ),
    }
    if missing or total == 0:
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Preview Prime Mover-Tanker Link Import",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            remarks=f"Link import preview rejected for {table['filename']}",
            details_summary=f"file={table['filename']}; missing={', '.join(missing) or 'none'}",
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=preview)
    if not confirm:
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Preview Prime Mover-Tanker Link Import",
            category="Import",
            current_user=actor,
            request=request,
            remarks=f"Link import previewed from {table['filename']}",
            details_summary=(
                f"file={table['filename']}; rows={total}; valid={valid}; invalid={total - valid}"
            ),
        )
        db.commit()
        return preview
    if preview["invalid_rows"] or not valid:
        preview["message"] = "Fix every row error before importing."
        create_audit_log(
            db,
            module_name=MODULE_NAME,
            action="Import Prime Mover-Tanker Links",
            category="Import",
            outcome="Failure",
            current_user=actor,
            request=request,
            remarks=f"Link import rejected for {table['filename']}",
            details_summary=f"file={table['filename']}; invalid={total - valid}",
            status_code=422,
        )
        db.commit()
        return JSONResponse(status_code=422, content=preview)

    created = updated = 0
    for row in prepared:
        values = {
            "prime_mover_asset_id": row["prime_mover_asset_id"],
            "tanker_asset_id": row["tanker_asset_id"],
            "linked_from": row["linked_from"],
            "linked_to": row["linked_to"],
            "remarks": clean_optional_text(row["remarks"]),
            "status": row["status"],
        }
        if row["match_id"] is not None:
            link = db.get(PrimeMoverTankerLink, row["match_id"])
            _apply_link_fields(link, values)
            link.updated_by_user_id = actor.id
            link.updated_at = utcnow()
            updated += 1
        else:
            link = PrimeMoverTankerLink(
                **values,
                created_by_user_id=actor.id,
                updated_by_user_id=actor.id,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(link)
            created += 1
        db.flush()
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Import Prime Mover-Tanker Links",
        category="Import",
        current_user=actor,
        request=request,
        remarks=f"Link import committed from {table['filename']}",
        details_summary=(
            f"file={table['filename']}; rows={total}; created={created}; updated={updated}"
        ),
        status_code=201,
    )
    db.commit()
    preview["imported"] = valid
    preview["created"] = created
    preview["updated"] = updated
    preview["message"] = f"{valid} link(s) imported ({created} created, {updated} updated)"
    return preview


# ---------------------------------------------------------------------------
# Create, read, update, close, delete
# ---------------------------------------------------------------------------
@router.post("", status_code=201)
def create_link(
    payload: PrimeMoverTankerLinkCreate,
    request: Request,
    actor: User = Depends(require_permission("prime_mover_tanker_links:create")),
    db: Session = Depends(get_db),
):
    prime_mover, tanker = _validate_link(
        db,
        actor,
        prime_mover_asset_id=payload.prime_mover_asset_id,
        tanker_asset_id=payload.tanker_asset_id,
        linked_from=payload.linked_from,
        linked_to=payload.linked_to,
        status=payload.status,
    )
    link = PrimeMoverTankerLink(
        prime_mover_asset_id=prime_mover.id,
        tanker_asset_id=tanker.id,
        linked_from=payload.linked_from,
        linked_to=payload.linked_to,
        remarks=clean_optional_text(payload.remarks),
        status=payload.status,
        created_by_user_id=actor.id,
        updated_by_user_id=actor.id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(link)
    db.flush()
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Create Prime Mover-Tanker Link",
        current_user=actor,
        request=request,
        entity_type="PrimeMoverTankerLink",
        entity_id=link.id,
        entity_label=f"{prime_mover.asset_code} -> {tanker.asset_code}",
        remarks="Prime mover linked to tanker trailer",
        details_summary=(
            f"prime_mover={prime_mover.asset_code}; tanker={tanker.asset_code}; "
            f"from={link.linked_from}; to={link.linked_to or 'open'}"
        ),
        new_status=link.status,
        status_code=201,
    )
    db.commit()
    return prime_mover_tanker_link_to_dict(_get_link(db, actor, link.id))


@router.get("/{link_id}")
def get_link(
    link_id: int,
    user: User = Depends(require_permission("prime_mover_tanker_links:read")),
    db: Session = Depends(get_db),
):
    return prime_mover_tanker_link_to_dict(_get_link(db, user, link_id))


@router.put("/{link_id}")
def update_link(
    link_id: int,
    payload: PrimeMoverTankerLinkUpdate,
    request: Request,
    actor: User = Depends(require_permission("prime_mover_tanker_links:update")),
    db: Session = Depends(get_db),
):
    link = _get_link(db, actor, link_id)
    before = {
        "prime_mover_asset_id": link.prime_mover_asset_id,
        "tanker_asset_id": link.tanker_asset_id,
        "linked_from": link.linked_from,
        "linked_to": link.linked_to,
        "remarks": link.remarks,
        "status": link.status,
    }
    old_status = link.status
    merged = {
        "prime_mover_asset_id": (
            payload.prime_mover_asset_id
            if payload.prime_mover_asset_id is not None
            else link.prime_mover_asset_id
        ),
        "tanker_asset_id": (
            payload.tanker_asset_id if payload.tanker_asset_id is not None else link.tanker_asset_id
        ),
        "linked_from": payload.linked_from if payload.linked_from is not None else link.linked_from,
        "linked_to": payload.linked_to if payload.linked_to is not None else link.linked_to,
        "remarks": (
            clean_optional_text(payload.remarks) if payload.remarks is not None else link.remarks
        ),
        "status": payload.status or link.status,
    }
    prime_mover, tanker = _validate_link(
        db,
        actor,
        prime_mover_asset_id=merged["prime_mover_asset_id"],
        tanker_asset_id=merged["tanker_asset_id"],
        linked_from=merged["linked_from"],
        linked_to=merged["linked_to"],
        status=merged["status"],
        exclude_id=link.id,
    )
    _apply_link_fields(link, merged)
    link.updated_by_user_id = actor.id
    link.updated_at = utcnow()

    changes = []
    for key, label in (
        ("prime_mover_asset_id", "prime mover"),
        ("tanker_asset_id", "tanker"),
        ("linked_from", "linked from"),
        ("linked_to", "linked to"),
        ("status", "status"),
    ):
        if before[key] != merged[key]:
            changes.append(f"{label}: {before[key] or 'open'} -> {merged[key] or 'open'}")
    if before["remarks"] != merged["remarks"]:
        changes.append("remarks updated")
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Update Prime Mover-Tanker Link",
        current_user=actor,
        request=request,
        entity_type="PrimeMoverTankerLink",
        entity_id=link.id,
        entity_label=f"{prime_mover.asset_code} -> {tanker.asset_code}",
        remarks="Prime mover-tanker link updated",
        details_summary="; ".join(changes) or "no field changes",
        old_status=old_status,
        new_status=link.status,
    )
    db.commit()
    return prime_mover_tanker_link_to_dict(_get_link(db, actor, link.id))


@router.post("/{link_id}/close")
def close_link(
    link_id: int,
    payload: PrimeMoverTankerLinkClose,
    request: Request,
    actor: User = Depends(require_permission("prime_mover_tanker_links:update")),
    db: Session = Depends(get_db),
):
    """End an active link. The end date defaults to today; remarks are appended."""
    link = _get_link(db, actor, link_id)
    if link.status != STATUS_ACTIVE:
        raise HTTPException(status_code=409, detail="This link is already closed")
    linked_to = payload.linked_to or utcnow().date()
    if linked_to < link.linked_from:
        raise HTTPException(
            status_code=422,
            detail="The linked-to date cannot be before the linked-from date",
        )
    close_remark = clean_optional_text(payload.remarks)
    if close_remark:
        note = f"Close Remarks: {close_remark}"
        link.remarks = f"{link.remarks}\n{note}" if link.remarks else note
    old_status = link.status
    link.linked_to = linked_to
    link.status = STATUS_INACTIVE
    link.updated_by_user_id = actor.id
    link.updated_at = utcnow()
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Close Prime Mover-Tanker Link",
        current_user=actor,
        request=request,
        entity_type="PrimeMoverTankerLink",
        entity_id=link.id,
        entity_label=_link_label(link),
        remarks="Prime mover-tanker link closed",
        details_summary=f"linked_to={linked_to}; {close_remark or 'no close remarks'}",
        old_status=old_status,
        new_status=link.status,
    )
    db.commit()
    return prime_mover_tanker_link_to_dict(_get_link(db, actor, link.id))


@router.delete("/{link_id}")
def delete_link(
    link_id: int,
    request: Request,
    actor: User = Depends(require_permission("prime_mover_tanker_links:delete")),
    db: Session = Depends(get_db),
):
    """Permanently remove a link. The snapshot is kept in the audit trail."""
    link = _get_link(db, actor, link_id)
    label = _link_label(link)
    snapshot = _snapshot(link)
    link_id_value = link.id
    db.delete(link)
    create_audit_log(
        db,
        module_name=MODULE_NAME,
        action="Delete Prime Mover-Tanker Link",
        current_user=actor,
        request=request,
        entity_type="PrimeMoverTankerLink",
        entity_id=link_id_value,
        entity_label=label,
        remarks="Prime mover-tanker link deleted",
        details_summary=snapshot,
    )
    db.commit()
    return {"deleted": True, "id": link_id_value}
