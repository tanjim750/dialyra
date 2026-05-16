import click
from werkzeug.security import generate_password_hash

from app.api.v1.auth.service import _get_or_create_system_business
from app.extensions import db
from app.models import User
from app.services.call_reconciliation import reconcile_call_logs_from_cdr
from scripts import (
    migrate_business_owner_user_id,
    migrate_business_schema,
    migrate_audio_assets,
    migrate_call_events,
    migrate_call_sessions,
    migrate_call_logs,
    migrate_drop_user_business_id,
    migrate_roles,
    migrate_flow_engine,
    migrate_sip_realtime,
    migrate_sip_trunks,
    migrate_tts_requests,
)


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
            full_name=full_name.strip(),
            email=normalized_email,
            password_hash=generate_password_hash(password),
            role="superuser",
            status="active",
        )
        db.session.add(user)
        db.session.commit()
        click.echo(f"Superuser created: {user.email}")

    @app.cli.group("migrate")
    def migrate_group():
        """Project migration commands (app-level)."""

    @app.cli.group("sip")
    def sip_group():
        """SIP related commands."""

    @app.cli.group("calls")
    def calls_group():
        """Calls and reporting related commands."""

    @migrate_group.command("roles")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    @click.option(
        "--apply-constraints",
        is_flag=True,
        default=False,
        help="Also apply membership role/status constraints",
    )
    def migrate_roles_cmd(apply, dry_run, apply_constraints):
        effective_dry_run = (not apply) or dry_run
        plan = migrate_roles.build_plan()
        migrate_roles.print_plan(plan)

        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return

        migrate_roles.apply_plan(plan)
        if apply_constraints:
            migrate_roles.apply_constraints_if_requested()
            click.echo("Constraints apply step completed (idempotent).")
        click.echo("\nApply mode: migration applied successfully.")

    @migrate_group.command("business-owner-column")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_business_owner_column_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        exists = migrate_business_owner_user_id.column_exists()
        fk = migrate_business_owner_user_id.fk_exists() if exists else False

        click.echo("Schema check: businesses.owner_user_id")
        click.echo(f"  column_exists: {exists}")
        click.echo(f"  fk_exists: {fk}")

        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            if not exists:
                click.echo("Would add column: businesses.owner_user_id")
                click.echo("Would add FK: fk_businesses_owner_user_id_users")
            elif exists and not fk:
                click.echo("Would add FK: fk_businesses_owner_user_id_users")
            return

        migrate_business_owner_user_id.apply_changes()
        click.echo("\nApply mode: schema updated successfully.")

    @migrate_group.command("business-schema")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_business_schema_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        existing = migrate_business_schema.list_columns()
        missing = [c for c in migrate_business_schema.REQUIRED_COLUMNS.keys() if c not in existing]
        click.echo("Businesses schema check:")
        click.echo(f"  existing columns: {len(existing)}")
        click.echo(f"  missing required columns: {missing}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return
        migrate_business_schema.apply_schema()
        click.echo("\nApply mode: businesses schema updated successfully.")

    @migrate_group.command("all")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    @click.option(
        "--apply-constraints",
        is_flag=True,
        default=False,
        help="Also apply membership role/status constraints",
    )
    def migrate_all_cmd(apply, dry_run, apply_constraints):
        effective_dry_run = (not apply) or dry_run

        click.echo("== Step 1: businesses schema check ==")
        existing = migrate_business_schema.list_columns()
        missing = [c for c in migrate_business_schema.REQUIRED_COLUMNS.keys() if c not in existing]
        click.echo(f"  existing columns: {len(existing)}")
        click.echo(f"  missing required columns: {missing}")

        if effective_dry_run:
            click.echo("  dry-run: no schema changes written.")
        else:
            migrate_business_schema.apply_schema()
            click.echo("  apply: schema step completed.")

        click.echo("\n== Step 2: role + membership migration ==")
        plan = migrate_roles.build_plan()
        migrate_roles.print_plan(plan)

        if effective_dry_run:
            click.echo("\nDry-run mode: no data changes written.")
            return

        migrate_roles.apply_plan(plan)
        if apply_constraints:
            migrate_roles.apply_constraints_if_requested()
            click.echo("Constraints apply step completed (idempotent).")
        click.echo("\n== Step 3: drop users.business_id ==")
        migrate_drop_user_business_id.apply_drop()
        click.echo("  apply: users.business_id dropped.")
        click.echo("\n== Step 4: sip_trunks schema ==")
        migrate_sip_trunks.apply_schema()
        migrate_sip_trunks.ensure_fk()
        migrate_sip_trunks.ensure_indexes_and_constraints()
        click.echo("  apply: sip_trunks schema step completed.")
        click.echo("\n== Step 5: sip_realtime schema ==")
        migrate_sip_realtime.apply_schema()
        click.echo("  apply: sip_realtime schema step completed.")
        click.echo("\n== Step 6: call_logs schema ==")
        migrate_call_logs.apply_schema()
        migrate_call_logs.ensure_fk()
        migrate_call_logs.ensure_indexes()
        migrate_call_logs.ensure_constraints()
        click.echo("  apply: call_logs schema step completed.")
        click.echo("\n== Step 7: call_sessions schema ==")
        migrate_call_sessions.apply_schema()
        migrate_call_sessions.ensure_fk()
        migrate_call_sessions.ensure_indexes()
        migrate_call_sessions.ensure_constraints()
        click.echo("  apply: call_sessions schema step completed.")
        click.echo("\n== Step 8: call_events schema ==")
        migrate_call_events.apply_schema()
        migrate_call_events.ensure_fk()
        migrate_call_events.ensure_indexes()
        migrate_call_events.ensure_constraints()
        click.echo("  apply: call_events schema step completed.")
        click.echo("\n== Step 9: audio_assets schema ==")
        migrate_audio_assets.apply_schema()
        migrate_audio_assets.ensure_fk()
        migrate_audio_assets.ensure_indexes()
        migrate_audio_assets.ensure_constraints()
        click.echo("  apply: audio_assets schema step completed.")
        click.echo("\n== Step 10: tts_requests schema ==")
        migrate_tts_requests.apply_schema()
        migrate_tts_requests.ensure_fk()
        migrate_tts_requests.ensure_indexes()
        migrate_tts_requests.ensure_constraints()
        click.echo("  apply: tts_requests schema step completed.")
        click.echo("\n== Step 11: flow_engine schema ==")
        migrate_flow_engine.apply_schema()
        migrate_flow_engine.ensure_fk()
        migrate_flow_engine.ensure_indexes()
        migrate_flow_engine.ensure_constraints()
        click.echo("  apply: flow_engine schema step completed.")
        click.echo("\nApply mode: all migration steps completed successfully.")

    @migrate_group.command("drop-user-business-id")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_drop_user_business_id_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        exists = migrate_drop_user_business_id.has_column()
        click.echo("Users schema check:")
        click.echo(f"  business_id_exists: {exists}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return
        migrate_drop_user_business_id.apply_drop()
        click.echo("\nApply mode: users.business_id dropped successfully.")

    @migrate_group.command("sip-trunks")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_sip_trunks_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        exists = migrate_sip_trunks.table_exists()
        columns = migrate_sip_trunks.list_columns() if exists else set()
        click.echo("SIP trunks schema check:")
        click.echo(f"  table_exists: {exists}")
        click.echo(f"  columns: {len(columns)}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return
        migrate_sip_trunks.apply_schema()
        migrate_sip_trunks.ensure_fk()
        migrate_sip_trunks.ensure_indexes_and_constraints()
        click.echo("\nApply mode: sip_trunks schema updated successfully.")

    @migrate_group.command("sip-realtime")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_sip_realtime_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        missing = migrate_sip_realtime.missing_tables()
        schema = app.config.get("SIP_REALTIME_SCHEMA", "public")
        dsn = app.config.get("SIP_REALTIME_DSN", "")
        click.echo("SIP realtime schema check:")
        click.echo(f"  schema: {schema}")
        click.echo(f"  using_external_dsn: {bool((dsn or '').strip())}")
        click.echo(f"  missing_tables: {missing}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return
        migrate_sip_realtime.apply_schema()
        after_missing = migrate_sip_realtime.missing_tables()
        counts = migrate_sip_realtime.table_counts()
        click.echo("\nApply mode: sip realtime schema updated successfully.")
        click.echo(f"  missing_tables_after_apply: {after_missing}")
        click.echo(f"  table_counts: {counts}")

    @migrate_group.command("call-logs")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_call_logs_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        exists = migrate_call_logs.table_exists()
        columns = migrate_call_logs.list_columns() if exists else set()
        click.echo("Call logs schema check:")
        click.echo(f"  table_exists: {exists}")
        click.echo(f"  columns: {len(columns)}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return
        migrate_call_logs.apply_schema()
        migrate_call_logs.ensure_fk()
        migrate_call_logs.ensure_indexes()
        migrate_call_logs.ensure_constraints()
        click.echo("\nApply mode: call_logs schema updated successfully.")

    @migrate_group.command("call-sessions")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_call_sessions_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        exists = migrate_call_sessions.table_exists()
        columns = migrate_call_sessions.list_columns() if exists else set()
        click.echo("Call sessions schema check:")
        click.echo(f"  table_exists: {exists}")
        click.echo(f"  columns: {len(columns)}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return
        migrate_call_sessions.apply_schema()
        migrate_call_sessions.ensure_fk()
        migrate_call_sessions.ensure_indexes()
        migrate_call_sessions.ensure_constraints()
        click.echo("\nApply mode: call_sessions schema updated successfully.")

    @migrate_group.command("call-events")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_call_events_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        exists = migrate_call_events.table_exists()
        columns = migrate_call_events.list_columns() if exists else set()
        click.echo("Call events schema check:")
        click.echo(f"  table_exists: {exists}")
        click.echo(f"  columns: {len(columns)}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return
        migrate_call_events.apply_schema()
        migrate_call_events.ensure_fk()
        migrate_call_events.ensure_indexes()
        migrate_call_events.ensure_constraints()
        click.echo("\nApply mode: call_events schema updated successfully.")

    @migrate_group.command("audio-assets")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_audio_assets_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        exists = migrate_audio_assets.table_exists()
        columns = migrate_audio_assets.list_columns() if exists else set()
        click.echo("Audio assets schema check:")
        click.echo(f"  table_exists: {exists}")
        click.echo(f"  columns: {len(columns)}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return
        migrate_audio_assets.apply_schema()
        migrate_audio_assets.ensure_fk()
        migrate_audio_assets.ensure_indexes()
        migrate_audio_assets.ensure_constraints()
        click.echo("\nApply mode: audio_assets schema updated successfully.")

    @migrate_group.command("tts-requests")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_tts_requests_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        exists = migrate_tts_requests.table_exists()
        columns = migrate_tts_requests.list_columns() if exists else set()
        click.echo("TTS requests schema check:")
        click.echo(f"  table_exists: {exists}")
        click.echo(f"  columns: {len(columns)}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return
        migrate_tts_requests.apply_schema()
        migrate_tts_requests.ensure_fk()
        migrate_tts_requests.ensure_indexes()
        migrate_tts_requests.ensure_constraints()
        click.echo("\nApply mode: tts_requests schema updated successfully.")

    @migrate_group.command("flow-engine")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def migrate_flow_engine_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        existing = migrate_flow_engine.existing_tables()
        missing = sorted(migrate_flow_engine.FLOW_TABLES - existing)
        click.echo("Flow engine schema check:")
        click.echo(f"  existing_tables: {sorted(existing)}")
        click.echo(f"  missing_tables: {missing}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            return
        migrate_flow_engine.apply_schema()
        migrate_flow_engine.ensure_fk()
        migrate_flow_engine.ensure_indexes()
        migrate_flow_engine.ensure_constraints()
        click.echo("\nApply mode: flow engine schema updated successfully.")

    @sip_group.command("init-realtime")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    def sip_init_realtime_cmd(apply, dry_run):
        effective_dry_run = (not apply) or dry_run
        missing = migrate_sip_realtime.missing_tables()
        schema = app.config.get("SIP_REALTIME_SCHEMA", "public")
        dsn = app.config.get("SIP_REALTIME_DSN", "")
        click.echo("SIP realtime init:")
        click.echo(f"  schema: {schema}")
        click.echo(f"  using_external_dsn: {bool((dsn or '').strip())}")
        click.echo(f"  missing_tables_before: {missing}")
        if effective_dry_run:
            click.echo("\nDry-run mode: no changes written.")
            click.echo("Run with --apply to create/fix realtime SIP tables.")
            return
        migrate_sip_realtime.apply_schema()
        after_missing = migrate_sip_realtime.missing_tables()
        counts = migrate_sip_realtime.table_counts()
        click.echo("\nApply mode: SIP realtime initialized successfully.")
        click.echo(f"  missing_tables_after_apply: {after_missing}")
        click.echo(f"  table_counts: {counts}")

    @calls_group.command("reconcile")
    @click.option("--apply", is_flag=True, default=False, help="Apply changes")
    @click.option("--dry-run", is_flag=True, default=False, help="Preview only")
    @click.option("--hours-back", default=24, type=int, show_default=True)
    @click.option("--limit", default=5000, type=int, show_default=True)
    def calls_reconcile_cmd(apply, dry_run, hours_back, limit):
        effective_dry_run = (not apply) or dry_run
        result, error = reconcile_call_logs_from_cdr(
            hours_back=hours_back,
            limit=limit,
            dry_run=effective_dry_run,
        )
        if error:
            click.echo(f"Reconcile failed: {error}")
            raise SystemExit(1)

        click.echo("Call reconciliation result:")
        click.echo(f"  source.cdr: {result['source']['cdr']}")
        click.echo(f"  source.cel: {result['source']['cel']}")
        click.echo(f"  window_start: {result['window_start']}")
        click.echo(f"  dry_run: {result['dry_run']}")
        stats = result["stats"]
        click.echo(f"  scanned: {stats['scanned']}")
        click.echo(f"  matched: {stats['matched']}")
        click.echo(f"  updated: {stats['updated']}")
        click.echo(f"  skipped_finalized: {stats['skipped_finalized']}")
        click.echo(f"  unmatched: {stats['unmatched']}")
