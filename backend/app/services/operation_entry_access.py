"""Entry permission pipeline: capability → location → availability → workflow policy."""
from fastapi import HTTPException
from sqlalchemy import or_
from app.models import Asset, Location, OperationEntry, OperationWorkflowPolicy
from app.dependencies.permissions import get_user_location_ids, get_user_role_ids, is_admin_user, user_has_permission


def require_capability(db, user, name):
    if not user_has_permission(db, user, name):
        raise HTTPException(403, f"Permission required: {name}")


def ensure_location(db, user, location_id):
    allowed = get_user_location_ids(db, user)
    if allowed is not None and location_id not in allowed:
        raise HTTPException(403, "Location is outside your assigned locations")


def scoped_entries(db, user, *, party=False):
    q = db.query(OperationEntry)
    allowed = get_user_location_ids(db, user)
    if allowed is not None:
        cols = [OperationEntry.location_id]
        if party:
            cols += [OperationEntry.sender_location_id, OperationEntry.receiver_location_id, OperationEntry.destination_location_id]
        q = q.filter(or_(*(c.in_(sorted(allowed)) for c in cols)))
    return q


def get_entry(db, user, entry_id, *, party=False, lock=False):
    q = scoped_entries(db, user, party=party).filter(OperationEntry.id == entry_id)
    if lock:
        q = q.with_for_update()
    row = q.first()
    if not row:
        raise HTTPException(404, "Operation entry not found")
    return row


def scoped_asset(db, user, asset_id, *, location_id=None, active=False, linked_ticket_id=None):
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    receiver_reference = False
    if linked_ticket_id:
        sender = get_entry(db, user, linked_ticket_id, party=True)
        target = sender.receiver_location_id or sender.destination_location_id
        if sender.status != "Approved" or sender.asset_id != asset_id or not target:
            raise HTTPException(400, "Invalid Approved sender reference for this asset")
        ensure_location(db, user, target)
        if location_id and target != location_id:
            raise HTTPException(403, "Sender reference does not address this receiving origin")
        receiver_reference = True
    if asset.asset_scope != "Global" and not receiver_reference:
        ensure_location(db, user, asset.location_id)
        if location_id and asset.location_id != location_id:
            raise HTTPException(400, "A Local asset must belong to the selected Origin Location")
    if active and asset.status != "Active":
        raise HTTPException(400, "Primary Asset must be Active")
    return asset


def check_policy(db, user, action, *, operation_type_code, asset_type_code, location_id, payload_code):
    if is_admin_user(user, db):
        return
    policies = db.query(OperationWorkflowPolicy).filter_by(status="Active", action_code=action).order_by(OperationWorkflowPolicy.priority, OperationWorkflowPolicy.id).all()
    matched = [p for p in policies if all(not getattr(p, k) or getattr(p, k) == v for k, v in {
        "operation_type_code": operation_type_code, "asset_type_code": asset_type_code,
        "location_id": location_id, "payload_code": payload_code}.items())]
    roles = get_user_role_ids(db, user)
    for p in matched:
        direct = next((r for r in p.users if r.user_id == user.id), None)
        if direct:
            if direct.mode == "DENY":
                raise HTTPException(403, f"Workflow policy '{p.policy_name}' denied this user")
            return
        if any(r.role_id in roles for r in p.roles):
            return
    if matched:
        raise HTTPException(403, f"Workflow policy '{matched[0].policy_name}' restricts this action; none of your roles are allowed")


def check_entry_policy(db, user, action, entry):
    check_policy(db, user, action, operation_type_code=entry.operation_type_code,
        asset_type_code=entry.asset_type_code, location_id=entry.location_id, payload_code=entry.payload_code)
