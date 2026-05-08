from flask import Blueprint, g, jsonify, request

from app.api.v1.access_tokens.service import (
    create_access_token,
    delete_access_token,
    get_access_token,
    list_access_tokens,
    revoke_access_token,
)
from app.middleware.permissions import jwt_context_required, require_roles
from app.middleware.permissions import require_permission

bp = Blueprint("access_tokens", __name__, url_prefix="/api/access-tokens")


@bp.post("")
@jwt_context_required
@require_roles("superuser", "stuff")
@require_permission("access_tokens.manage")
def create_access_token_endpoint():
    payload = request.get_json(silent=True) or {}
    result, error = create_access_token(g.actor_user, payload)
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 201


@bp.get("")
@jwt_context_required
@require_roles("superuser", "stuff")
@require_permission("access_tokens.manage")
def list_access_tokens_endpoint():
    business_id = request.args.get("business_id")
    result, error = list_access_tokens(g.actor_user, business_id=business_id)
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"items": result}), 200


@bp.get("/<int:token_id>")
@jwt_context_required
@require_roles("superuser", "stuff")
@require_permission("access_tokens.manage")
def get_access_token_endpoint(token_id):
    result, error = get_access_token(g.actor_user, token_id)
    if error:
        status = 404 if error == "Access token not found" else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/<int:token_id>/revoke")
@jwt_context_required
@require_roles("superuser", "stuff")
@require_permission("access_tokens.manage")
def revoke_access_token_endpoint(token_id):
    result, error = revoke_access_token(g.actor_user, token_id)
    if error:
        status = 404 if error == "Access token not found" else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.delete("/<int:token_id>")
@jwt_context_required
@require_roles("superuser", "stuff")
@require_permission("access_tokens.manage")
def delete_access_token_endpoint(token_id):
    result, error = delete_access_token(g.actor_user, token_id)
    if error:
        status = 404 if error == "Access token not found" else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200
