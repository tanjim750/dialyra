from dataclasses import dataclass


class TTSProviderError(Exception):
    pass


@dataclass
class TTSGenerationResult:
    file_path: str
    duration: float | None
    sample_rate: int | None
    channels: int | None
    format: str
    source: str


class BaseTTSProvider:
    name = "base"

    def generate_audio(
        self,
        *,
        text: str,
        language: str,
        voice: str,
        output_path: str,
        provider_options: dict | None = None,
    ) -> TTSGenerationResult:
        raise NotImplementedError

    def get_supported_voices(self):
        return []

    def get_supported_languages(self):
        return []
