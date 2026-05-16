import hashlib
import uuid
import json
from datetime import datetime
from functools import wraps
from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app.api.v2.calls.event_service import (
    list_call_events,
    process_call_event,
    reprocess_call_event,
)
from app.api.v2.audio_assets.service import resolve_playback_target_for_runtime_business
from app.api.v2.flows.runtime_service import append_runtime_event, get_runtime_state, resolve_next_runtime
from app.models import Business, BusinessAccessToken, CallSession, FlowRuntimeSession, User, WorkspaceMembership
from app.services.fastagi_call_token import verify_fastagi_call_token

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


def _resolve_internal_business(required_scopes, route_kwargs):
    # Priority: explicit header -> body/query business_id -> call/session lookup
    header_business_id = request.headers.get("X-Dialyra-Business-Id")
    if header_business_id is not None:
        try:
            normalized = int(str(header_business_id).strip())
        except (TypeError, ValueError):
            return None, "Invalid X-Dialyra-Business-Id"
        business = Business.query.get(normalized)
        if business is None:
            return None, "Business not found"
        return business, None

    payload = request.get_json(silent=True) or {}
    payload_business_id = payload.get("business_id") or request.args.get("business_id")
    if payload_business_id is not None:
        try:
            normalized = int(payload_business_id)
        except (TypeError, ValueError):
            return None, "Invalid business_id"
        business = Business.query.get(normalized)
        if business is None:
            return None, "Business not found"
        return business, None

    call_id = route_kwargs.get("call_id")
    if call_id:
        session = FlowRuntimeSession.query.filter_by(call_session_id=str(call_id)).first()
        if session is not None:
            business = Business.query.get(int(session.business_id))
            if business is None:
                return None, "Business not found"
            return business, None
        call_session = None
        try:
            call_session = CallSession.query.get(int(call_id))
        except (TypeError, ValueError):
            call_session = None
        if call_session is not None:
            business = Business.query.get(int(call_session.business_id))
            if business is None:
                return None, "Business not found"
            return business, None

    # Flow runtime endpoints require business context.
    if "flow:resolve" in required_scopes or "fastagi:runtime" in required_scopes or "events:write" in required_scopes:
        return None, "Missing business context for internal auth"
    return None, None


def _call_token_or_access_token_required(*required_scopes):
    required_scope_set = set(required_scopes)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            call_token = str(request.headers.get("X-Dialyra-Call-Token", "") or "").strip()
            if call_token:
                claims, token_error = verify_fastagi_call_token(call_token)
                if token_error:
                    return jsonify({"error": token_error}), 401
                business = Business.query.get(int(claims["business_id"]))
                if business is None:
                    return jsonify({"error": "Business not found"}), 404
                if business.status != "active":
                    return jsonify({"error": "Business is not active"}), 403
                expected_call_id = kwargs.get("call_id")
                payload = request.get_json(silent=True) or {}
                if not expected_call_id:
                    expected_call_id = payload.get("call_session_id")
                if expected_call_id:
                    if str(expected_call_id) != str(claims.get("call_session_id")):
                        return jsonify({"error": "Call token does not match call session"}), 403
                g.auth_type = "call_token"
                g.actor_user = None
                g.actor_business = business
                g.access_token = None
                g.scopes = sorted(required_scope_set)
                return fn(*args, **kwargs)

            raw_token = request.headers.get("X-Dialyra-Access-Token")
            if not raw_token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.lower().startswith("bearer "):
                    raw_token = auth_header.split(" ", 1)[1].strip()
            if not raw_token:
                return jsonify({"error": "Missing access token"}), 401

            # If bearer token looks like JWT, authenticate as platform user.
            if str(raw_token).count(".") == 2:
                try:
                    verify_jwt_in_request()
                except Exception:  # noqa: BLE001
                    return jsonify({"error": "Invalid JWT token"}), 401
                user_id = get_jwt_identity()
                if user_id is None:
                    return jsonify({"error": "Actor user not found"}), 404
                actor_user = User.query.get(int(user_id))
                if actor_user is None:
                    return jsonify({"error": "Actor user not found"}), 404
                if actor_user.role not in {"stuff", "superuser"}:
                    return jsonify({"error": "Stuff or superuser role required"}), 403

                business, business_error = _resolve_internal_business(required_scope_set, kwargs)
                if business_error:
                    return jsonify({"error": business_error}), 400 if "Missing business context" in business_error else 404 if business_error == "Business not found" else 400

                if actor_user.role != "superuser":
                    if business is None:
                        return jsonify({"error": "Business context is required"}), 400
                    membership = WorkspaceMembership.query.filter_by(
                        user_id=actor_user.id,
                        business_id=business.id,
                        status="active",
                    ).first()
                    if membership is None:
                        return jsonify({"error": "Business membership is not active"}), 403

                g.auth_type = "jwt"
                g.actor_user = actor_user
                g.actor_business = business
                g.access_token = None
                g.scopes = sorted(required_scope_set)
                return fn(*args, **kwargs)

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
            if business.status != "active":
                return jsonify({"error": "Business is not active"}), 403
            token_model.last_used_at = datetime.utcnow()
            from app.extensions import db

            db.session.commit()
            g.auth_type = "access_token"
            g.actor_user = None
            g.actor_business = business
            g.access_token = token_model
            g.scopes = sorted(token_scopes)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


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
@_call_token_or_access_token_required("fastagi:runtime")
def get_flow_runtime(flow_id):
    call_session_id = request.args.get("call_session_id")
    result, error = get_runtime_state(g.actor_business, flow_id, call_session_id=call_session_id)
    if error:
        status = 404 if "not found" in error.lower() else 400
        return jsonify({"error": error}), status
    result["auth_type"] = g.auth_type
    return jsonify(result), 200


@bp.post("/flow/resolve-next")
@_call_token_or_access_token_required("flow:resolve")
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
@_call_token_or_access_token_required("fastagi:runtime")
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
@_call_token_or_access_token_required("fastagi:runtime")
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
@_call_token_or_access_token_required("events:write")
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
@_call_token_or_access_token_required("events:write")
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
@_call_token_or_access_token_required("events:write")
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
@_call_token_or_access_token_required("events:write")
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
@_call_token_or_access_token_required("events:write")
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
@_call_token_or_access_token_required("events:write")
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
@_call_token_or_access_token_required("events:write")
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


@bp.get("/call-events")
@_call_token_or_access_token_required("events:write")
def list_call_events_endpoint():
    status = request.args.get("status")
    business_id = request.args.get("business_id")
    page = request.args.get("page", 1)
    page_size = request.args.get("page_size", 20)

    scoped_business_id = g.actor_business.id
    if business_id is not None:
        try:
            requested_business_id = int(business_id)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid business_id"}), 400
        if requested_business_id != scoped_business_id:
            return jsonify({"error": "Insufficient permission for this business"}), 403

    if status and str(status).strip().lower() not in {"pending", "processed", "failed"}:
        return jsonify({"error": "Invalid status"}), 400

    try:
        result, error = list_call_events(
            business_id=scoped_business_id,
            status=status,
            page=int(page),
            page_size=int(page_size),
        )
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid pagination params"}), 400

    if error:
        return jsonify({"error": error}), 400
    return jsonify(result), 200


@bp.post("/call-events/<string:event_id>/reprocess")
@_call_token_or_access_token_required("events:write")
def reprocess_call_events_endpoint(event_id):
    result, error = reprocess_call_event(event_id, business_id=g.actor_business.id)
    if error:
        if error == "Call event not found":
            return jsonify({"error": error}), 404
        if error == "Invalid event id":
            return jsonify({"error": error}), 400
        return jsonify({"error": error}), 422
    return jsonify({"status": "accepted", "event": "call-event.reprocess", "result": result}), 200


@bp.get("/audio-assets/<string:asset_id>/playback-target")
@_call_token_or_access_token_required("fastagi:runtime")
def get_runtime_playback_target(asset_id):
    result, error = resolve_playback_target_for_runtime_business(g.actor_business, asset_id)
    if error:
        status = (
            404
            if error in {"Audio asset not found for this business", "Audio file not found"}
            else 410
            if error == "Audio asset is deleted"
            else 400
        )
        return jsonify({"error": error}), status
    return jsonify(result), 200
