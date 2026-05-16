import uuid
import json
from datetime import datetime, timedelta

from app.extensions import db
from app.services.fastagi_call_token import issue_fastagi_call_token
from app.services.ami_service import AMIService
from app.services.asterisk_channels import (
    count_active_calls_for_endpoint,
    find_live_channel_by_number,
    find_live_channel_by_uniqueid,
)
from app.models import (
    AuditLog,
    Business,
    CallEvent,
    CallLog,
    CallSession,
    FlowRuntimeEvent,
    FlowVersion,
    SipTrunk,
)
from sqlalchemy import case, func


ami_service = AMIService()
ACTIVE_CALL_SESSION_STATUSES = {"queued", "initiating", "ringing", "answered"}


def _slug(value):
    import re

    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized or "trunk"


def _trunk_endpoint_name(trunk, realtime_enabled):
    business_part = trunk.business_id if trunk.business_id is not None else "global"
    if realtime_enabled:
        return f"dialyra_b{business_part}_t{trunk.id}_{_slug(trunk.name)}_ep"
    return f"dialyra-b{business_part}-t{trunk.id}-{_slug(trunk.name)}-endpoint"


def _build_originate_channel_variables(
    *,
    phone,
    trunk,
    endpoint,
    call_uuid,
    call_session_id,
    action_id,
    flow_id=None,
    flow_version_id=None,
    fastagi_call_token=None,
    extra_channel_variables=None,
):
    vars_map = {
        "TARGET_NUMBER": str(phone),
        "SIP_TRUNK_ENDPOINT": endpoint,
        "SIP_TRUNK_ID": trunk.id,
        "BUSINESS_ID": trunk.business_id,
        "SIP_TRUNK_HOST": trunk.host,
        "SIP_TRUNK_PORT": trunk.port,
        "SIP_TRUNK_TYPE": trunk.type,
        "CALL_LOG_UUID": call_uuid,
        "CALL_SESSION_ID": call_session_id,
        "CALL_ACTION_ID": action_id,
    }
    if flow_id is not None:
        vars_map["FLOW_ID"] = int(flow_id)
    if flow_version_id is not None:
        vars_map["FLOW_VERSION_ID"] = int(flow_version_id)
    if fastagi_call_token:
        vars_map["FASTAGI_CALL_TOKEN"] = str(fastagi_call_token)
    if isinstance(extra_channel_variables, dict):
        for key, value in extra_channel_variables.items():
            if key and value is not None:
                vars_map[str(key)] = value
    return vars_map


def originate_call(phone, channel_variables=None, action_id=None):
    return ami_service.originate_call(
        phone, channel_variables=channel_variables, action_id=action_id
    )


def _eligible_business_trunks(business_id):
    return (
        SipTrunk.query.filter_by(
            business_id=int(business_id),
            scope="business",
            is_active=True,
            status="active",
        )
        .order_by(SipTrunk.id.asc())
        .all()
    )


def _eligible_global_trunks():
    return (
        SipTrunk.query.filter_by(
            scope="global",
            is_active=True,
            status="active",
        )
        .order_by(SipTrunk.id.asc())
        .all()
    )


def _pick_min_load_trunk(trunks, realtime_enabled):
    ranked = []
    for trunk in trunks:
        endpoint = _trunk_endpoint_name(trunk, realtime_enabled=realtime_enabled)
        try:
            active_calls = count_active_calls_for_endpoint(endpoint, ami_service)["active_calls"]
        except Exception:
            active_calls = 0
        remaining = max(0, int(trunk.max_concurrent_calls or 0) - active_calls)
        ranked.append((trunk, endpoint, active_calls, remaining))

    with_capacity = [item for item in ranked if item[3] > 0]
    if not with_capacity:
        return None, ranked

    with_capacity.sort(key=lambda item: (item[2], -(item[3]), item[0].id))
    return with_capacity[0], ranked


def _count_active_sessions_for_business(business_id):
    return (
        CallSession.query.filter(
            CallSession.business_id == int(business_id),
            CallSession.status.in_(ACTIVE_CALL_SESSION_STATUSES),
            CallSession.ended_at.is_(None),
        )
        .count()
    )


def _count_active_sessions_systemwide():
    return (
        CallSession.query.filter(
            CallSession.status.in_(ACTIVE_CALL_SESSION_STATUSES),
            CallSession.ended_at.is_(None),
        )
        .count()
    )


def _cleanup_stale_active_sessions():
    """
    Close stale active sessions that were never finalized by event processing.
    This prevents false NO_SYSTEM_CAPACITY / NO_BUSINESS_CAPACITY blocks.
    """
    try:
        from flask import current_app

        timeout_minutes = int(
            current_app.config.get("CALL_SESSION_STALE_TIMEOUT_MINUTES", 15) or 15
        )
    except Exception:
        timeout_minutes = 15
    timeout_minutes = max(1, timeout_minutes)
    cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)

    stale_rows = (
        CallSession.query.filter(
            CallSession.status.in_(ACTIVE_CALL_SESSION_STATUSES),
            CallSession.ended_at.is_(None),
            CallSession.started_at.isnot(None),
            CallSession.started_at < cutoff,
        )
        .all()
    )
    if not stale_rows:
        return 0

    now = datetime.utcnow()
    for row in stale_rows:
        row.status = "failed"
        row.hangup_cause = row.hangup_cause or "stale_session_timeout"
        row.ended_at = now
    db.session.commit()
    return len(stale_rows)


def _business_max_concurrent_calls(business):
    raw = business.settings_json
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("max_concurrent_calls")
    if value is None:
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _business_default_flow_id(business):
    raw = business.settings_json
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("default_flow_id")
    if value is None:
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _resolve_flow_selection_for_business(business_id, *, flow_id=None, campaign_flow_id=None):
    # 1) explicit flow_id
    if flow_id is not None:
        row = (
            FlowVersion.query.filter_by(
                business_id=int(business_id),
                flow_id=int(flow_id),
                is_active=True,
            )
            .order_by(FlowVersion.version_number.desc())
            .first()
        )
        if row is None:
            return None, None, "INVALID_FLOW_ID: flow_id is not published/active for this business"
        return int(row.flow_id), int(row.id), "explicit_flow_id"

    # 2) campaign-linked flow (provided by caller integration)
    if campaign_flow_id is not None:
        row = (
            FlowVersion.query.filter_by(
                business_id=int(business_id),
                flow_id=int(campaign_flow_id),
                is_active=True,
            )
            .order_by(FlowVersion.version_number.desc())
            .first()
        )
        if row is None:
            return None, None, "INVALID_CAMPAIGN_FLOW_ID: campaign_flow_id is not published/active for this business"
        return int(row.flow_id), int(row.id), "campaign_flow_id"

    # 3) business default flow
    business = Business.query.get(int(business_id))
    default_flow_id = _business_default_flow_id(business) if business is not None else None
    if default_flow_id is not None:
        row = (
            FlowVersion.query.filter_by(
                business_id=int(business_id),
                flow_id=int(default_flow_id),
                is_active=True,
            )
            .order_by(FlowVersion.version_number.desc())
            .first()
        )
        if row is not None:
            return int(row.flow_id), int(row.id), "business_default_flow"

    # 4) latest active published flow for business
    row = (
        FlowVersion.query.filter_by(
            business_id=int(business_id),
            is_active=True,
        )
        .order_by(FlowVersion.published_at.desc(), FlowVersion.id.desc())
        .first()
    )
    if row is not None:
        return int(row.flow_id), int(row.id), "latest_published_flow"

    # 5) no flow
    return None, None, "NO_FLOW_AVAILABLE: No published flow available for this business"


def originate_call_for_business(
    phone,
    business_id,
    sip_trunk_id,
    realtime_enabled,
    actor_user_id=None,
    session_metadata=None,
    extra_channel_variables=None,
    flow_id=None,
    campaign_id=None,
    campaign_flow_id=None,
):
    business = Business.query.get(int(business_id))
    if business is None:
        return None, "Business not found"

    selected_flow_id, selected_flow_version_id, flow_selected_by = _resolve_flow_selection_for_business(
        business_id,
        flow_id=flow_id,
        campaign_flow_id=campaign_flow_id,
    )
    if flow_selected_by.startswith("INVALID_") or flow_selected_by.startswith("NO_FLOW_AVAILABLE"):
        return None, flow_selected_by

    # First reconcile stale sessions so capacity checks reflect real availability.
    _cleanup_stale_active_sessions()

    business_active_calls_before = _count_active_sessions_for_business(business_id)
    business_max_concurrent = _business_max_concurrent_calls(business)
    if (
        business_max_concurrent is not None
        and business_active_calls_before >= int(business_max_concurrent)
    ):
        return (
            None,
            "NO_BUSINESS_CAPACITY: No slot available for this business",
        )

    system_active_calls_before = _count_active_sessions_systemwide()
    system_max_concurrent = int(getattr(ami_service, "system_max_concurrent", 0) or 0)
    if system_max_concurrent <= 0:
        # pull from flask config when available
        try:
            from flask import current_app

            system_max_concurrent = int(current_app.config.get("SYSTEM_MAX_CONCURRENT_CALLS", 0) or 0)
        except Exception:
            system_max_concurrent = 0
    if system_max_concurrent > 0 and system_active_calls_before >= system_max_concurrent:
        return (
            None,
            "NO_SYSTEM_CAPACITY: No slot available at system capacity",
        )

    trunk = None
    endpoint = None
    active_calls_before = 0
    selected_by = "requested"
    if sip_trunk_id is not None:
        try:
            normalized_trunk_id = int(sip_trunk_id)
        except (TypeError, ValueError):
            return None, "Invalid sip_trunk_id"
        trunk = SipTrunk.query.filter_by(id=normalized_trunk_id, is_active=True).first()
        if trunk is None:
            return None, "SIP trunk not found for this business"
        if trunk.scope == "business" and trunk.business_id != int(business_id):
            return None, "SIP trunk not found for this business"
        if trunk.scope == "global" and not business.allow_global_sip_fallback:
            return (
                None,
                "GLOBAL_SIP_NOT_ALLOWED: Global SIP fallback is not enabled for this business",
            )
        endpoint = _trunk_endpoint_name(trunk, realtime_enabled=realtime_enabled)
        try:
            active_calls_before = count_active_calls_for_endpoint(endpoint, ami_service)["active_calls"]
        except Exception:
            active_calls_before = 0
        if active_calls_before >= int(trunk.max_concurrent_calls or 0):
            return (
                None,
                "NO_TRUNK_CAPACITY: No slot available on selected SIP trunk",
            )
    else:
        business_trunks = _eligible_business_trunks(business_id)
        if business_trunks:
            picked, _ranked = _pick_min_load_trunk(
                business_trunks, realtime_enabled=realtime_enabled
            )
            if picked is None:
                return (
                    None,
                    "NO_TRUNK_CAPACITY: No slot available on any business SIP trunk",
                )
            trunk, endpoint, active_calls_before, _remaining = picked
            selected_by = "auto_business"
        else:
            if not business.allow_global_sip_fallback:
                return (
                    None,
                    "NO_SIP_AVAILABLE: Business has no active SIP trunk and global fallback is disabled",
                )
            global_trunks = _eligible_global_trunks()
            if not global_trunks:
                return (
                    None,
                    "NO_SIP_AVAILABLE: No active global SIP trunk available",
                )
            picked, _ranked = _pick_min_load_trunk(
                global_trunks, realtime_enabled=realtime_enabled
            )
            if picked is None:
                return (
                    None,
                    "NO_TRUNK_CAPACITY: No slot available on any global SIP trunk",
                )
            trunk, endpoint, active_calls_before, _remaining = picked
            selected_by = "auto_global_fallback"

    action_id = str(uuid.uuid4())
    call_uuid = str(uuid.uuid4())

    started_at = datetime.utcnow()

    call_log = CallLog(
        uuid=call_uuid,
        action_id=action_id,
        business_id=int(business_id),
        sip_trunk_id=trunk.id,
        actor_user_id=actor_user_id,
        direction="outbound",
        to_number=str(phone),
        dialed_number=str(phone),
        status="queued",
        started_at=started_at,
    )
    call_session = CallSession(
        business_id=int(business_id),
        flow_id=selected_flow_id,
        flow_version_id=selected_flow_version_id,
        campaign_id=(int(campaign_id) if campaign_id is not None else None),
        contact_id=None,
        sip_trunk_id=trunk.id,
        call_direction="outbound",
        status="queued",
        phone_number=str(phone),
        caller_id=None,
        channel=None,
        uniqueid=None,
        linkedid=None,
        ami_action_id=action_id,
        variables_json=None,
        metadata_json=(json.dumps(session_metadata) if isinstance(session_metadata, dict) else None),
        started_at=started_at,
        answered_at=None,
        ended_at=None,
        hangup_cause=None,
        created_by=actor_user_id,
    )
    db.session.add(call_session)
    db.session.add(call_log)
    db.session.commit()

    channel_vars = _build_originate_channel_variables(
        phone=phone,
        trunk=trunk,
        endpoint=endpoint,
        call_uuid=call_uuid,
        call_session_id=call_session.id,
        action_id=action_id,
        flow_id=selected_flow_id,
        flow_version_id=selected_flow_version_id,
        fastagi_call_token=issue_fastagi_call_token(
            call_session_id=call_session.id,
            business_id=int(business_id),
            ttl_sec=int(getattr(ami_service, "fastagi_call_token_ttl_sec", 900) or 900),
        ),
        extra_channel_variables=extra_channel_variables,
    )

    response = originate_call(
        phone,
        channel_variables=channel_vars,
        action_id=action_id,
    )
    return {
        "ami_response": response,
        "call_log_uuid": call_uuid,
        "call_session_id": call_session.id,
        "action_id": action_id,
        "sip_trunk_id": trunk.id,
        "sip_endpoint": endpoint,
        "selected_by": selected_by,
        "selected_flow_id": selected_flow_id,
        "selected_flow_version_id": selected_flow_version_id,
        "flow_selected_by": flow_selected_by,
        "active_calls_before": active_calls_before,
        "max_concurrent_calls": trunk.max_concurrent_calls,
        "business_active_calls_before": business_active_calls_before,
        "business_max_concurrent_calls": business_max_concurrent,
        "system_active_calls_before": system_active_calls_before,
        "system_max_concurrent_calls": system_max_concurrent,
    }, None


def _parse_metadata_json(raw):
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def retry_call_session_for_business(
    *,
    source_call_session_id,
    business_id,
    realtime_enabled,
    actor_user_id=None,
    max_attempts=3,
):
    try:
        normalized_source_id = int(source_call_session_id)
    except (TypeError, ValueError):
        return None, "Invalid call_session_id"

    source = CallSession.query.filter_by(
        id=normalized_source_id,
        business_id=int(business_id),
    ).first()
    if source is None:
        return None, "Call session not found"

    if source.ended_at is None:
        return None, "Call is still active; retry is only allowed for ended calls"

    retryable_statuses = {"failed", "busy", "no_answer", "cancelled"}
    if str(source.status or "").lower() not in retryable_statuses:
        return None, "Call is not retry-eligible for its current status"

    metadata = _parse_metadata_json(source.metadata_json)
    retry_count = int(metadata.get("retry_count") or 0)
    normalized_max_attempts = max(1, int(max_attempts or 3))
    if retry_count >= normalized_max_attempts:
        return None, "Retry attempts exceeded for this call session"

    next_retry_count = retry_count + 1
    session_metadata = {
        "retry_of_call_session_id": source.id,
        "retry_count": next_retry_count,
    }
    result, error = originate_call_for_business(
        phone=source.phone_number,
        business_id=business_id,
        sip_trunk_id=source.sip_trunk_id,
        realtime_enabled=realtime_enabled,
        actor_user_id=actor_user_id,
        session_metadata=session_metadata,
        flow_id=source.flow_id,
        campaign_id=source.campaign_id,
        extra_channel_variables={
            "RETRY_COUNT": next_retry_count,
            "RETRY_OF_CALL_SESSION_ID": source.id,
        },
    )
    if error:
        return None, error
    return {
        **result,
        "retry_of_call_session_id": source.id,
        "retry_count": next_retry_count,
    }, None


def request_hangup_for_business(
    *,
    call_session_id,
    business_id,
    reason=None,
    explicit_channel=None,
):
    try:
        normalized_session_id = int(call_session_id)
    except (TypeError, ValueError):
        return None, "Invalid call_session_id"

    call_session = CallSession.query.filter_by(
        id=normalized_session_id,
        business_id=int(business_id),
    ).first()
    if call_session is None:
        return None, "Call session not found"

    # Idempotent safety: already ended.
    if call_session.ended_at is not None:
        return {
            "status": "already_ended",
            "call_session_id": call_session.id,
            "ended_at": call_session.ended_at.isoformat(),
            "message": "Call already ended",
        }, None

    # Resolve live channel from explicit input, stored channel, uniqueid lookup,
    # then a safe number-based fallback for early-call windows.
    resolved_channel = str(explicit_channel or "").strip() or str(call_session.channel or "").strip()
    if not resolved_channel:
        row = find_live_channel_by_uniqueid(call_session.uniqueid, ami_service)
        if row is not None:
            resolved_channel = row.get("channel") or ""
    if not resolved_channel:
        linked_log = None
        if call_session.ami_action_id:
            linked_log = (
                CallLog.query.filter(CallLog.action_id == str(call_session.ami_action_id))
                .order_by(CallLog.id.desc())
                .first()
            )
        if linked_log is None and call_session.uniqueid:
            linked_log = (
                CallLog.query.filter(CallLog.asterisk_uniqueid == str(call_session.uniqueid))
                .order_by(CallLog.id.desc())
                .first()
            )
        candidate_number = (
            linked_log.to_number
            if linked_log is not None and linked_log.to_number
            else call_session.phone_number
        )
        number_match = find_live_channel_by_number(candidate_number, ami_service)
        if number_match.get("ambiguous"):
            return (
                None,
                f"Ambiguous live channel match for number fallback ({number_match.get('match_count')} matches); provide explicit channel",
            )
        row = number_match.get("channel_row")
        if row is not None:
            resolved_channel = row.get("channel") or ""

    if not resolved_channel:
        return None, "Live channel not found for this call session"

    action_id = str(uuid.uuid4())
    response = ami_service.hangup_channel(resolved_channel, action_id=action_id)

    # Mark local status immediately as hangup request accepted.
    call_session.status = "hangup"
    call_session.channel = resolved_channel
    if reason:
        call_session.hangup_cause = str(reason)[:64]

    linked_log = None
    if call_session.ami_action_id:
        linked_log = (
            CallLog.query.filter(CallLog.action_id == str(call_session.ami_action_id))
            .order_by(CallLog.id.desc())
            .first()
        )
    if linked_log is None and call_session.uniqueid:
        linked_log = (
            CallLog.query.filter(CallLog.asterisk_uniqueid == str(call_session.uniqueid))
            .order_by(CallLog.id.desc())
            .first()
        )
    if linked_log is not None:
        linked_log.status = "canceled"
        if reason:
            linked_log.hangup_cause_text = str(reason)[:255]

    db.session.commit()
    return {
        "status": "hangup_requested",
        "call_session_id": call_session.id,
        "action_id": action_id,
        "channel": resolved_channel,
        "ami_response": response,
    }, None


def _serialize_call_log(row):
    return {
        "id": row.id,
        "uuid": row.uuid,
        "action_id": row.action_id,
        "asterisk_uniqueid": row.asterisk_uniqueid,
        "linkedid": row.linkedid,
        "business_id": row.business_id,
        "sip_trunk_id": row.sip_trunk_id,
        "actor_user_id": row.actor_user_id,
        "direction": row.direction,
        "from_number": row.from_number,
        "to_number": row.to_number,
        "dialed_number": row.dialed_number,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "answered_at": row.answered_at.isoformat() if row.answered_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "duration_sec": row.duration_sec,
        "billsec": row.billsec,
        "hangup_cause": row.hangup_cause,
        "hangup_cause_text": row.hangup_cause_text,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _safe_json_loads(value, default=None):
    if default is None:
        default = {}
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _resolve_call_session_for_log(call_log):
    if call_log is None:
        return None
    if call_log.action_id:
        row = (
            CallSession.query.filter(CallSession.ami_action_id == str(call_log.action_id))
            .order_by(CallSession.id.desc())
            .first()
        )
        if row:
            return row
    if call_log.asterisk_uniqueid:
        row = (
            CallSession.query.filter(CallSession.uniqueid == str(call_log.asterisk_uniqueid))
            .order_by(CallSession.id.desc())
            .first()
        )
        if row:
            return row
    if call_log.linkedid:
        row = (
            CallSession.query.filter(CallSession.linkedid == str(call_log.linkedid))
            .order_by(CallSession.id.desc())
            .first()
        )
        if row:
            return row
    return None


def _build_call_timeline(call_log, call_session):
    call_session_id = str(call_session.id) if call_session is not None else ""
    business_id = int(call_log.business_id) if call_log and call_log.business_id is not None else None

    dtmf_events = []
    actions = []

    if business_id is not None and call_session_id:
        runtime_rows = (
            FlowRuntimeEvent.query.filter(
                FlowRuntimeEvent.business_id == business_id,
                FlowRuntimeEvent.call_session_id == call_session_id,
            )
            .order_by(FlowRuntimeEvent.created_at.asc(), FlowRuntimeEvent.id.asc())
            .all()
        )
        for row in runtime_rows:
            payload = _safe_json_loads(row.event_data, default={})
            item = {
                "source": "runtime",
                "event_type": row.event_type,
                "timestamp": row.created_at.isoformat() if row.created_at else None,
                "node_id": row.node_id,
                "payload": payload,
            }
            actions.append(item)
            if row.event_type == "dtmf.received":
                dtmf_events.append(
                    {
                        "digits": str(payload.get("digits") or payload.get("value") or ""),
                        "timestamp": item["timestamp"],
                        "source": "runtime",
                        "node_id": row.node_id,
                        "trace_id": payload.get("trace_id"),
                    }
                )

        audit_rows = (
            AuditLog.query.filter(
                AuditLog.business_id == business_id,
                AuditLog.metadata_json.ilike(f"%{call_session_id}%"),
            )
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            .limit(500)
            .all()
        )
        for row in audit_rows:
            metadata = _safe_json_loads(row.metadata_json, default={})
            if str(
                metadata.get("call_session_id")
                or metadata.get("source_call_session_id")
                or ""
            ) != call_session_id:
                continue
            actions.append(
                {
                    "source": "audit",
                    "event_type": row.action,
                    "timestamp": row.created_at.isoformat() if row.created_at else None,
                    "payload": metadata,
                }
            )

    call_event_query = CallEvent.query
    if call_log is not None:
        if call_session is not None:
            call_event_query = call_event_query.filter(
                (CallEvent.call_log_id == call_log.id)
                | (CallEvent.call_session_id == call_session.id)
            )
        else:
            call_event_query = call_event_query.filter(CallEvent.call_log_id == call_log.id)
    call_event_rows = (
        call_event_query.order_by(CallEvent.created_at.asc(), CallEvent.id.asc()).limit(500).all()
    )
    for row in call_event_rows:
        payload = _safe_json_loads(row.event_payload_json, default={})
        actions.append(
            {
                "source": "ami",
                "event_type": row.event_name,
                "timestamp": row.created_at.isoformat() if row.created_at else None,
                "processing_status": row.processing_status,
                "payload": payload,
            }
        )

    actions.sort(key=lambda x: str(x.get("timestamp") or ""))
    dtmf_events.sort(key=lambda x: str(x.get("timestamp") or ""))
    return {
        "call_session_id": int(call_session.id) if call_session is not None else None,
        "dtmf_events": dtmf_events,
        "actions": actions,
    }


def _allowed_business_ids_for_actor(actor_user):
    if actor_user.role == "superuser":
        return None
    owned_ids = [b.id for b in Business.query.filter_by(owner_user_id=actor_user.id).all()]
    from app.models import WorkspaceMembership

    member_ids = [
        m.business_id
        for m in WorkspaceMembership.query.filter_by(user_id=actor_user.id, status="active").all()
    ]
    return sorted(set(owned_ids + member_ids))


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def list_call_history(actor_user, filters):
    query = CallLog.query

    allowed_ids = _allowed_business_ids_for_actor(actor_user)
    if allowed_ids is not None:
        if not allowed_ids:
            return {"items": [], "pagination": {"page": 1, "page_size": 20, "total": 0}}, None
        query = query.filter(CallLog.business_id.in_(allowed_ids))

    business_id = filters.get("business_id")
    if business_id is not None:
        try:
            business_id = int(business_id)
        except (TypeError, ValueError):
            return None, "Invalid business_id"
        if allowed_ids is not None and business_id not in allowed_ids:
            return None, "Insufficient permission for this business"
        query = query.filter(CallLog.business_id == business_id)

    sip_trunk_id = filters.get("sip_trunk_id")
    if sip_trunk_id is not None:
        try:
            query = query.filter(CallLog.sip_trunk_id == int(sip_trunk_id))
        except (TypeError, ValueError):
            return None, "Invalid sip_trunk_id"

    status = (filters.get("status") or "").strip().lower()
    if status:
        query = query.filter(CallLog.status == status)

    number = (filters.get("number") or "").strip()
    if number:
        like = f"%{number}%"
        query = query.filter(
            (CallLog.to_number.ilike(like))
            | (CallLog.from_number.ilike(like))
            | (CallLog.dialed_number.ilike(like))
        )

    date_from = _parse_dt(filters.get("date_from"))
    if filters.get("date_from") and date_from is None:
        return None, "Invalid date_from (expected ISO datetime)"
    if date_from:
        query = query.filter(CallLog.started_at >= date_from)

    date_to = _parse_dt(filters.get("date_to"))
    if filters.get("date_to") and date_to is None:
        return None, "Invalid date_to (expected ISO datetime)"
    if date_to:
        query = query.filter(CallLog.started_at <= date_to)

    try:
        page = max(1, int(filters.get("page") or 1))
        page_size = int(filters.get("page_size") or 20)
    except (TypeError, ValueError):
        return None, "Invalid pagination params"
    page_size = max(1, min(200, page_size))

    total = query.count()
    items = (
        query.order_by(CallLog.started_at.desc(), CallLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_serialize_call_log(item) for item in items],
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }, None


def get_call_history_by_id(actor_user, call_id):
    try:
        normalized_id = int(call_id)
    except (TypeError, ValueError):
        return None, "Invalid call id"

    row = CallLog.query.get(normalized_id)
    if row is None:
        return None, "Call history not found"

    allowed_ids = _allowed_business_ids_for_actor(actor_user)
    if allowed_ids is not None and row.business_id not in allowed_ids:
        return None, "Insufficient permission for this business"

    payload = _serialize_call_log(row)
    call_session = _resolve_call_session_for_log(row)
    payload["timeline"] = _build_call_timeline(row, call_session)
    return payload, None


def get_call_metrics(actor_user, filters):
    query = CallLog.query

    allowed_ids = _allowed_business_ids_for_actor(actor_user)
    if allowed_ids is not None:
        if not allowed_ids:
            empty = {
                "summary": {
                    "total_calls": 0,
                    "answered": 0,
                    "failed": 0,
                    "asr": 0.0,
                    "avg_duration_sec": 0.0,
                    "peak_concurrent_estimate": 0,
                },
                "by_business": [],
                "by_trunk": [],
            }
            return empty, None
        query = query.filter(CallLog.business_id.in_(allowed_ids))

    business_id = filters.get("business_id")
    if business_id is not None:
        try:
            business_id = int(business_id)
        except (TypeError, ValueError):
            return None, "Invalid business_id"
        if allowed_ids is not None and business_id not in allowed_ids:
            return None, "Insufficient permission for this business"
        query = query.filter(CallLog.business_id == business_id)

    sip_trunk_id = filters.get("sip_trunk_id")
    if sip_trunk_id is not None:
        try:
            query = query.filter(CallLog.sip_trunk_id == int(sip_trunk_id))
        except (TypeError, ValueError):
            return None, "Invalid sip_trunk_id"

    date_from = _parse_dt(filters.get("date_from"))
    if filters.get("date_from") and date_from is None:
        return None, "Invalid date_from (expected ISO datetime)"
    if date_from:
        query = query.filter(CallLog.started_at >= date_from)

    date_to = _parse_dt(filters.get("date_to"))
    if filters.get("date_to") and date_to is None:
        return None, "Invalid date_to (expected ISO datetime)"
    if date_to:
        query = query.filter(CallLog.started_at <= date_to)

    base_subquery = query.subquery()
    status_col = base_subquery.c.status
    duration_col = base_subquery.c.duration_sec
    business_col = base_subquery.c.business_id
    trunk_col = base_subquery.c.sip_trunk_id

    answered_expr = func.sum(case((status_col.in_(["answered", "completed"]), 1), else_=0))
    failed_expr = func.sum(
        case((status_col.in_(["failed", "busy", "no_answer", "canceled"]), 1), else_=0)
    )

    summary_row = db.session.query(
        func.count().label("total_calls"),
        answered_expr.label("answered"),
        failed_expr.label("failed"),
        func.avg(duration_col).label("avg_duration_sec"),
    ).select_from(base_subquery).first()

    total_calls = int(summary_row.total_calls or 0)
    answered = int(summary_row.answered or 0)
    failed = int(summary_row.failed or 0)
    avg_duration = float(summary_row.avg_duration_sec or 0.0)
    asr = round((answered / total_calls) * 100, 2) if total_calls else 0.0

    by_business_rows = (
        db.session.query(
            business_col.label("business_id"),
            func.count().label("total_calls"),
            answered_expr.label("answered"),
            failed_expr.label("failed"),
            func.avg(duration_col).label("avg_duration_sec"),
        )
        .select_from(base_subquery)
        .group_by(business_col)
        .order_by(business_col.asc())
        .all()
    )
    by_business = []
    for row in by_business_rows:
        row_total = int(row.total_calls or 0)
        row_answered = int(row.answered or 0)
        by_business.append(
            {
                "business_id": row.business_id,
                "total_calls": row_total,
                "answered": row_answered,
                "failed": int(row.failed or 0),
                "asr": round((row_answered / row_total) * 100, 2) if row_total else 0.0,
                "avg_duration_sec": float(row.avg_duration_sec or 0.0),
            }
        )

    by_trunk_rows = (
        db.session.query(
            trunk_col.label("sip_trunk_id"),
            func.count().label("total_calls"),
            answered_expr.label("answered"),
            failed_expr.label("failed"),
            func.avg(duration_col).label("avg_duration_sec"),
        )
        .select_from(base_subquery)
        .group_by(trunk_col)
        .order_by(trunk_col.asc())
        .all()
    )
    by_trunk = []
    for row in by_trunk_rows:
        row_total = int(row.total_calls or 0)
        row_answered = int(row.answered or 0)
        by_trunk.append(
            {
                "sip_trunk_id": row.sip_trunk_id,
                "total_calls": row_total,
                "answered": row_answered,
                "failed": int(row.failed or 0),
                "asr": round((row_answered / row_total) * 100, 2) if row_total else 0.0,
                "avg_duration_sec": float(row.avg_duration_sec or 0.0),
            }
        )

    peak_concurrent_estimate = _compute_peak_concurrency(
        query=query,
        date_from=date_from,
        date_to=date_to,
    )

    return {
        "summary": {
            "total_calls": total_calls,
            "answered": answered,
            "failed": failed,
            "asr": asr,
            "avg_duration_sec": avg_duration,
            "peak_concurrent_estimate": peak_concurrent_estimate,
        },
        "by_business": by_business,
        "by_trunk": by_trunk,
    }, None


def _serialize_audit_log(row):
    metadata = {}
    try:
        parsed = json.loads(row.metadata_json or "{}")
        if isinstance(parsed, dict):
            metadata = parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        metadata = {}
    return {
        "id": row.id,
        "business_id": row.business_id,
        "actor_user_id": row.actor_user_id,
        "action": row.action,
        "metadata": metadata,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _parse_audit_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def list_call_audit_events(
    actor_user,
    call_session_id,
    page=1,
    page_size=20,
    action=None,
    date_from=None,
    date_to=None,
):
    normalized_call_session_id = str(call_session_id or "").strip()
    if not normalized_call_session_id:
        return None, "Missing required query param: call_session_id"

    allowed_ids = _allowed_business_ids_for_actor(actor_user)
    query = AuditLog.query.filter(AuditLog.action.like("call.%"))
    action = str(action or "").strip()
    if action:
        query = query.filter(AuditLog.action == action)

    parsed_from = _parse_audit_dt(date_from)
    if date_from and parsed_from is None:
        return None, "Invalid date_from (expected ISO datetime)"
    if parsed_from:
        query = query.filter(AuditLog.created_at >= parsed_from)

    parsed_to = _parse_audit_dt(date_to)
    if date_to and parsed_to is None:
        return None, "Invalid date_to (expected ISO datetime)"
    if parsed_to:
        query = query.filter(AuditLog.created_at <= parsed_to)

    if allowed_ids is not None:
        if not allowed_ids:
            return {"items": [], "pagination": {"page": 1, "page_size": 20, "total": 0}}, None
        query = query.filter(AuditLog.business_id.in_(allowed_ids))

    # DB pre-filter by text, then strict JSON match in Python.
    text_hint = f"%{normalized_call_session_id}%"
    query = query.filter(AuditLog.metadata_json.ilike(text_hint))

    try:
        page = max(1, int(page or 1))
        page_size = max(1, min(200, int(page_size or 20)))
    except (TypeError, ValueError):
        return None, "Invalid pagination params"

    # Pull a bounded window for strict matching.
    candidate_rows = (
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(2000)
        .all()
    )

    strict = []
    for row in candidate_rows:
        try:
            parsed = json.loads(row.metadata_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, dict):
            continue
        if str(parsed.get("call_session_id") or parsed.get("source_call_session_id") or "") == normalized_call_session_id:
            strict.append(row)

    total = len(strict)
    start = (page - 1) * page_size
    end = start + page_size
    items = strict[start:end]
    return {
        "items": [_serialize_audit_log(item) for item in items],
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }, None


def _compute_peak_concurrency(query, date_from=None, date_to=None):
    rows = query.with_entities(
        CallLog.started_at,
        CallLog.ended_at,
        CallLog.duration_sec,
    ).all()
    if not rows:
        return 0

    now = datetime.utcnow()
    window_start = date_from
    window_end = date_to or now

    if window_start is None:
        starts = [r.started_at for r in rows if r.started_at is not None]
        window_start = min(starts) if starts else now

    events = []
    for row in rows:
        start = row.started_at
        if start is None:
            continue

        end = row.ended_at
        if end is None and row.duration_sec is not None:
            try:
                end = start + timedelta(seconds=max(0, int(row.duration_sec)))
            except (TypeError, ValueError):
                end = None
        if end is None:
            end = now

        # Keep only overlap with requested window.
        if end < window_start or start > window_end:
            continue
        if start < window_start:
            start = window_start
        if end > window_end:
            end = window_end
        if end < start:
            continue

        # [start, end): at same timestamp, process end(-1) before start(+1)
        events.append((start, +1))
        events.append((end, -1))

    if not events:
        return 0

    events.sort(key=lambda item: (item[0], item[1]))
    current = 0
    peak = 0
    for _ts, delta in events:
        current += delta
        if current > peak:
            peak = current
    return max(0, peak)
