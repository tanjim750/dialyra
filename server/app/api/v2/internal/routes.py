import hashlib
import uuid
from flask import Blueprint, current_app, g, jsonify, request

from app.api.v2.calls.event_service import process_call_event
from app.api.v2.flows.runtime_service import append_runtime_event, get_runtime_state, resolve_next_runtime
from app.middleware.permissions_v2 import access_token_context_required

bp = Blueprint("internal_v2", __name__, url_prefix="/api/v2/internal")
_TRANSFER_EVENT_TYPES = {"transfer_connected", "transfer_failed"}
_WAIT_EVENT_TYPES = {"wait_completed", "wait_failed"}
_RECORD_EVENT_TYPES = {
    "recording_started",
    "recording_stopped",
    "recording_paused",
    "recording_resumed",
    "recording_failed",
}


def _parse_int_csv(value):
    if not value:
        return set()
    out = set()
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


def _canary_gate_decision(actor_business_id, payload):
    enabled = bool(current_app.config.get("FLOW_RUNTIME_CANARY_ENABLED", False))
    percent = int(current_app.config.get("FLOW_RUNTIME_CANARY_PERCENT", 100))
    percent = max(0, min(100, percent))

    force_business_ids = _parse_int_csv(
        current_app.config.get("FLOW_RUNTIME_CANARY_FORCE_BUSINESS_IDS", "")
    )
    force_flow_ids = _parse_int_csv(
        current_app.config.get("FLOW_RUNTIME_CANARY_FORCE_FLOW_IDS", "")
    )

    flow_id = payload.get("flow_id")
    try:
        normalized_flow_id = int(flow_id) if flow_id is not None else None
    except (TypeError, ValueError):
        normalized_flow_id = None

    call_session_id = str(payload.get("call_session_id") or "").strip()
    canary_forced = bool(payload.get("force_canary")) or actor_business_id in force_business_ids
    if normalized_flow_id is not None and normalized_flow_id in force_flow_ids:
        canary_forced = True

    if not enabled:
        return {
            "enabled": False,
            "allowed": True,
            "forced": canary_forced,
            "bucket": None,
            "percent": percent,
        }

    if canary_forced:
        return {
            "enabled": True,
            "allowed": True,
            "forced": True,
            "bucket": None,
            "percent": percent,
        }

    if not call_session_id:
        # missing session id should still pass here; runtime service validates required fields.
        return {
            "enabled": True,
            "allowed": percent >= 100,
            "forced": False,
            "bucket": None,
            "percent": percent,
        }

    bucket = int(hashlib.md5(call_session_id.encode("utf-8")).hexdigest(), 16) % 100
    allowed = bucket < percent
    return {
        "enabled": True,
        "allowed": allowed,
        "forced": False,
        "bucket": bucket,
        "percent": percent,
    }


@bp.get("/health")
def internal_health():
    return jsonify({"module": "internal", "status": "scaffolded"})


@bp.get("/flows/<int:flow_id>/runtime")
@access_token_context_required("fastagi:runtime")
def get_flow_runtime(flow_id):
    call_session_id = request.args.get("call_session_id")
    result, error = get_runtime_state(g.actor_business, flow_id, call_session_id=call_session_id)
    if error:
        status = 404 if "not found" in error.lower() else 400
        return jsonify({"error": error}), status
    result["auth_type"] = g.auth_type
    return jsonify(result), 200


@bp.post("/flow/resolve-next")
@access_token_context_required("flow:resolve")
def resolve_next():
    payload = request.get_json(silent=True) or {}
    trace_id = str(payload.get("trace_id") or uuid.uuid4())
    payload["trace_id"] = trace_id
    canary = _canary_gate_decision(g.actor_business.id, payload)
    if not canary["allowed"]:
        return jsonify(
            {
                "status": "canary_skipped",
                "business_id": g.actor_business.id,
                "call_session_id": payload.get("call_session_id"),
                "flow_id": payload.get("flow_id"),
                "flow_version_id": payload.get("flow_version_id"),
                "runtime_action": {
                    "type": "legacy_fallback",
                    "reason": "runtime_canary_skip",
                },
                "fallback_used": True,
                "warning": "Flow runtime canary gate skipped this call",
                "observability": {
                    "trace_id": trace_id,
                    "resolved_at": None,
                    "event_type": "canary.skip",
                    "canary": canary,
                },
                "auth_type": g.auth_type,
            }
        ), 200
    result, error = resolve_next_runtime(g.actor_business, payload)
    if error:
        if bool(payload.get("use_fallback")):
            fallback_action = payload.get("fallback_action")
            if not isinstance(fallback_action, dict):
                fallback_action = {
                    "type": "hangup",
                    "reason": "runtime_error_fallback",
                }
            return jsonify(
                {
                    "status": "accepted_with_fallback",
                    "business_id": g.actor_business.id,
                    "call_session_id": payload.get("call_session_id"),
                    "flow_id": payload.get("flow_id"),
                    "flow_version_id": payload.get("flow_version_id"),
                    "runtime_action": fallback_action,
                    "fallback_used": True,
                    "warning": error,
                    "observability": {
                        "trace_id": trace_id,
                        "resolved_at": None,
                        "event_type": "fallback",
                        "canary": canary,
                    },
                    "auth_type": g.auth_type,
                }
            ), 200
        status = 404 if "not found" in error.lower() else 400
        return jsonify({"error": error}), status
    if isinstance(result.get("observability"), dict):
        result["observability"]["canary"] = canary
    result["auth_type"] = g.auth_type
    return jsonify(result), 200


@bp.post("/calls/<string:call_id>/node-entered")
@access_token_context_required("fastagi:runtime")
def node_entered(call_id):
    payload = request.get_json(silent=True) or {}
    result, error = append_runtime_event(g.actor_business, call_id, "node.entered", payload)
    if error:
        return jsonify({"error": error}), 404
    return jsonify(
        {
            **result,
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/calls/<string:call_id>/node-completed")
@access_token_context_required("fastagi:runtime")
def node_completed(call_id):
    payload = request.get_json(silent=True) or {}
    result, error = append_runtime_event(g.actor_business, call_id, "node.completed", payload)
    if error:
        return jsonify({"error": error}), 404
    return jsonify(
        {
            **result,
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/calls/<string:call_id>/dtmf")
@access_token_context_required("events:write")
def dtmf(call_id):
    payload = request.get_json(silent=True) or {}
    result, error = append_runtime_event(g.actor_business, call_id, "dtmf.received", payload)
    if error:
        return jsonify({"error": error}), 404
    return jsonify(
        {
            **result,
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/calls/<string:call_id>/playback-event")
@access_token_context_required("events:write")
def playback_event(call_id):
    payload = request.get_json(silent=True) or {}
    event_type = str(payload.get("event_type") or "playback.event")
    result, error = append_runtime_event(g.actor_business, call_id, event_type, payload)
    if error:
        return jsonify({"error": error}), 404
    return jsonify(
        {
            **result,
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/calls/<string:call_id>/runtime-error")
@access_token_context_required("events:write")
def runtime_error(call_id):
    payload = request.get_json(silent=True) or {}
    result, error = append_runtime_event(g.actor_business, call_id, "runtime.error", payload)
    if error:
        return jsonify({"error": error}), 404
    return jsonify(
        {
            **result,
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/calls/<string:call_id>/transfer-event")
@access_token_context_required("events:write")
def transfer_event(call_id):
    payload = request.get_json(silent=True) or {}
    event_type = str(payload.get("event_type") or "").strip().lower()
    if event_type not in _TRANSFER_EVENT_TYPES:
        return jsonify(
            {
                "error": "Invalid transfer event_type",
                "allowed_event_types": sorted(_TRANSFER_EVENT_TYPES),
            }
        ), 400

    result, error = append_runtime_event(g.actor_business, call_id, event_type, payload)
    if error:
        return jsonify({"error": error}), 404
    return jsonify(
        {
            **result,
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/calls/<string:call_id>/wait-event")
@access_token_context_required("events:write")
def wait_event(call_id):
    payload = request.get_json(silent=True) or {}
    event_type = str(payload.get("event_type") or "").strip().lower()
    if event_type not in _WAIT_EVENT_TYPES:
        return jsonify(
            {
                "error": "Invalid wait event_type",
                "allowed_event_types": sorted(_WAIT_EVENT_TYPES),
            }
        ), 400

    result, error = append_runtime_event(g.actor_business, call_id, event_type, payload)
    if error:
        return jsonify({"error": error}), 404
    return jsonify(
        {
            **result,
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/calls/<string:call_id>/record-event")
@access_token_context_required("events:write")
def record_event(call_id):
    payload = request.get_json(silent=True) or {}
    event_type = str(payload.get("event_type") or "").strip().lower()
    if event_type not in _RECORD_EVENT_TYPES:
        return jsonify(
            {
                "error": "Invalid record event_type",
                "allowed_event_types": sorted(_RECORD_EVENT_TYPES),
            }
        ), 400

    result, error = append_runtime_event(g.actor_business, call_id, event_type, payload)
    if error:
        return jsonify({"error": error}), 404
    return jsonify(
        {
            **result,
            "call_id": call_id,
            "business_id": g.actor_business.id,
            "payload": payload,
        }
    ), 200


@bp.post("/call-events")
@access_token_context_required("events:write")
def call_events():
    payload = request.get_json(silent=True) or {}
    result, error = process_call_event(payload, business_id=g.actor_business.id)
    if error:
        status = 404 if "not found" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(
        {
            "status": "accepted",
            "event": "call-events",
            "business_id": g.actor_business.id,
            "payload": payload,
            "call_log": result,
        }
    ), 200
