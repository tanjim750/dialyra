from app.api.v2.tts.providers.base import BaseTTSProvider, TTSProviderError


class StubExternalTTSProvider(BaseTTSProvider):
    def __init__(self, name: str):
        self.name = name

    def generate_audio(self, *, text: str, language: str, voice: str, output_path: str, provider_options=None):
        raise TTSProviderError(
            f"Provider '{self.name}' is configured as stub. Implement adapter/API integration first."
        )

    def get_supported_voices(self):
        return []

    def get_supported_languages(self):
        return []
