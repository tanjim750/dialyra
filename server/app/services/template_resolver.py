import re


_TPL = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

# Reserved system variables must never be overridden by user/runtime custom vars.
RESERVED_SYSTEM_VARIABLES = {
    "call_action_id",
    "call_session_id",
    "call_log_uuid",
    "business_id",
    "flow_id",
    "flow_version_id",
    "sip_trunk_id",
    "dialed_number",
    "dtmf_value",
    "retry_count",
    "call_started_at",
    "call_answered_at",
    "event_timestamp",
    "call_ended_at",
    "hangup_cause",
    "hangup_cause_text",
}


def extract_template_keys(value):
    out = set()

    def _walk(item):
        if isinstance(item, str):
            for m in _TPL.finditer(item):
                out.add(m.group(1))
            return
        if isinstance(item, list):
            for x in item:
                _walk(x)
            return
        if isinstance(item, dict):
            for v in item.values():
                _walk(v)

    _walk(value)
    return out


def render_template_value(value, variables, *, unresolved_as_empty=True):
    if isinstance(value, str):
        def repl(match):
            key = match.group(1)
            resolved = variables.get(key) if isinstance(variables, dict) else None
            if resolved is None:
                return "" if unresolved_as_empty else match.group(0)
            return str(resolved)

        return _TPL.sub(repl, value)
    if isinstance(value, list):
        return [
            render_template_value(item, variables, unresolved_as_empty=unresolved_as_empty)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            str(k): render_template_value(v, variables, unresolved_as_empty=unresolved_as_empty)
            for k, v in value.items()
        }
    return value


def build_node_resolution_context(
    *,
    runtime_variables=None,
    system_variables=None,
    input_map=None,
):
    """
    Returns an isolated node-scoped resolution context and mapping errors.

    Precedence:
    1) runtime_variables
    2) system_variables overwrite runtime values for reserved keys
    3) input_map materialized aliases (cannot override reserved keys)
    """
    runtime_variables = runtime_variables if isinstance(runtime_variables, dict) else {}
    system_variables = system_variables if isinstance(system_variables, dict) else {}
    input_map = input_map if isinstance(input_map, dict) else {}

    ctx = dict(runtime_variables)

    # Force reserved keys from system context to protect against overrides.
    for key, value in system_variables.items():
        if key in RESERVED_SYSTEM_VARIABLES:
            ctx[key] = value
        elif key not in ctx:
            ctx[key] = value

    errors = []
    for target, source in input_map.items():
        target_key = str(target or "").strip()
        if not target_key:
            continue
        if target_key in RESERVED_SYSTEM_VARIABLES:
            errors.append(
                {
                    "code": "RESERVED_VARIABLE_OVERRIDE_BLOCKED",
                    "message": f"input_map cannot override reserved variable '{target_key}'",
                }
            )
            continue
        ctx[target_key] = render_template_value(source, ctx)

    return ctx, errors

