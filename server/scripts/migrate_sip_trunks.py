#!/usr/bin/env python3
"""
Ensure sip_trunks table and constraints exist (idempotent).

Usage:
  python server/scripts/migrate_sip_trunks.py --dry-run
  python server/scripts/migrate_sip_trunks.py --apply
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
    p = argparse.ArgumentParser(description="Ensure sip_trunks schema")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def table_exists():
    row = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name='sip_trunks'
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
            WHERE table_name='sip_trunks'
            """
        )
    ).fetchall()
    return {r[0] for r in rows}


def apply_schema():
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS sip_trunks (
                id SERIAL PRIMARY KEY,
                business_id INTEGER NULL,
                scope VARCHAR(20) NOT NULL DEFAULT 'business',
                name VARCHAR(255) NOT NULL,
                provider_name VARCHAR(255),
                type VARCHAR(20) NOT NULL DEFAULT 'registration',
                host VARCHAR(255) NOT NULL,
                port INTEGER NOT NULL DEFAULT 5060,
                username VARCHAR(255),
                password_encrypted TEXT,
                auth_type VARCHAR(20) NOT NULL DEFAULT 'userpass',
                transport VARCHAR(20) NOT NULL DEFAULT 'udp',
                dtmf_mode VARCHAR(20) NOT NULL DEFAULT 'rfc4733',
                from_user VARCHAR(255),
                from_domain VARCHAR(255),
                context VARCHAR(255),
                status VARCHAR(20) NOT NULL DEFAULT 'inactive',
                max_concurrent_calls INTEGER NOT NULL DEFAULT 50,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                settings_json TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    db.session.commit()

    # FK is handled idempotently in ensure_fk().
    db.session.execute(
        text(
            "ALTER TABLE sip_trunks ADD COLUMN IF NOT EXISTS scope VARCHAR(20) NOT NULL DEFAULT 'business'"
        )
    )
    db.session.execute(
        text("ALTER TABLE sip_trunks ALTER COLUMN business_id DROP NOT NULL")
    )
    db.session.execute(
        text(
            "ALTER TABLE sip_trunks ADD COLUMN IF NOT EXISTS apply_status VARCHAR(20) NOT NULL DEFAULT 'pending'"
        )
    )
    db.session.execute(
        text("ALTER TABLE sip_trunks ADD COLUMN IF NOT EXISTS last_apply_error TEXT")
    )
    db.session.execute(
        text("ALTER TABLE sip_trunks ADD COLUMN IF NOT EXISTS previous_config_json TEXT")
    )
    db.session.execute(
        text("ALTER TABLE sip_trunks ADD COLUMN IF NOT EXISTS last_applied_at TIMESTAMP NULL")
    )
    db.session.execute(
        text("ALTER TABLE sip_trunks ADD COLUMN IF NOT EXISTS last_rollback_at TIMESTAMP NULL")
    )
    db.session.execute(
        text("ALTER TABLE sip_trunks ADD COLUMN IF NOT EXISTS dtmf_mode VARCHAR(20) NOT NULL DEFAULT 'rfc4733'")
    )
    db.session.commit()


def ensure_indexes_and_constraints():
    statements = [
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_sip_trunks_business_name ON sip_trunks (business_id, name)",
        "CREATE INDEX IF NOT EXISTS ix_sip_trunks_business_id ON sip_trunks (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_sip_trunks_status ON sip_trunks (status)",
        "CREATE INDEX IF NOT EXISTS ix_sip_trunks_created_at ON sip_trunks (created_at)",
    ]
    for sql in statements:
        db.session.execute(text(sql))
    db.session.commit()

    checks = [
        (
            "ck_sip_trunks_scope",
            "CHECK (scope IN ('business','global'))",
        ),
        (
            "ck_sip_trunks_scope_business_id",
            "CHECK ((scope='global' AND business_id IS NULL) OR (scope='business' AND business_id IS NOT NULL))",
        ),
        (
            "ck_sip_trunks_type",
            "CHECK (type IN ('registration','ip'))",
        ),
        (
            "ck_sip_trunks_auth_type",
            "CHECK (auth_type IN ('userpass','ip','none'))",
        ),
        (
            "ck_sip_trunks_transport",
            "CHECK (transport IN ('udp','tcp','tls'))",
        ),
        (
            "ck_sip_trunks_dtmf_mode",
            "CHECK (dtmf_mode IN ('rfc4733','inband','info','auto','auto_info','none'))",
        ),
        (
            "ck_sip_trunks_status",
            "CHECK (status IN ('active','inactive','failed','registering','rejected','unreachable'))",
        ),
        (
            "ck_sip_trunks_apply_status",
            "CHECK (apply_status IN ('pending','applying','active','failed','rolled_back'))",
        ),
    ]
    for name, expr in checks:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name='sip_trunks' AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"name": name},
        ).first()
        if not exists:
            db.session.execute(
                text(f"ALTER TABLE sip_trunks ADD CONSTRAINT {name} {expr}")
            )
            db.session.commit()


def ensure_fk():
    exists = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_name='sip_trunks'
              AND constraint_name='fk_sip_trunks_business_id_businesses'
            LIMIT 1
            """
        )
    ).first()
    if not exists:
        db.session.execute(
            text(
                """
                ALTER TABLE sip_trunks
                ADD CONSTRAINT fk_sip_trunks_business_id_businesses
                FOREIGN KEY (business_id) REFERENCES businesses(id)
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
        exists = table_exists()
        columns = list_columns() if exists else set()
        print("SIP trunks schema check:")
        print(f"  table_exists: {exists}")
        print(f"  columns: {len(columns)}")
        if dry_run:
            print("\nDry-run mode: no changes written.")
            return 0

        apply_schema()
        ensure_fk()
        ensure_indexes_and_constraints()
        print("\nApply mode: sip_trunks schema updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
