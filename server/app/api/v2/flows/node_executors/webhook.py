from datetime import datetime
from urllib.parse import urlparse

import requests
from flask import current_app

from .base import NodeExecutionResult, node_config
from app.services.post_call_intent_store import append_intent
from app.services.template_resolver import (
    build_node_resolution_context,
    render_template_value,
)
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_MAX_TIMEOUT_SECONDS = 15


def _validate_url(url):
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _json_path_get(data, path):
    if not path:
        return None
    cur = data
    for part in str(path).split("."):
        key = part.strip()
        if not key:
            return None
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
            continue
        if isinstance(cur, list):
            try:
                idx = int(key)
            except (TypeError, ValueError):
                return None
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
            continue
        return None
    return cur


def _deferred_mode_enabled():
    try:
        return bool(current_app.config.get("FLOW_WEBHOOK_DEFERRED_MODE", True))
    except Exception:
        return True


def _next_sequence(variables):
    raw = variables.get("__webhook_intent_seq")
    try:
        seq = int(raw or 0) + 1
    except (TypeError, ValueError):
        seq = 1
    variables["__webhook_intent_seq"] = seq
    return seq


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    scoped_vars, input_map_errors = build_node_resolution_context(
        runtime_variables=variables,
        system_variables={},
        input_map=cfg.get("input_map"),
    )
    if input_map_errors:
        return NodeExecutionResult(
            runtime_action={},
            error=input_map_errors[0]["message"],
        )
    method = str(cfg.get("method") or "GET").strip().upper()
    if method not in _ALLOWED_METHODS:
        return NodeExecutionResult(runtime_action={}, error="webhook node has invalid method")

    url = str(cfg.get("url") or "").strip()
    if not url:
        return NodeExecutionResult(runtime_action={}, error="webhook node missing config.url")
    url = render_template_value(url, scoped_vars)
    if not _validate_url(url):
        return NodeExecutionResult(runtime_action={}, error="webhook node url must be absolute http/https")

    raw_timeout = cfg.get("timeout_seconds", 5)
    try:
        timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError):
        timeout_seconds = 5.0
    timeout_seconds = max(1.0, min(_MAX_TIMEOUT_SECONDS, timeout_seconds))

    headers = render_template_value(
        cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {},
        scoped_vars,
    )
    body_template = cfg.get("payload")
    if body_template is None:
        # Backward compatibility for legacy webhook nodes.
        body_template = cfg.get("body_template")
    payload = render_template_value(body_template, scoped_vars) if body_template is not None else None

    if _deferred_mode_enabled():
        seq = _next_sequence(variables if isinstance(variables, dict) else {})
        node_key = str(node_payload.get("node_key") or "").strip()
        node_id = node_payload.get("id")
        intent = {
            "intent_type": "webhook",
            "sequence_no": seq,
            "node_id": node_id,
            "node_key": node_key,
            "method": method,
            "url": url,
            "headers": headers,
            "payload": payload,
            "timeout_seconds": timeout_seconds,
            "auth": cfg.get("auth") if isinstance(cfg.get("auth"), dict) else {"type": "none"},
            "description": str(cfg.get("description") or "").strip() or None,
            "captured_at": datetime.utcnow().isoformat(),
            "idempotency_hint": f"{scoped_vars.get('call_action_id', '')}:{node_key}:{seq}",
            "context": {
                "business_id": scoped_vars.get("business_id"),
                "call_action_id": scoped_vars.get("call_action_id"),
                "call_session_id": scoped_vars.get("call_session_id"),
                "call_log_uuid": scoped_vars.get("call_log_uuid"),
                "flow_id": scoped_vars.get("flow_id"),
                "flow_version_id": scoped_vars.get("flow_version_id"),
                "sip_trunk_id": scoped_vars.get("sip_trunk_id"),
                "dialed_number": scoped_vars.get("dialed_number"),
                "dtmf_value": scoped_vars.get("dtmf_value"),
                "retry_count": scoped_vars.get("retry_count"),
                "call_started_at": scoped_vars.get("call_started_at"),
                "call_answered_at": scoped_vars.get("call_answered_at"),
                "event_timestamp": scoped_vars.get("event_timestamp"),
                "call_ended_at": scoped_vars.get("call_ended_at"),
                "hangup_cause": scoped_vars.get("hangup_cause"),
                "hangup_cause_text": scoped_vars.get("hangup_cause_text"),
            },
        }
        intents = variables.get("__post_call_webhook_intents")
        if not isinstance(intents, list):
            intents = []
        intents.append(intent)
        variables["__post_call_webhook_intents"] = intents
        redis_captured = append_intent(scoped_vars.get("call_action_id"), intent)
        intent["redis_captured"] = bool(redis_captured)

        save_key = str(cfg.get("save_response_as") or "").strip() or None
        if save_key:
            variables[save_key] = {
                "deferred": True,
                "queued": True,
                "redis_captured": bool(redis_captured),
                "sequence_no": seq,
                "node_key": node_key,
            }

        return NodeExecutionResult(
            runtime_action={
                "type": "noop",
                "node_type": "webhook",
                "deferred": True,
                "queued": True,
                "redis_captured": bool(redis_captured),
                "sequence_no": seq,
            },
            metadata={
                "auto_result_type": "webhook_success",
                "auto_value": "deferred_queued",
                "webhook": {
                    "deferred": True,
                    "queued": True,
                    "redis_captured": bool(redis_captured),
                    "sequence_no": seq,
                    "node_key": node_key,
                    "method": method,
                    "url": url,
                },
                "post_call_webhook_intent": intent,
            },
        )

    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=payload if isinstance(payload, (dict, list)) else None,
            data=payload if isinstance(payload, (str, bytes)) else None,
            timeout=timeout_seconds,
        )
        ok = 200 <= resp.status_code < 300
        response_text = (resp.text or "")[:1000]
        response_mode = str(cfg.get("response_mode") or "text").strip().lower()
        if response_mode not in {"text", "json"}:
            response_mode = "text"
        response_json = None
        if response_mode == "json":
            try:
                response_json = resp.json()
            except ValueError:
                response_json = None
        save_key = str(cfg.get("save_response_as") or "").strip() or None
        if save_key:
            saved_payload = {"status_code": resp.status_code}
            if response_mode == "json":
                saved_payload["json"] = response_json
                if response_json is None:
                    saved_payload["json_parse_error"] = True
            else:
                saved_payload["body"] = response_text

            path_map = cfg.get("response_json_path_map")
            if response_json is not None and isinstance(path_map, dict):
                mapped = {}
                for target_var, source_path in path_map.items():
                    target_name = str(target_var).strip()
                    if not target_name:
                        continue
                    mapped[target_name] = _json_path_get(response_json, source_path)
                    variables[target_name] = mapped[target_name]
                saved_payload["mapped"] = mapped
            variables[save_key] = saved_payload
        return NodeExecutionResult(
            runtime_action={
                "type": "noop",
                "node_type": "webhook",
                "status_code": resp.status_code,
            },
            metadata={
                "auto_result_type": "webhook_success" if ok else "webhook_failed",
                "auto_value": str(resp.status_code),
                "webhook": {
                    "method": method,
                    "url": url,
                    "status_code": resp.status_code,
                    "ok": ok,
                    "response_mode": response_mode,
                },
            },
        )
    except requests.RequestException as exc:
        save_key = str(cfg.get("save_response_as") or "").strip() or None
        if save_key:
            variables[save_key] = {
                "error": str(exc),
            }
        return NodeExecutionResult(
            runtime_action={
                "type": "noop",
                "node_type": "webhook",
                "error": "request_failed",
            },
            metadata={
                "auto_result_type": "webhook_failed",
                "auto_value": "request_exception",
                "webhook": {
                    "method": method,
                    "url": url,
                    "ok": False,
                    "error_type": exc.__class__.__name__,
                },
            },
        )
