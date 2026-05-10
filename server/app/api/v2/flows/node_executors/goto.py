from .base import NodeExecutionResult, node_config


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    target_node_key = str(cfg.get("target_node_key") or "").strip() or None
    target_node_id = cfg.get("target_node_id")
    if target_node_key is None and target_node_id is None:
        return NodeExecutionResult(
            runtime_action={},
            error="goto node requires config.target_node_key or config.target_node_id",
        )
    return NodeExecutionResult(
        runtime_action={
            "type": "noop",
            "node_type": "goto",
            "target_node_key": target_node_key,
            "target_node_id": target_node_id,
        },
        metadata={
            "goto_target_node_key": target_node_key,
            "goto_target_node_id": target_node_id,
        },
    )
