from flask import Blueprint, g, jsonify, request
from flask import send_file

from app.api.v2.audio_assets.service import (
    delete_audio_asset,
    get_audio_asset,
    list_audio_assets,
    resolve_audio_asset_file,
    sync_audio_asset_to_asterisk,
    test_audio_asset_playback,
    update_audio_asset,
    upload_audio_asset,
)
from app.middleware.permissions_v2 import jwt_context_required, require_permission

bp = Blueprint("audio_assets_v2", __name__, url_prefix="/api/v2/audio-assets")


@bp.post("/upload")
@jwt_context_required
@require_permission("businesses.manage")
def upload_audio_asset_endpoint():
    result, error = upload_audio_asset(
        actor_user=g.actor_user,
        form_data=request.form,
        file_storage=request.files.get("file"),
    )
    if error:
        status = 404 if error == "Business not found" else 403 if "permission" in error.lower() else 409 if error == "Audio slug already exists in this business" else 400
        return jsonify({"error": error}), status
    return jsonify(result), 201


@bp.get("")
@jwt_context_required
@require_permission("businesses.read")
def list_audio_assets_endpoint():
    business_id = request.args.get("business_id")
    include_deleted = (request.args.get("include_deleted") or "false").strip().lower() == "true"
    result, error = list_audio_assets(
        actor_user=g.actor_user,
        business_id=business_id,
        include_deleted=include_deleted,
    )
    if error:
        status = 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify({"items": result}), 200


@bp.get("/<int:asset_id>")
@jwt_context_required
@require_permission("businesses.read")
def get_audio_asset_endpoint(asset_id):
    result, error = get_audio_asset(g.actor_user, asset_id)
    if error:
        status = 404 if error in {"Audio asset not found", "Business not found"} else 403
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.put("/<int:asset_id>")
@jwt_context_required
@require_permission("businesses.manage")
def update_audio_asset_endpoint(asset_id):
    payload = request.get_json(silent=True) or {}
    result, error = update_audio_asset(g.actor_user, asset_id, payload)
    if error:
        status = (
            404
            if error in {"Audio asset not found", "Business not found"}
            else 403
            if "permission" in error.lower() or error == "Cannot update deleted audio asset"
            else 409
            if error == "Audio slug already exists in this business"
            else 400
        )
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.get("/<int:asset_id>/stream")
@jwt_context_required
@require_permission("businesses.read")
def stream_audio_asset_endpoint(asset_id):
    result, error = resolve_audio_asset_file(g.actor_user, asset_id, purpose="stream")
    if error:
        status = (
            404
            if error in {"Audio asset not found", "Business not found", "Audio file not found"}
            else 403
            if "permission" in error.lower()
            else 410
            if error == "Audio asset is deleted"
            else 400
        )
        return jsonify({"error": error}), status

    return send_file(
        str(result["path"]),
        mimetype=result["mimetype"],
        as_attachment=False,
        download_name=result["download_name"],
        conditional=True,
    )


@bp.get("/<int:asset_id>/download")
@jwt_context_required
@require_permission("businesses.read")
def download_audio_asset_endpoint(asset_id):
    result, error = resolve_audio_asset_file(g.actor_user, asset_id, purpose="download")
    if error:
        status = (
            404
            if error in {"Audio asset not found", "Business not found", "Audio file not found"}
            else 403
            if "permission" in error.lower()
            else 410
            if error == "Audio asset is deleted"
            else 400
        )
        return jsonify({"error": error}), status

    return send_file(
        str(result["path"]),
        mimetype=result["mimetype"],
        as_attachment=True,
        download_name=result["download_name"],
        conditional=True,
    )


@bp.delete("/<int:asset_id>")
@jwt_context_required
@require_permission("businesses.manage")
def delete_audio_asset_endpoint(asset_id):
    payload = request.get_json(silent=True) or {}
    result, error = delete_audio_asset(
        actor_user=g.actor_user,
        asset_id=asset_id,
        delete_reason=payload.get("delete_reason"),
    )
    if error:
        status = (
            404
            if error in {"Audio asset not found", "Business not found"}
            else 403
            if "permission" in error.lower()
            else 500
            if error.startswith("Failed to delete audio file:")
            else 400
        )
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/<int:asset_id>/sync-to-asterisk")
@jwt_context_required
@require_permission("businesses.manage")
def sync_audio_asset_endpoint(asset_id):
    result, error = sync_audio_asset_to_asterisk(g.actor_user, asset_id)
    if error:
        status = (
            404
            if error in {"Audio asset not found", "Business not found", "Audio file not found"}
            else 403
            if "permission" in error.lower() or error == "Audio asset is deleted"
            else 400
        )
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.post("/<int:asset_id>/test-playback")
@jwt_context_required
@require_permission("businesses.manage")
def test_playback_audio_asset_endpoint(asset_id):
    result, error = test_audio_asset_playback(g.actor_user, asset_id)
    if error:
        status = (
            404
            if error in {"Audio asset not found", "Business not found", "Audio file not found"}
            else 403
            if "permission" in error.lower() or error == "Audio asset is deleted"
            else 400
        )
        return jsonify({"error": error}), status
    return jsonify(result), 200
