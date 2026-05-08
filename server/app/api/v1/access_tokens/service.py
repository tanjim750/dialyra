import hashlib
import json
import secrets
from datetime import datetime, timedelta

from flask import current_app

from app.extensions import db
from app.models import Business, BusinessAccessToken
from app.services.audit_service import log_audit_event

TOKEN_PREFIX = "dialyra_live_"
DEFAULT_TOKEN_EXPIRY_DAYS = 365


ALLOWED_SCOPES = {
    "calls:originate",
    "calls:read",
    "fastagi:runtime",
    "flow:resolve",
    "events:write",
    "audio:read",
    "campaigns:execute",
}


def _hash_token(raw_token):
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _parse_scopes(raw_scopes):
    if not isinstance(raw_scopes, list) or not raw_scopes:
        return None, "scopes must be a non-empty array"

    normalized = []
    for scope in raw_scopes:
        if not isinstance(scope, str):
            return None, "All scopes must be strings"
        value = scope.strip()
        if value not in ALLOWED_SCOPES:
            return None, f"Invalid scope: {value}"
        normalized.append(value)

    unique_scopes = sorted(set(normalized))
    return unique_scopes, None


def _serialize_scopes(scopes_text):
    if not scopes_text:
        return []
    try:
        parsed = json.loads(scopes_text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return []


def serialize_access_token(token_model):
    return {
        "id": token_model.id,
        "business_id": token_model.business_id,
        "name": token_model.name,
        "token_prefix": token_model.token_prefix,
        "scopes": _serialize_scopes(token_model.scopes),
        "is_active": token_model.is_active,
        "last_used_at": token_model.last_used_at.isoformat() if token_model.last_used_at else None,
        "expires_at": token_model.expires_at.isoformat() if token_model.expires_at else None,
        "created_by": token_model.created_by,
        "created_at": token_model.created_at.isoformat() if token_model.created_at else None,
        "revoked_at": token_model.revoked_at.isoformat() if token_model.revoked_at else None,
    }


def _resolve_target_business(actor_user, business_id):
    if actor_user.role == "superuser":
        if not business_id:
            return None, "business_id is required for superuser"
        business = Business.query.get(int(business_id))
        if business is None:
            return None, "Business not found"
        return business, None

    if actor_user.role == "stuff":
        if not actor_user.business_id:
            return None, "Stuff account has no business"
        business = Business.query.get(actor_user.business_id)
        if business is None:
            return None, "Business not found"
        if business_id and int(business_id) != business.id:
            return None, "Cross-business access denied"
        return business, None

    return None, "Only superuser or stuff can manage access tokens"


def create_access_token(actor_user, payload):
    name = (payload.get("name") or "").strip()
    raw_scopes = payload.get("scopes")
    business_id = payload.get("business_id")
    expires_days = payload.get("expires_days")

    if not name:
        return None, "Missing required field: name"

    scopes, scope_error = _parse_scopes(raw_scopes)
    if scope_error:
        return None, scope_error

    business, business_error = _resolve_target_business(actor_user, business_id)
    if business_error:
        return None, business_error

    if expires_days is None:
        expires_days = int(current_app.config.get("ACCESS_TOKEN_EXPIRES_DAYS", DEFAULT_TOKEN_EXPIRY_DAYS))
    try:
        expires_days = int(expires_days)
    except (TypeError, ValueError):
        return None, "expires_days must be an integer"
    if expires_days <= 0:
        return None, "expires_days must be positive"

    random_part = secrets.token_urlsafe(32)
    raw_token = f"{TOKEN_PREFIX}{random_part}"
    token_hash = _hash_token(raw_token)
    token_prefix = raw_token[:20]

    token_model = BusinessAccessToken(
        business_id=business.id,
        name=name,
        token_prefix=token_prefix,
        token_hash=token_hash,
        scopes=json.dumps(scopes),
        is_active=True,
        expires_at=datetime.utcnow() + timedelta(days=expires_days),
        created_by=actor_user.id,
    )
    db.session.add(token_model)
    db.session.commit()
    log_audit_event(
        "access_token.created",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"access_token_id": token_model.id, "name": token_model.name},
    )
    db.session.commit()

    return {
        "token": raw_token,
        "message": "Save this token now. It will not be shown again.",
        "access_token": serialize_access_token(token_model),
    }, None


def list_access_tokens(actor_user, business_id=None):
    query = BusinessAccessToken.query

    if actor_user.role == "superuser":
        if business_id:
            query = query.filter_by(business_id=int(business_id))
    elif actor_user.role == "stuff":
        if not actor_user.business_id:
            return None, "Stuff account has no business"
        query = query.filter_by(business_id=actor_user.business_id)
        if business_id and int(business_id) != actor_user.business_id:
            return None, "Cross-business access denied"
    else:
        return None, "Only superuser or stuff can view access tokens"

    tokens = query.order_by(BusinessAccessToken.created_at.desc()).all()
    return [serialize_access_token(token) for token in tokens], None


def get_access_token(actor_user, token_id):
    token_model = BusinessAccessToken.query.get(token_id)
    if token_model is None:
        return None, "Access token not found"

    if actor_user.role == "stuff" and token_model.business_id != actor_user.business_id:
        return None, "Cross-business access denied"
    if actor_user.role not in {"superuser", "stuff"}:
        return None, "Only superuser or stuff can view access tokens"

    return serialize_access_token(token_model), None


def revoke_access_token(actor_user, token_id):
    token_model = BusinessAccessToken.query.get(token_id)
    if token_model is None:
        return None, "Access token not found"

    if actor_user.role == "stuff" and token_model.business_id != actor_user.business_id:
        return None, "Cross-business access denied"
    if actor_user.role not in {"superuser", "stuff"}:
        return None, "Only superuser or stuff can revoke access tokens"

    token_model.is_active = False
    token_model.revoked_at = datetime.utcnow()
    db.session.commit()
    log_audit_event(
        "access_token.revoked",
        business_id=token_model.business_id,
        actor_user_id=actor_user.id,
        metadata={"access_token_id": token_model.id},
    )
    db.session.commit()

    return {"message": "Access token revoked", "access_token": serialize_access_token(token_model)}, None


def delete_access_token(actor_user, token_id):
    token_model = BusinessAccessToken.query.get(token_id)
    if token_model is None:
        return None, "Access token not found"

    if actor_user.role == "stuff" and token_model.business_id != actor_user.business_id:
        return None, "Cross-business access denied"
    if actor_user.role not in {"superuser", "stuff"}:
        return None, "Only superuser or stuff can delete access tokens"

    db.session.delete(token_model)
    db.session.commit()
    log_audit_event(
        "access_token.deleted",
        business_id=token_model.business_id,
        actor_user_id=actor_user.id,
        metadata={"access_token_id": token_model.id},
    )
    db.session.commit()

    return {"message": "Access token deleted"}, None
