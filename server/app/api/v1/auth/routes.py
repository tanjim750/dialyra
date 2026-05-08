from flask import Blueprint, g, jsonify, request

from app.api.v1.auth.service import (
    bootstrap_superuser,
    create_user_by_actor,
    create_user_with_role_by_actor,
    login_user,
    logout_session,
    refresh_session,
    register_owner,
    serialize_business,
    serialize_user,
)
from app.middleware.permissions import (
    jwt_context_required,
    require_same_business,
    require_stuff_or_superuser,
    require_superuser,
)
from app.models import Business

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/register")
def register():
    payload = request.get_json(silent=True) or {}
    result, error = register_owner(payload)
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 201


@bp.post("/bootstrap-superuser")
def create_first_superuser():
    from flask import current_app

    if not current_app.config.get("BOOTSTRAP_SUPERUSER_ENABLED", False):
        return jsonify({"error": "Bootstrap endpoint is disabled"}), 403

    expected_secret = current_app.config.get("BOOTSTRAP_SUPERUSER_SECRET", "")
    provided_secret = request.headers.get("X-Bootstrap-Secret", "")
    if not expected_secret or provided_secret != expected_secret:
        return jsonify({"error": "Invalid bootstrap secret"}), 401

    payload = request.get_json(silent=True) or {}
    result, error = bootstrap_superuser(payload)
    if error:
        if error == "Superuser already exists":
            return jsonify({"error": error}), 409
        return jsonify({"error": error}), 400
    return jsonify(result), 201


@bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    result, error = login_user(payload)
    if error:
        return jsonify({"error": error}), 401
    return jsonify(result), 200


@bp.post("/refresh")
def refresh():
    payload = request.get_json(silent=True) or {}
    raw_refresh_token = payload.get("refresh_token")
    result, error = refresh_session(raw_refresh_token)
    if error:
        return jsonify({"error": error}), 401
    return jsonify(result), 200


@bp.post("/logout")
def logout():
    payload = request.get_json(silent=True) or {}
    raw_refresh_token = payload.get("refresh_token")
    result, error = logout_session(raw_refresh_token)
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 200


@bp.get("/me")
@jwt_context_required
def me():
    user = g.actor_user

    business = None
    if user.role != "superuser" and user.business_id:
        business = Business.query.get(user.business_id)
        if business is None:
            return jsonify({"error": "Business not found"}), 404

    return (
        jsonify(
            {
                "user": serialize_user(user),
                "business": serialize_business(business) if business else None,
            }
        ),
        200,
    )


@bp.post("/users")
@bp.post("/users/")
@jwt_context_required
@require_stuff_or_superuser
@require_same_business("business_id")
def create_user():
    actor_user = g.actor_user
    payload = request.get_json(silent=True) or {}
    result, error = create_user_by_actor(actor_user, payload)
    return _user_create_response(result, error)


@bp.post("/users/superuser")
@jwt_context_required
@require_superuser
def create_superuser():
    actor_user = g.actor_user
    payload = request.get_json(silent=True) or {}
    result, error = create_user_with_role_by_actor(actor_user, payload, "superuser")
    return _user_create_response(result, error)


@bp.post("/users/owner")
@jwt_context_required
@require_superuser
def create_owner():
    actor_user = g.actor_user
    payload = request.get_json(silent=True) or {}
    result, error = create_user_with_role_by_actor(actor_user, payload, "owner")
    return _user_create_response(result, error)


@bp.post("/users/admin")
@jwt_context_required
@require_stuff_or_superuser
@require_same_business("business_id")
def create_admin():
    actor_user = g.actor_user
    payload = request.get_json(silent=True) or {}
    result, error = create_user_with_role_by_actor(actor_user, payload, "admin")
    return _user_create_response(result, error)


@bp.post("/users/manager")
@jwt_context_required
@require_stuff_or_superuser
@require_same_business("business_id")
def create_manager():
    actor_user = g.actor_user
    payload = request.get_json(silent=True) or {}
    result, error = create_user_with_role_by_actor(actor_user, payload, "manager")
    return _user_create_response(result, error)


@bp.post("/users/agent")
@jwt_context_required
@require_stuff_or_superuser
@require_same_business("business_id")
def create_agent():
    actor_user = g.actor_user
    payload = request.get_json(silent=True) or {}
    result, error = create_user_with_role_by_actor(actor_user, payload, "agent")
    return _user_create_response(result, error)


@bp.post("/users/viewer")
@jwt_context_required
@require_stuff_or_superuser
@require_same_business("business_id")
def create_viewer():
    actor_user = g.actor_user
    payload = request.get_json(silent=True) or {}
    result, error = create_user_with_role_by_actor(actor_user, payload, "viewer")
    return _user_create_response(result, error)


def _user_create_response(result, error):
    if error:
        if error in {
            "Only superuser, owner or admin can create users",
            "Owner/Admin cannot create superuser or owner",
        }:
            return jsonify({"error": error}), 403
        if error in {
            "Business not found",
            "Invalid role",
            "Missing required fields",
            "business_id is required for non-superuser users",
            "Owner/Admin account has no business",
            "Email already exists",
        }:
            return jsonify({"error": error}), 400
        return jsonify({"error": error}), 400

    return jsonify(result), 201
