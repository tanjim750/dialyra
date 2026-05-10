#!/usr/bin/env python3
"""
Ensure tts_requests table and constraints exist (idempotent).

Usage:
  python server/scripts/migrate_tts_requests.py --dry-run
  python server/scripts/migrate_tts_requests.py --apply
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
    p = argparse.ArgumentParser(description="Ensure tts_requests schema")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def table_exists():
    row = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name='tts_requests'
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
            WHERE table_name='tts_requests'
            """
        )
    ).fetchall()
    return {r[0] for r in rows}


def apply_schema():
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS tts_requests (
                id SERIAL PRIMARY KEY,
                uuid VARCHAR(36) NOT NULL UNIQUE,
                business_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                language VARCHAR(32) NOT NULL DEFAULT 'en',
                voice VARCHAR(64),
                provider VARCHAR(64) NOT NULL DEFAULT 'mock',
                status VARCHAR(32) NOT NULL DEFAULT 'queued',
                audio_asset_id INTEGER NULL,
                duration DOUBLE PRECISION NULL,
                generation_time_ms INTEGER NULL,
                cache_key VARCHAR(128),
                error_message TEXT,
                metadata_json TEXT,
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
        "CREATE INDEX IF NOT EXISTS ix_tts_requests_business_id ON tts_requests (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_tts_requests_status ON tts_requests (status)",
        "CREATE INDEX IF NOT EXISTS ix_tts_requests_provider ON tts_requests (provider)",
        "CREATE INDEX IF NOT EXISTS ix_tts_requests_cache_key ON tts_requests (cache_key)",
        "CREATE INDEX IF NOT EXISTS ix_tts_requests_created_at ON tts_requests (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_tts_requests_audio_asset_id ON tts_requests (audio_asset_id)",
        "CREATE INDEX IF NOT EXISTS ix_tts_requests_created_by ON tts_requests (created_by)",
    ]
    for sql in statements:
        db.session.execute(text(sql))
    db.session.commit()


def ensure_fk():
    constraints = [
        (
            "fk_tts_requests_business_id_businesses",
            "FOREIGN KEY (business_id) REFERENCES businesses(id)",
        ),
        (
            "fk_tts_requests_audio_asset_id_audio_assets",
            "FOREIGN KEY (audio_asset_id) REFERENCES audio_assets(id)",
        ),
        (
            "fk_tts_requests_created_by_users",
            "FOREIGN KEY (created_by) REFERENCES users(id)",
        ),
    ]
    for name, expr in constraints:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='tts_requests' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE tts_requests ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def ensure_constraints():
    checks = [
        (
            "ck_tts_requests_status",
            "CHECK (status IN ('queued','processing','completed','failed'))",
        ),
        (
            "ck_tts_requests_generation_time_ms_non_negative",
            "CHECK (generation_time_ms IS NULL OR generation_time_ms >= 0)",
        ),
        (
            "ck_tts_requests_duration_non_negative",
            "CHECK (duration IS NULL OR duration >= 0)",
        ),
    ]
    for name, expr in checks:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='tts_requests' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE tts_requests ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def main():
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run

    from app import create_app

    app = create_app()
    with app.app_context():
        exists = table_exists()
        columns = list_columns() if exists else set()
        print("TTS requests schema check:")
        print(f"  table_exists: {exists}")
        print(f"  columns: {len(columns)}")
        if dry_run:
            print("\nDry-run mode: no changes written.")
            return 0

        apply_schema()
        ensure_fk()
        ensure_indexes()
        ensure_constraints()
        print("\nApply mode: tts_requests schema updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
