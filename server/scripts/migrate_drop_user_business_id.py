#!/usr/bin/env python3
"""
Drop users.business_id safely (idempotent-ish).

Usage:
  python server/scripts/migrate_drop_user_business_id.py --dry-run
  python server/scripts/migrate_drop_user_business_id.py --apply
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
    p = argparse.ArgumentParser(description="Drop users.business_id")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def has_column():
    row = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name='users' AND column_name='business_id'
            LIMIT 1
            """
        )
    ).first()
    return row is not None


def apply_drop():
    db.session.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS business_id"))
    db.session.commit()


def main():
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run
    from app import create_app

    app = create_app()
    with app.app_context():
        exists = has_column()
        print("Users schema check:")
        print(f"  business_id_exists: {exists}")
        if dry_run:
            print("\nDry-run mode: no changes written.")
            return 0
        apply_drop()
        print("\nApply mode: users.business_id dropped successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

