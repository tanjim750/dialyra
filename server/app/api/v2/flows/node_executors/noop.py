from .base import NodeExecutionResult


def execute(actor_business, node_payload, variables):
    node_type = str(node_payload.get("node_type") or "").strip().lower()
    return NodeExecutionResult(runtime_action={"type": "noop", "node_type": node_type})
