#!/usr/bin/env python3
"""
Ensure Flow Engine tables and constraints exist (idempotent).

Usage:
  python server/scripts/migrate_flow_engine.py --dry-run
  python server/scripts/migrate_flow_engine.py --apply
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

FLOW_TABLES = {
    "flows",
    "flow_versions",
    "flow_nodes",
    "flow_edges",
    "flow_runtime_sessions",
    "flow_runtime_events",
}


def parse_args():
    p = argparse.ArgumentParser(description="Ensure flow engine schema")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def existing_tables():
    rows = db.session.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
              AND table_name IN (
                'flows','flow_versions','flow_nodes','flow_edges',
                'flow_runtime_sessions','flow_runtime_events'
              )
            """
        )
    ).fetchall()
    return {r[0] for r in rows}


def apply_schema():
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS flows (
                id SERIAL PRIMARY KEY,
                business_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                version INTEGER NOT NULL DEFAULT 1,
                start_node_id INTEGER NULL,
                published_at TIMESTAMP NULL,
                created_by INTEGER NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS flow_versions (
                id SERIAL PRIMARY KEY,
                flow_id INTEGER NOT NULL,
                business_id INTEGER NOT NULL,
                version_number INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL,
                published_by INTEGER NULL,
                published_at TIMESTAMP NOT NULL DEFAULT NOW(),
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS flow_nodes (
                id SERIAL PRIMARY KEY,
                flow_id INTEGER NOT NULL,
                business_id INTEGER NOT NULL,
                node_key VARCHAR(100) NOT NULL,
                node_type VARCHAR(50) NOT NULL,
                name VARCHAR(255) NOT NULL,
                config_json TEXT NULL,
                position_x DOUBLE PRECISION NULL,
                position_y DOUBLE PRECISION NULL,
                is_start BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS flow_edges (
                id SERIAL PRIMARY KEY,
                flow_id INTEGER NOT NULL,
                business_id INTEGER NOT NULL,
                source_node_id INTEGER NOT NULL,
                target_node_id INTEGER NOT NULL,
                condition_type VARCHAR(50) NOT NULL DEFAULT 'always',
                condition_value VARCHAR(255) NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                label VARCHAR(255) NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS flow_runtime_sessions (
                id SERIAL PRIMARY KEY,
                business_id INTEGER NOT NULL,
                call_session_id VARCHAR(128) NOT NULL,
                flow_id INTEGER NOT NULL,
                flow_version_id INTEGER NOT NULL,
                current_node_id INTEGER NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'running',
                variables_json TEXT NULL,
                started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                ended_at TIMESTAMP NULL
            )
            """
        )
    )
    db.session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS flow_runtime_events (
                id SERIAL PRIMARY KEY,
                business_id INTEGER NOT NULL,
                call_session_id VARCHAR(128) NOT NULL,
                flow_runtime_session_id INTEGER NULL,
                node_id INTEGER NULL,
                event_type VARCHAR(64) NOT NULL,
                event_data TEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    db.session.commit()


def ensure_fk():
    constraints = [
        ("flows", "fk_flows_business_id_businesses", "FOREIGN KEY (business_id) REFERENCES businesses(id)"),
        ("flows", "fk_flows_created_by_users", "FOREIGN KEY (created_by) REFERENCES users(id)"),
        ("flow_versions", "fk_flow_versions_flow_id_flows", "FOREIGN KEY (flow_id) REFERENCES flows(id)"),
        ("flow_versions", "fk_flow_versions_business_id_businesses", "FOREIGN KEY (business_id) REFERENCES businesses(id)"),
        ("flow_versions", "fk_flow_versions_published_by_users", "FOREIGN KEY (published_by) REFERENCES users(id)"),
        ("flow_nodes", "fk_flow_nodes_flow_id_flows", "FOREIGN KEY (flow_id) REFERENCES flows(id)"),
        ("flow_nodes", "fk_flow_nodes_business_id_businesses", "FOREIGN KEY (business_id) REFERENCES businesses(id)"),
        ("flow_edges", "fk_flow_edges_flow_id_flows", "FOREIGN KEY (flow_id) REFERENCES flows(id)"),
        ("flow_edges", "fk_flow_edges_business_id_businesses", "FOREIGN KEY (business_id) REFERENCES businesses(id)"),
        ("flow_edges", "fk_flow_edges_source_node_id_flow_nodes", "FOREIGN KEY (source_node_id) REFERENCES flow_nodes(id)"),
        ("flow_edges", "fk_flow_edges_target_node_id_flow_nodes", "FOREIGN KEY (target_node_id) REFERENCES flow_nodes(id)"),
        (
            "flow_runtime_sessions",
            "fk_flow_runtime_sessions_business_id_businesses",
            "FOREIGN KEY (business_id) REFERENCES businesses(id)",
        ),
        ("flow_runtime_sessions", "fk_flow_runtime_sessions_flow_id_flows", "FOREIGN KEY (flow_id) REFERENCES flows(id)"),
        (
            "flow_runtime_sessions",
            "fk_flow_runtime_sessions_flow_version_id_flow_versions",
            "FOREIGN KEY (flow_version_id) REFERENCES flow_versions(id)",
        ),
        (
            "flow_runtime_sessions",
            "fk_flow_runtime_sessions_current_node_id_flow_nodes",
            "FOREIGN KEY (current_node_id) REFERENCES flow_nodes(id)",
        ),
        (
            "flow_runtime_events",
            "fk_flow_runtime_events_business_id_businesses",
            "FOREIGN KEY (business_id) REFERENCES businesses(id)",
        ),
        (
            "flow_runtime_events",
            "fk_flow_runtime_events_session_id_flow_runtime_sessions",
            "FOREIGN KEY (flow_runtime_session_id) REFERENCES flow_runtime_sessions(id)",
        ),
        ("flow_runtime_events", "fk_flow_runtime_events_node_id_flow_nodes", "FOREIGN KEY (node_id) REFERENCES flow_nodes(id)"),
    ]
    for table_name, name, expr in constraints:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name=:table_name AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE {table_name} ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def ensure_indexes():
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_flows_business_id ON flows (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_flows_status ON flows (status)",
        "CREATE INDEX IF NOT EXISTS ix_flows_created_at ON flows (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_flow_versions_flow_id ON flow_versions (flow_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_versions_business_id ON flow_versions (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_versions_is_active ON flow_versions (is_active)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_versions_flow_version ON flow_versions (flow_id, version_number)",
        "CREATE INDEX IF NOT EXISTS ix_flow_nodes_flow_id ON flow_nodes (flow_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_nodes_business_id ON flow_nodes (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_nodes_node_type ON flow_nodes (node_type)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_nodes_flow_node_key ON flow_nodes (flow_id, node_key)",
        "CREATE INDEX IF NOT EXISTS ix_flow_edges_flow_id ON flow_edges (flow_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_edges_business_id ON flow_edges (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_edges_source_node_id ON flow_edges (source_node_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_edges_target_node_id ON flow_edges (target_node_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_runtime_sessions_business_id ON flow_runtime_sessions (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_runtime_sessions_call_session_id ON flow_runtime_sessions (call_session_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_runtime_sessions_status ON flow_runtime_sessions (status)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_flow_runtime_sessions_call ON flow_runtime_sessions (business_id, call_session_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_runtime_events_business_id ON flow_runtime_events (business_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_runtime_events_call_session_id ON flow_runtime_events (call_session_id)",
        "CREATE INDEX IF NOT EXISTS ix_flow_runtime_events_event_type ON flow_runtime_events (event_type)",
    ]
    for sql in statements:
        db.session.execute(text(sql))
    db.session.commit()


def ensure_constraints():
    checks = [
        ("flows", "ck_flows_status", "CHECK (status IN ('draft','published','archived','disabled'))"),
        ("flows", "ck_flows_version_positive", "CHECK (version >= 1)"),
        (
            "flow_nodes",
            "ck_flow_nodes_node_type",
            "CHECK (node_type IN ('play_audio','say_text','tts','gather_input','condition','webhook','transfer_call','hangup','wait','set_variable','record_control'))",
        ),
        (
            "flow_edges",
            "ck_flow_edges_condition_type",
            "CHECK (condition_type IN ('always','dtmf','timeout','invalid_input','variable_match','webhook_success','webhook_failed','retry_exceeded','transfer_failed','error'))",
        ),
        ("flow_runtime_sessions", "ck_flow_runtime_sessions_status", "CHECK (status IN ('running','completed','failed','transferred','hangup'))"),
    ]
    for table_name, name, expr in checks:
        exists = db.session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_name=:table_name AND constraint_name=:name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "name": name},
        ).first()
        if not exists:
            db.session.execute(text(f"ALTER TABLE {table_name} ADD CONSTRAINT {name} {expr}"))
            db.session.commit()


def main():
    args = parse_args()
    dry_run = (not args.apply) or args.dry_run

    from app import create_app

    app = create_app()
    with app.app_context():
        existing = existing_tables()
        missing = sorted(FLOW_TABLES - existing)
        print("Flow engine schema check:")
        print(f"  existing_tables: {sorted(existing)}")
        print(f"  missing_tables: {missing}")
        if dry_run:
            print("\nDry-run mode: no changes written.")
            return 0

        apply_schema()
        ensure_fk()
        ensure_indexes()
        ensure_constraints()
        print("\nApply mode: flow engine schema updated successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
