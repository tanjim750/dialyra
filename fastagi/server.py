import json
import os
import socketserver
import urllib.error
import urllib.request
import uuid


INTERNAL_BASE_URL = os.getenv("FASTAGI_INTERNAL_BASE_URL", "http://dialyra-flask:5000")
INTERNAL_TOKEN = os.getenv("FASTAGI_INTERNAL_ACCESS_TOKEN", "").strip()
REQUEST_TIMEOUT_SEC = float(os.getenv("FASTAGI_INTERNAL_TIMEOUT_SEC", "5"))
MAX_RUNTIME_STEPS = int(os.getenv("FASTAGI_MAX_RUNTIME_STEPS", "32"))


def _json_dumps(data):
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def _api_post(path, payload):
    if not INTERNAL_TOKEN:
        raise RuntimeError("FASTAGI_INTERNAL_ACCESS_TOKEN is not configured")
    url = f"{INTERNAL_BASE_URL.rstrip('/')}{path}"
    req = urllib.request.Request(
        url=url,
        data=_json_dumps(payload),
        headers={
            "Content-Type": "application/json",
            "X-Dialyra-Access-Token": INTERNAL_TOKEN,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body or "{}")


def _api_get(path):
    if not INTERNAL_TOKEN:
        raise RuntimeError("FASTAGI_INTERNAL_ACCESS_TOKEN is not configured")
    url = f"{INTERNAL_BASE_URL.rstrip('/')}{path}"
    req = urllib.request.Request(
        url=url,
        headers={
            "X-Dialyra-Access-Token": INTERNAL_TOKEN,
        },
        method="GET",
    )
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
        line = self.rfile.readline().decode("utf-8", errors="ignore").strip()
        return line

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
        # Empty escape digits means uninterrupted playback.
        safe = str(filename).strip() or "silence/1"
        return self._send_agi(f"STREAM FILE {safe} \"\"")

    def _get_data(self, filename, timeout_ms, max_digits):
        safe_file = str(filename).strip() or "silence/1"
        timeout_ms = max(1000, int(timeout_ms))
        max_digits = max(1, int(max_digits))
        raw = self._send_agi(f"GET DATA {safe_file} {timeout_ms} {max_digits}")
        # Expected: 200 result=<digits|timeout>
        marker = "result="
        if marker not in raw:
            return ""
        value = raw.split(marker, 1)[1].strip()
        if " " in value:
            value = value.split(" ", 1)[0]
        if value == "0":
            return ""
        return value

    def _post_runtime_event(self, call_session_id, event_path, payload):
        return _api_post(f"/api/v2/internal/calls/{call_session_id}/{event_path}", payload)

    def _resolve_next(self, payload):
        return _api_post("/api/v2/internal/flow/resolve-next", payload)

    def _collect_call_context(self, agi_env):
        return {
            "call_session_id": self._get_variable("CALL_SESSION_ID"),
            "business_id": self._get_variable("BUSINESS_ID"),
            "target_number": self._get_variable("TARGET_NUMBER") or agi_env.get("agi_extension", ""),
            "sip_trunk_id": self._get_variable("SIP_TRUNK_ID"),
            "sip_trunk_endpoint": self._get_variable("SIP_TRUNK_ENDPOINT"),
            "call_log_uuid": self._get_variable("CALL_LOG_UUID"),
            "call_action_id": self._get_variable("CALL_ACTION_ID"),
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
        }
        missing = [label for key, label in required.items() if not str(ctx.get(key) or "").strip()]
        return missing

    def _safe_emit_runtime_error(self, call_session_id, trace_id, reason, details=None):
        if not call_session_id:
            return
        payload = {
            "trace_id": trace_id,
            "reason": reason,
        }
        if details is not None:
            payload["details"] = details
        try:
            self._post_runtime_event(call_session_id, "runtime-error", payload)
        except Exception:  # noqa: BLE001
            pass

    def _bootstrap_payload(self, agi_env):
        # Channel vars set during originate
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
            return {"result_type": "completed"}

        if action_type == "hangup":
            self._hangup()
            return {"terminal": True, "result_type": "completed"}

        if action_type == "play_audio_asset":
            asset_id = action.get("audio_asset_id")
            playback_target = "silence/1"
            if asset_id is not None:
                try:
                    payload = _api_get(f"/api/v2/internal/audio-assets/{asset_id}/playback-target")
                    playback_target = str(payload.get("playback_target") or playback_target)
                except Exception:  # noqa: BLE001
                    playback_target = "silence/1"
            self._stream_file(playback_target)
            self._post_runtime_event(
                call_session_id,
                "playback-event",
                {
                    "event_type": "playback_completed",
                    "audio_asset_id": action.get("audio_asset_id"),
                    "playback_target": playback_target,
                    "trace_id": trace_id,
                    "call_action_id": call_context.get("call_action_id"),
                    "sip_trunk_id": call_context.get("sip_trunk_id"),
                },
            )
            return {"result_type": "completed"}

        if action_type == "collect_dtmf":
            timeout_s = int(action.get("timeout_seconds") or 5)
            max_digits = int(action.get("max_digits") or 1)
            digits = self._get_data("silence/1", timeout_s * 1000, max_digits)
            if digits:
                self._post_runtime_event(
                    call_session_id,
                    "dtmf",
                    {
                        "digits": digits,
                        "trace_id": trace_id,
                        "call_action_id": call_context.get("call_action_id"),
                    },
                )
                return {"result_type": "dtmf", "value": digits}
            return {"result_type": "timeout"}

        if action_type == "wait":
            duration = max(1, int(action.get("duration_seconds") or 1))
            self._send_agi(f"WAIT FOR DIGIT {duration * 1000}")
            self._post_runtime_event(
                call_session_id,
                "wait-event",
                {
                    "event_type": "wait_completed",
                    "duration_seconds": duration,
                    "trace_id": trace_id,
                    "call_action_id": call_context.get("call_action_id"),
                },
            )
            return {"result_type": "completed"}

        if action_type == "set_variable":
            key = str(action.get("key") or "").strip()
            value = action.get("value")
            if key:
                self._set_variable(key, value if value is not None else "")
            return {"result_type": "completed"}

        if action_type == "transfer_call":
            # Transfer execution path is AMI/dialplan-dependent; emit failed for now.
            self._post_runtime_event(
                call_session_id,
                "transfer-event",
                {
                    "event_type": "transfer_failed",
                    "reason": "not_implemented_in_fastagi",
                    "trace_id": trace_id,
                    "call_action_id": call_context.get("call_action_id"),
                },
            )
            return {"result_type": "transfer_failed"}

        if action_type == "record_control":
            mapped = {
                "start": "recording_started",
                "stop": "recording_stopped",
                "pause": "recording_paused",
                "resume": "recording_resumed",
            }.get(str(action.get("action") or "").strip().lower(), "recording_failed")
            self._post_runtime_event(
                call_session_id,
                "record-event",
                {
                    "event_type": mapped,
                    "trace_id": trace_id,
                    "call_action_id": call_context.get("call_action_id"),
                },
            )
            return {"result_type": "completed"}

        # Unknown action => move safely by reporting runtime error then hangup.
        self._post_runtime_event(
            call_session_id,
            "runtime-error",
            {
                "reason": "unsupported_runtime_action",
                "runtime_action_type": action_type,
                "trace_id": trace_id,
                "call_action_id": call_context.get("call_action_id"),
            },
        )
        self._hangup()
        return {"terminal": True, "result_type": "error"}

    def handle(self):
        agi_env = self._read_agi_env()
        payload, context = self._bootstrap_payload(agi_env)
        trace_id = str(payload.get("trace_id") or uuid.uuid4())
        missing_vars = self._validate_required_context(context)
        if missing_vars:
            self._verbose(f"FastAGI context missing required vars: {', '.join(missing_vars)}", 1)
            self._safe_emit_runtime_error(
                str(context.get("call_session_id") or ""),
                trace_id,
                "missing_required_channel_vars",
                {"missing": missing_vars},
            )
            # Return to dialplan fallback path instead of hard hangup.
            return
        call_session_id = payload["call_session_id"]
        self._verbose(
            "Dialyra FastAGI bound "
            f"call_session_id={call_session_id} "
            f"business_id={context.get('business_id')} "
            f"sip_trunk_id={context.get('sip_trunk_id')} "
            f"target={context.get('target_number')}",
            1,
        )

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
                resolved = self._resolve_next(req)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                self._verbose(f"Runtime resolve HTTPError: {exc.code} {body[:180]}", 1)
                self._safe_emit_runtime_error(
                    call_session_id,
                    trace_id,
                    "resolve_next_http_error",
                    {"status": exc.code, "body": body[:300]},
                )
                self._hangup()
                return
            except Exception as exc:  # noqa: BLE001
                self._verbose(f"Runtime resolve error: {exc}", 1)
                self._safe_emit_runtime_error(
                    call_session_id,
                    trace_id,
                    "resolve_next_error",
                    {"error": str(exc)},
                )
                self._hangup()
                return

            action = (resolved or {}).get("runtime_action") or {}
            handled = self._handle_runtime_action(context, action, trace_id)
            if handled.get("terminal"):
                return
            result_type = handled.get("result_type") or "completed"
            result_value = handled.get("value")
            steps += 1

        self._verbose("FastAGI runtime safety stop: max steps reached", 1)
        self._hangup()


if __name__ == "__main__":
    with socketserver.ThreadingTCPServer(("0.0.0.0", 4573), FastAGIHandler) as server:
        server.serve_forever()
