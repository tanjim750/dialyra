import wave

import requests
from flask import current_app

from app.api.v2.tts.providers.base import BaseTTSProvider, TTSGenerationResult, TTSProviderError


class ElevenLabsTTSProvider(BaseTTSProvider):
    name = "elevenlabs"

    # ElevenLabs uses voice IDs. Keep a single default and allow override via request `voice`.
    _DEFAULT_VOICES = ["JBFqnCBsd6RMkjVDRZzb"]
    _DEFAULT_LANGUAGES = ["en", "bn", "hi", "ar", "es"]

    def _api_key(self) -> str:
        api_key = (current_app.config.get("ELEVENLABS_API_KEY") or "").strip()
        if not api_key:
            raise TTSProviderError("ELEVENLABS_API_KEY is not configured")
        return api_key

    def _base_url(self) -> str:
        return (current_app.config.get("ELEVENLABS_TTS_BASE_URL") or "https://api.elevenlabs.io").strip().rstrip("/")

    def _default_voice(self) -> str:
        return (current_app.config.get("ELEVENLABS_TTS_VOICE_ID") or "JBFqnCBsd6RMkjVDRZzb").strip()

    def _default_model(self) -> str:
        return (current_app.config.get("ELEVENLABS_TTS_MODEL_ID") or "eleven_multilingual_v2").strip()

    def _output_format(self) -> str:
        # `pcm_16000` is widely available and easy to wrap as WAV.
        return (current_app.config.get("ELEVENLABS_TTS_OUTPUT_FORMAT") or "pcm_16000").strip()

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
        base_url = self._base_url()
        timeout = float(current_app.config.get("TTS_PROVIDER_TIMEOUT_SEC", 20))

        voice_id = (voice or self._default_voice()).strip()
        model_id = self._default_model()
        output_format = self._output_format()
        if output_format not in {"pcm_16000", "pcm_22050", "pcm_24000", "pcm_44100"}:
            raise TTSProviderError(
                "ELEVENLABS_TTS_OUTPUT_FORMAT must be one of: pcm_16000, pcm_22050, pcm_24000, pcm_44100"
            )

        endpoint = f"{base_url}/v1/text-to-speech/{voice_id}"
        payload = {
            "text": text,
            "model_id": model_id,
            "language_code": language,
        }
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                endpoint,
                params={"output_format": output_format},
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise TTSProviderError(f"ElevenLabs TTS request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
            raise TTSProviderError(f"ElevenLabs TTS error: {detail}")

        raw_pcm = response.content or b""
        if not raw_pcm:
            raise TTSProviderError("ElevenLabs TTS returned empty audio")
        if len(raw_pcm) % 2 == 1:
            # Keep 16-bit PCM alignment safe.
            raw_pcm = raw_pcm[:-1]

        sample_rate = int(output_format.split("_", 1)[1])
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(raw_pcm)

        return TTSGenerationResult(
            file_path=output_path,
            duration=None,
            sample_rate=sample_rate,
            channels=1,
            format="wav",
            source="tts_elevenlabs",
        )

    def get_supported_voices(self):
        return list(self._DEFAULT_VOICES)

    def get_supported_languages(self):
        return list(self._DEFAULT_LANGUAGES)
