import hashlib
import json
from datetime import datetime
from functools import wraps

from flask import g, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db
from app.models import Business, BusinessAccessToken, User, WorkspaceMembership
from app.services.authz_resolver import get_active_membership, resolve_target_business_id
from app.services.user_workspace import get_primary_business_id

VALID_USER_STATUSES = {"active"}
VALID_BUSINESS_STATUSES = {"active"}

PLATFORM_ROLE_PERMISSIONS = {
    "superuser": {
        "businesses.read",
        "businesses.manage",
        "settings.manage",
        "access_tokens.manage",
        "members.manage",
        "users.create",
    },
}

MEMBERSHIP_ROLE_PERMISSIONS = {
    "owner": {
        "businesses.read",
        "businesses.manage",
        "settings.manage",
        "access_tokens.manage",
        "members.manage",
        "users.create",
    },
    "admin": {
        "businesses.read",
        "businesses.manage",
        "settings.manage",
        "access_tokens.manage",
        "members.manage",
        "users.create",
    },
    "manager": {"businesses.read"},
    "agent": {"businesses.read"},
    "viewer": {"businesses.read"},
}


def _load_actor_user():
    actor_user = getattr(g, "actor_user", None)
    if actor_user is not None:
        return actor_user
    user_id = get_jwt_identity()
    if user_id is None:
        return None
    actor_user = User.query.get(int(user_id))
    if actor_user is not None:
        g.actor_user = actor_user
    return actor_user


def jwt_context_required(fn):
    @jwt_required()
    @wraps(fn)
    def wrapper(*args, **kwargs):
        actor_user = _load_actor_user()
        if actor_user is None:
            return jsonify({"error": "Actor user not found"}), 404
        if actor_user.status not in VALID_USER_STATUSES:
            return jsonify({"error": "User account is not active"}), 403

        g.auth_type = "jwt"
        g.actor_business = None
        actor_business_id = get_primary_business_id(actor_user.id)
        if actor_business_id:
            business = Business.query.get(actor_business_id)
            if business is not None and business.status in VALID_BUSINESS_STATUSES:
                g.actor_business = business
        return fn(*args, **kwargs)

    return wrapper


def require_roles(*allowed_roles):
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor_user = _load_actor_user()
            if actor_user is None:
                return jsonify({"error": "Actor user not found"}), 404
            if actor_user.role not in allowed:
                return jsonify({"error": "Insufficient role permission"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_permission(permission):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor_user = _load_actor_user()
            if actor_user is None:
                return jsonify({"error": "Actor user not found"}), 404
            if actor_user.role == "superuser":
                allowed = PLATFORM_ROLE_PERMISSIONS.get("superuser", set())
                if permission not in allowed:
                    return jsonify({"error": "Insufficient permission"}), 403
                return fn(*args, **kwargs)

            # Allow stuff users to create their first business without requiring
            # a pre-existing workspace membership.
            if (
                actor_user.role == "stuff"
                and permission == "businesses.manage"
                and request.method == "POST"
                and request.path.rstrip("/") == "/api/v2/businesses"
            ):
                return fn(*args, **kwargs)

            target_business_id = resolve_target_business_id(
                default_business_id=get_primary_business_id(actor_user.id)
            )
            if target_business_id is None:
                target_business_id = get_primary_business_id(actor_user.id)
            membership = get_active_membership(actor_user.id, target_business_id)
            if membership is None:
                return jsonify({"error": "Business membership is not active"}), 403
            allowed = MEMBERSHIP_ROLE_PERMISSIONS.get(membership.role, set())
            if permission not in allowed:
                return jsonify({"error": "Insufficient permission"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def _looks_like_jwt(token):
    return token.count(".") == 2


def _extract_access_token():
    token = request.headers.get("X-Dialyra-Access-Token")
    if token:
        normalized = token.strip()
        if _looks_like_jwt(normalized):
            return None, "JWT tokens are not allowed on this endpoint"
        return normalized, None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        bearer_token = auth_header.split(" ", 1)[1].strip()
        if _looks_like_jwt(bearer_token):
            return None, "JWT tokens are not allowed on this endpoint"
        return bearer_token, None
    return None, "Missing access token"


def _parse_token_scopes(scopes_text):
    if not scopes_text:
        return set()
    try:
        parsed = json.loads(scopes_text)
        if isinstance(parsed, list):
            return {scope for scope in parsed if isinstance(scope, str)}
    except json.JSONDecodeError:
        pass
    return set()


def access_token_context_required(*required_scopes):
    required_scope_set = set(required_scopes)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            raw_token, token_error = _extract_access_token()
            if token_error:
                status = 401 if token_error == "Missing access token" else 403
                return jsonify({"error": token_error}), status
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            token_model = BusinessAccessToken.query.filter_by(token_hash=token_hash).first()
            if token_model is None:
                return jsonify({"error": "Invalid access token"}), 401
            if not token_model.is_active or token_model.revoked_at is not None:
                return jsonify({"error": "Access token is revoked"}), 403
            if token_model.expires_at is not None and token_model.expires_at <= datetime.utcnow():
                return jsonify({"error": "Access token is expired"}), 403
            token_scopes = _parse_token_scopes(token_model.scopes)
            missing_scopes = sorted(required_scope_set - token_scopes)
            if missing_scopes:
                return jsonify({"error": "Missing required scopes", "missing_scopes": missing_scopes}), 403
            business = Business.query.get(token_model.business_id)
            if business is None:
                return jsonify({"error": "Business not found"}), 404
            if business.status not in VALID_BUSINESS_STATUSES:
                return jsonify({"error": "Business is not active"}), 403
            token_model.last_used_at = datetime.utcnow()
            db.session.commit()
            g.auth_type = "access_token"
            g.actor_user = None
            g.actor_business = business
            g.access_token = token_model
            g.scopes = sorted(token_scopes)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_superuser(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        actor_user = _load_actor_user()
        if actor_user is None:
            return jsonify({"error": "Actor user not found"}), 404
        if actor_user.role != "superuser":
            return jsonify({"error": "Superuser role required"}), 403
        return fn(*args, **kwargs)

    return wrapper


def require_stuff_or_superuser(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        actor_user = _load_actor_user()
        if actor_user is None:
            return jsonify({"error": "Actor user not found"}), 404
        if actor_user.role not in {"superuser", "stuff"}:
            return jsonify({"error": "Stuff or superuser role required"}), 403
        return fn(*args, **kwargs)

    return wrapper


def require_same_business(payload_key="business_id"):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor_user = _load_actor_user()
            if actor_user is None:
                return jsonify({"error": "Actor user not found"}), 404
            if actor_user.role == "superuser":
                return fn(*args, **kwargs)
            payload = request.get_json(silent=True) or {}
            target_business_id = payload.get(payload_key)
            if target_business_id is None:
                return fn(*args, **kwargs)
            try:
                normalized_target = int(target_business_id)
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid business_id"}), 400
            membership = get_active_membership(actor_user.id, normalized_target)
            if membership is None:
                return jsonify({"error": "Cross-business access denied"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_business_access(param_name="business_id"):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor_user = _load_actor_user()
            if actor_user is None:
                return jsonify({"error": "Actor user not found"}), 404
            raw_business_id = kwargs.get(param_name)
            if raw_business_id is None:
                return jsonify({"error": f"Missing path parameter: {param_name}"}), 400
            try:
                business_id = int(raw_business_id)
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid business id"}), 400
            business = Business.query.get(business_id)
            if business is None:
                return jsonify({"error": "Business not found"}), 404
            if business.status not in VALID_BUSINESS_STATUSES:
                return jsonify({"error": "Business is not active"}), 403
            if actor_user.role != "superuser":
                membership = get_active_membership(actor_user.id, business_id)
                if membership is None:
                    return jsonify({"error": "Cross-business access denied"}), 403
            g.target_business = business
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_business_membership(*roles, param_name="business_id"):
    allowed_roles = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor_user = _load_actor_user()
            if actor_user is None:
                return jsonify({"error": "Actor user not found"}), 404
            if actor_user.role == "superuser":
                return fn(*args, **kwargs)

            raw_business_id = kwargs.get(param_name)
            if raw_business_id is None:
                payload = request.get_json(silent=True) or {}
                raw_business_id = payload.get(param_name)
            if raw_business_id is None:
                raw_business_id = request.args.get(param_name)
            if raw_business_id is None:
                return jsonify({"error": f"Missing business context: {param_name}"}), 400

            try:
                business_id = int(raw_business_id)
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid business id"}), 400

            membership = get_active_membership(actor_user.id, business_id)
            if membership is None:
                return jsonify({"error": "Business membership is not active"}), 403
            if allowed_roles and membership.role not in allowed_roles:
                return jsonify({"error": "Membership role not allowed"}), 403

            return fn(*args, **kwargs)

        return wrapper

    return decorator
