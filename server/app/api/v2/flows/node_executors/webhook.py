import re
from urllib.parse import urlparse

import requests

from .base import NodeExecutionResult, node_config

_TPL = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_MAX_TIMEOUT_SECONDS = 15


def _render_template(value, variables):
    if isinstance(value, str):
        def repl(match):
            key = match.group(1)
            resolved = variables.get(key)
            return "" if resolved is None else str(resolved)

        return _TPL.sub(repl, value)
    if isinstance(value, list):
        return [_render_template(item, variables) for item in value]
    if isinstance(value, dict):
        return {str(k): _render_template(v, variables) for k, v in value.items()}
    return value


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


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    method = str(cfg.get("method") or "GET").strip().upper()
    if method not in _ALLOWED_METHODS:
        return NodeExecutionResult(runtime_action={}, error="webhook node has invalid method")

    url = str(cfg.get("url") or "").strip()
    if not url:
        return NodeExecutionResult(runtime_action={}, error="webhook node missing config.url")
    url = _render_template(url, variables)
    if not _validate_url(url):
        return NodeExecutionResult(runtime_action={}, error="webhook node url must be absolute http/https")

    raw_timeout = cfg.get("timeout_seconds", 5)
    try:
        timeout_seconds = float(raw_timeout)
    except (TypeError, ValueError):
        timeout_seconds = 5.0
    timeout_seconds = max(1.0, min(_MAX_TIMEOUT_SECONDS, timeout_seconds))

    headers = _render_template(cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}, variables)
    body_template = cfg.get("body_template")
    payload = _render_template(body_template, variables) if body_template is not None else None

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
