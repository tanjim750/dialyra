import os

from dotenv import load_dotenv
from flask import Flask

from app.config import CONFIG_MAP
from app.cli import register_cli_commands
from app.extensions import db, init_extensions
from app.middleware.error_handlers import register_error_handlers
from app.middleware.request_id import register_request_id_middleware
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
    register_cli_commands(app)

    with app.app_context():
        # Bootstrap tables for the current scaffold. Move to migrations flow later.
        db.create_all()

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
