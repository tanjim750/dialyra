#!/usr/bin/env python3
"""
Ensure call_events table and indexes exist (idempotent).
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
    p = argparse.ArgumentParser(description="Ensure call_events schema")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def table_exists():
    row = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name='call_events'
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
            WHERE table_name='call_events'
            """
        )
    ).fetchall()
    return {r[0] for r in rows}


def apply_schema():
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS call_events (
                id SERIAL PRIMARY KEY,
                business_id INTEGER NULL,
                call_log_id INTEGER NULL,
                call_session_id INTEGER NULL,
                event_name VARCHAR(64) NOT NULL,
                event_fingerprint VARCHAR(64) NOT NULL UNIQUE,
                event_payload_json TEXT NOT NULL,
                action_id VARCHAR(64) NULL,
                uniqueid VARCHAR(64) NULL,
                linkedid VARCHAR(64) NULL,
                processing_status VARCHAR(20) NOT NULL DEFAULT 'pending',
                process_attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NULL,
                processed_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    db.session.commit()


def ensure_fk():
    constraints = [
        ("fk_call_events_business_id_businesses", "FOREIGN KEY (business_id) REFERENCES businesses(id)"),
        ("fk_call_events_call_log_id_call_logs", "FOREIGN KEY (call_log_id) REFERENCES call_logs(id)"),
        (
            "fk_call_events_call_session_id_call_sessions",
            "FOREIGN KEY (call_session_id) REFERENCES call_sessions(id)",
        ),
    ]
    for name, expr in constraints:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='call_events' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE call_events ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def ensure_indexes():
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_call_events_business_id ON call_events (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_events_call_log_id ON call_events (call_log_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_events_call_session_id ON call_events (call_session_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_events_event_name ON call_events (event_name)",
        "CREATE INDEX IF NOT EXISTS ix_call_events_action_id ON call_events (action_id)",
        "CREATE INDEX IF NOT EXISTS ix_call_events_uniqueid ON call_events (uniqueid)",
        "CREATE INDEX IF NOT EXISTS ix_call_events_linkedid ON call_events (linkedid)",
        "CREATE INDEX IF NOT EXISTS ix_call_events_processing_status ON call_events (processing_status)",
        "CREATE INDEX IF NOT EXISTS ix_call_events_created_at ON call_events (created_at)",
    ]
    for sql in statements:
        db.session.execute(text(sql))
    db.session.commit()


def ensure_constraints():
    checks = [
        (
            "ck_call_events_processing_status",
            "CHECK (processing_status IN ('pending','processed','failed'))",
        )
    ]
    for name, expr in checks:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='call_events' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE call_events ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def main():
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run

    from app import create_app

    app = create_app()
    with app.app_context():
        exists = table_exists()
        columns = list_columns() if exists else set()
        print("Call events schema check:")
        print(f"  table_exists: {exists}")
        print(f"  columns: {len(columns)}")
        if dry_run:
            print("\nDry-run mode: no changes written.")
            return 0
        apply_schema()
        ensure_fk()
        ensure_indexes()
        ensure_constraints()
        print("\nApply mode: call_events schema updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
