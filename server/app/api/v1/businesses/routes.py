from flask import Blueprint, g, jsonify, request

from app.api.v1.businesses.service import (
    add_member,
    create_business,
    get_business,
    get_business_settings,
    list_members,
    list_businesses,
    remove_member,
    soft_delete_business,
    transfer_ownership,
    update_member,
    update_business,
    update_business_settings,
)
from app.middleware.permissions import (
    jwt_context_required,
    require_business_access,
    require_permission,
)

bp = Blueprint("businesses", __name__, url_prefix="/api/businesses")


@bp.post("")
@jwt_context_required
@require_permission("businesses.manage")
def create_business_endpoint():
    payload = request.get_json(silent=True) or {}
    result, error = create_business(g.actor_user, payload)
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 201


@bp.get("")
@jwt_context_required
@require_permission("businesses.read")
def list_businesses_endpoint():
    result, error = list_businesses(g.actor_user)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"items": result}), 200


@bp.get("/<int:business_id>")
@jwt_context_required
@require_permission("businesses.read")
@require_business_access("business_id")
def get_business_endpoint(business_id):
    result, error = get_business(g.actor_user, g.target_business)
    if error:
        return jsonify({"error": error}), 403
    return jsonify(result), 200


@bp.put("/<int:business_id>")
@jwt_context_required
@require_permission("businesses.manage")
@require_business_access("business_id")
def update_business_endpoint(business_id):
    payload = request.get_json(silent=True) or {}
    result, error = update_business(g.actor_user, g.target_business, payload)
    if error:
        status = 403 if error == "Cross-business access denied" else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.delete("/<int:business_id>")
@jwt_context_required
@require_permission("businesses.manage")
@require_business_access("business_id")
def delete_business_endpoint(business_id):
    result, error = soft_delete_business(g.actor_user, g.target_business)
    if error:
        status = 403 if error == "Cross-business access denied" else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.get("/<int:business_id>/settings")
@jwt_context_required
@require_permission("businesses.read")
@require_business_access("business_id")
def get_business_settings_endpoint(business_id):
    result, error = get_business_settings(g.actor_user, g.target_business)
    if error:
        return jsonify({"error": error}), 403
    return jsonify(result), 200


@bp.put("/<int:business_id>/settings")
@jwt_context_required
@require_permission("settings.manage")
@require_business_access("business_id")
def update_business_settings_endpoint(business_id):
    payload = request.get_json(silent=True) or {}
    result, error = update_business_settings(g.actor_user, g.target_business, payload)
    if error:
        status = 403 if error == "Cross-business access denied" else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/<int:business_id>/members")
@jwt_context_required
@require_permission("members.manage")
@require_business_access("business_id")
def add_member_endpoint(business_id):
    payload = request.get_json(silent=True) or {}
    result, error = add_member(g.actor_user, g.target_business, payload)
    if error:
        status = 404 if error in {"Business not found", "User not found"} else 400
        return jsonify({"error": error}), status
    return jsonify(result), 201


@bp.get("/<int:business_id>/members")
@jwt_context_required
@require_permission("businesses.read")
@require_business_access("business_id")
def list_members_endpoint(business_id):
    result, error = list_members(g.actor_user, g.target_business)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"items": result}), 200


@bp.put("/<int:business_id>/members/<int:member_id>")
@jwt_context_required
@require_permission("members.manage")
@require_business_access("business_id")
def update_member_endpoint(business_id, member_id):
    payload = request.get_json(silent=True) or {}
    result, error = update_member(g.actor_user, g.target_business, member_id, payload)
    if error:
        status = 404 if error == "Member not found" else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.delete("/<int:business_id>/members/<int:member_id>")
@jwt_context_required
@require_permission("members.manage")
@require_business_access("business_id")
def remove_member_endpoint(business_id, member_id):
    result, error = remove_member(g.actor_user, g.target_business, member_id)
    if error:
        status = 404 if error == "Member not found" else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/<int:business_id>/transfer-ownership")
@jwt_context_required
@require_permission("businesses.manage")
@require_business_access("business_id")
def transfer_ownership_endpoint(business_id):
    payload = request.get_json(silent=True) or {}
    result, error = transfer_ownership(g.actor_user, g.target_business, payload)
    if error:
        status = 404 if error in {"Target user not found"} else 403 if error in {"Only current owner can transfer ownership"} else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200
