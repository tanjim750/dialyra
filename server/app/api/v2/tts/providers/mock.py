import struct
import wave

from app.api.v2.tts.providers.base import BaseTTSProvider, TTSGenerationResult

MOCK_VOICES = ["female_en_1", "male_en_1", "female_bn_1", "male_bn_1"]
MOCK_LANGUAGES = ["en", "bn", "hi", "ar", "es"]


class MockTTSProvider(BaseTTSProvider):
    name = "mock"

    def get_supported_voices(self):
        return list(MOCK_VOICES)

    def get_supported_languages(self):
        return list(MOCK_LANGUAGES)

    def generate_audio(self, *, text: str, language: str, voice: str, output_path: str, provider_options=None):
        words = max(1, len((text or "").split()))
        duration = max(1.0, round(words / 2.5, 2))

        sample_rate = 8000
        channels = 1
        sample_width = 2
        total_frames = int(sample_rate * max(0.1, float(duration)))
        silence_frame = struct.pack("<h", 0)

        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(silence_frame * total_frames)

        return TTSGenerationResult(
            file_path=str(output_path),
            duration=duration,
            sample_rate=sample_rate,
            channels=channels,
            format="wav",
            source="tts_mock",
        )
