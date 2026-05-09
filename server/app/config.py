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
    PJSIP_CONFIG_PATH = os.getenv("PJSIP_CONFIG_PATH", "/app/asterisk/pjsip.conf")
    PJSIP_TRANSPORT_NAME = os.getenv("PJSIP_TRANSPORT_NAME", "transport-udp")
    SIP_REALTIME_ENABLED = os.getenv("SIP_REALTIME_ENABLED", "false").lower() == "true"
    SIP_REALTIME_DSN = os.getenv("SIP_REALTIME_DSN", "")
    SIP_REALTIME_SCHEMA = os.getenv("SIP_REALTIME_SCHEMA", "public")


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
