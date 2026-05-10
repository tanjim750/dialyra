import socket

from flask import Blueprint, current_app, g, jsonify, request
from app.api.v2.calls.schemas import validate_originate_payload
from app.api.v2.calls.service import (
    ami_service,
    get_call_metrics,
    get_call_history_by_id,
    list_call_history,
    originate_call,
    originate_call_for_business,
)
from app.middleware.permissions_v2 import (
    access_token_context_required,
    jwt_context_required,
    require_stuff_or_superuser,
)

bp = Blueprint("calls_v2", __name__, url_prefix="/api/v2")


@bp.post("/call")
def make_call():
    payload = request.get_json(silent=True)
    validation_error = validate_originate_payload(payload)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    phone = payload["phone"]
    sip_endpoint = payload.get("sip_endpoint")
    channel_vars = {}
    if sip_endpoint:
        channel_vars["SIP_TRUNK_ENDPOINT"] = sip_endpoint

    try:
        result = originate_call(phone, channel_variables=channel_vars or None)
        return jsonify(
            {
                "status": "initiated",
                "phone": phone,
                "sip_endpoint": sip_endpoint,
                "response": str(result),
            }
        )
    except socket.gaierror as exc:
        return jsonify(
            {
                "error": "AMI host resolution failed",
                "ami_host": ami_service.host,
                "details": str(exc),
            }
        ), 502
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        return jsonify(
            {
                "error": "Failed to connect to AMI",
                "ami_host": ami_service.host,
                "ami_port": ami_service.port,
                "details": str(exc),
            }
        ), 502


@bp.post("/calls/originate")
@access_token_context_required("calls:originate")
def originate_call_runtime():
    payload = request.get_json(silent=True)
    validation_error = validate_originate_payload(payload)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    phone = payload["phone"]
    sip_trunk_id = payload.get("sip_trunk_id")
    try:
        result, error = originate_call_for_business(
            phone=phone,
            business_id=g.actor_business.id,
            sip_trunk_id=sip_trunk_id,
            realtime_enabled=bool(current_app.config.get("SIP_REALTIME_ENABLED", False)),
            actor_user_id=(g.actor_user.id if getattr(g, "actor_user", None) else None),
        )
        if error:
            if error == "Invalid sip_trunk_id":
                return jsonify({"error": error}), 400
            if error in {"SIP trunk not found for this business", "Business not found"}:
                return jsonify({"error": error}), 404
            if error.startswith("GLOBAL_SIP_NOT_ALLOWED:"):
                return (
                    jsonify(
                        {
                            "status": "warning",
                            "code": "GLOBAL_SIP_NOT_ALLOWED",
                            "message": error.split(":", 1)[1].strip(),
                        }
                    ),
                    403,
                )
            if error.startswith("NO_SIP_AVAILABLE:"):
                return (
                    jsonify(
                        {
                            "status": "warning",
                            "code": "NO_SIP_AVAILABLE",
                            "message": error.split(":", 1)[1].strip(),
                        }
                    ),
                    409,
                )
            if error.startswith("NO_TRUNK_CAPACITY:"):
                return (
                    jsonify(
                        {
                            "status": "warning",
                            "code": "NO_TRUNK_CAPACITY",
                            "message": error.split(":", 1)[1].strip(),
                        }
                    ),
                    409,
                )
            return jsonify({"error": error}), 403
        return jsonify(
            {
                "status": "initiated",
                "phone": phone,
                "business_id": g.actor_business.id,
                "call_log_uuid": result["call_log_uuid"],
                "action_id": result["action_id"],
                "sip_trunk_id": result["sip_trunk_id"],
                "sip_endpoint": result["sip_endpoint"],
                "selected_by": result["selected_by"],
                "active_calls_before": result["active_calls_before"],
                "max_concurrent_calls": result["max_concurrent_calls"],
                "auth_type": g.auth_type,
                "response": str(result["ami_response"]),
            }
        ), 200
    except socket.gaierror as exc:
        return jsonify({"error": "AMI host resolution failed", "details": str(exc)}), 502
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        return jsonify({"error": "Failed to connect to AMI", "details": str(exc)}), 502


@bp.get("/calls")
@access_token_context_required("calls:read")
def list_calls_runtime():
    return jsonify(
        {
            "items": [],
            "business_id": g.actor_business.id,
            "auth_type": g.auth_type,
        }
    ), 200


@bp.get("/calls/<string:call_id>")
@access_token_context_required("calls:read")
def get_call_runtime(call_id):
    return jsonify(
        {
            "id": call_id,
            "business_id": g.actor_business.id,
            "auth_type": g.auth_type,
            "status": "not_implemented",
        }
    ), 200


@bp.get("/calls/history")
@jwt_context_required
@require_stuff_or_superuser
def list_call_history_endpoint():
    filters = {
        "business_id": request.args.get("business_id"),
        "sip_trunk_id": request.args.get("sip_trunk_id"),
        "status": request.args.get("status"),
        "number": request.args.get("number"),
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
        "page": request.args.get("page"),
        "page_size": request.args.get("page_size"),
    }
    result, error = list_call_history(g.actor_user, filters)
    if error:
        status = 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.get("/calls/history/<string:call_id>")
@jwt_context_required
@require_stuff_or_superuser
def get_call_history_endpoint(call_id):
    result, error = get_call_history_by_id(g.actor_user, call_id)
    if error:
        status = (
            404
            if error == "Call history not found"
            else 403
            if "permission" in error.lower()
            else 400
        )
        return jsonify({"error": error}), status
    return jsonify(result), 200


@bp.get("/calls/metrics")
@jwt_context_required
@require_stuff_or_superuser
def get_call_metrics_endpoint():
    filters = {
        "business_id": request.args.get("business_id"),
        "sip_trunk_id": request.args.get("sip_trunk_id"),
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
    }
    result, error = get_call_metrics(g.actor_user, filters)
    if error:
        status = 403 if "permission" in error.lower() else 400
        return jsonify({"error": error}), status
    return jsonify(result), 200
