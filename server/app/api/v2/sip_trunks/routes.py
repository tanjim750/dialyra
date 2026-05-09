from flask import Blueprint, g, jsonify, request

from app.api.v2.sip_trunks.service import (
    rollback_sip_trunk,
    create_sip_trunk,
    delete_sip_trunk,
    get_sip_trunk,
    list_sip_trunks,
    reload_sip_trunk,
    sip_trunk_status,
    sip_realtime_health,
    test_sip_trunk,
    update_sip_trunk,
)
from app.middleware.permissions_v2 import jwt_context_required, require_permission, require_superuser

bp = Blueprint("sip_trunks_v2", __name__, url_prefix="/api/v2/sip-trunks")


@bp.post("")
@jwt_context_required
@require_permission("businesses.manage")
def create_sip_trunk_endpoint():
    payload = request.get_json(silent=True) or {}
    result, error = create_sip_trunk(g.actor_user, payload)
    if error:
        status = 409 if error == "SIP trunk name already exists in this business" else 403 if "permission" in error.lower() else 404 if error == "Business not found" else 400
        return jsonify({"error": error}), status
    return jsonify(result), 201


@bp.get("")
@jwt_context_required
@require_permission("businesses.read")
def list_sip_trunks_endpoint():
    business_id = request.args.get("business_id")
    result, error = list_sip_trunks(g.actor_user, business_id=business_id)
    if error:
        status = 403 if "permission" in error.lower() else 404 if error == "Business not found" else 400
        return jsonify({"error": error}), status
    return jsonify({"items": result}), 200


@bp.get("/<int:trunk_id>")
@jwt_context_required
@require_permission("businesses.read")
def get_sip_trunk_endpoint(trunk_id):
    result, error = get_sip_trunk(g.actor_user, trunk_id)
    if error:
        status = 404 if error in {"SIP trunk not found", "Business not found"} else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.put("/<int:trunk_id>")
@jwt_context_required
@require_permission("businesses.manage")
def update_sip_trunk_endpoint(trunk_id):
    payload = request.get_json(silent=True) or {}
    result, error = update_sip_trunk(g.actor_user, trunk_id, payload)
    if error:
        status = 409 if error == "SIP trunk name already exists in this business" else 404 if error in {"SIP trunk not found", "Business not found"} else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.delete("/<int:trunk_id>")
@jwt_context_required
@require_permission("businesses.manage")
def delete_sip_trunk_endpoint(trunk_id):
    result, error = delete_sip_trunk(g.actor_user, trunk_id)
    if error:
        status = 404 if error in {"SIP trunk not found", "Business not found"} else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/<int:trunk_id>/test")
@jwt_context_required
@require_permission("businesses.manage")
def test_sip_trunk_endpoint(trunk_id):
    result, error = test_sip_trunk(g.actor_user, trunk_id)
    if error:
        status = 404 if error in {"SIP trunk not found", "Business not found"} else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/<int:trunk_id>/reload")
@jwt_context_required
@require_permission("businesses.manage")
def reload_sip_trunk_endpoint(trunk_id):
    result, error = reload_sip_trunk(g.actor_user, trunk_id)
    if error:
        status = 404 if error in {"SIP trunk not found", "Business not found"} else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/<int:trunk_id>/apply")
@jwt_context_required
@require_permission("businesses.manage")
def apply_sip_trunk_endpoint(trunk_id):
    result, error = reload_sip_trunk(g.actor_user, trunk_id)
    if error:
        status = 404 if error in {"SIP trunk not found", "Business not found"} else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/<int:trunk_id>/rollback")
@jwt_context_required
@require_permission("businesses.manage")
def rollback_sip_trunk_endpoint(trunk_id):
    result, error = rollback_sip_trunk(g.actor_user, trunk_id)
    if error:
        status = 404 if error in {"SIP trunk not found", "Business not found"} else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.get("/<int:trunk_id>/status")
@jwt_context_required
@require_permission("businesses.read")
def status_sip_trunk_endpoint(trunk_id):
    result, error = sip_trunk_status(g.actor_user, trunk_id)
    if error:
        status = 404 if error in {"SIP trunk not found", "Business not found"} else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.get("/realtime/health")
@jwt_context_required
@require_superuser
def sip_realtime_health_endpoint():
    result, _ = sip_realtime_health()
    return jsonify(result), 200
