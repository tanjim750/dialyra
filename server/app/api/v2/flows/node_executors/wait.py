from .base import NodeExecutionResult, node_config


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    duration_seconds = cfg.get("duration_seconds", 1)
    try:
        duration_seconds = int(duration_seconds)
    except (TypeError, ValueError):
        duration_seconds = 1
    duration_seconds = max(1, min(300, duration_seconds))

    return NodeExecutionResult(
        runtime_action={
            "type": "wait",
            "duration_seconds": duration_seconds,
        },
        metadata={
            "wait": {"duration_seconds": duration_seconds},
        },
    )
