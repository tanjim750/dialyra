#!/usr/bin/env python3
"""
Ensure businesses table has required model columns (idempotent).

Usage:
  python server/scripts/migrate_business_schema.py --dry-run
  python server/scripts/migrate_business_schema.py --apply
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


REQUIRED_COLUMNS = {
    "uuid": "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS uuid VARCHAR(36)",
    "owner_user_id": "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS owner_user_id INTEGER NULL",
    "timezone": "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS timezone VARCHAR(100) NOT NULL DEFAULT 'Asia/Dhaka'",
    "country": "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS country VARCHAR(100)",
    "logo_path": "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS logo_path VARCHAR(500)",
    "settings_json": "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS settings_json TEXT",
    "allow_global_sip_fallback": "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS allow_global_sip_fallback BOOLEAN NOT NULL DEFAULT FALSE",
    "deleted_at": "ALTER TABLE businesses ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL",
}


def parse_args():
    p = argparse.ArgumentParser(description="Ensure businesses schema columns")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def list_columns():
    rows = db.session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='businesses'
            """
        )
    ).fetchall()
    return {r[0] for r in rows}


def apply_schema():
    for _, sql in REQUIRED_COLUMNS.items():
        db.session.execute(text(sql))
    db.session.commit()

    # backfill uuid if column exists and null
    db.session.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    db.session.execute(
        text(
            """
            UPDATE businesses
            SET uuid = gen_random_uuid()::text
            WHERE uuid IS NULL OR uuid = ''
            """
        )
    )
    db.session.execute(
        text("ALTER TABLE businesses ALTER COLUMN uuid SET DEFAULT gen_random_uuid()::text")
    )
    db.session.commit()

    # constraints/indexes idempotent
    db.session.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS uq_businesses_uuid ON businesses(uuid)")
    )
    db.session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_businesses_updated_at ON businesses(updated_at)")
    )
    db.session.commit()

    # owner fk idempotent
    fk = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_name='businesses'
              AND constraint_name='fk_businesses_owner_user_id_users'
            LIMIT 1
            """
        )
    ).first()
    if not fk:
        db.session.execute(
            text(
                """
                ALTER TABLE businesses
                ADD CONSTRAINT fk_businesses_owner_user_id_users
                FOREIGN KEY (owner_user_id) REFERENCES users(id)
                """
            )
        )
        db.session.commit()


def main():
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run

    from app import create_app

    app = create_app()
    with app.app_context():
        existing = list_columns()
        missing = [c for c in REQUIRED_COLUMNS.keys() if c not in existing]
        print("Businesses schema check:")
        print(f"  existing columns: {len(existing)}")
        print(f"  missing required columns: {missing}")
        if dry_run:
            print("\nDry-run mode: no changes written.")
            return 0
        apply_schema()
        print("\nApply mode: businesses schema updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
