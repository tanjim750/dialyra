from .base import NodeExecutionResult, node_config


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    return NodeExecutionResult(
        runtime_action={
            "type": "collect_dtmf",
            "max_digits": cfg.get("max_digits", 1),
            "timeout_seconds": cfg.get("timeout_seconds", 5),
            "allowed_inputs": cfg.get("allowed_inputs", []),
            "terminator_key": cfg.get("terminator_key", "#"),
        }
    )
