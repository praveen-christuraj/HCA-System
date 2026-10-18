"""Export Operations Suite API:
  - Dashboard KPIs & Block Permit Utilization
  - Export Locations, Entities, Blocks & Consignees Masters
  - Export Permits (quarterly allocation, auto-expiry, multi-block assignment)
  - Export Transactions (BL entry, multi-block expansion, permit limit check & override)
  - Export Reports & Settings
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import MAX_EXPORT_ROWS
from app.database import get_db
from app.dependencies.permissions import require_permission
from app.models import (
    ExportBlock,
    ExportConfig,
    ExportConsignee,
    ExportEntity,
    ExportEntityBlock,
    ExportLocation,
    ExportLocationEntity,
    ExportPermit,
    ExportPermitBlockAssignment,
    ExportTransaction,
    User,
)
from app.services.audit_service import create_audit_log
from app.utils.exporters import csv_response, pdf_response, xlsx_response
from app.utils.pagination import paginate_query
from app.utils.time import utcnow

router = APIRouter(prefix="/export-operations", tags=["Export Operations"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _f(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _quarter_from_date(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"Q{q}_{d.year}"


def _normalize_quarter(quarter: str, year: int | str | None = None) -> str:
    q = str(quarter or "").strip().upper()
    if "_" in q:
        return q
    if not q.startswith("Q"):
        q = f"Q{q}"
    y = year if year is not None else date.today().year
    return f"{q}_{y}"


def _quarter_end_date(quarter_code: str) -> date | None:
    text = str(quarter_code or "").strip().upper()
    if "_" not in text:
        return None
    q_part, y_part = text.split("_", 1)
    try:
        year = int(y_part)
    except ValueError:
        return None
    q_num = q_part.replace("Q", "")
    return {
        "1": date(year, 3, 31),
        "2": date(year, 6, 30),
        "3": date(year, 9, 30),
        "4": date(year, 12, 31),
    }.get(q_num)


def _expire_permits_if_needed(db: Session):
    today = date.today()
    active_permits = db.query(ExportPermit).filter(ExportPermit.status == "Active").all()
    changed = False
    for p in active_permits:
        end_d = p.expiry_date or _quarter_end_date(p.quarter)
        if end_d and today > end_d:
            p.status = "Expired"
            if not p.remarks:
                p.remarks = "Auto-expired after quarter ended"
            p.updated_at = utcnow()
            changed = True
    if changed:
        db.commit()


# ===========================================================================
# 1. Export Locations
# ===========================================================================
class ExportLocationPayload(StrictModel):
    location_code: str = Field(min_length=1, max_length=50)
    location_name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    entity_codes: list[str] = Field(default_factory=list)
    status: Literal["Active", "Inactive"] = "Active"


def _serialize_export_location(db: Session, row: ExportLocation) -> dict:
    entity_links = (
        db.query(ExportLocationEntity)
        .filter(
            ExportLocationEntity.location_code == row.location_code,
            ExportLocationEntity.status == "Active",
        )
        .all()
    )
    ecodes = [e.entity_code for e in entity_links]
    return {
        "id": row.id,
        "location_code": row.location_code,
        "location_name": row.location_name,
        "description": row.description or "",
        "entity_codes": ecodes,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/locations")
def list_export_locations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    q = db.query(ExportLocation)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(or_(ExportLocation.location_code.ilike(term), ExportLocation.location_name.ilike(term)))
    if status:
        q = q.filter(ExportLocation.status == status)
    result = paginate_query(q.order_by(ExportLocation.location_code.asc()), page=page, page_size=page_size)
    result["items"] = [_serialize_export_location(db, r) for r in result["items"]]
    return result


@router.post("/locations", status_code=201)
def create_export_location(
    payload: ExportLocationPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:create")),
    db: Session = Depends(get_db),
):
    code = payload.location_code.strip().upper()
    if db.query(ExportLocation).filter(func.upper(ExportLocation.location_code) == code).first():
        raise HTTPException(status_code=400, detail="Export location code already exists")
    row = ExportLocation(
        location_code=code,
        location_name=payload.location_name.strip(),
        description=(payload.description or "").strip() or None,
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    for ec in sorted({c.strip().upper() for c in payload.entity_codes if c.strip()}):
        db.add(ExportLocationEntity(location_code=code, entity_code=ec, status="Active", created_at=utcnow()))

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Create Export Location",
        category="Data Change",
        current_user=actor,
        entity_type="ExportLocation",
        entity_id=row.id,
        entity_label=f"{row.location_name} ({row.location_code})",
        new_status=row.status,
        request=request,
        remarks="Export location created",
        details_summary=f"code={row.location_code}; name={row.location_name}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_export_location(db, row)


@router.put("/locations/{loc_id}")
def update_export_location(
    loc_id: int,
    payload: ExportLocationPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:update")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportLocation, loc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export location not found")
    code = payload.location_code.strip().upper()
    old_code = row.location_code
    old_status = row.status
    row.location_code = code
    row.location_name = payload.location_name.strip()
    row.description = (payload.description or "").strip() or None
    row.status = payload.status
    row.updated_at = utcnow()

    db.query(ExportLocationEntity).filter(ExportLocationEntity.location_code == old_code).delete()
    for ec in sorted({c.strip().upper() for c in payload.entity_codes if c.strip()}):
        db.add(ExportLocationEntity(location_code=code, entity_code=ec, status="Active", created_at=utcnow()))

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Update Export Location",
        category="Data Change",
        current_user=actor,
        entity_type="ExportLocation",
        entity_id=row.id,
        entity_label=f"{row.location_name} ({row.location_code})",
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Export location updated",
        details_summary=f"code={row.location_code}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_export_location(db, row)


@router.delete("/locations/{loc_id}")
def delete_export_location(
    loc_id: int,
    request: Request,
    actor: User = Depends(require_permission("export_operations:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportLocation, loc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export location not found")
    db.query(ExportLocationEntity).filter(ExportLocationEntity.location_code == row.location_code).delete()
    create_audit_log(
        db,
        module_name="Export Operations",
        action="Delete Export Location",
        category="Data Change",
        current_user=actor,
        entity_type="ExportLocation",
        entity_id=row.id,
        entity_label=row.location_code,
        old_status=row.status,
        request=request,
        remarks="Export location deleted",
        details_summary=f"code={row.location_code}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Export location deleted successfully"}


# ===========================================================================
# 2. Export Entities
# ===========================================================================
class ExportEntityPayload(StrictModel):
    entity_code: str = Field(min_length=1, max_length=50)
    entity_name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    location_codes: list[str] = Field(default_factory=list)
    block_codes: list[str] = Field(default_factory=list)
    status: Literal["Active", "Inactive"] = "Active"


def _serialize_export_entity(db: Session, row: ExportEntity) -> dict:
    loc_links = (
        db.query(ExportLocationEntity)
        .filter(ExportLocationEntity.entity_code == row.entity_code, ExportLocationEntity.status == "Active")
        .all()
    )
    blk_links = (
        db.query(ExportEntityBlock)
        .filter(ExportEntityBlock.entity_code == row.entity_code, ExportEntityBlock.status == "Active")
        .all()
    )
    return {
        "id": row.id,
        "entity_code": row.entity_code,
        "entity_name": row.entity_name,
        "description": row.description or "",
        "location_codes": [l.location_code for l in loc_links],
        "block_codes": [b.block_code for b in blk_links],
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/entities")
def list_export_entities(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    q = db.query(ExportEntity)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(or_(ExportEntity.entity_code.ilike(term), ExportEntity.entity_name.ilike(term)))
    if status:
        q = q.filter(ExportEntity.status == status)
    if location_code:
        ecodes = (
            db.query(ExportLocationEntity.entity_code)
            .filter(func.upper(ExportLocationEntity.location_code) == location_code.strip().upper())
        )
        q = q.filter(ExportEntity.entity_code.in_(ecodes))
    result = paginate_query(q.order_by(ExportEntity.entity_code.asc()), page=page, page_size=page_size)
    result["items"] = [_serialize_export_entity(db, r) for r in result["items"]]
    return result


@router.post("/entities", status_code=201)
def create_export_entity(
    payload: ExportEntityPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:create")),
    db: Session = Depends(get_db),
):
    code = payload.entity_code.strip().upper()
    if db.query(ExportEntity).filter(func.upper(ExportEntity.entity_code) == code).first():
        raise HTTPException(status_code=400, detail="Export entity code already exists")
    row = ExportEntity(
        entity_code=code,
        entity_name=payload.entity_name.strip(),
        description=(payload.description or "").strip() or None,
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    for lc in sorted({c.strip().upper() for c in payload.location_codes if c.strip()}):
        db.add(ExportLocationEntity(location_code=lc, entity_code=code, status="Active", created_at=utcnow()))
    for bc in sorted({c.strip().upper() for c in payload.block_codes if c.strip()}):
        db.add(ExportEntityBlock(entity_code=code, block_code=bc, status="Active", created_at=utcnow()))

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Create Export Entity",
        category="Data Change",
        current_user=actor,
        entity_type="ExportEntity",
        entity_id=row.id,
        entity_label=f"{row.entity_name} ({row.entity_code})",
        new_status=row.status,
        request=request,
        remarks="Export entity created",
        details_summary=f"code={row.entity_code}; name={row.entity_name}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_export_entity(db, row)


@router.put("/entities/{entity_id}")
def update_export_entity(
    entity_id: int,
    payload: ExportEntityPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:update")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportEntity, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export entity not found")
    code = payload.entity_code.strip().upper()
    old_code = row.entity_code
    old_status = row.status
    row.entity_code = code
    row.entity_name = payload.entity_name.strip()
    row.description = (payload.description or "").strip() or None
    row.status = payload.status
    row.updated_at = utcnow()

    db.query(ExportLocationEntity).filter(ExportLocationEntity.entity_code == old_code).delete()
    db.query(ExportEntityBlock).filter(ExportEntityBlock.entity_code == old_code).delete()
    for lc in sorted({c.strip().upper() for c in payload.location_codes if c.strip()}):
        db.add(ExportLocationEntity(location_code=lc, entity_code=code, status="Active", created_at=utcnow()))
    for bc in sorted({c.strip().upper() for c in payload.block_codes if c.strip()}):
        db.add(ExportEntityBlock(entity_code=code, block_code=bc, status="Active", created_at=utcnow()))

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Update Export Entity",
        category="Data Change",
        current_user=actor,
        entity_type="ExportEntity",
        entity_id=row.id,
        entity_label=f"{row.entity_name} ({row.entity_code})",
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Export entity updated",
        details_summary=f"code={row.entity_code}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_export_entity(db, row)


@router.delete("/entities/{entity_id}")
def delete_export_entity(
    entity_id: int,
    request: Request,
    actor: User = Depends(require_permission("export_operations:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportEntity, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export entity not found")
    db.query(ExportLocationEntity).filter(ExportLocationEntity.entity_code == row.entity_code).delete()
    db.query(ExportEntityBlock).filter(ExportEntityBlock.entity_code == row.entity_code).delete()
    create_audit_log(
        db,
        module_name="Export Operations",
        action="Delete Export Entity",
        category="Data Change",
        current_user=actor,
        entity_type="ExportEntity",
        entity_id=row.id,
        entity_label=row.entity_code,
        old_status=row.status,
        request=request,
        remarks="Export entity deleted",
        details_summary=f"code={row.entity_code}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Export entity deleted successfully"}


# ===========================================================================
# 3. Export Blocks
# ===========================================================================
class ExportBlockPayload(StrictModel):
    block_code: str = Field(min_length=1, max_length=50)
    block_name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    entity_codes: list[str] = Field(default_factory=list)
    status: Literal["Active", "Inactive"] = "Active"


def _serialize_export_block(db: Session, row: ExportBlock) -> dict:
    ent_links = (
        db.query(ExportEntityBlock)
        .filter(ExportEntityBlock.block_code == row.block_code, ExportEntityBlock.status == "Active")
        .all()
    )
    return {
        "id": row.id,
        "block_code": row.block_code,
        "block_name": row.block_name,
        "description": row.description or "",
        "entity_codes": [e.entity_code for e in ent_links],
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/blocks")
def list_export_blocks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    entity_code: str | None = None,
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    q = db.query(ExportBlock)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(or_(ExportBlock.block_code.ilike(term), ExportBlock.block_name.ilike(term)))
    if status:
        q = q.filter(ExportBlock.status == status)
    if entity_code:
        bcodes = (
            db.query(ExportEntityBlock.block_code)
            .filter(func.upper(ExportEntityBlock.entity_code) == entity_code.strip().upper())
        )
        q = q.filter(ExportBlock.block_code.in_(bcodes))
    result = paginate_query(q.order_by(ExportBlock.block_code.asc()), page=page, page_size=page_size)
    result["items"] = [_serialize_export_block(db, r) for r in result["items"]]
    return result


@router.post("/blocks", status_code=201)
def create_export_block(
    payload: ExportBlockPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:create")),
    db: Session = Depends(get_db),
):
    code = payload.block_code.strip().upper()
    if db.query(ExportBlock).filter(func.upper(ExportBlock.block_code) == code).first():
        raise HTTPException(status_code=400, detail="Export block code already exists")
    row = ExportBlock(
        block_code=code,
        block_name=payload.block_name.strip(),
        description=(payload.description or "").strip() or None,
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    for ec in sorted({c.strip().upper() for c in payload.entity_codes if c.strip()}):
        db.add(ExportEntityBlock(entity_code=ec, block_code=code, status="Active", created_at=utcnow()))

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Create Export Block",
        category="Data Change",
        current_user=actor,
        entity_type="ExportBlock",
        entity_id=row.id,
        entity_label=f"{row.block_name} ({row.block_code})",
        new_status=row.status,
        request=request,
        remarks="Export block created",
        details_summary=f"code={row.block_code}; name={row.block_name}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_export_block(db, row)


@router.put("/blocks/{block_id}")
def update_export_block(
    block_id: int,
    payload: ExportBlockPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:update")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportBlock, block_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export block not found")
    code = payload.block_code.strip().upper()
    old_code = row.block_code
    old_status = row.status
    row.block_code = code
    row.block_name = payload.block_name.strip()
    row.description = (payload.description or "").strip() or None
    row.status = payload.status
    row.updated_at = utcnow()

    db.query(ExportEntityBlock).filter(ExportEntityBlock.block_code == old_code).delete()
    for ec in sorted({c.strip().upper() for c in payload.entity_codes if c.strip()}):
        db.add(ExportEntityBlock(entity_code=ec, block_code=code, status="Active", created_at=utcnow()))

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Update Export Block",
        category="Data Change",
        current_user=actor,
        entity_type="ExportBlock",
        entity_id=row.id,
        entity_label=f"{row.block_name} ({row.block_code})",
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Export block updated",
        details_summary=f"code={row.block_code}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_export_block(db, row)


@router.delete("/blocks/{block_id}")
def delete_export_block(
    block_id: int,
    request: Request,
    actor: User = Depends(require_permission("export_operations:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportBlock, block_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export block not found")
    db.query(ExportEntityBlock).filter(ExportEntityBlock.block_code == row.block_code).delete()
    create_audit_log(
        db,
        module_name="Export Operations",
        action="Delete Export Block",
        category="Data Change",
        current_user=actor,
        entity_type="ExportBlock",
        entity_id=row.id,
        entity_label=row.block_code,
        old_status=row.status,
        request=request,
        remarks="Export block deleted",
        details_summary=f"code={row.block_code}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Export block deleted successfully"}


# ===========================================================================
# 4. Export Consignees
# ===========================================================================
class ExportConsigneePayload(StrictModel):
    consignee_code: str = Field(min_length=1, max_length=50)
    consignee_name: str = Field(min_length=1, max_length=150)
    country: str | None = Field(default=None, max_length=100)
    contact_info: str | None = Field(default=None, max_length=200)
    status: Literal["Active", "Inactive"] = "Active"


def _serialize_consignee(row: ExportConsignee) -> dict:
    return {
        "id": row.id,
        "consignee_code": row.consignee_code,
        "consignee_name": row.consignee_name,
        "country": row.country or "",
        "contact_info": row.contact_info or "",
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/consignees")
def list_export_consignees(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    country: str | None = None,
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    q = db.query(ExportConsignee)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                ExportConsignee.consignee_code.ilike(term),
                ExportConsignee.consignee_name.ilike(term),
                ExportConsignee.country.ilike(term),
            )
        )
    if status:
        q = q.filter(ExportConsignee.status == status)
    if country:
        q = q.filter(ExportConsignee.country == country)
    result = paginate_query(q.order_by(ExportConsignee.consignee_code.asc()), page=page, page_size=page_size)
    result["items"] = [_serialize_consignee(r) for r in result["items"]]
    return result


@router.post("/consignees", status_code=201)
def create_export_consignee(
    payload: ExportConsigneePayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:create")),
    db: Session = Depends(get_db),
):
    code = payload.consignee_code.strip().upper()
    if db.query(ExportConsignee).filter(func.upper(ExportConsignee.consignee_code) == code).first():
        raise HTTPException(status_code=400, detail="Consignee code already exists")
    row = ExportConsignee(
        consignee_code=code,
        consignee_name=payload.consignee_name.strip(),
        country=(payload.country or "").strip() or None,
        contact_info=(payload.contact_info or "").strip() or None,
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    create_audit_log(
        db,
        module_name="Export Operations",
        action="Create Export Consignee",
        category="Data Change",
        current_user=actor,
        entity_type="ExportConsignee",
        entity_id=row.id,
        entity_label=f"{row.consignee_name} ({row.consignee_code})",
        new_status=row.status,
        request=request,
        remarks="Export consignee created",
        details_summary=f"code={row.consignee_code}; country={row.country or ''}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_consignee(row)


@router.put("/consignees/{consignee_id}")
def update_export_consignee(
    consignee_id: int,
    payload: ExportConsigneePayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:update")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportConsignee, consignee_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Consignee not found")
    old_status = row.status
    row.consignee_code = payload.consignee_code.strip().upper()
    row.consignee_name = payload.consignee_name.strip()
    row.country = (payload.country or "").strip() or None
    row.contact_info = (payload.contact_info or "").strip() or None
    row.status = payload.status
    row.updated_at = utcnow()
    create_audit_log(
        db,
        module_name="Export Operations",
        action="Update Export Consignee",
        category="Data Change",
        current_user=actor,
        entity_type="ExportConsignee",
        entity_id=row.id,
        entity_label=f"{row.consignee_name} ({row.consignee_code})",
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Export consignee updated",
        details_summary=f"code={row.consignee_code}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_consignee(row)


@router.delete("/consignees/{consignee_id}")
def delete_export_consignee(
    consignee_id: int,
    request: Request,
    actor: User = Depends(require_permission("export_operations:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportConsignee, consignee_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Consignee not found")
    create_audit_log(
        db,
        module_name="Export Operations",
        action="Delete Export Consignee",
        category="Data Change",
        current_user=actor,
        entity_type="ExportConsignee",
        entity_id=row.id,
        entity_label=row.consignee_code,
        old_status=row.status,
        request=request,
        remarks="Export consignee deleted",
        details_summary=f"code={row.consignee_code}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Export consignee deleted successfully"}


# ===========================================================================
# 5. Export Permits
# ===========================================================================
class ExportPermitPayload(StrictModel):
    permit_number: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=50)
    entity_code: str = Field(min_length=1, max_length=50)
    block_code: str | None = Field(default=None, max_length=50)
    block_codes: list[str] = Field(default_factory=list)
    quarter: str = Field(min_length=2, max_length=20)
    year: int | None = None
    permit_volume: float = Field(ge=0)
    issue_date: date | None = None
    expiry_date: date | None = None
    remarks: str | None = Field(default=None, max_length=2000)
    status: Literal["Active", "Expired", "Inactive", "Exhausted"] = "Active"


def _serialize_permit(db: Session, row: ExportPermit) -> dict:
    blocks = [b.block_code for b in row.block_assignments]
    if not blocks and row.block_code:
        blocks = [row.block_code]
    used_vol = _f(
        db.query(func.coalesce(func.sum(ExportTransaction.volume), 0))
        .filter(
            ExportTransaction.permit_number == row.permit_number,
            ExportTransaction.status == "Active",
        )
        .scalar()
    )
    permit_vol = _f(row.permit_volume)
    remaining_vol = max(0.0, round(permit_vol - used_vol, 4))
    usage_pct = round((used_vol / permit_vol) * 100.0, 2) if permit_vol > 0 else 0.0
    return {
        "id": row.id,
        "permit_number": row.permit_number,
        "location_code": row.location_code,
        "entity_code": row.entity_code,
        "block_code": row.block_code or (blocks[0] if blocks else ""),
        "block_codes": blocks,
        "quarter": row.quarter,
        "permit_volume": permit_vol,
        "used_volume": round(used_vol, 4),
        "remaining_volume": remaining_vol,
        "usage_pct": usage_pct,
        "issue_date": row.issue_date,
        "expiry_date": row.expiry_date or _quarter_end_date(row.quarter),
        "remarks": row.remarks or "",
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/permits")
def list_export_permits(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    entity_code: str | None = None,
    block_code: str | None = None,
    quarter: str | None = None,
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    _expire_permits_if_needed(db)
    q = db.query(ExportPermit)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                ExportPermit.permit_number.ilike(term),
                ExportPermit.location_code.ilike(term),
                ExportPermit.entity_code.ilike(term),
                ExportPermit.quarter.ilike(term),
            )
        )
    if status:
        q = q.filter(ExportPermit.status == status)
    if location_code:
        q = q.filter(func.upper(ExportPermit.location_code) == location_code.strip().upper())
    if entity_code:
        q = q.filter(func.upper(ExportPermit.entity_code) == entity_code.strip().upper())
    if block_code:
        pids = db.query(ExportPermitBlockAssignment.permit_id).filter(
            func.upper(ExportPermitBlockAssignment.block_code) == block_code.strip().upper()
        )
        q = q.filter(or_(ExportPermit.id.in_(pids), func.upper(ExportPermit.block_code) == block_code.strip().upper()))
    if quarter:
        q = q.filter(ExportPermit.quarter == quarter)

    result = paginate_query(q.order_by(ExportPermit.id.desc()), page=page, page_size=page_size)
    result["items"] = [_serialize_permit(db, r) for r in result["items"]]
    return result


@router.get("/permits/export")
def export_permits(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    status: str | None = None,
    location_code: str | None = None,
    quarter: str | None = None,
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    q = db.query(ExportPermit)
    if status:
        q = q.filter(ExportPermit.status == status)
    if location_code:
        q = q.filter(func.upper(ExportPermit.location_code) == location_code.strip().upper())
    if quarter:
        q = q.filter(ExportPermit.quarter == quarter)
    records = q.order_by(ExportPermit.id.desc()).limit(MAX_EXPORT_ROWS).all()
    headers = [
        "Permit Number",
        "Location",
        "Entity",
        "Blocks",
        "Quarter",
        "Permit Vol (bbl)",
        "Used Vol (bbl)",
        "Remaining Vol (bbl)",
        "Usage %",
        "Status",
    ]
    rows = []
    for r in records:
        p = _serialize_permit(db, r)
        rows.append(
            [
                p["permit_number"],
                p["location_code"],
                p["entity_code"],
                ", ".join(p["block_codes"]),
                p["quarter"],
                p["permit_volume"],
                p["used_volume"],
                p["remaining_volume"],
                p["usage_pct"],
                p["status"],
            ]
        )
    create_audit_log(
        db,
        module_name="Export Operations",
        action="Export Permits",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} export permits as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("export-permits", headers, rows)
    if format == "xlsx":
        return xlsx_response("export-permits", "Export Permits", headers, rows)
    return pdf_response("export-permits", "Export Permits Register", headers, rows)


@router.post("/permits", status_code=201)
def create_export_permit(
    payload: ExportPermitPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:create")),
    db: Session = Depends(get_db),
):
    pnum = payload.permit_number.strip().upper()
    if db.query(ExportPermit).filter(func.upper(ExportPermit.permit_number) == pnum).first():
        raise HTTPException(status_code=400, detail="Permit number already exists")
    q_code = _normalize_quarter(payload.quarter, payload.year)
    blocks = sorted({b.strip().upper() for b in payload.block_codes if b.strip()})
    if not blocks and payload.block_code:
        blocks = [payload.block_code.strip().upper()]
    if not blocks:
        raise HTTPException(status_code=400, detail="At least one block is required for a permit")

    row = ExportPermit(
        permit_number=pnum,
        location_code=payload.location_code.strip().upper(),
        entity_code=payload.entity_code.strip().upper(),
        block_code=blocks[0],
        quarter=q_code,
        permit_volume=payload.permit_volume,
        issue_date=payload.issue_date,
        expiry_date=payload.expiry_date or _quarter_end_date(q_code),
        remarks=(payload.remarks or "").strip() or None,
        status=payload.status,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(row)
    db.flush()
    for bc in blocks:
        db.add(ExportPermitBlockAssignment(permit_id=row.id, block_code=bc))

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Create Export Permit",
        category="Data Change",
        current_user=actor,
        entity_type="ExportPermit",
        entity_id=row.id,
        entity_label=row.permit_number,
        new_status=row.status,
        request=request,
        remarks="Export permit created",
        details_summary=f"permit={row.permit_number}; quarter={row.quarter}; volume={row.permit_volume}",
        status_code=201,
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_permit(db, row)


@router.put("/permits/{permit_id}")
def update_export_permit(
    permit_id: int,
    payload: ExportPermitPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:update")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportPermit, permit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export permit not found")
    q_code = _normalize_quarter(payload.quarter, payload.year)
    blocks = sorted({b.strip().upper() for b in payload.block_codes if b.strip()})
    if not blocks and payload.block_code:
        blocks = [payload.block_code.strip().upper()]

    old_status = row.status
    row.permit_number = payload.permit_number.strip().upper()
    row.location_code = payload.location_code.strip().upper()
    row.entity_code = payload.entity_code.strip().upper()
    row.block_code = blocks[0] if blocks else row.block_code
    row.quarter = q_code
    row.permit_volume = payload.permit_volume
    row.issue_date = payload.issue_date
    row.expiry_date = payload.expiry_date or _quarter_end_date(q_code)
    row.remarks = (payload.remarks or "").strip() or None
    row.status = payload.status
    row.updated_at = utcnow()

    if blocks:
        db.query(ExportPermitBlockAssignment).filter(ExportPermitBlockAssignment.permit_id == row.id).delete()
        for bc in blocks:
            db.add(ExportPermitBlockAssignment(permit_id=row.id, block_code=bc))

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Update Export Permit",
        category="Data Change",
        current_user=actor,
        entity_type="ExportPermit",
        entity_id=row.id,
        entity_label=row.permit_number,
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Export permit updated",
        details_summary=f"permit={row.permit_number}; volume={row.permit_volume}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_permit(db, row)


@router.delete("/permits/{permit_id}")
def delete_export_permit(
    permit_id: int,
    request: Request,
    actor: User = Depends(require_permission("export_operations:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportPermit, permit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export permit not found")
    create_audit_log(
        db,
        module_name="Export Operations",
        action="Delete Export Permit",
        category="Data Change",
        current_user=actor,
        entity_type="ExportPermit",
        entity_id=row.id,
        entity_label=row.permit_number,
        old_status=row.status,
        request=request,
        remarks="Export permit deleted",
        details_summary=f"permit={row.permit_number}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Export permit deleted successfully"}


# ===========================================================================
# 6. Export Transactions & Reports
# ===========================================================================
class ExportBlockEntryInput(StrictModel):
    block_code: str = Field(min_length=1, max_length=50)
    volume: float = Field(gt=0)


class ExportTransactionPayload(StrictModel):
    bl_date: date
    location_code: str = Field(min_length=1, max_length=50)
    entity_code: str = Field(min_length=1, max_length=50)
    block_code: str | None = Field(default=None, max_length=50)
    block_entries: list[ExportBlockEntryInput] = Field(default_factory=list)
    permit_number: str | None = Field(default=None, max_length=80)
    quarter: str | None = Field(default=None, max_length=20)
    vessel_name: str | None = Field(default=None, max_length=150)
    consignee: str | None = Field(default=None, max_length=150)
    country: str | None = Field(default=None, max_length=100)
    volume: float | None = Field(default=None, ge=0)
    override_permit_limit: bool = False
    remarks: str | None = Field(default=None, max_length=2000)
    status: Literal["Active", "Cancelled"] = "Active"


def _serialize_tx(row: ExportTransaction) -> dict:
    return {
        "id": row.id,
        "bl_date": row.bl_date,
        "location_code": row.location_code,
        "entity_code": row.entity_code,
        "block_code": row.block_code,
        "permit_number": row.permit_number or "",
        "quarter": row.quarter,
        "vessel_name": row.vessel_name or "",
        "consignee": row.consignee or "",
        "country": row.country or "",
        "volume": _f(row.volume),
        "override_permit_limit": bool(row.override_permit_limit),
        "remarks": row.remarks or "",
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/transactions")
def list_export_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20),
    search: str | None = None,
    status: str | None = None,
    location_code: str | None = None,
    entity_code: str | None = None,
    block_code: str | None = None,
    quarter: str | None = None,
    country: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    q = db.query(ExportTransaction)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                ExportTransaction.vessel_name.ilike(term),
                ExportTransaction.consignee.ilike(term),
                ExportTransaction.permit_number.ilike(term),
                ExportTransaction.block_code.ilike(term),
            )
        )
    if status:
        q = q.filter(ExportTransaction.status == status)
    if location_code:
        q = q.filter(func.upper(ExportTransaction.location_code) == location_code.strip().upper())
    if entity_code:
        q = q.filter(func.upper(ExportTransaction.entity_code) == entity_code.strip().upper())
    if block_code:
        q = q.filter(func.upper(ExportTransaction.block_code) == block_code.strip().upper())
    if quarter:
        q = q.filter(ExportTransaction.quarter == quarter)
    if country:
        q = q.filter(ExportTransaction.country == country)
    if date_from:
        q = q.filter(ExportTransaction.bl_date >= date_from)
    if date_to:
        q = q.filter(ExportTransaction.bl_date <= date_to)

    result = paginate_query(
        q.order_by(ExportTransaction.bl_date.desc(), ExportTransaction.id.desc()),
        page=page,
        page_size=page_size,
    )
    result["items"] = [_serialize_tx(r) for r in result["items"]]
    return result


@router.get("/transactions/export")
def export_export_transactions(
    request: Request,
    format: str = Query("csv", pattern="^(csv|xlsx|pdf)$"),
    status: str | None = None,
    location_code: str | None = None,
    entity_code: str | None = None,
    block_code: str | None = None,
    quarter: str | None = None,
    country: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    q = db.query(ExportTransaction)
    if status:
        q = q.filter(ExportTransaction.status == status)
    if location_code:
        q = q.filter(func.upper(ExportTransaction.location_code) == location_code.strip().upper())
    if entity_code:
        q = q.filter(func.upper(ExportTransaction.entity_code) == entity_code.strip().upper())
    if block_code:
        q = q.filter(func.upper(ExportTransaction.block_code) == block_code.strip().upper())
    if quarter:
        q = q.filter(ExportTransaction.quarter == quarter)
    if country:
        q = q.filter(ExportTransaction.country == country)
    if date_from:
        q = q.filter(ExportTransaction.bl_date >= date_from)
    if date_to:
        q = q.filter(ExportTransaction.bl_date <= date_to)

    records = q.order_by(ExportTransaction.bl_date.desc()).limit(MAX_EXPORT_ROWS).all()
    headers = [
        "B/L Date",
        "Quarter",
        "Location",
        "Entity",
        "Block",
        "Permit #",
        "Vessel",
        "Consignee",
        "Country",
        "Volume (bbl)",
        "Status",
    ]
    rows = [
        [
            r.bl_date,
            r.quarter,
            r.location_code,
            r.entity_code,
            r.block_code,
            r.permit_number or "",
            r.vessel_name or "",
            r.consignee or "",
            r.country or "",
            _f(r.volume),
            r.status,
        ]
        for r in records
    ]
    create_audit_log(
        db,
        module_name="Export Operations",
        action="Export Transactions",
        category="Export",
        current_user=actor,
        request=request,
        remarks=f"Exported {len(rows)} export transactions as {format.upper()}",
        details_summary=f"format={format}; count={len(rows)}",
    )
    db.commit()
    request.state.audit_written = True
    if format == "csv":
        return csv_response("export-transactions", headers, rows)
    if format == "xlsx":
        return xlsx_response("export-transactions", "Export Transactions", headers, rows)
    return pdf_response("export-transactions", "Export Transactions Register", headers, rows)


@router.post("/transactions", status_code=201)
def create_export_transaction(
    payload: ExportTransactionPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:create")),
    db: Session = Depends(get_db),
):
    entries = payload.block_entries
    if not entries:
        if not payload.block_code or payload.volume is None or payload.volume <= 0:
            raise HTTPException(status_code=400, detail="Provide a block and positive export volume")
        entries = [ExportBlockEntryInput(block_code=payload.block_code, volume=payload.volume)]

    q_code = _quarter_from_date(payload.bl_date)
    pnum = (payload.permit_number or "").strip().upper() or None
    if pnum:
        permit = db.query(ExportPermit).filter(func.upper(ExportPermit.permit_number) == pnum).first()
        if permit is None:
            raise HTTPException(status_code=400, detail=f"Permit '{pnum}' not found")
        p_info = _serialize_permit(db, permit)
        total_req = sum(e.volume for e in entries)
        if total_req > p_info["remaining_volume"] and not payload.override_permit_limit:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Permit {pnum} has insufficient remaining volume. "
                    f"Required {total_req:,.2f} bbl, remaining {p_info['remaining_volume']:,.2f} bbl. "
                    "Enable Override Permit Limit to proceed."
                ),
            )

    created_rows = []
    for item in entries:
        row = ExportTransaction(
            bl_date=payload.bl_date,
            location_code=payload.location_code.strip().upper(),
            entity_code=payload.entity_code.strip().upper(),
            block_code=item.block_code.strip().upper(),
            permit_number=pnum,
            quarter=q_code,
            vessel_name=(payload.vessel_name or "").strip() or None,
            consignee=(payload.consignee or "").strip() or None,
            country=(payload.country or "").strip() or None,
            volume=item.volume,
            override_permit_limit=payload.override_permit_limit,
            remarks=(payload.remarks or "").strip() or None,
            status=payload.status,
            created_by_user_id=actor.id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(row)
        db.flush()
        created_rows.append(row)

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Create Export Transaction",
        category="Data Change",
        current_user=actor,
        entity_type="ExportTransaction",
        entity_id=created_rows[0].id,
        entity_label=f"{payload.vessel_name or 'Export'} ({payload.bl_date})",
        new_status=payload.status,
        request=request,
        remarks="Export transaction recorded",
        details_summary=f"bl_date={payload.bl_date}; blocks={len(created_rows)}; total_vol={sum(e.volume for e in entries)}",
        status_code=201,
    )
    db.commit()
    for r in created_rows:
        db.refresh(r)
    request.state.audit_written = True
    return _serialize_tx(created_rows[0])


@router.put("/transactions/{tx_id}")
def update_export_transaction(
    tx_id: int,
    payload: ExportTransactionPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:update")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportTransaction, tx_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export transaction not found")
    old_status = row.status
    row.bl_date = payload.bl_date
    row.location_code = payload.location_code.strip().upper()
    row.entity_code = payload.entity_code.strip().upper()
    if payload.block_code:
        row.block_code = payload.block_code.strip().upper()
    row.permit_number = (payload.permit_number or "").strip().upper() or None
    row.quarter = _quarter_from_date(payload.bl_date)
    row.vessel_name = (payload.vessel_name or "").strip() or None
    row.consignee = (payload.consignee or "").strip() or None
    row.country = (payload.country or "").strip() or None
    if payload.volume is not None:
        row.volume = payload.volume
    row.override_permit_limit = payload.override_permit_limit
    row.remarks = (payload.remarks or "").strip() or None
    row.status = payload.status
    row.updated_at = utcnow()

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Update Export Transaction",
        category="Data Change",
        current_user=actor,
        entity_type="ExportTransaction",
        entity_id=row.id,
        entity_label=f"{row.vessel_name or 'Export'} ({row.bl_date})",
        old_status=old_status,
        new_status=row.status,
        request=request,
        remarks="Export transaction updated",
        details_summary=f"id={row.id}; volume={row.volume}",
    )
    db.commit()
    db.refresh(row)
    request.state.audit_written = True
    return _serialize_tx(row)


@router.delete("/transactions/{tx_id}")
def delete_export_transaction(
    tx_id: int,
    request: Request,
    actor: User = Depends(require_permission("export_operations:delete")),
    db: Session = Depends(get_db),
):
    row = db.get(ExportTransaction, tx_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export transaction not found")
    create_audit_log(
        db,
        module_name="Export Operations",
        action="Delete Export Transaction",
        category="Data Change",
        current_user=actor,
        entity_type="ExportTransaction",
        entity_id=row.id,
        entity_label=f"{row.vessel_name or 'Export'} ({row.bl_date})",
        old_status=row.status,
        request=request,
        remarks="Export transaction deleted",
        details_summary=f"id={row.id}; volume={row.volume}",
    )
    db.delete(row)
    db.commit()
    request.state.audit_written = True
    return {"message": "Export transaction deleted successfully"}


# ===========================================================================
# 7. Export Dashboard, Report & Settings
# ===========================================================================
@router.get("/dashboard")
def export_operations_dashboard(
    location_code: str | None = None,
    entity_code: str | None = None,
    block_code: str | None = None,
    quarter: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    _expire_permits_if_needed(db)
    tx_q = db.query(ExportTransaction).filter(ExportTransaction.status == "Active")
    permit_q = db.query(ExportPermit).filter(ExportPermit.status == "Active")

    if location_code:
        tx_q = tx_q.filter(func.upper(ExportTransaction.location_code) == location_code.strip().upper())
        permit_q = permit_q.filter(func.upper(ExportPermit.location_code) == location_code.strip().upper())
    if entity_code:
        tx_q = tx_q.filter(func.upper(ExportTransaction.entity_code) == entity_code.strip().upper())
        permit_q = permit_q.filter(func.upper(ExportPermit.entity_code) == entity_code.strip().upper())
    if block_code:
        tx_q = tx_q.filter(func.upper(ExportTransaction.block_code) == block_code.strip().upper())
    if quarter:
        tx_q = tx_q.filter(ExportTransaction.quarter == quarter)
        permit_q = permit_q.filter(ExportPermit.quarter == quarter)
    if date_from:
        tx_q = tx_q.filter(ExportTransaction.bl_date >= date_from)
    if date_to:
        tx_q = tx_q.filter(ExportTransaction.bl_date <= date_to)

    tx_rows = tx_q.order_by(ExportTransaction.bl_date.desc(), ExportTransaction.id.desc()).all()
    permits = [_serialize_permit(db, p) for p in permit_q.all()]

    total_export_vol = round(sum(_f(t.volume) for t in tx_rows), 4)
    total_permit_vol = round(sum(p["permit_volume"] for p in permits), 4)
    total_used_vol = round(sum(p["used_volume"] for p in permits), 4)
    total_rem_vol = round(sum(p["remaining_volume"] for p in permits), 4)

    cfg = db.query(ExportConfig).filter(ExportConfig.config_key == "permit_insufficiency_threshold_pct").first()
    threshold_pct = _f(cfg.config_value) if cfg else 90.0
    if threshold_pct <= 0:
        threshold_pct = 90.0

    insufficient_permits = [
        p for p in permits if p["permit_volume"] > 0 and p["usage_pct"] >= threshold_pct
    ]

    loc_map = {l.location_code: l.location_name for l in db.query(ExportLocation).all()}
    blk_map = {b.block_code: b.block_name for b in db.query(ExportBlock).all()}
    ent_map = {e.entity_code: e.entity_name for e in db.query(ExportEntity).all()}

    loc_totals: dict[str, float] = {}
    for t in tx_rows:
        loc_totals[t.location_code] = loc_totals.get(t.location_code, 0.0) + _f(t.volume)

    locations_kpi = []
    for lcode in sorted(set(loc_totals.keys()) | {p["location_code"] for p in permits}):
        l_permits = [p for p in permits if p["location_code"] == lcode]
        locations_kpi.append(
            {
                "location_code": lcode,
                "location_name": loc_map.get(lcode, lcode),
                "total_export_volume": round(loc_totals.get(lcode, 0.0), 4),
                "total_permit_volume": round(sum(p["permit_volume"] for p in l_permits), 4),
                "total_remaining_volume": round(sum(p["remaining_volume"] for p in l_permits), 4),
            }
        )

    blocks_summary = []
    for p in permits:
        for bcode in p["block_codes"]:
            blocks_summary.append(
                {
                    "location_code": p["location_code"],
                    "location_name": loc_map.get(p["location_code"], p["location_code"]),
                    "entity_code": p["entity_code"],
                    "entity_name": ent_map.get(p["entity_code"], p["entity_code"]),
                    "block_code": bcode,
                    "block_name": blk_map.get(bcode, bcode),
                    "quarter": p["quarter"],
                    "permit_number": p["permit_number"],
                    "permit_volume": p["permit_volume"],
                    "used_permit_volume": p["used_volume"],
                    "remaining_permit_volume": p["remaining_volume"],
                    "usage_pct": p["usage_pct"],
                }
            )

    return {
        "total_export_volume": total_export_vol,
        "total_permits": len(permits),
        "total_permit_volume": total_permit_vol,
        "total_used_permit_volume": total_used_vol,
        "total_remaining_permit_volume": total_rem_vol,
        "permit_insufficient_count": len(insufficient_permits),
        "insufficient_threshold_pct": threshold_pct,
        "locations_kpi": locations_kpi,
        "blocks_summary": blocks_summary,
        "recent_exports": [_serialize_tx(t) for t in tx_rows[:20]],
    }


@router.get("/report")
def get_export_report(
    location_code: str | None = None,
    entity_code: str | None = None,
    block_code: str | None = None,
    quarter: str | None = None,
    country: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    q = db.query(ExportTransaction).filter(ExportTransaction.status == "Active")
    if location_code:
        q = q.filter(func.upper(ExportTransaction.location_code) == location_code.strip().upper())
    if entity_code:
        q = q.filter(func.upper(ExportTransaction.entity_code) == entity_code.strip().upper())
    if block_code:
        q = q.filter(func.upper(ExportTransaction.block_code) == block_code.strip().upper())
    if quarter:
        q = q.filter(ExportTransaction.quarter == quarter)
    if country:
        q = q.filter(ExportTransaction.country == country)
    if date_from:
        q = q.filter(ExportTransaction.bl_date >= date_from)
    if date_to:
        q = q.filter(ExportTransaction.bl_date <= date_to)

    rows = [_serialize_tx(t) for t in q.order_by(ExportTransaction.bl_date.desc()).all()]
    return {
        "rows": rows,
        "total_rows": len(rows),
        "total_volume": round(sum(r["volume"] for r in rows), 4),
    }


class ExportSettingsPayload(StrictModel):
    permit_insufficiency_threshold_pct: float = Field(default=90.0, ge=1.0, le=100.0)
    default_volume_unit: str = Field(default="BBL", max_length=20)
    auto_expire_permits: bool = True


@router.get("/settings")
def get_export_settings(
    actor: User = Depends(require_permission("export_operations:read")),
    db: Session = Depends(get_db),
):
    rows = {r.config_key: r.config_value for r in db.query(ExportConfig).all()}
    return {
        "permit_insufficiency_threshold_pct": _f(rows.get("permit_insufficiency_threshold_pct", 90.0)) or 90.0,
        "default_volume_unit": rows.get("default_volume_unit", "BBL"),
        "auto_expire_permits": rows.get("auto_expire_permits", "true").lower() in ("true", "1", "yes"),
    }


@router.put("/settings")
def update_export_settings(
    payload: ExportSettingsPayload,
    request: Request,
    actor: User = Depends(require_permission("export_operations:update")),
    db: Session = Depends(get_db),
):
    kv = {
        "permit_insufficiency_threshold_pct": str(payload.permit_insufficiency_threshold_pct),
        "default_volume_unit": payload.default_volume_unit.strip().upper(),
        "auto_expire_permits": "true" if payload.auto_expire_permits else "false",
    }
    for k, v in kv.items():
        row = db.query(ExportConfig).filter(ExportConfig.config_key == k).first()
        if row:
            row.config_value = v
            row.updated_at = utcnow()
        else:
            db.add(ExportConfig(config_key=k, config_value=v, updated_at=utcnow()))

    create_audit_log(
        db,
        module_name="Export Operations",
        action="Update Export Settings",
        category="Configuration",
        current_user=actor,
        request=request,
        remarks="Export settings updated",
        details_summary=f"threshold={payload.permit_insufficiency_threshold_pct}%; unit={payload.default_volume_unit}",
    )
    db.commit()
    request.state.audit_written = True
    return get_export_settings(actor=actor, db=db)
