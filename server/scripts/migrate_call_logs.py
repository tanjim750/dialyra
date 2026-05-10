#!/usr/bin/env python3
"""
Ensure call_logs table and indexes exist (idempotent).

Usage:
  python server/scripts/migrate_call_logs.py --dry-run
  python server/scripts/migrate_call_logs.py --apply
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
    p = argparse.ArgumentParser(description="Ensure call_logs schema")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def table_exists():
    row = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name='call_logs'
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
            WHERE table_name='call_logs'
            """
        )
    ).fetchall()
    return {r[0] for r in rows}


def apply_schema():
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS call_logs (
                id SERIAL PRIMARY KEY,
                uuid VARCHAR(36) NOT NULL UNIQUE,
                action_id VARCHAR(64),
                asterisk_uniqueid VARCHAR(64),
                linkedid VARCHAR(64),
                business_id INTEGER NOT NULL,
                sip_trunk_id INTEGER NULL,
                actor_user_id INTEGER NULL,
                direction VARCHAR(20) NOT NULL DEFAULT 'outbound',
                from_number VARCHAR(64),
                to_number VARCHAR(64) NOT NULL,
                dialed_number VARCHAR(64),
                status VARCHAR(32) NOT NULL DEFAULT 'queued',
                started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                answered_at TIMESTAMP NULL,
                ended_at TIMESTAMP NULL,
                duration_sec INTEGER NULL,
                billsec INTEGER NULL,
                hangup_cause VARCHAR(32),
                hangup_cause_text VARCHAR(255),
                raw_event_json TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    db.session.commit()


def ensure_indexes():
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_call_logs_business_id ON call_logs (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_logs_sip_trunk_id ON call_logs (sip_trunk_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_logs_actor_user_id ON call_logs (actor_user_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_logs_status ON call_logs (status)",
        "CREATE INDEX IF NOT EXISTS ix_call_logs_to_number ON call_logs (to_number)",
        "CREATE INDEX IF NOT EXISTS ix_call_logs_action_id ON call_logs (action_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_logs_asterisk_uniqueid ON call_logs (asterisk_uniqueid)",
        "CREATE INDEX IF NOT EXISTS ix_call_logs_linkedid ON call_logs (linkedid)",
        "CREATE INDEX IF NOT EXISTS ix_call_logs_started_at ON call_logs (started_at)",
    ]
    for sql in statements:
        db.session.execute(text(sql))
    db.session.commit()


def ensure_fk():
    constraints = [
        (
            "fk_call_logs_business_id_businesses",
            "FOREIGN KEY (business_id) REFERENCES businesses(id)",
        ),
        (
            "fk_call_logs_sip_trunk_id_sip_trunks",
            "FOREIGN KEY (sip_trunk_id) REFERENCES sip_trunks(id)",
        ),
        (
            "fk_call_logs_actor_user_id_users",
            "FOREIGN KEY (actor_user_id) REFERENCES users(id)",
        ),
    ]
    for name, expr in constraints:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='call_logs' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE call_logs ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def ensure_constraints():
    checks = [
        ("ck_call_logs_direction", "CHECK (direction IN ('outbound','inbound'))"),
        (
            "ck_call_logs_status",
            "CHECK (status IN ('queued','ringing','answered','completed','failed','no_answer','busy','canceled'))",
        ),
    ]
    for name, expr in checks:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='call_logs' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE call_logs ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def main():
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run

    from app import create_app

    app = create_app()
    with app.app_context():
        exists = table_exists()
        columns = list_columns() if exists else set()
        print("Call logs schema check:")
        print(f"  table_exists: {exists}")
        print(f"  columns: {len(columns)}")
        if dry_run:
            print("\nDry-run mode: no changes written.")
            return 0

        apply_schema()
        ensure_fk()
        ensure_indexes()
        ensure_constraints()
        print("\nApply mode: call_logs schema updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
