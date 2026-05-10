from flask import Blueprint, current_app, g, jsonify, request

from app.api.v2.tts.service import (
    delete_tts_request,
    enqueue_tts,
    generate_tts,
    get_supported_languages,
    get_supported_voices,
    get_tts_request,
    list_tts_requests,
)
from app.api.v2.tts.worker_service import enqueue_tts_job, get_tts_worker_health
from app.middleware.permissions_v2 import jwt_context_required, require_permission

bp = Blueprint("tts_v2", __name__, url_prefix="/api/v2/tts")


@bp.post("/generate")
@jwt_context_required
@require_permission("businesses.manage")
def generate_tts_endpoint():
    payload = request.get_json(silent=True) or {}
    if bool(current_app.config.get("TTS_ASYNC_ENABLED", False)):
        result, error = enqueue_tts(g.actor_user, payload)
        if error:
            status = 404 if error == "Business not found" else 403 if "permission" in error.lower() else 400
            return jsonify({"error": error}), status
        if isinstance(result, dict) and result.get("status") == "queued":
            enqueue_tts_job(result["tts_request_id"], result["actor_user_id"])
            result = {k: v for k, v in result.items() if k not in {"tts_request_id", "actor_user_id"}}
            return jsonify(result), 202
        return jsonify(result), 200

    result, error = generate_tts(g.actor_user, payload)
    if error:
        status = 404 if error == "Business not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 201


@bp.get("")
@jwt_context_required
@require_permission("businesses.read")
def list_tts_endpoint():
    business_id = request.args.get("business_id")
    result, error = list_tts_requests(g.actor_user, business_id=business_id)
    if error:
        status = 404 if error == "Business not found" else 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify({"items": result}), 200


@bp.get("/<int:request_id>")
@jwt_context_required
@require_permission("businesses.read")
def get_tts_endpoint(request_id):
    result, error = get_tts_request(g.actor_user, request_id)
    if error:
        status = 404 if error in {"TTS request not found", "Business not found"} else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.delete("/<int:request_id>")
@jwt_context_required
@require_permission("businesses.manage")
def delete_tts_endpoint(request_id):
    result, error = delete_tts_request(g.actor_user, request_id)
    if error:
        status = 404 if error in {"TTS request not found", "Business not found"} else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.get("/voices")
@jwt_context_required
@require_permission("businesses.read")
def get_voices_endpoint():
    provider = request.args.get("provider")
    result, error = get_supported_voices(provider)
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 200


@bp.get("/languages")
@jwt_context_required
@require_permission("businesses.read")
def get_languages_endpoint():
    provider = request.args.get("provider")
    result, error = get_supported_languages(provider)
    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 200


@bp.get("/worker/health")
@jwt_context_required
@require_permission("businesses.read")
def tts_worker_health_endpoint():
    result = get_tts_worker_health()
    result["async_enabled"] = bool(current_app.config.get("TTS_ASYNC_ENABLED", False))
    return jsonify(result), 200
