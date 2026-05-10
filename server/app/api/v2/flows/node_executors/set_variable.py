import re

from .base import NodeExecutionResult, node_config


_TPL = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _render(value, variables):
    if not isinstance(value, str):
        return value

    def repl(match):
        key = match.group(1)
        resolved = variables.get(key)
        return "" if resolved is None else str(resolved)

    return _TPL.sub(repl, value)


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    key = str(cfg.get("key") or "").strip()
    if not key:
        return NodeExecutionResult(runtime_action={}, error="set_variable node missing config.key")

    raw_value = cfg.get("value")
    rendered = _render(raw_value, variables)
    variables[key] = rendered

    return NodeExecutionResult(
        runtime_action={
            "type": "noop",
            "node_type": "set_variable",
            "key": key,
        },
        metadata={
            "auto_result_type": "completed",
            "auto_value": key,
            "set_variable": {"key": key, "value": rendered},
        },
    )
