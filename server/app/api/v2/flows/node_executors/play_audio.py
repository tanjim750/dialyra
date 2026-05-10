from .base import NodeExecutionResult, node_config


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    audio_asset_id = cfg.get("audio_asset_id")
    if not audio_asset_id:
        return NodeExecutionResult(runtime_action={}, error="play_audio node missing config.audio_asset_id")
    return NodeExecutionResult(
        runtime_action={
            "type": "play_audio_asset",
            "audio_asset_id": audio_asset_id,
        }
    )
