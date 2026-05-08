import click
from werkzeug.security import generate_password_hash

from app.api.v1.auth.service import _get_or_create_system_business
from app.extensions import db
from app.models import User


def register_cli_commands(app):
    @app.cli.group("auth")
    def auth_group():
        """Authentication related commands."""

    @auth_group.command("create-superuser")
    @click.option("--full-name", required=True, help="Superuser full name")
    @click.option("--email", required=True, help="Superuser email")
    @click.option("--password", required=True, hide_input=True, prompt=True)
    def create_superuser(full_name, email, password):
        normalized_email = email.strip().lower()
        if User.query.filter_by(email=normalized_email).first() is not None:
            click.echo("User already exists with this email.")
            raise SystemExit(1)

        user = User(
            business_id=_get_or_create_system_business().id,
            full_name=full_name.strip(),
            email=normalized_email,
            password_hash=generate_password_hash(password),
            role="superuser",
            status="active",
        )
        db.session.add(user)
        db.session.commit()
        click.echo(f"Superuser created: {user.email}")
