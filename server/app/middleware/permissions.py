import hashlib
import json
from datetime import datetime
from functools import wraps

from flask import g, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db
from app.models import Business, BusinessAccessToken, User

VALID_USER_STATUSES = {"active"}
VALID_BUSINESS_STATUSES = {"active"}
ROLE_PERMISSIONS = {
    "superuser": {
        "businesses.read",
        "businesses.manage",
        "settings.manage",
        "access_tokens.manage",
        "members.manage",
    },
    "owner": {
        "businesses.read",
        "businesses.manage",
        "settings.manage",
        "access_tokens.manage",
        "members.manage",
    },
    "admin": {
        "businesses.read",
        "businesses.manage",
        "settings.manage",
        "access_tokens.manage",
        "members.manage",
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

        if actor_user.role != "superuser":
            if not actor_user.business_id:
                return jsonify({"error": "User business is not configured"}), 403
            business = Business.query.get(actor_user.business_id)
            if business is None:
                return jsonify({"error": "Business not found"}), 404
            if business.status not in VALID_BUSINESS_STATUSES:
                return jsonify({"error": "Business is not active"}), 403
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
            allowed = ROLE_PERMISSIONS.get(actor_user.role, set())
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
        if actor_user.role not in {"superuser", "owner", "admin"}:
            return jsonify({"error": "Owner/Admin or superuser role required"}), 403
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

            if actor_user.role not in {"owner", "admin"}:
                return jsonify({"error": "Same-business permission denied"}), 403

            payload = request.get_json(silent=True) or {}
            target_business_id = payload.get(payload_key)
            if target_business_id is None:
                return fn(*args, **kwargs)

            try:
                normalized_target = int(target_business_id)
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid business_id"}), 400

            if actor_user.business_id != normalized_target:
                return jsonify({"error": "Cross-business access denied"}), 403

            return fn(*args, **kwargs)

        return wrapper

    return decorator


def assert_same_business(resource_business_id):
    actor_user = _load_actor_user()
    if actor_user is None:
        return jsonify({"error": "Actor user not found"}), 404
    if actor_user.role == "superuser":
        return None
    if actor_user.business_id != resource_business_id:
        return jsonify({"error": "Cross-business access denied"}), 403
    return None


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

            if actor_user.role != "superuser" and actor_user.business_id != business_id:
                return jsonify({"error": "Cross-business access denied"}), 403

            g.target_business = business
            return fn(*args, **kwargs)

        return wrapper

    return decorator
