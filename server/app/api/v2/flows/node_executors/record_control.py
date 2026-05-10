from .base import NodeExecutionResult, node_config

_ALLOWED_ACTIONS = {"start", "stop", "pause", "resume"}


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    action = str(cfg.get("action") or "").strip().lower()
    if action not in _ALLOWED_ACTIONS:
        return NodeExecutionResult(
            runtime_action={},
            error="record_control node has invalid config.action",
        )

    return NodeExecutionResult(
        runtime_action={
            "type": "record_control",
            "action": action,
        },
        metadata={
            "record_control": {"action": action},
        },
    )
