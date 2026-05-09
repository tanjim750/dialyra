#!/usr/bin/env python3
"""
Ensure businesses.owner_user_id exists (idempotent).

Usage:
  python server/scripts/migrate_business_owner_user_id.py --dry-run
  python server/scripts/migrate_business_owner_user_id.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

# Ensure `server/` is on sys.path so `app` package is importable.
SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_DIR = SCRIPT_DIR.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app.extensions import db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure businesses.owner_user_id exists")
    parser.add_argument("--apply", action="store_true", help="Apply changes")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    return parser.parse_args()


def column_exists() -> bool:
    sql = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'businesses'
          AND column_name = 'owner_user_id'
        LIMIT 1
        """
    )
    row = db.session.execute(sql).first()
    return row is not None


def fk_exists() -> bool:
    sql = text(
        """
        SELECT 1
        FROM information_schema.table_constraints tc
        WHERE tc.table_name = 'businesses'
          AND tc.constraint_type = 'FOREIGN KEY'
          AND tc.constraint_name = 'fk_businesses_owner_user_id_users'
        LIMIT 1
        """
    )
    row = db.session.execute(sql).first()
    return row is not None


def apply_changes() -> None:
    db.session.execute(
        text("ALTER TABLE businesses ADD COLUMN IF NOT EXISTS owner_user_id INTEGER NULL")
    )
    db.session.commit()

    if not fk_exists():
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


def main() -> int:
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run

    from app import create_app

    app = create_app()
    with app.app_context():
        exists = column_exists()
        fk = fk_exists() if exists else False

        print("Schema check: businesses.owner_user_id")
        print(f"  column_exists: {exists}")
        print(f"  fk_exists: {fk}")

        if dry_run:
            print("\nDry-run mode: no changes written.")
            if not exists:
                print("Would add column: businesses.owner_user_id")
                print("Would add FK: fk_businesses_owner_user_id_users")
            elif exists and not fk:
                print("Would add FK: fk_businesses_owner_user_id_users")
            return 0

        apply_changes()
        print("\nApply mode: schema updated successfully.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
