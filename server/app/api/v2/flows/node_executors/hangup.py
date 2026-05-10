from .base import NodeExecutionResult, node_config


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    return NodeExecutionResult(
        runtime_action={
            "type": "hangup",
            "reason": cfg.get("reason", "flow_completed"),
        }
    )
