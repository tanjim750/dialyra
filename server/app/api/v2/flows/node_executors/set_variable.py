from .base import NodeExecutionResult, node_config
from app.services.template_resolver import render_template_value


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    key = str(cfg.get("key") or "").strip()
    if not key:
        return NodeExecutionResult(runtime_action={}, error="set_variable node missing config.key")

    raw_value = cfg.get("value")
    rendered = render_template_value(raw_value, variables)
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
