import json
import uuid
from datetime import datetime
from time import perf_counter

from flask import current_app
from app.api.v2.flows.node_executors import execute_node
from app.extensions import db
from app.models import CallLog, CallSession, FlowRuntimeEvent, FlowRuntimeSession, FlowVersion


def _json_load(value, default):
    if not value:
        return default
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, type(default)) else default
    except json.JSONDecodeError:
        return default


def _log_event(session, event_type, event_data=None, node_id=None):
    row = FlowRuntimeEvent(
        business_id=session.business_id,
        call_session_id=session.call_session_id,
        flow_runtime_session_id=session.id,
        node_id=node_id,
        event_type=event_type,
        event_data=json.dumps(event_data or {}),
    )
    db.session.add(row)
    return row


def _resolve_active_version(business_id, payload):
    flow_version_id = payload.get("flow_version_id")
    if flow_version_id is not None:
        row = FlowVersion.query.filter_by(
            id=int(flow_version_id), business_id=business_id
        ).first()
        if row is None:
            return None, "Flow version not found"
        return row, None

    flow_id = payload.get("flow_id")
    if flow_id is None:
        return None, "Missing required field: flow_id or flow_version_id"
    row = (
        FlowVersion.query.filter_by(
            flow_id=int(flow_id),
            business_id=business_id,
            is_active=True,
        )
        .order_by(FlowVersion.version_number.desc())
        .first()
    )
    if row is None:
        return None, "No active published flow version found"
    return row, None


def _snapshot_maps(version_row):
    snapshot = _json_load(version_row.snapshot_json, {})
    flow_payload = snapshot.get("flow") if isinstance(snapshot, dict) else {}
    nodes = snapshot.get("nodes") if isinstance(snapshot, dict) else []
    edges = snapshot.get("edges") if isinstance(snapshot, dict) else []

    node_map = {int(n["id"]): n for n in nodes if isinstance(n, dict) and n.get("id") is not None}
    edge_list = [e for e in edges if isinstance(e, dict)]
    start_node_id = flow_payload.get("start_node_id")
    try:
        start_node_id = int(start_node_id) if start_node_id is not None else None
    except (TypeError, ValueError):
        start_node_id = None
    return node_map, edge_list, start_node_id


def _ensure_session(business_id, payload):
    call_session_id = (payload.get("call_session_id") or "").strip()
    if not call_session_id:
        return None, None, "Missing required field: call_session_id"

    session = FlowRuntimeSession.query.filter_by(
        business_id=int(business_id),
        call_session_id=call_session_id,
    ).first()
    if session is not None:
        return session, False, None

    version_row, err = _resolve_active_version(business_id, payload)
    if err:
        return None, None, err
    node_map, _, start_node_id = _snapshot_maps(version_row)
    if start_node_id is None or start_node_id not in node_map:
        return None, None, "Published flow version has no valid start node"

    variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
    session = FlowRuntimeSession(
        business_id=int(business_id),
        call_session_id=call_session_id,
        flow_id=version_row.flow_id,
        flow_version_id=version_row.id,
        current_node_id=start_node_id,
        status="running",
        variables_json=json.dumps(variables or {}),
        started_at=datetime.utcnow(),
    )
    db.session.add(session)
    db.session.flush()
    _log_event(
        session,
        "flow.started",
        {"flow_id": session.flow_id, "flow_version_id": session.flow_version_id, "start_node_id": start_node_id},
        node_id=start_node_id,
    )
    db.session.commit()
    return session, True, None


def _hydrate_runtime_variables(actor_business, session, merged_vars, *, result_type=None, value=None):
    out = dict(merged_vars or {})
    out.setdefault("call_session_id", str(session.call_session_id))
    out.setdefault("business_id", str(actor_business.id))
    out.setdefault("flow_id", str(session.flow_id) if session.flow_id is not None else None)
    out.setdefault(
        "flow_version_id", str(session.flow_version_id) if session.flow_version_id is not None else None
    )

    call_session_row = None
    try:
        call_session_row = CallSession.query.get(int(session.call_session_id))
    except (TypeError, ValueError):
        call_session_row = None

    if call_session_row is not None:
        out.setdefault("sip_trunk_id", str(call_session_row.sip_trunk_id or ""))
        out.setdefault("dialed_number", str(call_session_row.phone_number or ""))
        out.setdefault("call_started_at", call_session_row.started_at.isoformat() if call_session_row.started_at else None)
        out.setdefault(
            "call_answered_at", call_session_row.answered_at.isoformat() if call_session_row.answered_at else None
        )
        out.setdefault("call_ended_at", call_session_row.ended_at.isoformat() if call_session_row.ended_at else None)
        out.setdefault("hangup_cause", str(call_session_row.hangup_cause or ""))
        out.setdefault("call_action_id", str(call_session_row.ami_action_id or ""))

        call_session_vars = _json_load(call_session_row.variables_json, {})
        template_vars = None
        if isinstance(call_session_vars, dict):
            # primary key for new payload contract
            template_vars = call_session_vars.get("webhook_variables")
            # backward compatibility for older sessions
            if template_vars is None:
                template_vars = call_session_vars.get("template_variables")
        if isinstance(template_vars, dict):
            for key, val in template_vars.items():
                out.setdefault(str(key), val)

        if call_session_row.ami_action_id:
            log_row = (
                CallLog.query.filter(CallLog.action_id == str(call_session_row.ami_action_id))
                .order_by(CallLog.id.desc())
                .first()
            )
            if log_row is not None:
                out.setdefault("call_log_uuid", str(log_row.uuid or ""))

    if str(result_type or "").strip().lower() == "dtmf" and value is not None:
        out["dtmf_value"] = str(value)
    return out


def _edge_matches(edge, result_type, value, variables):
    cond = str(edge.get("condition_type") or "always").strip().lower()
    cond_val = edge.get("condition_value")
    result_type = (result_type or "").strip().lower()
    str_value = "" if value is None else str(value)

    if cond == "always":
        return True
    if cond in {"condition_matched", "condition_not_matched"}:
        return result_type == cond
    if cond in {"timeout", "invalid_input", "webhook_success", "webhook_failed", "retry_exceeded", "transfer_failed", "error"}:
        return result_type == cond
    if cond == "dtmf":
        return result_type == "dtmf" and str(cond_val or "") == str_value
    if cond == "variable_match":
        # expected pattern: key=value
        raw = str(cond_val or "")
        if "=" not in raw:
            return False
        k, expected = raw.split("=", 1)
        k = k.strip()
        expected = expected.strip()
        actual = variables.get(k)
        actual_str = "" if actual is None else str(actual)
        return actual_str == expected
    return False


def _resolve_next_edge(edges, source_node_id, result_type, value, variables):
    scoped = [e for e in edges if int(e.get("source_node_id", -1)) == int(source_node_id)]
    if not scoped:
        return None
    result_type = (result_type or "").strip().lower()
    str_value = "" if value is None else str(value)

    def _sort(edges_):
        return sorted(edges_, key=lambda e: (int(e.get("priority", 100)), int(e.get("id", 0))))

    # 1) Exact condition match (including typed + value checks)
    exact = []
    for e in scoped:
        cond = str(e.get("condition_type") or "always").strip().lower()
        cond_val = e.get("condition_value")
        if cond == "dtmf" and result_type == "dtmf" and str(cond_val or "") == str_value:
            exact.append(e)
        elif cond == "variable_match" and _edge_matches(e, result_type, value, variables):
            exact.append(e)
        elif cond in {
            "timeout",
            "invalid_input",
            "webhook_success",
            "webhook_failed",
            "retry_exceeded",
            "transfer_connected",
            "transfer_failed",
            "condition_matched",
            "condition_not_matched",
            "error",
        } and result_type == cond:
            exact.append(e)
    if exact:
        return _sort(exact)[0]

    # 2) DTMF unmatched handling:
    # If runtime returned DTMF but no exact dtmf edge matched, route to invalid_input
    # when present instead of falling through to an arbitrary dtmf edge.
    if result_type == "dtmf":
        invalid_edges = [
            e for e in scoped if str(e.get("condition_type") or "").strip().lower() == "invalid_input"
        ]
        if invalid_edges:
            return _sort(invalid_edges)[0]
        # No invalid_input edge configured; do not guess a dtmf branch.
        return None

    # 3) Error fallback edge
    error_edges = [e for e in scoped if str(e.get("condition_type") or "").strip().lower() == "error"]
    if error_edges:
        return _sort(error_edges)[0]

    # 4) Default always edge
    always_edges = [e for e in scoped if str(e.get("condition_type") or "").strip().lower() == "always"]
    if always_edges:
        return _sort(always_edges)[0]

    return None


def _enabled_node_types():
    raw = str(current_app.config.get("FLOW_RUNTIME_ENABLED_NODE_TYPES", "") or "").strip()
    if not raw:
        return None
    out = {item.strip().lower() for item in raw.split(",") if item.strip()}
    return out if out else None


def _bool_from_text(value):
    normalized = str(value or "").strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return None


def _is_node_type_enabled(node_type):
    # 1) explicit per-node flags (highest priority)
    flag_map = {
        "play_audio": "FLOW_RUNTIME_ENABLE_PLAY_AUDIO",
        "say_text": "FLOW_RUNTIME_ENABLE_SAY_TEXT",
        "tts": "FLOW_RUNTIME_ENABLE_TTS",
        "gather_input": "FLOW_RUNTIME_ENABLE_GATHER_INPUT",
        "condition": "FLOW_RUNTIME_ENABLE_CONDITION",
        "set_variable": "FLOW_RUNTIME_ENABLE_SET_VARIABLE",
        "goto": "FLOW_RUNTIME_ENABLE_GOTO",
        "webhook": "FLOW_RUNTIME_ENABLE_WEBHOOK",
        "transfer_call": "FLOW_RUNTIME_ENABLE_TRANSFER_CALL",
        "wait": "FLOW_RUNTIME_ENABLE_WAIT",
        "record_control": "FLOW_RUNTIME_ENABLE_RECORD_CONTROL",
        "hangup": "FLOW_RUNTIME_ENABLE_HANGUP",
    }
    cfg_key = flag_map.get(node_type)
    if cfg_key:
        explicit = _bool_from_text(current_app.config.get(cfg_key, ""))
        if explicit is not None:
            return explicit, "explicit_flag"

    # 2) global allowlist
    enabled = _enabled_node_types()
    if enabled is not None:
        return node_type in enabled, "allowlist"

    # 3) default allow
    return True, "default"


def _execute_node_with_observability(
    actor_business,
    session,
    node_payload,
    variables,
    trace_id,
):
    node_type = str(node_payload.get("node_type") or "").strip().lower()
    is_enabled, enable_source = _is_node_type_enabled(node_type)
    if not is_enabled:
        _log_event(
            session,
            "node.failed",
            {
                "trace_id": trace_id,
                "node_type": node_type,
                "error": "node_type_disabled_by_rollout",
                "rollout_source": enable_source,
            },
            node_id=node_payload.get("id"),
        )
        db.session.commit()
        return None, f"Node type disabled by rollout: {node_type}"

    started = perf_counter()
    execution = execute_node(actor_business, node_payload, variables)
    elapsed_ms = int((perf_counter() - started) * 1000)

    if execution.error:
        _log_event(
            session,
            "node.failed",
            {
                "trace_id": trace_id,
                "node_type": node_type,
                "duration_ms": elapsed_ms,
                "error": execution.error,
            },
            node_id=node_payload.get("id"),
        )
        db.session.commit()
        return None, execution.error

    _log_event(
        session,
        "node.executed",
        {
            "trace_id": trace_id,
            "node_type": node_type,
            "duration_ms": elapsed_ms,
            "runtime_action_type": execution.runtime_action.get("type"),
            "webhook": (execution.metadata or {}).get("webhook"),
            "rollout_source": enable_source,
        },
        node_id=node_payload.get("id"),
    )
    db.session.commit()
    return execution, None


def _node_id_by_key(node_map, node_key):
    if not node_key:
        return None
    normalized = str(node_key).strip()
    for node_id, node in node_map.items():
        if str(node.get("node_key") or "").strip() == normalized:
            return int(node_id)
    return None


def resolve_next_runtime(actor_business, payload):
    trace_id = str(payload.get("trace_id") or uuid.uuid4())
    session, created, err = _ensure_session(actor_business.id, payload)
    if err:
        return None, err

    version_row = FlowVersion.query.filter_by(id=session.flow_version_id).first()
    if version_row is None:
        return None, "Flow version not found for runtime session"
    node_map, edge_list, start_node_id = _snapshot_maps(version_row)
    if not node_map:
        return None, "Flow version snapshot has no nodes"

    existing_vars = _json_load(session.variables_json, {})
    incoming_vars = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
    merged_vars = dict(existing_vars)
    merged_vars.update(incoming_vars)
    merged_vars = _hydrate_runtime_variables(
        actor_business,
        session,
        merged_vars,
        result_type=payload.get("result_type"),
        value=payload.get("value"),
    )

    current_node_id = payload.get("current_node_id", session.current_node_id)
    try:
        current_node_id = int(current_node_id) if current_node_id is not None else None
    except (TypeError, ValueError):
        current_node_id = None
    if current_node_id is None:
        current_node_id = start_node_id
    if current_node_id not in node_map:
        return None, "Current node not found in flow snapshot"

    result_type = payload.get("result_type")
    value = payload.get("value")

    next_node_id = current_node_id
    matched_edge = None
    # If this is not the first entrance or if result_type provided, resolve via edges.
    if (not created) or result_type:
        matched_edge = _resolve_next_edge(edge_list, current_node_id, result_type, value, merged_vars)
        if matched_edge is None:
            return None, "No matching edge found for current node/result"
        next_node_id = int(matched_edge.get("target_node_id"))
        if next_node_id not in node_map:
            return None, "Matched edge target node not found in flow snapshot"

    next_node = node_map[next_node_id]
    execution, exec_error = _execute_node_with_observability(
        actor_business, session, next_node, merged_vars, trace_id
    )
    if exec_error:
        return None, exec_error
    runtime_action = execution.runtime_action
    tts_result = (execution.metadata or {}).get("tts")

    hops = 0
    max_hops = 8
    last_auto_result_type = None
    while hops < max_hops:
        metadata = execution.metadata or {}
        goto_target_id = metadata.get("goto_target_node_id")
        goto_target_key = metadata.get("goto_target_node_key")
        auto_result_type = metadata.get("auto_result_type")
        auto_value = metadata.get("auto_value")

        computed_target = None
        computed_edge = None
        if goto_target_id is not None:
            try:
                computed_target = int(goto_target_id)
            except (TypeError, ValueError):
                return None, "Invalid goto target_node_id"
        elif goto_target_key:
            computed_target = _node_id_by_key(node_map, goto_target_key)
            if computed_target is None:
                return None, "goto target_node_key not found in flow snapshot"
        elif auto_result_type:
            computed_edge = _resolve_next_edge(
                edge_list,
                next_node_id,
                auto_result_type,
                auto_value,
                merged_vars,
            )
            if computed_edge is None:
                break
            computed_target = int(computed_edge.get("target_node_id"))
            last_auto_result_type = auto_result_type
        else:
            break

        if computed_target not in node_map:
            return None, "Auto progression target node not found in flow snapshot"

        matched_edge = computed_edge or matched_edge
        next_node_id = computed_target
        next_node = node_map[next_node_id]
        execution, exec_error = _execute_node_with_observability(
            actor_business, session, next_node, merged_vars, trace_id
        )
        if exec_error:
            return None, exec_error
        runtime_action = execution.runtime_action
        maybe_tts = (execution.metadata or {}).get("tts")
        if maybe_tts is not None:
            tts_result = maybe_tts
        hops += 1

    if hops >= max_hops:
        return None, "Auto progression exceeded safety hop limit"

    session.current_node_id = next_node_id
    session.variables_json = json.dumps(merged_vars)
    _log_event(
        session,
        "edge.selected" if matched_edge else "node.entered",
        {
            "trace_id": trace_id,
            "from_node_id": current_node_id,
            "matched_edge_id": matched_edge.get("id") if matched_edge else None,
            "next_node_id": next_node_id,
            "result_type": result_type,
            "value": value,
            "auto_result_type": last_auto_result_type,
            "auto_hops": hops,
        },
        node_id=next_node_id,
    )
    db.session.commit()

    response = {
        "status": "accepted",
        "business_id": actor_business.id,
        "call_session_id": session.call_session_id,
        "flow_id": session.flow_id,
        "flow_version_id": session.flow_version_id,
        "session_id": session.id,
        "created_session": bool(created),
        "current_node_id": current_node_id,
        "next_node_id": next_node_id,
        "next_node_type": next_node.get("node_type"),
        "matched_edge_id": matched_edge.get("id") if matched_edge else None,
        "runtime_action": runtime_action,
        "variables": merged_vars,
        "observability": {
            "trace_id": trace_id,
            "resolved_at": datetime.utcnow().isoformat(),
            "event_type": "edge.selected" if matched_edge else "node.entered",
        },
    }
    if tts_result is not None:
        response["tts"] = tts_result
    return response, None


def append_runtime_event(actor_business, call_session_id, event_type, payload):
    session = FlowRuntimeSession.query.filter_by(
        business_id=actor_business.id,
        call_session_id=call_session_id,
    ).first()
    if session is None:
        return None, "Runtime session not found"

    event_payload = payload if isinstance(payload, dict) else {"payload": payload}
    if "trace_id" not in event_payload:
        event_payload["trace_id"] = str(uuid.uuid4())
    row = _log_event(
        session,
        event_type,
        event_payload,
        node_id=session.current_node_id,
    )
    db.session.commit()
    return {
        "status": "accepted",
        "session_id": session.id,
        "event": event_type,
        "event_id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "trace_id": event_payload.get("trace_id"),
    }, None


def get_runtime_state(actor_business, flow_id, call_session_id=None):
    try:
        normalized_flow_id = int(flow_id)
    except (TypeError, ValueError):
        return None, "Invalid flow_id"

    if call_session_id:
        session = (
            FlowRuntimeSession.query.filter_by(
                business_id=actor_business.id,
                flow_id=normalized_flow_id,
                call_session_id=str(call_session_id),
            )
            .order_by(FlowRuntimeSession.started_at.desc())
            .first()
        )
    else:
        session = (
            FlowRuntimeSession.query.filter_by(
                business_id=actor_business.id,
                flow_id=normalized_flow_id,
            )
            .order_by(FlowRuntimeSession.started_at.desc())
            .first()
        )

    active_version = (
        FlowVersion.query.filter_by(
            business_id=actor_business.id,
            flow_id=normalized_flow_id,
            is_active=True,
        )
        .order_by(FlowVersion.version_number.desc())
        .first()
    )
    if active_version is None:
        return None, "No active published flow version found"

    node_map, _, _ = _snapshot_maps(active_version)

    if session is None:
        return {
            "business_id": actor_business.id,
            "flow_id": normalized_flow_id,
            "session": None,
            "active_flow_version": {
                "id": active_version.id,
                "version_number": active_version.version_number,
                "published_at": active_version.published_at.isoformat() if active_version.published_at else None,
            },
            "current_node": None,
            "variables": {},
        }, None

    current_node_payload = node_map.get(session.current_node_id) if session.current_node_id else None
    return {
        "business_id": actor_business.id,
        "flow_id": normalized_flow_id,
        "session": {
            "id": session.id,
            "call_session_id": session.call_session_id,
            "flow_version_id": session.flow_version_id,
            "current_node_id": session.current_node_id,
            "status": session.status,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        },
        "active_flow_version": {
            "id": active_version.id,
            "version_number": active_version.version_number,
            "published_at": active_version.published_at.isoformat() if active_version.published_at else None,
        },
        "current_node": current_node_payload,
        "variables": _json_load(session.variables_json, {}),
    }, None
