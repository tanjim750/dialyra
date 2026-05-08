from flask import Blueprint, g, jsonify, request

from app.middleware.permissions import access_token_context_required

bp = Blueprint("internal", __name__, url_prefix="/api/internal")


@bp.get("/health")
def internal_health():
    return jsonify({"module": "internal", "status": "scaffolded"})


@bp.post("/flow/resolve-next")
@access_token_context_required("flow:resolve")
def resolve_next():
    payload = request.get_json(silent=True) or {}
    return jsonify(
        {
            "status": "accepted",
            "business_id": g.actor_business.id,
            "auth_type": g.auth_type,
            "payload": payload,
        }
    ), 200


@bp.post("/calls/<string:call_id>/node-entered")
@access_token_context_required("fastagi:runtime")
def node_entered(call_id):
    payload = request.get_json(silent=True) or {}
    return jsonify(
        {
            "status": "accepted",
            "event": "node-entered",
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/calls/<string:call_id>/dtmf")
@access_token_context_required("events:write")
def dtmf(call_id):
    payload = request.get_json(silent=True) or {}
    return jsonify(
        {
            "status": "accepted",
            "event": "dtmf",
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/calls/<string:call_id>/playback-event")
@access_token_context_required("events:write")
def playback_event(call_id):
    payload = request.get_json(silent=True) or {}
    return jsonify(
        {
            "status": "accepted",
            "event": "playback-event",
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/call-events")
@access_token_context_required("events:write")
def call_events():
    payload = request.get_json(silent=True) or {}
    return jsonify(
        {
            "status": "accepted",
            "event": "call-events",
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200
