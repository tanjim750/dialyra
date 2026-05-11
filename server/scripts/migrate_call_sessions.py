#!/usr/bin/env python3
"""
Ensure call_sessions table and indexes exist (idempotent).

Usage:
  python server/scripts/migrate_call_sessions.py --dry-run
  python server/scripts/migrate_call_sessions.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_DIR = SCRIPT_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app.extensions import db


def parse_args():
    p = argparse.ArgumentParser(description="Ensure call_sessions schema")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def table_exists():
    row = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name='call_sessions'
            LIMIT 1
            """
        )
    ).first()
    return row is not None


def list_columns():
    rows = db.session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='call_sessions'
            """
        )
    ).fetchall()
    return {r[0] for r in rows}


def apply_schema():
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS call_sessions (
                id SERIAL PRIMARY KEY,
                business_id INTEGER NOT NULL,
                flow_id INTEGER NULL,
                flow_version_id INTEGER NULL,
                campaign_id INTEGER NULL,
                contact_id INTEGER NULL,
                sip_trunk_id INTEGER NULL,
                call_direction VARCHAR(20) NOT NULL DEFAULT 'outbound',
                status VARCHAR(32) NOT NULL DEFAULT 'queued',
                phone_number VARCHAR(64) NOT NULL,
                caller_id VARCHAR(128) NULL,
                channel VARCHAR(255) NULL,
                uniqueid VARCHAR(64) NULL,
                linkedid VARCHAR(64) NULL,
                ami_action_id VARCHAR(64) NULL UNIQUE,
                variables_json TEXT NULL,
                metadata_json TEXT NULL,
                started_at TIMESTAMP NULL,
                answered_at TIMESTAMP NULL,
                ended_at TIMESTAMP NULL,
                hangup_cause VARCHAR(64) NULL,
                created_by INTEGER NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    db.session.commit()


def ensure_indexes():
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_business_id ON call_sessions (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_flow_id ON call_sessions (flow_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_flow_version_id ON call_sessions (flow_version_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_campaign_id ON call_sessions (campaign_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_contact_id ON call_sessions (contact_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_sip_trunk_id ON call_sessions (sip_trunk_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_call_direction ON call_sessions (call_direction)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_status ON call_sessions (status)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_phone_number ON call_sessions (phone_number)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_uniqueid ON call_sessions (uniqueid)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_linkedid ON call_sessions (linkedid)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_created_by ON call_sessions (created_by)",
        "CREATE INDEX IF NOT EXISTS ix_call_sessions_started_at ON call_sessions (started_at)",
    ]
    for sql in statements:
        db.session.execute(text(sql))
    db.session.commit()


def ensure_fk():
    constraints = [
        (
            "fk_call_sessions_business_id_businesses",
            "FOREIGN KEY (business_id) REFERENCES businesses(id)",
        ),
        (
            "fk_call_sessions_flow_id_flows",
            "FOREIGN KEY (flow_id) REFERENCES flows(id)",
        ),
        (
            "fk_call_sessions_flow_version_id_flow_versions",
            "FOREIGN KEY (flow_version_id) REFERENCES flow_versions(id)",
        ),
        (
            "fk_call_sessions_sip_trunk_id_sip_trunks",
            "FOREIGN KEY (sip_trunk_id) REFERENCES sip_trunks(id)",
        ),
        (
            "fk_call_sessions_created_by_users",
            "FOREIGN KEY (created_by) REFERENCES users(id)",
        ),
    ]
    for name, expr in constraints:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='call_sessions' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE call_sessions ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def ensure_constraints():
    checks = [
        ("ck_call_sessions_call_direction", "CHECK (call_direction IN ('outbound','inbound','internal'))"),
        (
            "ck_call_sessions_status",
            "CHECK (status IN ('queued','initiating','ringing','answered','completed','failed','busy','no_answer','cancelled','hangup'))",
        ),
    ]
    for name, expr in checks:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='call_sessions' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE call_sessions ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def main():
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run

    from app import create_app

    app = create_app()
    with app.app_context():
        exists = table_exists()
        columns = list_columns() if exists else set()
        print("Call sessions schema check:")
        print(f"  table_exists: {exists}")
        print(f"  columns: {len(columns)}")
        if dry_run:
            print("\nDry-run mode: no changes written.")
            return 0

        apply_schema()
        ensure_fk()
        ensure_indexes()
        ensure_constraints()
        print("\nApply mode: call_sessions schema updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
