#!/usr/bin/env python3
"""
Ensure audio_assets table and constraints exist (idempotent).

Usage:
  python server/scripts/migrate_audio_assets.py --dry-run
  python server/scripts/migrate_audio_assets.py --apply
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
    p = argparse.ArgumentParser(description="Ensure audio_assets schema")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def table_exists():
    row = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name='audio_assets'
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
            WHERE table_name='audio_assets'
            """
        )
    ).fetchall()
    return {r[0] for r in rows}


def apply_schema():
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS audio_assets (
                id SERIAL PRIMARY KEY,
                uuid VARCHAR(36) NOT NULL UNIQUE,
                business_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(255),
                type VARCHAR(32) NOT NULL DEFAULT 'upload',
                category VARCHAR(64),
                file_name VARCHAR(255) NOT NULL,
                original_file_name VARCHAR(255),
                file_path VARCHAR(1024) NOT NULL,
                public_path VARCHAR(1024),
                duration DOUBLE PRECISION,
                format VARCHAR(32),
                sample_rate INTEGER,
                channels INTEGER,
                file_size BIGINT,
                source VARCHAR(64),
                language VARCHAR(32),
                voice VARCHAR(64),
                status VARCHAR(32) NOT NULL DEFAULT 'processing',
                metadata_json TEXT,
                created_by INTEGER NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                deleted_at TIMESTAMP NULL,
                deleted_by INTEGER NULL,
                delete_reason VARCHAR(255)
            )
            """
        )
    )
    db.session.commit()


def ensure_indexes():
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_audio_assets_business_id ON audio_assets (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_audio_assets_slug ON audio_assets (slug)",
        "CREATE INDEX IF NOT EXISTS ix_audio_assets_status ON audio_assets (status)",
        "CREATE INDEX IF NOT EXISTS ix_audio_assets_created_at ON audio_assets (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_audio_assets_created_by ON audio_assets (created_by)",
        "CREATE INDEX IF NOT EXISTS ix_audio_assets_deleted_by ON audio_assets (deleted_by)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_audio_assets_business_slug_not_deleted ON audio_assets (business_id, slug) WHERE slug IS NOT NULL AND is_deleted = FALSE",
    ]
    for sql in statements:
        db.session.execute(text(sql))
    db.session.commit()


def ensure_fk():
    constraints = [
        (
            "fk_audio_assets_business_id_businesses",
            "FOREIGN KEY (business_id) REFERENCES businesses(id)",
        ),
        (
            "fk_audio_assets_created_by_users",
            "FOREIGN KEY (created_by) REFERENCES users(id)",
        ),
        (
            "fk_audio_assets_deleted_by_users",
            "FOREIGN KEY (deleted_by) REFERENCES users(id)",
        ),
    ]
    for name, expr in constraints:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='audio_assets' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE audio_assets ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def ensure_constraints():
    checks = [
        (
            "ck_audio_assets_type",
            "CHECK (type IN ('upload','tts','system','generated'))",
        ),
        (
            "ck_audio_assets_status",
            "CHECK (status IN ('processing','ready','failed','deleted'))",
        ),
        (
            "ck_audio_assets_file_size_non_negative",
            "CHECK (file_size IS NULL OR file_size >= 0)",
        ),
        (
            "ck_audio_assets_duration_non_negative",
            "CHECK (duration IS NULL OR duration >= 0)",
        ),
    ]
    for name, expr in checks:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='audio_assets' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE audio_assets ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def main():
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run

    from app import create_app

    app = create_app()
    with app.app_context():
        exists = table_exists()
        columns = list_columns() if exists else set()
        print("Audio assets schema check:")
        print(f"  table_exists: {exists}")
        print(f"  columns: {len(columns)}")
        if dry_run:
            print("\nDry-run mode: no changes written.")
            return 0

        apply_schema()
        ensure_fk()
        ensure_indexes()
        ensure_constraints()
        print("\nApply mode: audio_assets schema updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
