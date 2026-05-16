import json
import re
import socket
from datetime import datetime
from pathlib import Path

from flask import current_app
from itsdangerous import URLSafeSerializer
from sqlalchemy.exc import IntegrityError

from app.api.v2.sip_trunks.pjsip_generator import write_config
from app.api.v2.sip_trunks.realtime_sync import delete_trunk as realtime_delete_trunk
from app.api.v2.sip_trunks.realtime_sync import (
    ensure_realtime_ready,
    realtime_health,
    trunk_sync_snapshot,
    upsert_trunk as realtime_upsert_trunk,
)
from app.extensions import db
from app.models import Business, SipTrunk, WorkspaceMembership
from app.services.asterisk_channels import count_active_calls_for_endpoint
from app.services.ami_service import AMIService
from app.services.audit_service import log_audit_event

TRUNK_TYPES = {"registration", "ip"}
AUTH_TYPES = {"userpass", "ip", "none"}
TRANSPORT_TYPES = {"udp", "tcp", "tls"}
DTMF_MODES = {"rfc4733", "inband", "info", "auto", "auto_info", "none"}
STATUS_TYPES = {"active", "inactive", "failed", "registering", "rejected", "unreachable"}
MANAGE_ROLES = {"owner", "admin"}
VIEW_ROLES = {"owner", "admin", "manager", "agent", "viewer"}
RUNTIME_SOCKET_TIMEOUT = 3.0


def _slug(value):
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized or "trunk"


def _trunk_endpoint_name(trunk, realtime_enabled):
    business_part = trunk.business_id if trunk.business_id is not None else "global"
    if realtime_enabled:
        return f"dialyra_b{business_part}_t{trunk.id}_{_slug(trunk.name)}_ep"
    return f"dialyra-b{business_part}-t{trunk.id}-{_slug(trunk.name)}-endpoint"


def _secret_serializer():
    from flask import current_app

    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="sip-trunk-password")


def _seal_secret(value):
    if not value:
        return None
    return _secret_serializer().dumps(value)


def _normalize_settings(settings):
    if settings is None:
        return None
    if not isinstance(settings, dict):
        return None
    return json.dumps(settings)


def serialize_trunk(trunk):
    settings = {}
    if trunk.settings_json:
        try:
            parsed = json.loads(trunk.settings_json)
            if isinstance(parsed, dict):
                settings = parsed
        except json.JSONDecodeError:
            settings = {}
    return {
        "id": trunk.id,
        "scope": trunk.scope,
        "business_id": trunk.business_id,
        "name": trunk.name,
        "provider_name": trunk.provider_name,
        "type": trunk.type,
        "host": trunk.host,
        "port": trunk.port,
        "username": trunk.username,
        "auth_type": trunk.auth_type,
        "transport": trunk.transport,
        "dtmf_mode": trunk.dtmf_mode,
        "from_user": trunk.from_user,
        "from_domain": trunk.from_domain,
        "context": trunk.context,
        "status": trunk.status,
        "max_concurrent_calls": trunk.max_concurrent_calls,
        "is_active": trunk.is_active,
        "apply_status": trunk.apply_status,
        "last_apply_error": trunk.last_apply_error,
        "last_applied_at": trunk.last_applied_at.isoformat() if trunk.last_applied_at else None,
        "last_rollback_at": trunk.last_rollback_at.isoformat() if trunk.last_rollback_at else None,
        "settings": settings,
        "created_at": trunk.created_at.isoformat() if trunk.created_at else None,
        "updated_at": trunk.updated_at.isoformat() if trunk.updated_at else None,
    }


def _snapshot_trunk(trunk):
    return {
        "name": trunk.name,
        "provider_name": trunk.provider_name,
        "type": trunk.type,
        "host": trunk.host,
        "port": trunk.port,
        "username": trunk.username,
        "password_encrypted": trunk.password_encrypted,
        "auth_type": trunk.auth_type,
        "transport": trunk.transport,
        "dtmf_mode": trunk.dtmf_mode,
        "from_user": trunk.from_user,
        "from_domain": trunk.from_domain,
        "context": trunk.context,
        "status": trunk.status,
        "max_concurrent_calls": trunk.max_concurrent_calls,
        "is_active": trunk.is_active,
        "settings_json": trunk.settings_json,
    }


def _read_current_pjsip():
    path = Path(current_app.config["PJSIP_CONFIG_PATH"])
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _write_pjsip_for_all_active():
    trunks = (
        SipTrunk.query.filter_by(is_active=True)
        .order_by(SipTrunk.business_id.asc(), SipTrunk.id.asc())
        .all()
    )
    return write_config(
        current_app.config["PJSIP_CONFIG_PATH"],
        trunks,
        transport_name=current_app.config.get("PJSIP_TRANSPORT_NAME", "transport-udp"),
    )


def _restore_snapshot(trunk, snapshot):
    for field, value in snapshot.items():
        setattr(trunk, field, value)


def _get_active_membership(actor_user_id, business_id):
    return WorkspaceMembership.query.filter_by(
        user_id=actor_user_id, business_id=business_id, status="active"
    ).first()


def _can_manage_business(actor_user, business):
    if actor_user.role == "superuser":
        return True
    if actor_user.role == "stuff" and business.owner_user_id == actor_user.id:
        return True
    membership = _get_active_membership(actor_user.id, business.id)
    return membership is not None and membership.role in MANAGE_ROLES


def _can_view_business(actor_user, business):
    if actor_user.role == "superuser":
        return True
    if actor_user.role == "stuff" and business.owner_user_id == actor_user.id:
        return True
    membership = _get_active_membership(actor_user.id, business.id)
    return membership is not None and membership.role in VIEW_ROLES


def _validate_payload(payload, is_update=False):
    scope = (payload.get("scope") or "").strip().lower()
    trunk_type = (payload.get("type") or "").strip().lower()
    auth_type = (payload.get("auth_type") or "").strip().lower()
    transport = (payload.get("transport") or "").strip().lower()
    dtmf_mode = (payload.get("dtmf_mode") or "").strip().lower()
    status = (payload.get("status") or "").strip().lower()

    if not is_update:
        if not payload.get("name") or not payload.get("host") or not trunk_type:
            return "Missing required fields: name, host, type"

    if scope and scope not in {"business", "global"}:
        return "Invalid scope"
    if trunk_type and trunk_type not in TRUNK_TYPES:
        return "Invalid trunk type"
    if auth_type and auth_type not in AUTH_TYPES:
        return "Invalid auth_type"
    if transport and transport not in TRANSPORT_TYPES:
        return "Invalid transport"
    if dtmf_mode and dtmf_mode not in DTMF_MODES:
        return "Invalid dtmf_mode. Allowed values: rfc4733, inband, info, auto, auto_info, none"
    if status and status not in STATUS_TYPES:
        return "Invalid status"

    if trunk_type == "registration":
        if not is_update and (not payload.get("username") or not payload.get("password")):
            return "registration trunk requires username and password"

    return None


def create_sip_trunk(actor_user, payload):
    explicit_scope = (payload.get("scope") or "").strip().lower() or None
    scope = None
    business = None
    business_id = payload.get("business_id")

    # Dynamic scope inference:
    # - superuser with no business_id => global
    # - everyone else => business (business_id required)
    if actor_user.role == "superuser" and not business_id:
        scope = "global"
        business_id = None
    else:
        scope = "business"
        if not business_id:
            return None, "business_id is required"
        business = Business.query.get(int(business_id))
        if business is None:
            return None, "Business not found"
        if not _can_manage_business(actor_user, business):
            return None, "Insufficient permission for this business"

    if explicit_scope and explicit_scope != scope:
        return None, f"scope must be '{scope}' for this request"

    error = _validate_payload(payload, is_update=False)
    if error:
        return None, error

    name = payload.get("name").strip()
    exists = SipTrunk.query.filter_by(business_id=business.id if business else None, name=name).first()
    if exists is not None:
        return None, "SIP trunk name already exists in this business"

    trunk = SipTrunk(
        business_id=business.id if business else None,
        scope=scope,
        name=name,
        provider_name=(payload.get("provider_name") or "").strip() or None,
        type=(payload.get("type") or "registration").strip().lower(),
        host=(payload.get("host") or "").strip(),
        port=int(payload.get("port") or 5060),
        username=(payload.get("username") or "").strip() or None,
        password_encrypted=_seal_secret(payload.get("password")),
        auth_type=(payload.get("auth_type") or "userpass").strip().lower(),
        transport=(payload.get("transport") or "udp").strip().lower(),
        dtmf_mode=(payload.get("dtmf_mode") or "rfc4733").strip().lower(),
        from_user=(payload.get("from_user") or "").strip() or None,
        from_domain=(payload.get("from_domain") or "").strip() or None,
        context=(payload.get("context") or "").strip() or None,
        status=(payload.get("status") or "inactive").strip().lower(),
        max_concurrent_calls=int(payload.get("max_concurrent_calls") or 50),
        is_active=bool(payload.get("is_active", True)),
        apply_status="pending",
        last_apply_error=None,
        settings_json=_normalize_settings(payload.get("settings")),
    )
    db.session.add(trunk)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "SIP trunk name already exists in this business"
    log_audit_event(
        "sip_trunk.created",
        business_id=business.id if business else None,
        actor_user_id=actor_user.id,
        metadata={"sip_trunk_id": trunk.id, "name": trunk.name},
    )
    db.session.commit()
    return serialize_trunk(trunk), None


def list_sip_trunks(actor_user, business_id=None):
    query = SipTrunk.query
    if business_id:
        business = Business.query.get(int(business_id))
        if business is None:
            return None, "Business not found"
        if not _can_view_business(actor_user, business):
            return None, "Insufficient permission for this business"
        query = query.filter(SipTrunk.business_id == business.id)
        if business.allow_global_sip_fallback:
            query = query.union(SipTrunk.query.filter(SipTrunk.scope == "global"))
    elif actor_user.role != "superuser":
        owned_ids = [b.id for b in Business.query.filter_by(owner_user_id=actor_user.id).all()]
        member_ids = [
            m.business_id
            for m in WorkspaceMembership.query.filter_by(user_id=actor_user.id, status="active").all()
        ]
        allowed_ids = sorted(set(owned_ids + member_ids))
        if not allowed_ids:
            return [], None
        query = query.filter(SipTrunk.business_id.in_(allowed_ids), SipTrunk.scope == "business")
    trunks = query.order_by(SipTrunk.created_at.desc()).all()
    return [serialize_trunk(t) for t in trunks], None


def get_sip_trunk(actor_user, trunk_id):
    trunk = SipTrunk.query.get(trunk_id)
    if trunk is None:
        return None, "SIP trunk not found"
    if trunk.scope == "global":
        if actor_user.role != "superuser":
            return None, "Insufficient permission for this business"
        return serialize_trunk(trunk), None
    business = Business.query.get(trunk.business_id)
    if business is None:
        return None, "Business not found"
    if not _can_view_business(actor_user, business):
        return None, "Insufficient permission for this business"
    return serialize_trunk(trunk), None


def update_sip_trunk(actor_user, trunk_id, payload):
    trunk = SipTrunk.query.get(trunk_id)
    if trunk is None:
        return None, "SIP trunk not found"
    business = Business.query.get(trunk.business_id) if trunk.business_id else None
    if trunk.scope == "global":
        if actor_user.role != "superuser":
            return None, "Only superuser can manage global SIP trunks"
    else:
        if business is None:
            return None, "Business not found"
        if not _can_manage_business(actor_user, business):
            return None, "Insufficient permission for this business"
    error = _validate_payload(payload, is_update=True)
    if error:
        return None, error
    trunk.previous_config_json = json.dumps(_snapshot_trunk(trunk))

    if "name" in payload and payload.get("name"):
        normalized_name = payload.get("name").strip()
        duplicate = SipTrunk.query.filter(
            SipTrunk.business_id.is_(trunk.business_id),
            SipTrunk.name == normalized_name,
            SipTrunk.id != trunk.id,
        ).first()
        if duplicate is not None:
            return None, "SIP trunk name already exists in this business"

    for field in ["name", "provider_name", "host", "username", "from_user", "from_domain", "context"]:
        if field in payload:
            value = payload.get(field)
            setattr(trunk, field, value.strip() if isinstance(value, str) else value)
    if "password" in payload and payload.get("password"):
        trunk.password_encrypted = _seal_secret(payload.get("password"))
    if "type" in payload:
        trunk.type = (payload.get("type") or trunk.type).strip().lower()
    if "auth_type" in payload:
        trunk.auth_type = (payload.get("auth_type") or trunk.auth_type).strip().lower()
    if "transport" in payload:
        trunk.transport = (payload.get("transport") or trunk.transport).strip().lower()
    if "dtmf_mode" in payload:
        trunk.dtmf_mode = (payload.get("dtmf_mode") or trunk.dtmf_mode).strip().lower()
    if "status" in payload:
        trunk.status = (payload.get("status") or trunk.status).strip().lower()
    if "is_active" in payload:
        trunk.is_active = bool(payload.get("is_active"))
    if "port" in payload:
        trunk.port = int(payload.get("port") or trunk.port)
    if "max_concurrent_calls" in payload:
        trunk.max_concurrent_calls = int(payload.get("max_concurrent_calls") or trunk.max_concurrent_calls)
    if "settings" in payload:
        trunk.settings_json = _normalize_settings(payload.get("settings"))
    trunk.apply_status = "pending"
    trunk.last_apply_error = None

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, "SIP trunk name already exists in this business"
    log_audit_event(
        "sip_trunk.updated",
        business_id=business.id if business else None,
        actor_user_id=actor_user.id,
        metadata={"sip_trunk_id": trunk.id},
    )
    db.session.commit()
    return serialize_trunk(trunk), None


def delete_sip_trunk(actor_user, trunk_id):
    trunk = SipTrunk.query.get(trunk_id)
    if trunk is None:
        return None, "SIP trunk not found"
    business = Business.query.get(trunk.business_id) if trunk.business_id else None
    if trunk.scope == "global":
        if actor_user.role != "superuser":
            return None, "Only superuser can manage global SIP trunks"
    else:
        if business is None:
            return None, "Business not found"
        if not _can_manage_business(actor_user, business):
            return None, "Insufficient permission for this business"

    trunk.previous_config_json = json.dumps(
        {"trunk": _snapshot_trunk(trunk), "pjsip_content": _read_current_pjsip()}
    )
    trunk.is_active = False
    trunk.status = "inactive"
    trunk.apply_status = "pending"
    trunk.last_apply_error = None
    if current_app.config.get("SIP_REALTIME_ENABLED", False):
        missing = ensure_realtime_ready()
        if missing:
            db.session.rollback()
            return None, f"SIP realtime tables missing: {', '.join(missing)}"
        try:
            realtime_delete_trunk(trunk)
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            return None, f"Realtime trunk delete failed: {exc}"
    db.session.commit()
    log_audit_event(
        "sip_trunk.deleted",
        business_id=business.id if business else None,
        actor_user_id=actor_user.id,
        metadata={"sip_trunk_id": trunk.id},
    )
    db.session.commit()
    return {"message": "SIP trunk soft deleted"}, None


def test_sip_trunk(actor_user, trunk_id):
    trunk = SipTrunk.query.get(trunk_id)
    if trunk is None:
        return None, "SIP trunk not found"
    business = Business.query.get(trunk.business_id) if trunk.business_id else None
    if trunk.scope == "global":
        if actor_user.role != "superuser":
            return None, "Only superuser can manage global SIP trunks"
    else:
        if business is None:
            return None, "Business not found"
        if not _can_manage_business(actor_user, business):
            return None, "Insufficient permission for this business"
    checks = {
        "dns_resolve": {"ok": False, "details": ""},
        "tcp_connect": {"ok": False, "details": ""},
        "ami_ping": {"ok": False, "details": ""},
    }

    try:
        socket.getaddrinfo(trunk.host, trunk.port)
        checks["dns_resolve"] = {"ok": True, "details": "resolved"}
    except Exception as exc:  # noqa: BLE001
        checks["dns_resolve"] = {"ok": False, "details": str(exc)}

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(RUNTIME_SOCKET_TIMEOUT)
    try:
        probe.connect((trunk.host, trunk.port))
        checks["tcp_connect"] = {"ok": True, "details": "connected"}
    except Exception as exc:  # noqa: BLE001
        checks["tcp_connect"] = {"ok": False, "details": str(exc)}
    finally:
        probe.close()

    ami = AMIService()
    try:
        ping_response = ami.ping()
        checks["ami_ping"] = {"ok": "Pong" in ping_response or "Success" in ping_response, "details": ping_response[:300]}
    except Exception as exc:  # noqa: BLE001
        checks["ami_ping"] = {"ok": False, "details": str(exc)}

    overall_ok = all(step["ok"] for step in checks.values())
    return {
        "sip_trunk_id": trunk.id,
        "status": "ok" if overall_ok else "failed",
        "checks": checks,
    }, None


def reload_sip_trunk(actor_user, trunk_id):
    trunk = SipTrunk.query.get(trunk_id)
    if trunk is None:
        return None, "SIP trunk not found"
    business = Business.query.get(trunk.business_id) if trunk.business_id else None
    if trunk.scope == "global":
        if actor_user.role != "superuser":
            return None, "Only superuser can manage global SIP trunks"
    else:
        if business is None:
            return None, "Business not found"
        if not _can_manage_business(actor_user, business):
            return None, "Insufficient permission for this business"
    snapshot = {
        "trunk": _snapshot_trunk(trunk),
        "pjsip_content": _read_current_pjsip(),
    }
    trunk.previous_config_json = json.dumps(snapshot)
    trunk.apply_status = "applying"
    trunk.last_apply_error = None
    db.session.commit()
    config_path = None
    if current_app.config.get("SIP_REALTIME_ENABLED", False):
        missing = ensure_realtime_ready()
        if missing:
            trunk.apply_status = "failed"
            trunk.last_apply_error = f"realtime_tables_missing: {', '.join(missing)}"
            db.session.commit()
            return None, f"SIP realtime tables missing: {', '.join(missing)}"
        try:
            realtime_upsert_trunk(trunk)
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            trunk.apply_status = "failed"
            trunk.last_apply_error = f"realtime_sync_failed: {exc}"
            db.session.commit()
            return None, f"Realtime SIP sync failed: {exc}"
    else:
        try:
            config_path = _write_pjsip_for_all_active()
        except Exception as exc:  # noqa: BLE001
            trunk.apply_status = "failed"
            trunk.last_apply_error = f"pjsip_write_failed: {exc}"
            db.session.commit()
            return None, f"PJSIP config write failed: {exc}"

    ami = AMIService()
    try:
        output = ami.run_command("pjsip reload")
    except Exception as exc:  # noqa: BLE001
        trunk.apply_status = "failed"
        trunk.last_apply_error = str(exc)
        db.session.commit()
        return None, f"Asterisk reload failed: {exc}"

    ok = "Response: Success" in output or "Successfully reloaded" in output
    if ok:
        trunk.apply_status = "active"
        trunk.last_applied_at = datetime.utcnow()
        trunk.last_apply_error = None
    else:
        trunk.apply_status = "failed"
        trunk.last_apply_error = output[:500]
    db.session.commit()
    return {
        "sip_trunk_id": trunk.id,
        "status": "accepted" if ok else "failed",
        "message": "Asterisk pjsip reload executed",
        "config_path": config_path,
        "realtime_enabled": bool(current_app.config.get("SIP_REALTIME_ENABLED", False)),
        "output": output[:1000],
        "apply_status": trunk.apply_status,
    }, None


def rollback_sip_trunk(actor_user, trunk_id):
    trunk = SipTrunk.query.get(trunk_id)
    if trunk is None:
        return None, "SIP trunk not found"
    business = Business.query.get(trunk.business_id) if trunk.business_id else None
    if trunk.scope == "global":
        if actor_user.role != "superuser":
            return None, "Only superuser can manage global SIP trunks"
    else:
        if business is None:
            return None, "Business not found"
        if not _can_manage_business(actor_user, business):
            return None, "Insufficient permission for this business"
    if not trunk.previous_config_json:
        return None, "No previous snapshot available for rollback"
    try:
        snapshot = json.loads(trunk.previous_config_json)
    except json.JSONDecodeError:
        return None, "Rollback snapshot is invalid"

    trunk_snapshot = snapshot.get("trunk")
    if not isinstance(trunk_snapshot, dict):
        return None, "Rollback snapshot is invalid"
    _restore_snapshot(trunk, trunk_snapshot)
    if current_app.config.get("SIP_REALTIME_ENABLED", False):
        missing = ensure_realtime_ready()
        if missing:
            return None, f"SIP realtime tables missing: {', '.join(missing)}"
        try:
            realtime_upsert_trunk(trunk)
        except Exception as exc:  # noqa: BLE001
            return None, f"Realtime SIP rollback sync failed: {exc}"
    else:
        pjsip_content = snapshot.get("pjsip_content", "")
        path = Path(current_app.config["PJSIP_CONFIG_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pjsip_content, encoding="utf-8")
    trunk.apply_status = "rolled_back"
    trunk.last_rollback_at = datetime.utcnow()
    trunk.last_apply_error = None
    db.session.commit()

    ami = AMIService()
    output = ""
    try:
        output = ami.run_command("pjsip reload")
    except Exception as exc:  # noqa: BLE001
        output = f"reload_after_rollback_failed: {exc}"

    return {
        "sip_trunk_id": trunk.id,
        "status": "rolled_back",
        "apply_status": trunk.apply_status,
        "reload_output": output[:1000],
    }, None


def sip_trunk_status(actor_user, trunk_id):
    trunk = SipTrunk.query.get(trunk_id)
    if trunk is None:
        return None, "SIP trunk not found"
    business = Business.query.get(trunk.business_id) if trunk.business_id else None
    if trunk.scope == "global":
        if actor_user.role != "superuser":
            return None, "Insufficient permission for this business"
    else:
        if business is None:
            return None, "Business not found"
        if not _can_view_business(actor_user, business):
            return None, "Insufficient permission for this business"
    runtime_status = trunk.status
    runtime_details = ""
    active_calls = 0
    matched_channels = []
    count_source = "ami_live"
    ami = AMIService()
    try:
        cmd = f"pjsip show registrations"
        output = ami.run_command(cmd)
        runtime_details = output[:1000]
        lowered = output.lower()
        if trunk.host.lower() in lowered:
            if "registered" in lowered:
                runtime_status = "active"
            elif "rejected" in lowered:
                runtime_status = "rejected"
            elif "unreachable" in lowered:
                runtime_status = "unreachable"
            elif "failed" in lowered:
                runtime_status = "failed"
        endpoint = _trunk_endpoint_name(
            trunk, realtime_enabled=bool(current_app.config.get("SIP_REALTIME_ENABLED", False))
        )
        call_snapshot = count_active_calls_for_endpoint(endpoint, ami)
        active_calls = int(call_snapshot.get("active_calls") or 0)
        matched_channels = call_snapshot.get("matched_channels") or []
    except Exception as exc:  # noqa: BLE001
        runtime_details = f"AMI status check failed: {exc}"
        count_source = "unknown"

    response = {
        "sip_trunk_id": trunk.id,
        "status": runtime_status,
        "active_calls": active_calls,
        "max_concurrent_calls": trunk.max_concurrent_calls,
        "sip_endpoint": _trunk_endpoint_name(
            trunk, realtime_enabled=bool(current_app.config.get("SIP_REALTIME_ENABLED", False))
        ),
        "count_source": count_source,
        "matched_channels": [
            {"channel": item.get("channel"), "state": item.get("state")}
            for item in matched_channels[:10]
        ],
        "runtime_details": runtime_details,
    }
    if current_app.config.get("SIP_REALTIME_ENABLED", False):
        try:
            response["realtime"] = trunk_sync_snapshot(trunk)
        except Exception as exc:  # noqa: BLE001
            response["realtime"] = {"error": str(exc)}
    return response, None


def sip_realtime_health():
    return realtime_health(), None
