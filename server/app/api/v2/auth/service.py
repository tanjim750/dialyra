import hashlib
import re
import secrets
from datetime import datetime, timedelta

from flask import current_app
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models import Business, RefreshToken, User, WorkspaceMembership
from app.services.audit_service import log_audit_event
from app.services.business_limits import can_add_user_to_business
from app.services.user_workspace import get_primary_business_id

USER_ROLES = {"superuser", "stuff", "general"}
MEMBERSHIP_ROLES = {"admin", "manager", "agent", "viewer"}
VALID_ROLES = set(USER_ROLES)
REGISTER_ALLOWED_ROLES = {"stuff", "general"}
VALID_USER_STATUSES = {"active", "inactive", "suspended"}
VALID_BUSINESS_STATUSES = {"active", "inactive", "suspended"}
SYSTEM_BUSINESS_SLUG = "dialyra-system"
FAILED_LOGIN_ATTEMPTS = {}


def _slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "business"


def _unique_slug(base_slug):
    slug = base_slug
    counter = 1
    while Business.query.filter_by(slug=slug).first() is not None:
        counter += 1
        slug = f"{base_slug}-{counter}"
    return slug


def _get_or_create_system_business():
    business = Business.query.filter_by(slug=SYSTEM_BUSINESS_SLUG).first()
    if business is not None:
        return business

    business = Business(
        name="Dialyra System",
        slug=SYSTEM_BUSINESS_SLUG,
        owner_name="System",
        phone=None,
        email="system@dialyra.local",
        status="active",
    )
    db.session.add(business)
    db.session.flush()
    return business


def _hash_refresh_token(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _create_refresh_token(user):
    raw = secrets.token_urlsafe(48)
    token_hash = _hash_refresh_token(raw)
    expires_days = int(current_app.config.get("JWT_EXPIRES_DAYS", 90))
    expires_at = datetime.utcnow() + timedelta(days=expires_days)

    token = RefreshToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
    db.session.add(token)
    db.session.flush()

    return raw


def _build_access_token(user):
    claims = {
        "business_id": get_primary_business_id(user.id),
        "role": user.role,
        "auth_type": "jwt",
    }
    return create_access_token(identity=str(user.id), additional_claims=claims)


def _cleanup_old_login_attempts(email, now, window_seconds):
    history = FAILED_LOGIN_ATTEMPTS.get(email, [])
    filtered = [t for t in history if (now - t).total_seconds() <= window_seconds]
    FAILED_LOGIN_ATTEMPTS[email] = filtered
    return filtered


def _register_failed_login(email):
    now = datetime.utcnow()
    window_minutes = int(current_app.config.get("LOGIN_RATE_LIMIT_WINDOW_MINUTES", 15))
    window_seconds = window_minutes * 60
    attempts = _cleanup_old_login_attempts(email, now, window_seconds)
    attempts.append(now)
    FAILED_LOGIN_ATTEMPTS[email] = attempts


def _is_login_rate_limited(email):
    now = datetime.utcnow()
    window_minutes = int(current_app.config.get("LOGIN_RATE_LIMIT_WINDOW_MINUTES", 15))
    max_attempts = int(current_app.config.get("LOGIN_MAX_FAILED_ATTEMPTS", 5))
    window_seconds = window_minutes * 60
    attempts = _cleanup_old_login_attempts(email, now, window_seconds)
    return len(attempts) >= max_attempts


def serialize_business(business):
    return {
        "id": business.id,
        "name": business.name,
        "slug": business.slug,
        "owner_user_id": business.owner_user_id,
        "phone": business.phone,
        "email": business.email,
        "status": business.status,
        "created_at": business.created_at.isoformat() if business.created_at else None,
        "updated_at": business.updated_at.isoformat() if business.updated_at else None,
    }


def serialize_user(user):
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def _serialize_membership(membership):
    return {
        "membership_id": membership.id,
        "business_id": membership.business_id,
        "membership_role": membership.role,
        "membership_status": membership.status,
        "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
    }


def list_users_by_actor(actor_user):
    if actor_user.role == "superuser":
        users = User.query.order_by(User.created_at.desc()).all()
        return {"items": [serialize_user(user) for user in users]}, None

    if actor_user.role != "stuff":
        return None, "Only superuser or stuff can list users"

    owned_businesses = Business.query.filter_by(owner_user_id=actor_user.id).all()
    owned_business_ids = [b.id for b in owned_businesses]
    if not owned_business_ids:
        return {"items": []}, None

    memberships = (
        WorkspaceMembership.query.filter(WorkspaceMembership.business_id.in_(owned_business_ids))
        .order_by(WorkspaceMembership.joined_at.desc())
        .all()
    )

    users_by_id = {}
    for membership in memberships:
        user = User.query.get(membership.user_id)
        if user is None:
            continue
        if user.id not in users_by_id:
            users_by_id[user.id] = {
                "user": serialize_user(user),
                "memberships": [],
            }
        users_by_id[user.id]["memberships"].append(_serialize_membership(membership))

    return {"items": list(users_by_id.values())}, None


def register_owner(payload):
    full_name = (payload.get("full_name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    role = (payload.get("role") or "general").strip().lower()

    if not full_name or not email or not password:
        return None, "Missing required fields"
    if role not in REGISTER_ALLOWED_ROLES:
        return None, "Register role must be stuff or general"

    if User.query.filter_by(email=email).first() is not None:
        return None, "Email already exists"

    user = User(
        full_name=full_name,
        email=email,
        password_hash=generate_password_hash(password),
        role=role,
        status="active",
    )
    db.session.add(user)

    access_token = _build_access_token(user)
    refresh_token = _create_refresh_token(user)

    db.session.commit()
    log_audit_event(
        "auth.register",
        business_id=None,
        actor_user_id=user.id,
        metadata={"email": user.email, "role": user.role},
    )
    db.session.commit()

    return {
        "message": "Registration successful",
        "business": None,
        "user": serialize_user(user),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }, None


def bootstrap_superuser(payload):
    full_name = (payload.get("full_name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    if not full_name or not email or not password:
        return None, "Missing required fields"
    if User.query.filter_by(email=email).first() is not None:
        return None, "Email already exists"

    existing = User.query.filter_by(role="superuser").first()
    if existing is not None:
        return None, "Superuser already exists"

    system_business = _get_or_create_system_business()

    user = User(
        full_name=full_name,
        email=email,
        password_hash=generate_password_hash(password),
        role="superuser",
        status="active",
    )
    db.session.add(user)
    db.session.flush()

    access_token = _build_access_token(user)
    refresh_token = _create_refresh_token(user)
    db.session.commit()
    log_audit_event(
        "auth.bootstrap_superuser",
        business_id=system_business.id,
        actor_user_id=user.id,
        metadata={"email": user.email},
    )
    db.session.commit()

    return {
        "message": "Superuser created successfully",
        "user": serialize_user(user),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }, None


def login_user(payload):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    if not email or not password:
        return None, "Missing email or password"
    if _is_login_rate_limited(email):
        return None, "Too many failed attempts. Please try again later."

    user = User.query.filter_by(email=email).first()
    if user is None or not check_password_hash(user.password_hash, password):
        _register_failed_login(email)
        return None, "Invalid credentials"

    if user.role not in VALID_ROLES or user.status not in VALID_USER_STATUSES:
        return None, "User account is not allowed"

    business = None
    if user.role != "superuser":
        target_business_id = get_primary_business_id(user.id)
        if target_business_id is not None:
            business = Business.query.get(target_business_id)
            if business is not None and business.status not in VALID_BUSINESS_STATUSES:
                return None, "Business account is not active"

    user.last_login_at = datetime.utcnow()

    access_token = _build_access_token(user)
    refresh_token = _create_refresh_token(user)

    db.session.commit()
    FAILED_LOGIN_ATTEMPTS.pop(email, None)
    log_audit_event(
        "auth.login",
        business_id=business.id if business else None,
        actor_user_id=user.id,
        metadata={"role": user.role},
    )
    db.session.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": serialize_user(user),
        "business": serialize_business(business) if business else None,
    }, None


def refresh_session(raw_refresh_token):
    if not raw_refresh_token:
        return None, "Missing refresh token"

    token_hash = _hash_refresh_token(raw_refresh_token)
    token = RefreshToken.query.filter_by(token_hash=token_hash).first()

    if token is None:
        return None, "Invalid refresh token"
    if token.revoked_at is not None:
        return None, "Refresh token revoked"
    if token.expires_at < datetime.utcnow():
        return None, "Refresh token expired"

    user = User.query.get(token.user_id)
    if user is None:
        return None, "Invalid refresh token user"

    token.revoked_at = datetime.utcnow()

    access_token = _build_access_token(user)
    new_refresh = _create_refresh_token(user)

    db.session.commit()

    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "user": serialize_user(user),
    }, None


def logout_session(raw_refresh_token):
    if not raw_refresh_token:
        return None, "Missing refresh token"

    token_hash = _hash_refresh_token(raw_refresh_token)
    token = RefreshToken.query.filter_by(token_hash=token_hash).first()

    if token is None:
        return {"message": "Logout successful"}, None

    if token.revoked_at is None:
        token.revoked_at = datetime.utcnow()
        db.session.commit()
        log_audit_event(
            "auth.logout",
            business_id=None,
            actor_user_id=token.user_id,
        )
        db.session.commit()

    return {"message": "Logout successful"}, None


def create_user_by_actor(actor_user, payload):
    full_name = (payload.get("full_name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    role = (payload.get("role") or "").strip().lower()
    requested_business_id = payload.get("business_id")
    membership_role = (payload.get("membership_role") or "").strip().lower()

    if not full_name or not email or not password or not role:
        return None, "Missing required fields"
    if role not in VALID_ROLES:
        return None, "Invalid role"
    if role == "general" and membership_role not in MEMBERSHIP_ROLES:
        return None, "membership_role is required and must be one of admin|manager|agent|viewer"
    if User.query.filter_by(email=email).first() is not None:
        return None, "Email already exists"
    business_id = None

    if actor_user.role not in {"stuff", "superuser"}:
        return None, "Only stuff or superuser can create users from this endpoint"

    if actor_user.role == "stuff":
        if role != "general":
            return None, "Stuff can create only general users"
        if not requested_business_id:
            return None, "business_id is required for general user creation"

        target_business = Business.query.get(int(requested_business_id))
        if target_business is None:
            return None, "Business not found"
        if target_business.status not in VALID_BUSINESS_STATUSES:
            return None, "Business account is not active"
        if target_business.owner_user_id != actor_user.id:
            return None, "Stuff can only create users for owned business"
        business_id = target_business.id

    if actor_user.role == "superuser":
        if role == "general":
            if not requested_business_id:
                return None, "business_id is required for general user creation"
            target_business = Business.query.get(int(requested_business_id))
            if target_business is None:
                return None, "Business not found"
            if target_business.status not in VALID_BUSINESS_STATUSES:
                return None, "Business account is not active"
            business_id = target_business.id
        elif role not in {"superuser", "stuff"}:
            return None, "Superuser can create only superuser, stuff, or general users"

    user = User(
        full_name=full_name,
        email=email,
        password_hash=generate_password_hash(password),
        role=role,
        status="active",
    )
    if business_id is not None:
        can_add, limit_error = can_add_user_to_business(business_id)
        if not can_add:
            return None, limit_error
    db.session.add(user)
    db.session.flush()

    if role == "general":
        db.session.add(
            WorkspaceMembership(
                business_id=business_id,
                user_id=user.id,
                role=membership_role,
                status="active",
            )
        )

    db.session.commit()
    log_audit_event(
        "auth.user_created",
        business_id=business_id,
        actor_user_id=actor_user.id,
        metadata={"created_user_id": user.id, "role": user.role},
    )
    db.session.commit()

    return {"message": "User created successfully", "user": serialize_user(user)}, None


def assign_general_membership(actor_user, user_id, payload):
    business_id = payload.get("business_id")
    membership_role = (payload.get("membership_role") or payload.get("role") or "").strip().lower()
    status = (payload.get("status") or "active").strip().lower()

    if not business_id:
        return None, "business_id is required"
    if membership_role not in MEMBERSHIP_ROLES:
        return None, "membership_role is required and must be one of admin|manager|agent|viewer"
    if status not in {"active", "inactive", "suspended"}:
        return None, "Invalid membership status"

    user = User.query.get(int(user_id))
    if user is None:
        return None, "User not found"
    if user.role != "general":
        return None, "Only general users can be assigned via this endpoint"

    business = Business.query.get(int(business_id))
    if business is None:
        return None, "Business not found"

    if actor_user.role == "stuff" and business.owner_user_id != actor_user.id:
        return None, "Stuff can only manage memberships for owned business"
    if actor_user.role not in {"superuser", "stuff"}:
        return None, "Only superuser or stuff can manage general memberships"

    membership = WorkspaceMembership.query.filter_by(
        business_id=business.id,
        user_id=user.id,
    ).first()

    action = "created"
    if membership is None:
        membership = WorkspaceMembership(
            business_id=business.id,
            user_id=user.id,
            role=membership_role,
            status=status,
        )
        db.session.add(membership)
    else:
        action = "updated"
        membership.role = membership_role
        membership.status = status

    db.session.commit()
    log_audit_event(
        "workspace.membership_upserted",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={
            "action": action,
            "target_user_id": user.id,
            "membership_id": membership.id,
            "role": membership.role,
            "status": membership.status,
        },
    )
    db.session.commit()

    return {
        "message": f"Membership {action} successfully",
        "membership": {
            "id": membership.id,
            "business_id": membership.business_id,
            "user_id": membership.user_id,
            "membership_role": membership.role,
            "status": membership.status,
            "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
        },
    }, None


def remove_general_membership(actor_user, user_id, payload):
    business_id = payload.get("business_id")
    if not business_id:
        return None, "business_id is required"

    user = User.query.get(int(user_id))
    if user is None:
        return None, "User not found"
    if user.role != "general":
        return None, "Only general users can be removed via this endpoint"

    business = Business.query.get(int(business_id))
    if business is None:
        return None, "Business not found"

    if actor_user.role == "stuff" and business.owner_user_id != actor_user.id:
        return None, "Stuff can only manage memberships for owned business"
    if actor_user.role not in {"superuser", "stuff"}:
        return None, "Only superuser or stuff can manage general memberships"

    membership = WorkspaceMembership.query.filter_by(
        business_id=business.id,
        user_id=user.id,
    ).first()
    if membership is None:
        return None, "Membership not found"

    db.session.delete(membership)
    db.session.commit()
    log_audit_event(
        "workspace.membership_deleted",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={
            "target_user_id": user.id,
            "membership_id": membership.id,
        },
    )
    db.session.commit()

    return {"message": "Membership removed successfully"}, None
