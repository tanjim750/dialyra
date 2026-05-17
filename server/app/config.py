import os
from datetime import timedelta
from urllib.parse import quote_plus


def _build_database_uri():
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")

    if db_host and db_name and db_user and db_password:
        escaped_password = quote_plus(db_password)
        return (
            f"postgresql+psycopg2://{db_user}:{escaped_password}"
            f"@{db_host}:{db_port}/{db_name}"
        )

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    return "sqlite:///dialyra_dev.db"


class Config:
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.getenv("SECRET_KEY", "dialyra-dev-secret")

    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        days=int(os.getenv("JWT_EXPIRES_DAYS", "90"))
    )
    LOGIN_MAX_FAILED_ATTEMPTS = int(os.getenv("LOGIN_MAX_FAILED_ATTEMPTS", "5"))
    LOGIN_RATE_LIMIT_WINDOW_MINUTES = int(
        os.getenv("LOGIN_RATE_LIMIT_WINDOW_MINUTES", "15")
    )
    ACCESS_TOKEN_EXPIRES_DAYS = int(os.getenv("ACCESS_TOKEN_EXPIRES_DAYS", "365"))
    BOOTSTRAP_SUPERUSER_ENABLED = (
        os.getenv("BOOTSTRAP_SUPERUSER_ENABLED", "false").lower() == "true"
    )
    BOOTSTRAP_SUPERUSER_SECRET = os.getenv("BOOTSTRAP_SUPERUSER_SECRET", "")
    AUTHZ_V2_ENABLED = os.getenv("AUTHZ_V2_ENABLED", "false").lower() == "true"
    AUTHZ_V2_COMPARE_ENABLED = (
        os.getenv("AUTHZ_V2_COMPARE_ENABLED", "false").lower() == "true"
    )

    AMI_HOST = os.getenv("AMI_HOST", "dialyra-asterisk")
    AMI_PORT = int(os.getenv("AMI_PORT", "5038"))
    AMI_USERNAME = os.getenv("AMI_USERNAME", "admin")
    AMI_SECRET = os.getenv("AMI_SECRET", "dialyra123")
    AMI_TIMEOUT = float(os.getenv("AMI_TIMEOUT", "5"))
    AMI_EVENT_LISTENER_ENABLED = (
        os.getenv("AMI_EVENT_LISTENER_ENABLED", "false").lower() == "true"
    )
    AMI_EVENT_RECONNECT_DELAY_SEC = float(
        os.getenv("AMI_EVENT_RECONNECT_DELAY_SEC", "2")
    )
    REDIS_URL = os.getenv("REDIS_URL", "")
    POSTCALL_INTENT_TTL_SEC = int(os.getenv("POSTCALL_INTENT_TTL_SEC", "86400"))
    POSTCALL_FLUSH_LOCK_TTL_SEC = int(os.getenv("POSTCALL_FLUSH_LOCK_TTL_SEC", "60"))
    POSTCALL_WEBHOOK_WORKER_ENABLED = (
        os.getenv("POSTCALL_WEBHOOK_WORKER_ENABLED", "true").lower() == "true"
    )
    POSTCALL_WEBHOOK_WORKER_POLL_SEC = float(
        os.getenv("POSTCALL_WEBHOOK_WORKER_POLL_SEC", "1.5")
    )
    POSTCALL_WEBHOOK_WORKER_BATCH_SIZE = int(
        os.getenv("POSTCALL_WEBHOOK_WORKER_BATCH_SIZE", "20")
    )
    POSTCALL_WEBHOOK_MAX_ATTEMPTS = int(os.getenv("POSTCALL_WEBHOOK_MAX_ATTEMPTS", "4"))
    POSTCALL_WEBHOOK_RETRY_SCHEDULE_SEC = os.getenv(
        "POSTCALL_WEBHOOK_RETRY_SCHEDULE_SEC", "10,30,120"
    )
    POSTCALL_WEBHOOK_NO_RETRY_STATUS_CODES = os.getenv(
        "POSTCALL_WEBHOOK_NO_RETRY_STATUS_CODES",
        "400,401,403,404,405,409,410,411,413,414,415,422",
    )
    CALL_PIPELINE_VERBOSE = os.getenv("CALL_PIPELINE_VERBOSE", "false").lower() == "true"
    # 0 means unlimited system-wide concurrent outbound calls.
    SYSTEM_MAX_CONCURRENT_CALLS = int(os.getenv("SYSTEM_MAX_CONCURRENT_CALLS", "0"))
    CALL_RETRY_MAX_ATTEMPTS = int(os.getenv("CALL_RETRY_MAX_ATTEMPTS", "3"))
    AUDIO_PLAYBACK_TEST_CHANNEL = os.getenv("AUDIO_PLAYBACK_TEST_CHANNEL", "")
    AUDIO_PLAYBACK_TEST_TIMEOUT_MS = int(os.getenv("AUDIO_PLAYBACK_TEST_TIMEOUT_MS", "10000"))
    PJSIP_CONFIG_PATH = os.getenv("PJSIP_CONFIG_PATH", "/app/asterisk/pjsip.conf")
    PJSIP_TRANSPORT_NAME = os.getenv("PJSIP_TRANSPORT_NAME", "transport-udp")
    SIP_REALTIME_ENABLED = os.getenv("SIP_REALTIME_ENABLED", "false").lower() == "true"
    SIP_REALTIME_DSN = os.getenv("SIP_REALTIME_DSN", "")
    SIP_REALTIME_SCHEMA = os.getenv("SIP_REALTIME_SCHEMA", "public")
    AUDIO_ASSETS_ROOT = os.getenv("AUDIO_ASSETS_ROOT", "/data/audio-assets")
    AUDIO_ASSET_EXTRA_CATEGORIES = os.getenv("AUDIO_ASSET_EXTRA_CATEGORIES", "")
    AUDIO_ASSET_MAX_FILE_SIZE_MB = int(os.getenv("AUDIO_ASSET_MAX_FILE_SIZE_MB", "20"))
    AUDIO_ASSET_ENFORCE_MIME = os.getenv("AUDIO_ASSET_ENFORCE_MIME", "true").lower() == "true"
    AUDIO_ASSET_ALLOWED_EXTENSIONS = os.getenv(
        "AUDIO_ASSET_ALLOWED_EXTENSIONS", "wav,gsm,ulaw,alaw,mp3"
    )
    TTS_DEFAULT_PROVIDER = os.getenv("TTS_DEFAULT_PROVIDER", "mock")
    TTS_ENABLED_PROVIDERS = os.getenv(
        "TTS_ENABLED_PROVIDERS", "mock,openai,google,amazon_polly,azure,elevenlabs,coqui,piper"
    )
    TTS_ASYNC_ENABLED = os.getenv("TTS_ASYNC_ENABLED", "false").lower() == "true"
    TTS_PROVIDER_TIMEOUT_SEC = float(os.getenv("TTS_PROVIDER_TIMEOUT_SEC", "20"))
    GOOGLE_TTS_API_KEY = os.getenv("GOOGLE_TTS_API_KEY", "")
    GOOGLE_TTS_ENDPOINT = os.getenv(
        "GOOGLE_TTS_ENDPOINT", "https://texttospeech.googleapis.com/v1/text:synthesize"
    )
    GOOGLE_TTS_VARIANT = os.getenv("GOOGLE_TTS_VARIANT", "gemini-tts")
    GOOGLE_GEMINI_TTS_MODEL = os.getenv("GOOGLE_GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
    GOOGLE_GEMINI_TTS_ENDPOINT = os.getenv("GOOGLE_GEMINI_TTS_ENDPOINT", "")
    GOOGLE_GEMINI_TTS_SAMPLE_RATE = int(os.getenv("GOOGLE_GEMINI_TTS_SAMPLE_RATE", "24000"))
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_TTS_ENDPOINT = os.getenv("OPENAI_TTS_ENDPOINT", "https://api.openai.com/v1/audio/speech")
    OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
    ELEVENLABS_TTS_BASE_URL = os.getenv("ELEVENLABS_TTS_BASE_URL", "https://api.elevenlabs.io")
    ELEVENLABS_TTS_VOICE_ID = os.getenv("ELEVENLABS_TTS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    ELEVENLABS_TTS_MODEL_ID = os.getenv("ELEVENLABS_TTS_MODEL_ID", "eleven_multilingual_v2")
    ELEVENLABS_TTS_OUTPUT_FORMAT = os.getenv("ELEVENLABS_TTS_OUTPUT_FORMAT", "pcm_16000")
    FLOW_RUNTIME_CANARY_ENABLED = (
        os.getenv("FLOW_RUNTIME_CANARY_ENABLED", "false").lower() == "true"
    )
    FLOW_RUNTIME_CANARY_PERCENT = int(os.getenv("FLOW_RUNTIME_CANARY_PERCENT", "100"))
    FLOW_RUNTIME_CANARY_FORCE_BUSINESS_IDS = os.getenv(
        "FLOW_RUNTIME_CANARY_FORCE_BUSINESS_IDS", ""
    )
    FLOW_RUNTIME_CANARY_FORCE_FLOW_IDS = os.getenv(
        "FLOW_RUNTIME_CANARY_FORCE_FLOW_IDS", ""
    )
    # Optional comma-separated allowlist of runtime node types for phased rollout.
    # Empty means all implemented node types are allowed.
    FLOW_RUNTIME_ENABLED_NODE_TYPES = os.getenv("FLOW_RUNTIME_ENABLED_NODE_TYPES", "")
    # Optional granular per-node flags. When set, these override allowlist behavior.
    FLOW_RUNTIME_ENABLE_PLAY_AUDIO = os.getenv("FLOW_RUNTIME_ENABLE_PLAY_AUDIO", "").lower()
    FLOW_RUNTIME_ENABLE_SAY_TEXT = os.getenv("FLOW_RUNTIME_ENABLE_SAY_TEXT", "").lower()
    FLOW_RUNTIME_ENABLE_TTS = os.getenv("FLOW_RUNTIME_ENABLE_TTS", "").lower()
    FLOW_RUNTIME_ENABLE_GATHER_INPUT = os.getenv("FLOW_RUNTIME_ENABLE_GATHER_INPUT", "").lower()
    FLOW_RUNTIME_ENABLE_CONDITION = os.getenv("FLOW_RUNTIME_ENABLE_CONDITION", "").lower()
    FLOW_RUNTIME_ENABLE_SET_VARIABLE = os.getenv("FLOW_RUNTIME_ENABLE_SET_VARIABLE", "").lower()
    FLOW_RUNTIME_ENABLE_GOTO = os.getenv("FLOW_RUNTIME_ENABLE_GOTO", "").lower()
    FLOW_RUNTIME_ENABLE_WEBHOOK = os.getenv("FLOW_RUNTIME_ENABLE_WEBHOOK", "").lower()
    # When true, webhook nodes capture post-call intent during runtime and do not execute HTTP inline.
    FLOW_WEBHOOK_DEFERRED_MODE = os.getenv("FLOW_WEBHOOK_DEFERRED_MODE", "true").lower() == "true"
    FLOW_RUNTIME_ENABLE_TRANSFER_CALL = os.getenv("FLOW_RUNTIME_ENABLE_TRANSFER_CALL", "").lower()
    FLOW_RUNTIME_ENABLE_WAIT = os.getenv("FLOW_RUNTIME_ENABLE_WAIT", "").lower()
    FLOW_RUNTIME_ENABLE_RECORD_CONTROL = os.getenv("FLOW_RUNTIME_ENABLE_RECORD_CONTROL", "").lower()
    FLOW_RUNTIME_ENABLE_HANGUP = os.getenv("FLOW_RUNTIME_ENABLE_HANGUP", "").lower()


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class ProductionConfig(Config):
    pass


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
