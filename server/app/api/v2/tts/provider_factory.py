from flask import current_app

from app.api.v2.tts.providers.elevenlabs import ElevenLabsTTSProvider
from app.api.v2.tts.providers.google import GoogleTTSProvider
from app.api.v2.tts.providers.mock import MockTTSProvider
from app.api.v2.tts.providers.openai import OpenAITTSProvider
from app.api.v2.tts.providers.stub import StubExternalTTSProvider

KNOWN_PROVIDERS = {
    "mock",
    "openai",
    "google",
    "amazon_polly",
    "azure",
    "elevenlabs",
    "coqui",
    "piper",
}


def enabled_providers():
    raw = current_app.config.get("TTS_ENABLED_PROVIDERS", "")
    if not raw:
        return {"mock"}
    values = {item.strip().lower() for item in str(raw).split(",") if item.strip()}
    return values or {"mock"}


def get_provider(name=None):
    provider_name = (name or current_app.config.get("TTS_DEFAULT_PROVIDER", "mock")).strip().lower()
    if provider_name not in enabled_providers():
        return None, f"Provider '{provider_name}' is not enabled"
    if provider_name not in KNOWN_PROVIDERS:
        return None, "Unsupported provider"

    if provider_name == "mock":
        return MockTTSProvider(), None
    if provider_name == "google":
        return GoogleTTSProvider(), None
    if provider_name == "openai":
        return OpenAITTSProvider(), None
    if provider_name == "elevenlabs":
        return ElevenLabsTTSProvider(), None
    return StubExternalTTSProvider(provider_name), None
