import socket

from flask import Blueprint, g, jsonify, request

from app.api.v1.calls.schemas import validate_originate_payload
from app.api.v1.calls.service import ami_service, originate_call
from app.middleware.permissions import access_token_context_required

bp = Blueprint("calls", __name__, url_prefix="/api")


@bp.post("/call")
def make_call():
    payload = request.get_json(silent=True)
    validation_error = validate_originate_payload(payload)
    if validation_error:
        return jsonify({"error": validation_error}), 400

    phone = payload["phone"]

    try:
        result = originate_call(phone)
        return jsonify({"status": "initiated", "phone": phone, "response": str(result)})
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
    try:
        result = originate_call(phone)
        return jsonify(
            {
                "status": "initiated",
                "phone": phone,
                "business_id": g.actor_business.id,
                "auth_type": g.auth_type,
                "response": str(result),
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
