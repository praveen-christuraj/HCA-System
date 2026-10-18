"""Extended System & Administration APIs:
  1. System Notification Master (/api/system-notifications) — targeted notifications, popups, acknowledgements, delivery reports
  2. Read-Only Database Browser (/api/database-browser) — schema inspector, paginated row viewer with sensitive field masking, export
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import inspect, or_, text
from sqlalchemy.orm import Session

from app.config import MAX_EXPORT_ROWS
from app.database import engine, get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import get_user_location_ids, require_permission
from app.models import (
    Location,
    Role,
    SystemNotification,
    SystemNotificationReceipt,
    SystemNotificationTargetLocation,
    SystemNotificationTargetRole,
    SystemNotificationTargetUser,
    User,
)
from app.services.audit_service import create_audit_log
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.helpers import display_name
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(tags=["System & Administration Extended"])

SENSITIVE_COLUMN_NAMES = {
    "password_hash",
    "totp_secret",
    "totp_backup_codes",
    "token_hash",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ===========================================================================
# 1. System Notification Master
# ===========================================================================
class SystemNotificationPayload(StrictModel):
    title: str = Field(min_length=2, max_length=200)
    message: str = Field(min_length=2, max_length=4000)
    notification_type: str = Field(default="Info", max_length=30)
    priority: Literal["Low", "Normal", "High", "Critical"] = "Normal"
    target_scope: Literal["All Users", "Roles", "Locations", "Specific Users"] = "All Users"
    delivery_mode: str = Field(default="Banner + Inbox", max_length=30)
    requires_acknowledgement: bool = False
    popup_enabled: bool = False
    banner_enabled: bool = True
    display_from: datetime | None = None
    display_until: datetime | None = None
    status: Literal["Draft", "Published", "Archived", "Active", "Inactive"] = "Published"
    deactivation_reason: str | None = Field(default=None, max_length=2000)
    role_ids: list[int] = Field(default_factory=list)
    user_ids: list[int] = Field(default_factory=list)
    location_codes: list[str] = Field(default_factory=list)


def _resolve_target_users(db: Session, notif: SystemNotification) -> list[User]:
    q = db.query(User).filter(User.status == "Active")
    scope = notif.target_scope
    if scope == "All Users":
        return q.all()
    if scope == "Specific Users":
        uids = [t.user_id for t in notif.target_users]
        return q.filter(User.id.in_(uids)).all() if uids else []
    if scope == "Roles":
        rids = {t.role_id for t in notif.target_roles}
        users = q.all()
        return [u for u in users if any(ur.role_id in rids for ur in u.user_roles)]
    if scope == "Locations":
        lcodes = {t.location_code.upper() for t in notif.target_locations}
        loc_ids = {
            loc_id
            for (loc_id,) in db.query(Location.id).filter(Location.location_code.in_(lcodes)).all()
        }
        users = q.all()
        matched = []
        for u in users:
            u_locs = get_user_location_ids(db, u)
            if u_locs is None or bool(u_locs & loc_ids):
                matched.append(u)
        return matched
    return q.all()


def _sync_notification_receipts(db: Session, notif: SystemNotification) -> None:
    if notif.status not in ("Published", "Active"):
        return
    targets = _resolve_target_users(db, notif)
    existing_uids = {r.user_id for r in notif.receipts}
    now = utcnow()
    for u in targets:
        if u.id not in existing_uids:
            db.add(
                SystemNotificationReceipt(
                    notification_id=notif.id,
                    user_id=u.id,
                    username=u.username,
                    status="Unread",
                    delivered_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
    db.flush()


def _serialize_notification(row: SystemNotification, current_user_id: int | None = None) -> dict:
    total_receipts = len(row.receipts)
    read_count = sum(1 for r in row.receipts if r.first_seen_at is not None or r.status in ("Read", "Acknowledged"))
    ack_count = sum(1 for r in row.receipts if r.acknowledged_at is not None or r.status == "Acknowledged")
    my_receipt = next((r for r in row.receipts if r.user_id == current_user_id), None) if current_user_id else None
    return {
        "id": row.id,
        "notification_number": row.notification_number,
        "notification_code": row.notification_number,
        "title": row.title,
        "message": row.message,
        "notification_type": row.notification_type,
        "category": row.notification_type,
        "priority": row.priority,
        "target_scope": row.target_scope,
        "delivery_mode": row.delivery_mode,
        "requires_acknowledgement": bool(row.requires_acknowledgement),
        "popup_enabled": bool(row.popup_enabled),
        "banner_enabled": bool(row.banner_enabled),
        "display_from": row.display_from,
        "display_until": row.display_until,
        "published_at": row.published_at,
        "status": row.status,
        "created_by_display": row.created_by_display or "",
        "deactivation_reason": row.deactivation_reason or "",
        "role_ids": [t.role_id for t in row.target_roles],
        "user_ids": [t.user_id for t in row.target_users],
        "location_codes": [t.location_code for t in row.target_locations],
        "total_recipients": total_receipts,
        "read_count": read_count,
        "acknowledged_count": ack_count,
        "my_receipt": (
            {
                "id": my_receipt.id,
                "status": my_receipt.status,
                "delivered_at": my_receipt.delivered_at,
                "first_seen_at": my_receipt.first_seen_at,
                "acknowledged_at": my_receipt.acknowledged_at,
            }
            if my_receipt
            else None
        ),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/system-notifications")
def list_system_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    notification_type: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("system_notifications:read")),
    db: Session = Depends(get_db),
):
    q = db.query(SystemNotification)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                SystemNotification.notification_number.ilike(term),
                SystemNotification.title.ilike(term),
                SystemNotification.message.ilike(term),
            )
        )
    if notification_type:
        q = q.filter(SystemNotification.notification_type == notification_type)
    if priority:
        q = q.filter(SystemNotification.priority == priority)
    if status:
        q = q.filter(SystemNotification.status == status)
    if date_from:
        q = q.filter(SystemNotification.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        q = q.filter(SystemNotification.created_at <= datetime.combine(date_to, time.max))

    result = paginate_query(q.order_by(SystemNotification.id.desc()), page=page, page_size=page_size)
    result["items"] = [_serialize_notification(r, actor.id) for r in result["items"]]
    return result


@router.get("/system-notifications/my")
def list_my_notifications(
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    receipts = (
        db.query(SystemNotificationReceipt)
        .filter(SystemNotificationReceipt.user_id == actor.id)
        .order_by(SystemNotificationReceipt.id.desc())
        .limit(50)
        .all()
    )
    items = []
    for rec in receipts:
        n = rec.notification
        if not n or n.status not in ("Published", "Active"):
            continue
        items.append(_serialize_notification(n, actor.id))
    return {"items": items, "unread_count": sum(1 for i in items if i["my_receipt"]["status"] == "Unread")}


@router.get("/system-notifications/delivery-report")
def notification_delivery_report(
    notification_id: int | None = None,
    actor: User = Depends(require_permission("system_notifications:read")),
    db: Session = Depends(get_db),
):
    q = db.query(SystemNotificationReceipt)
    if notification_id:
        q = q.filter(SystemNotificationReceipt.notification_id == notification_id)
    rows = q.order_by(SystemNotificationReceipt.id.desc()).limit(500).all()
    items = []
    for r in rows:
        u = db.get(User, r.user_id)
        items.append(
            {
                "id": r.id,
                "notification_id": r.notification_id,
                "notification_number": r.notification.notification_number if r.notification else "",
                "title": r.notification.title if r.notification else "",
                "user_id": r.user_id,
                "username": r.username,
                "full_name": display_name(u) if u else r.username,
                "status": r.status,
                "delivered_at": r.delivered_at,
                "first_seen_at": r.first_seen_at,
                "acknowledged_at": r.acknowledged_at,
                "acknowledgement_remarks": r.acknowledgement_remarks or "",
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/system-notifications/export")
def export_system_notifications(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    actor: User = Depends(require_permission("system_notifications:read")),
    db: Session = Depends(get_db),
):
    records = db.query(SystemNotification).order_by(SystemNotification.id.desc()).limit(MAX_EXPORT_ROWS).all()
    headers = [
        "Notification #",
        "Title",
        "Type",
        "Priority",
        "Target Scope",
        "Delivery Mode",
        "Status",
        "Recipients",
        "Acknowledged",
    ]
    rows = []
    for r in records:
        s = _serialize_notification(r)
        rows.append(
            [
                s["notification_number"],
                s["title"],
                s["notification_type"],
                s["priority"],
                s["target_scope"],
                s["delivery_mode"],
                s["status"],
                s["total_recipients"],
                s["acknowledged_count"],
            ]
        )
    create_audit_log(
        db,
        module_name="System Notifications",
        action="Export System Notifications",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} notifications as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("system-notifications", headers, rows)
    if format == "xlsx":
        return xlsx_response("system-notifications", "Notifications", headers, rows)
    return pdf_response("system-notifications", "System Notification Master", headers, rows)


def _apply_notification_targets(db: Session, row: SystemNotification, payload: SystemNotificationPayload) -> None:
    db.query(SystemNotificationTargetRole).filter(SystemNotificationTargetRole.notification_id == row.id).delete()
    db.query(SystemNotificationTargetUser).filter(SystemNotificationTargetUser.notification_id == row.id).delete()
    db.query(SystemNotificationTargetLocation).filter(SystemNotificationTargetLocation.notification_id == row.id).delete()
    db.flush()
    for rid in sorted(set(payload.role_ids)):
        if db.get(Role, rid):
            db.add(SystemNotificationTargetRole(notification_id=row.id, role_id=rid))
    for uid in sorted(set(payload.user_ids)):
        if db.get(User, uid):
            db.add(SystemNotificationTargetUser(notification_id=row.id, user_id=uid))
    for lcode in sorted(set(c.strip().upper() for c in payload.location_codes if c.strip())):
        db.add(SystemNotificationTargetLocation(notification_id=row.id, location_code=lcode))
    db.flush()
    db.refresh(row)
    _sync_notification_receipts(db, row)


@router.post("/system-notifications", status_code=201)
def create_system_notification(
    payload: SystemNotificationPayload,
    request: Request,
    actor: User = Depends(require_permission("system_notifications:create")),
    db: Session = Depends(get_db),
):
    seq = db.query(SystemNotification).count() + 1
    code = f"NTF-{utcnow().strftime('%Y%m')}-{seq:04d}"
    while db.query(SystemNotification).filter(SystemNotification.notification_number == code).first():
        seq += 1
        code = f"NTF-{utcnow().strftime('%Y%m')}-{seq:04d}"

    now = utcnow()
    row = SystemNotification(
        notification_number=code,
        title=payload.title.strip(),
        message=payload.message.strip(),
        notification_type=payload.notification_type.strip(),
        priority=payload.priority,
        target_scope=payload.target_scope,
        delivery_mode=payload.delivery_mode,
        requires_acknowledgement=payload.requires_acknowledgement,
        popup_enabled=payload.popup_enabled,
        banner_enabled=payload.banner_enabled,
        display_from=payload.display_from,
        display_until=payload.display_until,
        status=payload.status,
        created_by_user_id=actor.id,
        created_by_display=display_name(actor),
        published_at=now if payload.status in ("Published", "Active") else None,
        published_by_user_id=actor.id if payload.status in ("Published", "Active") else None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    _apply_notification_targets(db, row, payload)

    create_audit_log(
        db,
        module_name="System Notifications",
        action="Create System Notification",
        category="Administration",
        current_user=actor,
        entity_type="SystemNotification",
        entity_id=row.id,
        entity_label=row.notification_number,
        new_status=row.status,
        request=request,
        remarks=row.title,
        details_summary=f"code={row.notification_number}; scope={row.target_scope}; priority={row.priority}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_notification(row, actor.id)


@router.put("/system-notifications/{notification_id}")
def update_system_notification(
    notification_id: int,
    payload: SystemNotificationPayload,
    request: Request,
    actor: User = Depends(require_permission("system_notifications:update")),
    db: Session = Depends(get_db),
):
    row = db.get(SystemNotification, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")

    old_status = row.status
    row.title = payload.title.strip()
    row.message = payload.message.strip()
    row.notification_type = payload.notification_type.strip()
    row.priority = payload.priority
    row.target_scope = payload.target_scope
    row.delivery_mode = payload.delivery_mode
    row.requires_acknowledgement = payload.requires_acknowledgement
    row.popup_enabled = payload.popup_enabled
    row.banner_enabled = payload.banner_enabled
    row.display_from = payload.display_from
    row.display_until = payload.display_until
    row.status = payload.status
    if payload.status in ("Published", "Active") and not row.published_at:
        row.published_at = utcnow()
        row.published_by_user_id = actor.id
    if payload.deactivation_reason:
        row.deactivation_reason = payload.deactivation_reason.strip()
    row.updated_at = utcnow()
    _apply_notification_targets(db, row, payload)

    create_audit_log(
        db,
        module_name="System Notifications",
        action="Update System Notification",
        category="Administration",
        current_user=actor,
        entity_type="SystemNotification",
        entity_id=row.id,
        entity_label=row.notification_number,
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks=row.title,
        details_summary=f"code={row.notification_number}; status={row.status}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_notification(row, actor.id)


@router.post("/system-notifications/{notification_id}/acknowledge")
def acknowledge_system_notification(
    notification_id: int,
    request: Request,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.get(SystemNotification, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    rec = (
        db.query(SystemNotificationReceipt)
        .filter(
            SystemNotificationReceipt.notification_id == row.id,
            SystemNotificationReceipt.user_id == actor.id,
        )
        .first()
    )
    now = utcnow()
    if rec is None:
        rec = SystemNotificationReceipt(
            notification_id=row.id,
            user_id=actor.id,
            username=actor.username,
            status="Acknowledged",
            delivered_at=now,
            first_seen_at=now,
            last_seen_at=now,
            acknowledged_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(rec)
    else:
        rec.status = "Acknowledged"
        rec.first_seen_at = rec.first_seen_at or now
        rec.last_seen_at = now
        rec.acknowledged_at = now
        rec.updated_at = now
    db.commit()
    request.state.audit_written = True
    return {"message": "Notification acknowledged", "notification_id": row.id}


@router.delete("/system-notifications/{notification_id}")
def delete_system_notification(
    notification_id: int,
    request: Request,
    actor: User = Depends(require_permission("system_notifications:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(SystemNotification, notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    code = row.notification_number
    db.delete(row)
    create_audit_log(
        db,
        module_name="System Notifications",
        action="Delete System Notification",
        category="Administration",
        current_user=actor,
        entity_type="SystemNotification",
        entity_id=notification_id,
        entity_label=code,
        old_status="Active",
        new_status="Deleted",
        request=request,
        remarks=f"Deleted notification {code}",
        details_summary=f"code={code}",
    )
    db.commit()
    request.state.audit_written = True
    return {"message": "Notification deleted"}


# ===========================================================================
# 2. Read-Only Database Browser
# ===========================================================================
def _mask_row_values(columns: list[str], row_mapping: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for col in columns:
        val = row_mapping.get(col)
        if col.lower() in SENSITIVE_COLUMN_NAMES and val is not None:
            out[col] = "********"
        elif isinstance(val, (datetime, date, time)):
            out[col] = val.isoformat()
        else:
            out[col] = val
    return out


@router.get("/database-browser/tables")
def list_database_tables(
    search: str | None = None,
    actor: User = Depends(require_permission("database_browser:read")),
    db: Session = Depends(get_db),
):
    inspector = inspect(engine)
    table_names = sorted(inspector.get_table_names())
    if search:
        term = search.strip().lower()
        table_names = [t for t in table_names if term in t.lower()]

    items = []
    for tname in table_names:
        cols = inspector.get_columns(tname)
        pks = inspector.get_pk_constraint(tname).get("constrained_columns", [])
        fks = inspector.get_foreign_keys(tname)
        try:
            row_count = int(db.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar() or 0)
        except Exception:
            row_count = 0
        items.append(
            {
                "table_name": tname,
                "column_count": len(cols),
                "row_count": row_count,
                "primary_keys": pks,
                "foreign_key_count": len(fks),
                "columns": [
                    {
                        "name": c["name"],
                        "type": str(c["type"]),
                        "nullable": bool(c.get("nullable", True)),
                        "is_primary_key": c["name"] in pks,
                        "is_sensitive": c["name"].lower() in SENSITIVE_COLUMN_NAMES,
                    }
                    for c in cols
                ],
            }
        )
    return {"items": items, "total_tables": len(items)}


@router.get("/database-browser/tables/{table_name}")
def browse_database_table(
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = None,
    actor: User = Depends(require_permission("database_browser:read")),
    db: Session = Depends(get_db),
):
    inspector = inspect(engine)
    valid_tables = set(inspector.get_table_names())
    if table_name not in valid_tables:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    cols_meta = inspector.get_columns(table_name)
    col_names = [c["name"] for c in cols_meta]
    pks = inspector.get_pk_constraint(table_name).get("constrained_columns", [])
    order_col = pks[0] if pks else col_names[0]

    where_sql = ""
    params: dict[str, Any] = {}
    if search and search.strip():
        searchable_cols = [
            c["name"]
            for c in cols_meta
            if c["name"].lower() not in SENSITIVE_COLUMN_NAMES
        ]
        if searchable_cols:
            clauses = [f'CAST("{c}" AS TEXT) LIKE :search_term' for c in searchable_cols]
            where_sql = " WHERE " + " OR ".join(clauses)
            params["search_term"] = f"%{search.strip()}%"

    total = int(
        db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"{where_sql}'), params).scalar() or 0
    )
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset
    raw_rows = db.execute(
        text(f'SELECT * FROM "{table_name}"{where_sql} ORDER BY "{order_col}" DESC LIMIT :limit OFFSET :offset'),
        params,
    ).mappings().all()

    items = [_mask_row_values(col_names, dict(r)) for r in raw_rows]
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "table_name": table_name,
        "columns": [
            {
                "name": c["name"],
                "type": str(c["type"]),
                "nullable": bool(c.get("nullable", True)),
                "is_primary_key": c["name"] in pks,
                "is_sensitive": c["name"].lower() in SENSITIVE_COLUMN_NAMES,
            }
            for c in cols_meta
        ],
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/database-browser/tables/{table_name}/export")
def export_database_table(
    table_name: str,
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    actor: User = Depends(require_permission("database_browser:read")),
    db: Session = Depends(get_db),
):
    inspector = inspect(engine)
    if table_name not in set(inspector.get_table_names()):
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    cols_meta = inspector.get_columns(table_name)
    col_names = [c["name"] for c in cols_meta]
    raw_rows = (
        db.execute(text(f'SELECT * FROM "{table_name}" LIMIT :lim'), {"lim": MAX_EXPORT_ROWS})
        .mappings()
        .all()
    )
    rows = []
    for r in raw_rows:
        masked = _mask_row_values(col_names, dict(r))
        rows.append([masked.get(c, "") for c in col_names])

    create_audit_log(
        db,
        module_name="Database Browser",
        action="Export Database Table",
        category="Export",
        current_user=actor,
        entity_type="Table",
        entity_label=table_name,
        request=request,
        remarks=f"Exported {len(rows)} rows from table {table_name} as {format.upper()}",
        details_summary=f"table={table_name}; format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response(f"db-{table_name}", col_names, rows)
    if format == "xlsx":
        return xlsx_response(f"db-{table_name}", table_name[:31], col_names, rows)
    return pdf_response(f"db-{table_name}", f"Database Table: {table_name}", col_names, rows)
