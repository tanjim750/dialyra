import json
from datetime import datetime

from flask import current_app

from app.extensions import db
from app.models import Business, User, WorkspaceMembership
from app.services.audit_service import log_audit_event
from app.services.user_workspace import get_primary_business_id


VALID_BUSINESS_STATUSES = {"active", "inactive", "suspended", "deleted"}
VALID_MEMBER_STATUSES = {"active", "inactive", "suspended"}
VALID_MEMBER_ROLES = {"owner", "admin", "manager", "agent", "viewer"}
ASSIGNABLE_MEMBER_ROLES = {"admin", "manager", "agent", "viewer"}
LIMIT_KEYS = {
    "max_users",
    "max_concurrent_calls",
    "max_campaigns",
    "max_sip_trunks",
    "max_storage",
}


def _serialize_settings(settings_json):
    if not settings_json:
        return {}
    try:
        parsed = json.loads(settings_json)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {}


def serialize_business(business):
    return {
        "id": business.id,
        "uuid": business.uuid,
        "name": business.name,
        "slug": business.slug,
        "owner_user_id": business.owner_user_id,
        "email": business.email,
        "phone": business.phone,
        "timezone": business.timezone,
        "country": business.country,
        "logo_path": business.logo_path,
        "status": business.status,
        "settings": _serialize_settings(business.settings_json),
        "allow_global_sip_fallback": bool(business.allow_global_sip_fallback),
        "deleted_at": business.deleted_at.isoformat() if business.deleted_at else None,
        "created_at": business.created_at.isoformat() if business.created_at else None,
        "updated_at": business.updated_at.isoformat() if business.updated_at else None,
    }


def list_businesses(actor_user):
    if actor_user.role == "superuser":
        items = Business.query.order_by(Business.created_at.desc()).all()
    else:
        if current_app.config.get("AUTHZ_V2_ENABLED", False):
            memberships = WorkspaceMembership.query.filter_by(
                user_id=actor_user.id, status="active"
            ).all()
            business_ids = sorted({m.business_id for m in memberships})
            if not business_ids:
                return [], None
            items = (
                Business.query.filter(Business.id.in_(business_ids))
                .order_by(Business.created_at.desc())
                .all()
            )
        else:
            actor_business_id = get_primary_business_id(actor_user.id)
            if not actor_business_id:
                return None, "User business is not configured"
            items = Business.query.filter_by(id=actor_business_id).all()
    return [serialize_business(item) for item in items], None


def get_business(actor_user, business):
    return serialize_business(business), None


def set_global_sip_fallback(actor_user, business, enabled):
    business.allow_global_sip_fallback = bool(enabled)
    db.session.commit()
    log_audit_event(
        "business.global_sip_fallback_updated",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"allow_global_sip_fallback": bool(enabled)},
    )
    db.session.commit()
    return {
        "business_id": business.id,
        "allow_global_sip_fallback": bool(business.allow_global_sip_fallback),
    }, None


def create_business(actor_user, payload):
    name = (payload.get("name") or "").strip()
    slug = (payload.get("slug") or "").strip().lower()
    email = (payload.get("email") or "").strip().lower()
    phone = (payload.get("phone") or "").strip() or None
    timezone = (payload.get("timezone") or "Asia/Dhaka").strip()
    country = (payload.get("country") or "").strip() or None

    if not name or not slug or not email:
        return None, "Missing required fields"
    if Business.query.filter_by(slug=slug).first() is not None:
        return None, "Business slug already exists"

    owner_user_id = actor_user.id if actor_user.role == "stuff" else None
    owner_name = actor_user.full_name if owner_user_id else "Unassigned"
    business = Business(
        name=name,
        slug=slug,
        owner_name=owner_name,
        owner_user_id=owner_user_id,
        email=email,
        phone=phone,
        timezone=timezone,
        country=country,
        status="active",
    )
    db.session.add(business)
    db.session.flush()

    if owner_user_id:
        existing = WorkspaceMembership.query.filter_by(
            business_id=business.id,
            user_id=owner_user_id,
        ).first()
        if existing is None:
            db.session.add(
                WorkspaceMembership(
                    business_id=business.id,
                    user_id=owner_user_id,
                    role="owner",
                    status="active",
                )
            )
    db.session.commit()

    log_audit_event(
        "business.created",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"name": business.name, "slug": business.slug},
    )
    db.session.commit()

    return serialize_business(business), None


def update_business(actor_user, business, payload):
    if "name" in payload:
        business.name = (payload.get("name") or "").strip() or business.name
    if "email" in payload:
        business.email = (payload.get("email") or "").strip().lower() or business.email
    if "phone" in payload:
        business.phone = (payload.get("phone") or "").strip() or None
    if "timezone" in payload:
        business.timezone = (payload.get("timezone") or "").strip() or business.timezone
    if "country" in payload:
        business.country = (payload.get("country") or "").strip() or None
    if "logo_path" in payload:
        business.logo_path = (payload.get("logo_path") or "").strip() or None
    if "status" in payload:
        next_status = (payload.get("status") or "").strip().lower()
        if next_status not in VALID_BUSINESS_STATUSES:
            return None, "Invalid status"
        business.status = next_status
        if next_status == "deleted":
            business.deleted_at = datetime.utcnow()

    db.session.commit()
    log_audit_event(
        "business.updated",
        business_id=business.id,
        actor_user_id=actor_user.id,
    )
    db.session.commit()

    return serialize_business(business), None


def soft_delete_business(actor_user, business):
    business.status = "deleted"
    business.deleted_at = datetime.utcnow()
    db.session.commit()

    log_audit_event(
        "business.deleted",
        business_id=business.id,
        actor_user_id=actor_user.id,
    )
    db.session.commit()

    return {"message": "Business deleted"}, None


def get_business_settings(actor_user, business):
    return {"business_id": business.id, "settings": _serialize_settings(business.settings_json)}, None


def update_business_settings(actor_user, business, payload):
    settings = payload.get("settings")
    if not isinstance(settings, dict):
        return None, "settings must be an object"
    for key in LIMIT_KEYS:
        if key in settings and settings[key] is not None:
            try:
                parsed = int(settings[key])
            except (TypeError, ValueError):
                return None, f"{key} must be an integer"
            if parsed <= 0:
                return None, f"{key} must be positive"
            settings[key] = parsed

    business.settings_json = json.dumps(settings)
    db.session.commit()

    log_audit_event(
        "business.settings_updated",
        business_id=business.id,
        actor_user_id=actor_user.id,
    )
    db.session.commit()

    return {"business_id": business.id, "settings": settings}, None


def serialize_membership(membership):
    return {
        "id": membership.id,
        "business_id": membership.business_id,
        "user_id": membership.user_id,
        "role": membership.role,
        "status": membership.status,
        "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
    }


def add_member(actor_user, business, payload):
    user_id = payload.get("user_id")
    role = (payload.get("role") or "viewer").strip().lower()
    status = (payload.get("status") or "active").strip().lower()

    if not user_id:
        return None, "Missing required field: user_id"
    if role not in ASSIGNABLE_MEMBER_ROLES:
        return None, "Invalid member role"
    if status not in VALID_MEMBER_STATUSES:
        return None, "Invalid member status"

    user = User.query.get(int(user_id))
    if user is None:
        return None, "User not found"
    if user.role == "superuser":
        return None, "Superuser cannot be assigned as workspace member"

    exists = WorkspaceMembership.query.filter_by(
        business_id=business.id, user_id=user.id
    ).first()
    if exists is not None:
        return None, "User is already a member"

    membership = WorkspaceMembership(
        business_id=business.id,
        user_id=user.id,
        role=role,
        status=status,
    )
    db.session.add(membership)
    db.session.commit()

    log_audit_event(
        "workspace.member_added",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"member_id": membership.id, "user_id": user.id, "role": role},
    )
    db.session.commit()

    return serialize_membership(membership), None


def list_members(actor_user, business):
    memberships = WorkspaceMembership.query.filter_by(business_id=business.id).order_by(
        WorkspaceMembership.joined_at.desc()
    ).all()
    return [serialize_membership(m) for m in memberships], None


def update_member(actor_user, business, member_id, payload):
    membership = WorkspaceMembership.query.filter_by(
        id=member_id, business_id=business.id
    ).first()
    if membership is None:
        return None, "Member not found"
    actor_membership = WorkspaceMembership.query.filter_by(
        business_id=business.id, user_id=actor_user.id, status="active"
    ).first()
    actor_is_owner = actor_user.role == "superuser" or (
        actor_membership is not None and actor_membership.role == "owner"
    )
    if membership.role == "owner" and not actor_is_owner:
        return None, "Only owner can manage owner membership"

    if "role" in payload:
        role = (payload.get("role") or "").strip().lower()
        if role not in ASSIGNABLE_MEMBER_ROLES:
            return None, "Invalid member role"
        if membership.role == "owner":
            return None, "Owner role cannot be reassigned from this endpoint"
        membership.role = role

    if "status" in payload:
        status = (payload.get("status") or "").strip().lower()
        if status not in VALID_MEMBER_STATUSES:
            return None, "Invalid member status"
        membership.status = status

    db.session.commit()
    log_audit_event(
        "workspace.member_updated",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"member_id": membership.id, "user_id": membership.user_id},
    )
    db.session.commit()

    return serialize_membership(membership), None


def remove_member(actor_user, business, member_id):
    membership = WorkspaceMembership.query.filter_by(
        id=member_id, business_id=business.id
    ).first()
    if membership is None:
        return None, "Member not found"
    actor_membership = WorkspaceMembership.query.filter_by(
        business_id=business.id, user_id=actor_user.id, status="active"
    ).first()
    actor_is_owner = actor_user.role == "superuser" or (
        actor_membership is not None and actor_membership.role == "owner"
    )
    if membership.role == "owner" and not actor_is_owner:
        return None, "Only owner can remove owner membership"
    if membership.user_id == business.owner_user_id:
        return None, "Cannot remove active business owner membership"

    db.session.delete(membership)
    db.session.commit()
    log_audit_event(
        "workspace.member_removed",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"member_id": member_id, "user_id": membership.user_id},
    )
    db.session.commit()

    return {"message": "Member removed"}, None


def transfer_ownership(actor_user, business, payload):
    if actor_user.role != "superuser" and business.owner_user_id != actor_user.id:
        return None, "Only current owner can transfer ownership"

    target_user_id = payload.get("target_user_id")
    if not target_user_id:
        return None, "Missing required field: target_user_id"

    target_user = User.query.get(int(target_user_id))
    if target_user is None:
        return None, "Target user not found"

    target_membership = WorkspaceMembership.query.filter_by(
        business_id=business.id, user_id=target_user.id
    ).first()
    if target_membership is None:
        return None, "Target user is not a workspace member"
    if target_membership.status != "active":
        return None, "Target user membership must be active"
    if target_user.role == "superuser":
        return None, "Superuser cannot become business owner"

    previous_owner_id = business.owner_user_id
    business.owner_user_id = target_user.id
    business.owner_name = target_user.full_name

    target_user.role = "stuff"
    target_membership.role = "owner"
    target_membership.status = "active"

    if previous_owner_id and previous_owner_id != target_user.id:
        prev_user = User.query.get(previous_owner_id)
        if prev_user is not None:
            owns_other_businesses = (
                Business.query.filter(
                    Business.owner_user_id == prev_user.id,
                    Business.id != business.id,
                    Business.status != "deleted",
                ).count()
                > 0
            )
            if not owns_other_businesses:
                prev_user.role = "general"
            prev_membership = WorkspaceMembership.query.filter_by(
                business_id=business.id, user_id=prev_user.id
            ).first()
            if prev_membership is not None:
                prev_membership.role = "admin"

    db.session.commit()
    log_audit_event(
        "business.ownership_transferred",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"target_user_id": target_user.id, "previous_owner_id": previous_owner_id},
    )
    db.session.commit()

    return {
        "message": "Ownership transferred successfully",
        "business_id": business.id,
        "owner_user_id": business.owner_user_id,
    }, None
