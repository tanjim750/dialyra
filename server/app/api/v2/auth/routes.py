from flask import Blueprint, g, jsonify, request

from app.api.v2.auth.service import (
    list_users_by_actor,
    assign_general_membership,
    remove_general_membership,
    bootstrap_superuser,
    create_user_by_actor,
    login_user,
    logout_session,
    refresh_session,
    register_owner,
    serialize_business,
    serialize_user,
)
from app.middleware.permissions_v2 import (
    jwt_context_required,
    require_permission,
    require_same_business,
    require_stuff_or_superuser,
    require_superuser,
)
from app.models import AuditLog
from app.models import Business
from app.models import WorkspaceMembership
from app.services.user_workspace import get_primary_business_id

bp = Blueprint("auth_v2", __name__, url_prefix="/api/v2/auth")


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
    if user.role != "superuser":
        membership = (
            WorkspaceMembership.query.filter_by(user_id=user.id, status="active")
            .order_by(WorkspaceMembership.joined_at.asc())
            .first()
        )
        target_business_id = membership.business_id if membership is not None else get_primary_business_id(user.id)
        if target_business_id:
            business = Business.query.get(target_business_id)
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
def create_user():
    actor_user = g.actor_user
    payload = request.get_json(silent=True) or {}
    result, error = create_user_by_actor(actor_user, payload)
    return _user_create_response(result, error)


def _user_create_response(result, error):
    if error:
        if error in {
            "Only stuff or superuser can create users from this endpoint",
            "Superuser can create only superuser, stuff, or general users",
            "Only general user creation is allowed on this endpoint",
            "Stuff can only create users for owned business",
            "Stuff can create only general users",
        }:
            return jsonify({"error": error}), 403
        if error in {
            "Business not found",
            "Business account is not active",
            "Invalid role",
            "Missing required fields",
            "business_id is required for general user creation",
            "membership_role is required and must be one of admin|manager|agent|viewer",
            "Stuff account has no business",
            "Email already exists",
        }:
            return jsonify({"error": error}), 400
        return jsonify({"error": error}), 400

    return jsonify(result), 201


@bp.get("/users")
@bp.get("/users/")
@jwt_context_required
@require_stuff_or_superuser
def list_users():
    result, error = list_users_by_actor(g.actor_user)
    if error:
        return jsonify({"error": error}), 403
    return jsonify(result), 200


@bp.post("/users/<int:user_id>/membership")
@bp.put("/users/<int:user_id>/membership")
@jwt_context_required
@require_stuff_or_superuser
def upsert_user_membership(user_id):
    payload = request.get_json(silent=True) or {}
    result, error = assign_general_membership(g.actor_user, user_id, payload)
    if error:
        if error in {
            "Stuff can only manage memberships for owned business",
            "Only superuser or stuff can manage general memberships",
        }:
            return jsonify({"error": error}), 403
        if error in {
            "business_id is required",
            "membership_role is required and must be one of admin|manager|agent|viewer",
            "Invalid membership status",
            "Only general users can be assigned via this endpoint",
        }:
            return jsonify({"error": error}), 400
        if error in {"User not found", "Business not found"}:
            return jsonify({"error": error}), 404
        return jsonify({"error": error}), 400

    return jsonify(result), 200


@bp.delete("/users/<int:user_id>/membership")
@jwt_context_required
@require_stuff_or_superuser
def delete_user_membership(user_id):
    payload = request.get_json(silent=True) or {}
    result, error = remove_general_membership(g.actor_user, user_id, payload)
    if error:
        if error in {
            "Stuff can only manage memberships for owned business",
            "Only superuser or stuff can manage general memberships",
        }:
            return jsonify({"error": error}), 403
        if error in {
            "business_id is required",
            "Only general users can be removed via this endpoint",
        }:
            return jsonify({"error": error}), 400
        if error in {"User not found", "Business not found", "Membership not found"}:
            return jsonify({"error": error}), 404
        return jsonify({"error": error}), 400
    return jsonify(result), 200


@bp.get("/authz-diffs")
@jwt_context_required
@require_superuser
def list_authz_diffs():
    limit_arg = request.args.get("limit", "100")
    actor_user_id_arg = request.args.get("actor_user_id")
    business_id_arg = request.args.get("business_id")

    try:
        limit = int(limit_arg)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid limit"}), 400
    if limit <= 0:
        return jsonify({"error": "limit must be positive"}), 400
    limit = min(limit, 500)

    query = AuditLog.query.filter_by(action="authz.decision_diff")

    if actor_user_id_arg is not None:
        try:
            actor_user_id = int(actor_user_id_arg)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid actor_user_id"}), 400
        query = query.filter_by(actor_user_id=actor_user_id)

    if business_id_arg is not None:
        try:
            business_id = int(business_id_arg)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid business_id"}), 400
        query = query.filter_by(business_id=business_id)

    rows = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    items = []
    for row in rows:
        metadata = {}
        try:
            import json

            metadata = json.loads(row.metadata_json or "{}")
        except Exception:
            metadata = {"raw": row.metadata_json}
        items.append(
            {
                "id": row.id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "actor_user_id": row.actor_user_id,
                "business_id": row.business_id,
                "action": row.action,
                "metadata": metadata,
            }
        )

    return jsonify({"items": items, "count": len(items)}), 200
