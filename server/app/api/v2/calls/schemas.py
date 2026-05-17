import json
import re

from app.services.template_resolver import RESERVED_SYSTEM_VARIABLES


_TPL_VAR_KEY_RE = re.compile(r"^[A-Za-z0-9_]+$")
_TPL_MAX_KEYS = 100
_TPL_MAX_KEY_LEN = 64
_TPL_MAX_JSON_BYTES = 16 * 1024


def _is_scalar(value):
    return value is None or isinstance(value, (str, int, float, bool))


def _validate_template_variables_shape(value, path="webhook_variables"):
    if _is_scalar(value):
        return None
    if isinstance(value, list):
        for idx, item in enumerate(value):
            err = _validate_template_variables_shape(item, path=f"{path}[{idx}]")
            if err:
                return err
        return None
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                return f"{path} contains non-string key"
            if len(k) > _TPL_MAX_KEY_LEN:
                return f"{path}.{k} exceeds max key length ({_TPL_MAX_KEY_LEN})"
            if not _TPL_VAR_KEY_RE.match(k):
                return f"{path}.{k} has invalid key format (allowed: a-zA-Z0-9_)"
            err = _validate_template_variables_shape(v, path=f"{path}.{k}")
            if err:
                return err
        return None
    return f"{path} contains unsupported value type"


def validate_originate_payload(payload):
    if not isinstance(payload, dict):
        return "Invalid JSON payload"

    phone = payload.get("phone")
    if not phone:
        return "Missing required field: phone"

    sip_trunk_id = payload.get("sip_trunk_id")
    if sip_trunk_id is not None:
        try:
            if int(sip_trunk_id) <= 0:
                return "sip_trunk_id must be a positive integer"
        except (TypeError, ValueError):
            return "sip_trunk_id must be an integer"

    flow_id = payload.get("flow_id")
    if flow_id is not None:
        try:
            if int(flow_id) <= 0:
                return "flow_id must be a positive integer"
        except (TypeError, ValueError):
            return "flow_id must be an integer"

    campaign_flow_id = payload.get("campaign_flow_id")
    if campaign_flow_id is not None:
        try:
            if int(campaign_flow_id) <= 0:
                return "campaign_flow_id must be a positive integer"
        except (TypeError, ValueError):
            return "campaign_flow_id must be an integer"

    campaign_id = payload.get("campaign_id")
    if campaign_id is not None:
        try:
            if int(campaign_id) <= 0:
                return "campaign_id must be a positive integer"
        except (TypeError, ValueError):
            return "campaign_id must be an integer"

    if payload.get("template_variables") is not None:
        return "template_variables is not supported; use webhook_variables"

    webhook_variables = payload.get("webhook_variables")
    if webhook_variables is not None:
        if not isinstance(webhook_variables, dict):
            return "webhook_variables must be an object"
        if len(webhook_variables) > _TPL_MAX_KEYS:
            return f"webhook_variables exceeds max key count ({_TPL_MAX_KEYS})"
        for key in webhook_variables.keys():
            if str(key).strip().lower() in RESERVED_SYSTEM_VARIABLES:
                return f"webhook_variables cannot override reserved key: {key}"
        shape_error = _validate_template_variables_shape(webhook_variables)
        if shape_error:
            return shape_error
        try:
            raw = json.dumps(webhook_variables, ensure_ascii=False)
        except (TypeError, ValueError):
            return "webhook_variables contains non-serializable values"
        if len(raw.encode("utf-8")) > _TPL_MAX_JSON_BYTES:
            return f"webhook_variables exceeds max size ({_TPL_MAX_JSON_BYTES} bytes)"

    return None
