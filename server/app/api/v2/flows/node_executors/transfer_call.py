from .base import NodeExecutionResult, node_config

_ALLOWED_TRANSFER_TYPES = {"agent", "queue", "department", "external_number"}


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    transfer_type = str(cfg.get("transfer_type") or "").strip().lower()
    if transfer_type not in _ALLOWED_TRANSFER_TYPES:
        return NodeExecutionResult(
            runtime_action={},
            error="transfer_call node has invalid config.transfer_type",
        )

    timeout_seconds = cfg.get("timeout_seconds", 30)
    try:
        timeout_seconds = int(timeout_seconds)
    except (TypeError, ValueError):
        timeout_seconds = 30
    timeout_seconds = max(1, min(180, timeout_seconds))

    target = {
        "agent": cfg.get("agent_id") or cfg.get("agent"),
        "queue": cfg.get("queue_id") or cfg.get("queue"),
        "department": cfg.get("department_id") or cfg.get("department"),
        "external_number": cfg.get("number") or cfg.get("phone_number"),
    }.get(transfer_type)
    if not target:
        return NodeExecutionResult(
            runtime_action={},
            error=f"transfer_call node missing target for transfer_type={transfer_type}",
        )

    fallback_node_key = str(cfg.get("fallback_node_key") or "").strip() or None

    return NodeExecutionResult(
        runtime_action={
            "type": "transfer_call",
            "transfer_type": transfer_type,
            "target": str(target),
            "timeout_seconds": timeout_seconds,
            "fallback_node_key": fallback_node_key,
        },
        metadata={
            "transfer": {
                "transfer_type": transfer_type,
                "target": str(target),
                "timeout_seconds": timeout_seconds,
                "fallback_node_key": fallback_node_key,
            }
        },
    )
