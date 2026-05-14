import json
import os
import socketserver
import urllib.error
import urllib.request
import uuid


INTERNAL_BASE_URL = os.getenv("FASTAGI_INTERNAL_BASE_URL", "http://dialyra-flask:5000")
INTERNAL_TOKEN = os.getenv("FASTAGI_INTERNAL_ACCESS_TOKEN", "").strip()
REQUEST_TIMEOUT_SEC = float(os.getenv("FASTAGI_INTERNAL_TIMEOUT_SEC", "30"))
MAX_RUNTIME_STEPS = int(os.getenv("FASTAGI_MAX_RUNTIME_STEPS", "32"))


def _json_dumps(data):
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _api_post(path, payload, extra_headers=None):
    if not INTERNAL_TOKEN:
        raise RuntimeError("FASTAGI_INTERNAL_ACCESS_TOKEN must be set")
    url = f"{INTERNAL_BASE_URL.rstrip('/')}{path}"
    headers = {"Content-Type": "application/json", "X-Dialyra-Access-Token": INTERNAL_TOKEN}
    if isinstance(extra_headers, dict):
        headers.update({str(k): str(v) for k, v in extra_headers.items() if v is not None})
    req = urllib.request.Request(url=url, data=_json_dumps(payload), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body or "{}")


def _api_get(path, extra_headers=None):
    if not INTERNAL_TOKEN:
        raise RuntimeError("FASTAGI_INTERNAL_ACCESS_TOKEN must be set")
    url = f"{INTERNAL_BASE_URL.rstrip('/')}{path}"
    headers = {"X-Dialyra-Access-Token": INTERNAL_TOKEN}
    if isinstance(extra_headers, dict):
        headers.update({str(k): str(v) for k, v in extra_headers.items() if v is not None})
    req = urllib.request.Request(url=url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body or "{}")


class FastAGIHandler(socketserver.StreamRequestHandler):
    def _read_agi_env(self):
        agi_env = {}
        while True:
            line = self.rfile.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                break
            if ":" in line:
                key, value = line.split(":", 1)
                agi_env[key.strip()] = value.strip()
        return agi_env

    def _send_agi(self, command):
        self.wfile.write((command.rstrip() + "\n").encode("utf-8"))
        self.wfile.flush()
        return self.rfile.readline().decode("utf-8", errors="ignore").strip()

    def _verbose(self, message, level=1):
        safe = str(message).replace('"', "'")
        return self._send_agi(f'VERBOSE "{safe}" {int(level)}')

    def _hangup(self):
        return self._send_agi("HANGUP")

    def _get_variable(self, key):
        raw = self._send_agi(f"GET VARIABLE {key}")
        if "(" in raw and ")" in raw:
            return raw.split("(", 1)[1].rsplit(")", 1)[0]
        return ""

    def _set_variable(self, key, value):
        safe = str(value).replace('"', "")
        return self._send_agi(f'SET VARIABLE {key} "{safe}"')

    def _stream_file(self, filename):
        safe = str(filename).strip()
        if not safe:
            # No default prompt fallback dependency (e.g. silence/1) to avoid missing-file aborts.
            return "200 result=0"
        return self._send_agi(f"STREAM FILE {safe} \"\"")

    def _get_data(self, filename, timeout_ms, max_digits):
        safe_file = str(filename).strip() or "silence/1"
        timeout_ms = max(1000, int(timeout_ms))
        max_digits = max(1, int(max_digits))
        raw = self._send_agi(f"GET DATA {safe_file} {timeout_ms} {max_digits}")
        marker = "result="
        if marker not in raw:
            return ""
        value = raw.split(marker, 1)[1].strip()
        if " " in value:
            value = value.split(" ", 1)[0]
        if value == "0":
            return ""
        return value

    def _wait_for_digit(self, timeout_ms):
        timeout_ms = max(1000, int(timeout_ms))
        raw = self._send_agi(f"WAIT FOR DIGIT {timeout_ms}")
        marker = "result="
        if marker not in raw:
            return ""
        value = raw.split(marker, 1)[1].strip()
        if " " in value:
            value = value.split(" ", 1)[0]
        try:
            code = int(value)
        except ValueError:
            return ""
        # -1: hangup/error, 0: timeout
        if code <= 0:
            return ""
        try:
            return chr(code)
        except ValueError:
            return ""

    def _internal_headers(self, call_context):
        headers = {}
        business_id = call_context.get("business_id")
        call_token = call_context.get("fastagi_call_token")
        if business_id:
            headers["X-Dialyra-Business-Id"] = str(business_id)
        if call_token:
            headers["X-Dialyra-Call-Token"] = str(call_token)
        return headers

    def _post_runtime_event(self, call_session_id, event_path, payload, call_context):
        return _api_post(
            f"/api/v2/internal/calls/{call_session_id}/{event_path}",
            payload,
            extra_headers=self._internal_headers(call_context),
        )

    def _resolve_next(self, payload, call_context):
        self._verbose(
            f"FastAGI resolve-next call_session_id={payload.get('call_session_id')} flow_id={payload.get('flow_id')} flow_version_id={payload.get('flow_version_id')}",
            1,
        )
        return _api_post(
            "/api/v2/internal/flow/resolve-next",
            payload,
            extra_headers=self._internal_headers(call_context),
        )

    def _collect_call_context(self, agi_env):
        return {
            "call_session_id": self._get_variable("CALL_SESSION_ID"),
            "business_id": self._get_variable("BUSINESS_ID"),
            "target_number": self._get_variable("TARGET_NUMBER") or agi_env.get("agi_extension", ""),
            "sip_trunk_id": self._get_variable("SIP_TRUNK_ID"),
            "sip_trunk_endpoint": self._get_variable("SIP_TRUNK_ENDPOINT"),
            "call_log_uuid": self._get_variable("CALL_LOG_UUID"),
            "call_action_id": self._get_variable("CALL_ACTION_ID"),
            "fastagi_call_token": self._get_variable("FASTAGI_CALL_TOKEN"),
            "flow_id": self._get_variable("FLOW_ID"),
            "flow_version_id": self._get_variable("FLOW_VERSION_ID"),
            "retry_count": self._get_variable("RETRY_COUNT"),
            "retry_of_call_session_id": self._get_variable("RETRY_OF_CALL_SESSION_ID"),
            "agi_channel": agi_env.get("agi_channel", ""),
            "agi_uniqueid": agi_env.get("agi_uniqueid", ""),
        }

    def _validate_required_context(self, ctx):
        required = {
            "call_session_id": "CALL_SESSION_ID",
            "business_id": "BUSINESS_ID",
            "target_number": "TARGET_NUMBER",
            "sip_trunk_id": "SIP_TRUNK_ID",
            "sip_trunk_endpoint": "SIP_TRUNK_ENDPOINT",
            "fastagi_call_token": "FASTAGI_CALL_TOKEN",
        }
        return [label for key, label in required.items() if not str(ctx.get(key) or "").strip()]

    def _safe_emit_runtime_error(self, call_session_id, trace_id, reason, details, call_context):
        if not call_session_id:
            return
        payload = {"trace_id": trace_id, "reason": reason, "details": details or {}}
        try:
            self._post_runtime_event(call_session_id, "runtime-error", payload, call_context)
        except Exception:
            pass

    def _bootstrap_payload(self, agi_env):
        context = self._collect_call_context(agi_env)
        call_session_id = str(context.get("call_session_id") or agi_env.get("agi_uniqueid") or str(uuid.uuid4()))
        payload = {
            "call_session_id": call_session_id,
            "trace_id": str(uuid.uuid4()),
            "use_fallback": True,
            "fallback_action": {"type": "hangup", "reason": "runtime_error_fallback"},
            "variables": {
                "dialed_number": context.get("target_number", ""),
                "target_number": context.get("target_number", ""),
                "business_id": context.get("business_id", ""),
                "sip_trunk_id": context.get("sip_trunk_id", ""),
                "sip_trunk_endpoint": context.get("sip_trunk_endpoint", ""),
                "call_log_uuid": context.get("call_log_uuid", ""),
                "call_action_id": context.get("call_action_id", ""),
                "agi_channel": context.get("agi_channel", ""),
                "agi_uniqueid": context.get("agi_uniqueid", ""),
            },
        }
        if context.get("flow_id"):
            try:
                payload["flow_id"] = int(context.get("flow_id"))
            except ValueError:
                pass
        if context.get("flow_version_id"):
            try:
                payload["flow_version_id"] = int(context.get("flow_version_id"))
            except ValueError:
                pass
        if context.get("retry_count"):
            payload["variables"]["retry_count"] = context.get("retry_count")
        if context.get("retry_of_call_session_id"):
            payload["variables"]["retry_of_call_session_id"] = context.get("retry_of_call_session_id")
        return payload, context

    def _handle_runtime_action(self, call_context, action, trace_id):
        call_session_id = str(call_context.get("call_session_id") or "")
        action_type = str((action or {}).get("type") or "").strip().lower()

        if action_type in {"noop", "legacy_fallback"}:
            self._verbose(f"FastAGI action={action_type}", 1)
            return {"result_type": "completed"}
        if action_type == "hangup":
            self._verbose("FastAGI action=hangup", 1)
            self._hangup()
            return {"terminal": True, "result_type": "completed"}

        if action_type == "play_audio_asset":
            asset_id = action.get("audio_asset_id")
            playback_target = ""
            if asset_id is not None:
                try:
                    payload = _api_get(
                        f"/api/v2/internal/audio-assets/{asset_id}/playback-target",
                        extra_headers=self._internal_headers(call_context),
                    )
                    playback_target = str(payload.get("playback_target") or playback_target)
                except Exception as exc:
                    self._verbose(f"FastAGI playback-target lookup failed asset_id={asset_id} error={exc}", 1)
                    playback_target = ""
            self._verbose(f"FastAGI action=play_audio_asset asset_id={asset_id} target={playback_target or '(none)'}", 1)
            self._stream_file(playback_target)
            self._post_runtime_event(
                call_session_id,
                "playback-event",
                {
                    "event_type": "playback_completed",
                    "audio_asset_id": action.get("audio_asset_id"),
                    "playback_target": playback_target,
                    "trace_id": trace_id,
                },
                call_context,
            )
            return {"result_type": "completed"}

        if action_type == "collect_dtmf":
            self._verbose("FastAGI action=collect_dtmf", 1)
            timeout_ms = int(action.get("timeout_seconds") or 5) * 1000
            max_digits = max(1, int(action.get("max_digits") or 1))
            digits = ""
            for _ in range(max_digits):
                digit = self._wait_for_digit(timeout_ms)
                if not digit:
                    break
                digits += digit
            if digits:
                self._post_runtime_event(
                    call_session_id,
                    "dtmf",
                    {"digits": digits, "trace_id": trace_id},
                    call_context,
                )
                return {"result_type": "dtmf", "value": digits}
            return {"result_type": "timeout"}

        if action_type == "wait":
            self._verbose("FastAGI action=wait", 1)
            duration = max(1, int(action.get("duration_seconds") or 1))
            self._send_agi(f"WAIT FOR DIGIT {duration * 1000}")
            self._post_runtime_event(
                call_session_id,
                "wait-event",
                {"event_type": "wait_completed", "duration_seconds": duration, "trace_id": trace_id},
                call_context,
            )
            return {"result_type": "completed"}

        if action_type == "set_variable":
            self._verbose("FastAGI action=set_variable", 1)
            key = str(action.get("key") or "").strip()
            if key:
                self._set_variable(key, action.get("value") if action.get("value") is not None else "")
            return {"result_type": "completed"}

        if action_type == "transfer_call":
            self._verbose("FastAGI action=transfer_call(not_implemented)", 1)
            self._post_runtime_event(
                call_session_id,
                "transfer-event",
                {"event_type": "transfer_failed", "reason": "not_implemented_in_fastagi", "trace_id": trace_id},
                call_context,
            )
            return {"result_type": "transfer_failed"}

        if action_type == "record_control":
            self._verbose("FastAGI action=record_control", 1)
            mapped = {
                "start": "recording_started",
                "stop": "recording_stopped",
                "pause": "recording_paused",
                "resume": "recording_resumed",
            }.get(str(action.get("action") or "").strip().lower(), "recording_failed")
            self._post_runtime_event(
                call_session_id,
                "record-event",
                {"event_type": mapped, "trace_id": trace_id},
                call_context,
            )
            return {"result_type": "completed"}

        self._post_runtime_event(
            call_session_id,
            "runtime-error",
            {"reason": "unsupported_runtime_action", "runtime_action_type": action_type, "trace_id": trace_id},
            call_context,
        )
        self._hangup()
        return {"terminal": True, "result_type": "error"}

    def handle(self):
        agi_env = self._read_agi_env()
        payload, context = self._bootstrap_payload(agi_env)
        trace_id = str(payload.get("trace_id") or uuid.uuid4())
        missing = self._validate_required_context(context)
        if missing:
            self._verbose(f"FastAGI context missing required vars: {', '.join(missing)}", 1)
            self._safe_emit_runtime_error(
                str(context.get("call_session_id") or ""),
                trace_id,
                "missing_required_channel_vars",
                {"missing": missing},
                context,
            )
            return

        steps = 0
        result_type = None
        result_value = None
        while steps < MAX_RUNTIME_STEPS:
            req = dict(payload)
            req["trace_id"] = trace_id
            if result_type:
                req["result_type"] = result_type
            if result_value is not None:
                req["value"] = result_value
            try:
                resolved = self._resolve_next(req, context)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                self._verbose(
                    f"FastAGI resolve-next HTTP error status={exc.code} body={body[:180]}",
                    1,
                )
                self._safe_emit_runtime_error(
                    payload["call_session_id"],
                    trace_id,
                    "resolve_next_http_error",
                    {"status": exc.code, "body": body[:300]},
                    context,
                )
                self._hangup()
                return
            except Exception as exc:
                self._verbose(f"FastAGI resolve-next error: {exc}", 1)
                self._safe_emit_runtime_error(
                    payload["call_session_id"],
                    trace_id,
                    "resolve_next_error",
                    {"error": str(exc)},
                    context,
                )
                self._hangup()
                return

            action = (resolved or {}).get("runtime_action") or {}
            self._verbose(f"FastAGI resolved action type={action.get('type')}", 1)
            handled = self._handle_runtime_action(context, action, trace_id)
            if handled.get("terminal"):
                return
            result_type = handled.get("result_type") or "completed"
            result_value = handled.get("value")
            steps += 1

        self._hangup()


if __name__ == "__main__":
    with socketserver.ThreadingTCPServer(("0.0.0.0", 4573), FastAGIHandler) as server:
        server.serve_forever()
