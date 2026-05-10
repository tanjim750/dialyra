from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class NodeExecutionResult:
    runtime_action: Dict[str, Any]
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


def node_config(node_payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = node_payload.get("config")
    return cfg if isinstance(cfg, dict) else {}
