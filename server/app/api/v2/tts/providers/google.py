import base64
import shutil
import subprocess
import tempfile
import wave

import requests
from flask import current_app

from app.api.v2.tts.providers.base import BaseTTSProvider, TTSGenerationResult, TTSProviderError


class GoogleTTSProvider(BaseTTSProvider):
    name = "google"

    # `gemini-tts:*` and `gtts:*` are virtual voice selectors for variant routing.
    _DEFAULT_VOICES = [
        "gemini-tts:Kore",
        "gemini-tts:Puck",
        "gemini-tts:Charon",
        "gtts:free",
    ]
    _DEFAULT_LANGUAGES = ["en", "en-US", "en-GB", "bn", "bn-BD", "hi", "hi-IN", "es", "es-ES", "ar", "ar-XA"]

    def _api_key(self) -> str:
        api_key = (current_app.config.get("GOOGLE_TTS_API_KEY") or "").strip()
        if not api_key:
            raise TTSProviderError("GOOGLE_TTS_API_KEY is not configured")
        return api_key

    def _endpoint(self) -> str:
        return (
            current_app.config.get("GOOGLE_TTS_ENDPOINT")
            or "https://texttospeech.googleapis.com/v1/text:synthesize"
        )

    def _gemini_endpoint(self) -> str:
        model = (current_app.config.get("GOOGLE_GEMINI_TTS_MODEL") or "gemini-2.5-flash-preview-tts").strip()
        return (
            current_app.config.get("GOOGLE_GEMINI_TTS_ENDPOINT")
            or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        )

    def _resolve_variant(self, voice: str, provider_options: dict | None) -> tuple[str, str]:
        v = (voice or "").strip()
        if v.startswith("gtts:"):
            return "gtts", v.split(":", 1)[1].strip() or "free"
        if v.startswith("gemini-tts:"):
            return "gemini-tts", v.split(":", 1)[1].strip() or "Kore"

        opt_variant = ""
        if provider_options and isinstance(provider_options, dict):
            opt_variant = str(provider_options.get("variant") or "").strip().lower()
        cfg_variant = str(current_app.config.get("GOOGLE_TTS_VARIANT", "gemini-tts")).strip().lower()
        variant = opt_variant or cfg_variant or "gemini-tts"

        if variant == "gtts":
            return "gtts", "free"
        return "gemini-tts", (v or "Kore")

    def _generate_gemini_tts(self, *, text: str, voice_name: str, output_path: str) -> TTSGenerationResult:
        api_key = self._api_key()
        endpoint = self._gemini_endpoint()
        timeout = float(current_app.config.get("TTS_PROVIDER_TIMEOUT_SEC", 20))
        sample_rate = int(current_app.config.get("GOOGLE_GEMINI_TTS_SAMPLE_RATE", 24000))

        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice_name or "Kore"}
                    }
                },
            },
        }

        try:
            response = requests.post(
                endpoint,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise TTSProviderError(f"Google Gemini TTS request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
            raise TTSProviderError(f"Google Gemini TTS error: {detail}")

        data = response.json() if response.content else {}
        audio_b64 = (
            (data.get("candidates") or [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("inlineData", {})
            .get("data")
        )
        if not audio_b64:
            raise TTSProviderError("Google Gemini TTS returned empty inlineData")

        try:
            pcm_bytes = base64.b64decode(audio_b64)
        except Exception as exc:  # noqa: BLE001
            raise TTSProviderError(f"Failed to decode Gemini audio: {exc}") from exc

        # Gemini TTS returns raw PCM bytes; wrap as WAV for telephony pipeline compatibility.
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)

        return TTSGenerationResult(
            file_path=str(output_path),
            duration=None,
            sample_rate=sample_rate,
            channels=1,
            format="wav",
            source="tts_google_gemini",
        )

    def _generate_gtts(self, *, text: str, language: str, output_path: str) -> TTSGenerationResult:
        try:
            from gtts import gTTS
        except Exception as exc:  # noqa: BLE001
            raise TTSProviderError(
                "gTTS library is not installed. Add `gTTS` to requirements."
            ) from exc

        ffmpeg_bin = shutil.which("ffmpeg") or shutil.which("avconv")
        if not ffmpeg_bin:
            raise TTSProviderError(
                "gTTS mode requires ffmpeg (or avconv) to convert mp3 to wav."
            )

        lang = (language or "en").split("-")[0].lower()
        with tempfile.NamedTemporaryFile(prefix="dialyra_gtts_", suffix=".mp3", delete=False) as tmp:
            tmp_mp3 = tmp.name

        try:
            gTTS(text=text, lang=lang).save(tmp_mp3)
            # Telephony-friendly conversion (8k mono wav).
            cmd = [
                ffmpeg_bin,
                "-y",
                "-i",
                tmp_mp3,
                "-ac",
                "1",
                "-ar",
                "8000",
                output_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "ffmpeg conversion failed")[:800]
                raise TTSProviderError(f"gTTS conversion failed: {err}")
        finally:
            try:
                import os

                os.unlink(tmp_mp3)
            except Exception:
                pass

        return TTSGenerationResult(
            file_path=str(output_path),
            duration=None,
            sample_rate=8000,
            channels=1,
            format="wav",
            source="tts_google_gtts",
        )

    def generate_audio(
        self,
        *,
        text: str,
        language: str,
        voice: str,
        output_path: str,
        provider_options=None,
    ) -> TTSGenerationResult:
        variant, resolved_voice = self._resolve_variant(voice, provider_options)
        if variant == "gtts":
            return self._generate_gtts(text=text, language=language, output_path=output_path)
        return self._generate_gemini_tts(text=text, voice_name=resolved_voice, output_path=output_path)

    # Backward-compatible classic endpoint method retained but not defaulted.
    def generate_audio_cloud_tts(self, *, text: str, language: str, voice: str, output_path: str) -> TTSGenerationResult:
        api_key = self._api_key()
        endpoint = self._endpoint()
        timeout = float(current_app.config.get("TTS_PROVIDER_TIMEOUT_SEC", 20))

        language_code = language or "en-US"
        voice_name = voice or "en-US-Standard-C"
        payload = {
            "input": {"text": text},
            "voice": {"languageCode": language_code, "name": voice_name},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 8000},
        }

        try:
            response = requests.post(
                endpoint,
                params={"key": api_key},
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise TTSProviderError(f"Google TTS request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500] if response.text else f"HTTP {response.status_code}"
            raise TTSProviderError(f"Google TTS error: {detail}")

        data = response.json() if response.content else {}
        audio_b64 = data.get("audioContent")
        if not audio_b64:
            raise TTSProviderError("Google TTS returned empty audioContent")

        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception as exc:  # noqa: BLE001
            raise TTSProviderError(f"Failed to decode Google TTS audio: {exc}") from exc

        with open(output_path, "wb") as fh:
            fh.write(audio_bytes)

        return TTSGenerationResult(
            file_path=output_path,
            duration=None,
            sample_rate=8000,
            channels=1,
            format="wav",
            source="tts_google_cloud",
        )

    def get_supported_voices(self):
        return list(self._DEFAULT_VOICES)

    def get_supported_languages(self):
        return list(self._DEFAULT_LANGUAGES)
