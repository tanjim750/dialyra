import requests
from flask import current_app

from app.api.v2.tts.providers.base import BaseTTSProvider, TTSGenerationResult, TTSProviderError


class OpenAITTSProvider(BaseTTSProvider):
    name = "openai"

    _DEFAULT_VOICES = [
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "nova",
        "onyx",
        "sage",
        "shimmer",
    ]
    _DEFAULT_LANGUAGES = ["en", "bn", "hi", "ar", "es"]

    def _api_key(self) -> str:
        api_key = (current_app.config.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise TTSProviderError("OPENAI_API_KEY is not configured")
        return api_key

    def _endpoint(self) -> str:
        return (
            current_app.config.get("OPENAI_TTS_ENDPOINT")
            or "https://api.openai.com/v1/audio/speech"
        )

    def _default_model(self) -> str:
        return (current_app.config.get("OPENAI_TTS_MODEL") or "gpt-4o-mini-tts").strip()

    def _default_voice(self) -> str:
        return (current_app.config.get("OPENAI_TTS_VOICE") or "alloy").strip()

    def generate_audio(
        self,
        *,
        text: str,
        language: str,
        voice: str,
        output_path: str,
        provider_options=None,
    ) -> TTSGenerationResult:
        api_key = self._api_key()
        endpoint = self._endpoint()
        timeout = float(current_app.config.get("TTS_PROVIDER_TIMEOUT_SEC", 20))

        # OpenAI endpoint does not require an explicit language field in payload;
        # language can be naturally inferred from text/voice.
        payload = {
            "model": self._default_model(),
            "input": text,
            "voice": voice or self._default_voice(),
            "format": "wav",
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise TTSProviderError(f"OpenAI TTS request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
            raise TTSProviderError(f"OpenAI TTS error: {detail}")

        if not response.content:
            raise TTSProviderError("OpenAI TTS returned empty audio")

        with open(output_path, "wb") as fh:
            fh.write(response.content)

        return TTSGenerationResult(
            file_path=output_path,
            duration=None,
            sample_rate=8000,
            channels=1,
            format="wav",
            source="tts_openai",
        )

    def get_supported_voices(self):
        return list(self._DEFAULT_VOICES)

    def get_supported_languages(self):
        return list(self._DEFAULT_LANGUAGES)
