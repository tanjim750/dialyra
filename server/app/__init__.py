import os

from dotenv import load_dotenv
from flask import Flask, request

from app.config import CONFIG_MAP
from app.cli import register_cli_commands
from app.extensions import db, init_extensions
from app.middleware.error_handlers import register_error_handlers
from app.middleware.request_id import register_request_id_middleware
from app.services.ami_event_listener import start_ami_event_listener
from app.api.v2.tts.worker_service import start_tts_worker
from app.services.post_call_webhook_worker import start_post_call_webhook_worker
from app.utils.logging import configure_logging


def create_app(config_name=None):
    load_dotenv()

    app = Flask(__name__)

    env_name = (config_name or os.getenv("FLASK_ENV", "development")).lower()
    config_class = CONFIG_MAP.get(env_name, CONFIG_MAP["development"])
    app.config.from_object(config_class)

    configure_logging(app)
    init_extensions(app)
    register_request_id_middleware(app)
    register_error_handlers(app)
    register_blueprints(app)
    register_v1_deprecation_marker(app)
    register_cli_commands(app)

    with app.app_context():
        # Bootstrap tables for the current scaffold. Move to migrations flow later.
        db.create_all()

    start_ami_event_listener(app)
    start_tts_worker(app)
    start_post_call_webhook_worker(app)

    return app


def register_blueprints(app):
    from app.api.v1.access_tokens.routes import bp as access_tokens_bp
    from app.api.v1.auth.routes import bp as auth_bp
    from app.api.v1.businesses.routes import bp as businesses_bp
    from app.api.v1.calls.routes import bp as calls_bp
    from app.api.v1.health.routes import bp as health_bp
    from app.api.v1.internal.routes import bp as internal_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(calls_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(access_tokens_bp)
    app.register_blueprint(businesses_bp)
    app.register_blueprint(internal_bp)

    if app.config.get("AUTHZ_V2_ENABLED", False):
        from app.api.v2.access_tokens.routes import bp as access_tokens_v2_bp
        from app.api.v2.auth.routes import bp as auth_v2_bp
        from app.api.v2.audio_assets.routes import bp as audio_assets_v2_bp
        from app.api.v2.businesses.routes import bp as businesses_v2_bp
        from app.api.v2.calls.routes import bp as calls_v2_bp
        from app.api.v2.flows.routes import bp as flows_v2_bp
        from app.api.v2.health.routes import bp as health_v2_bp
        from app.api.v2.internal.routes import bp as internal_v2_bp
        from app.api.v2.sip_trunks.routes import bp as sip_trunks_v2_bp
        from app.api.v2.tts.routes import bp as tts_v2_bp

        app.register_blueprint(health_v2_bp)
        app.register_blueprint(calls_v2_bp)
        app.register_blueprint(auth_v2_bp)
        app.register_blueprint(audio_assets_v2_bp)
        app.register_blueprint(access_tokens_v2_bp)
        app.register_blueprint(businesses_v2_bp)
        app.register_blueprint(flows_v2_bp)
        app.register_blueprint(sip_trunks_v2_bp)
        app.register_blueprint(tts_v2_bp)
        app.register_blueprint(internal_v2_bp)


def register_v1_deprecation_marker(app):
    @app.after_request
    def mark_v1_deprecated(response):
        path = request.path or ""
        if not path.startswith("/api/") or path.startswith("/api/v2/"):
            return response

        response.headers["X-API-Deprecated"] = "true"
        response.headers["X-API-Deprecated-Message"] = "API v1 is deprecated. Use /api/v2/*"
        if response.is_json:
            payload = response.get_json(silent=True)
            if isinstance(payload, dict):
                payload.setdefault("deprecated", True)
                payload.setdefault("deprecated_message", "API v1 is deprecated. Use /api/v2/*")
                response.set_data(app.json.dumps(payload))
        return response
