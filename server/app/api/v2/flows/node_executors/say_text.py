from app.api.v2.tts.service import generate_tts_for_runtime_business

from .base import NodeExecutionResult, node_config


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    tts_payload = {
        "text": cfg.get("text"),
        "provider": cfg.get("provider"),
        "provider_variant": cfg.get("provider_variant"),
        "language": cfg.get("language"),
        "voice": cfg.get("voice"),
        "node": node_payload,
        "node_config": cfg,
    }
    tts_result, tts_error = generate_tts_for_runtime_business(
        actor_business,
        tts_payload,
        variables=variables,
        created_by=None,
    )
    if tts_error:
        return NodeExecutionResult(runtime_action={}, error=tts_error)

    return NodeExecutionResult(
        runtime_action={
            "type": "play_audio_asset",
            "audio_asset_id": tts_result["audio_asset_id"],
            "tts_request_id": tts_result["tts_request_id"],
            "source": tts_result["source"],
        },
        metadata={"tts": tts_result},
    )
