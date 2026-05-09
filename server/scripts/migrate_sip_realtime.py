#!/usr/bin/env python3
"""
Ensure Asterisk PJSIP realtime tables exist (idempotent).

Usage:
  flask migrate sip-realtime --dry-run
  flask migrate sip-realtime --apply
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache

from flask import current_app
from sqlalchemy import create_engine, text

from app.extensions import db

REQUIRED_TABLES = [
    "ps_endpoints",
    "ps_aors",
    "ps_auths",
    "ps_registrations",
    "ps_endpoint_id_ips",
]


@lru_cache(maxsize=4)
def _external_engine(dsn: str):
    return create_engine(dsn, future=True)


@contextmanager
def _conn(write: bool = False):
    dsn = (current_app.config.get("SIP_REALTIME_DSN") or "").strip()
    if dsn:
        engine = _external_engine(dsn)
        if write:
            with engine.begin() as conn:
                yield conn
        else:
            with engine.connect() as conn:
                yield conn
        return
    yield db.session


def _schema() -> str:
    return (current_app.config.get("SIP_REALTIME_SCHEMA") or "public").strip()


def _qualified(table: str) -> str:
    schema = _schema()
    if schema and schema != "public":
        return f"{schema}.{table}"
    return table


def table_exists(table_name: str) -> bool:
    with _conn(write=False) as conn:
        row = conn.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema=:schema AND table_name=:table
                LIMIT 1
                """
            ),
            {"schema": _schema(), "table": table_name},
        ).first()
    return row is not None


def missing_tables():
    return [t for t in REQUIRED_TABLES if not table_exists(t)]


def create_schema_if_needed():
    schema = _schema()
    if schema and schema != "public":
        with _conn(write=True) as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))


def apply_schema():
    create_schema_if_needed()
    ps_aors = _qualified("ps_aors")
    ps_auths = _qualified("ps_auths")
    ps_endpoints = _qualified("ps_endpoints")
    ps_reg = _qualified("ps_registrations")
    ps_ident = _qualified("ps_endpoint_id_ips")

    with _conn(write=True) as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {ps_aors} (
                  id VARCHAR(40) PRIMARY KEY,
                  contact VARCHAR(255)
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {ps_auths} (
                  id VARCHAR(40) PRIMARY KEY,
                  auth_type VARCHAR(20),
                  username VARCHAR(80),
                  password VARCHAR(80)
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {ps_endpoints} (
                  id VARCHAR(40) PRIMARY KEY,
                  transport VARCHAR(40),
                  aors VARCHAR(200),
                  auth VARCHAR(40),
                  outbound_auth VARCHAR(40),
                  context VARCHAR(40),
                  disallow VARCHAR(200),
                  allow VARCHAR(200),
                  from_user VARCHAR(80),
                  from_domain VARCHAR(80),
                  direct_media VARCHAR(10),
                  rtp_symmetric VARCHAR(10),
                  force_rport VARCHAR(10),
                  rewrite_contact VARCHAR(10)
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                ALTER TABLE {ps_endpoints}
                ADD COLUMN IF NOT EXISTS mailboxes VARCHAR(255) DEFAULT ''
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {ps_reg} (
                  id VARCHAR(40) PRIMARY KEY,
                  transport VARCHAR(40),
                  outbound_auth VARCHAR(40),
                  server_uri VARCHAR(255),
                  client_uri VARCHAR(255),
                  contact_user VARCHAR(80),
                  retry_interval INTEGER,
                  forbidden_retry_interval INTEGER,
                  expiration INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {ps_ident} (
                  id VARCHAR(40) PRIMARY KEY,
                  endpoint VARCHAR(40),
                  match VARCHAR(80)
                )
                """
            )
        )


def table_counts():
    counts = {}
    with _conn(write=False) as conn:
        for table in REQUIRED_TABLES:
            if not table_exists(table):
                counts[table] = None
                continue
            row = conn.execute(
                text(f"SELECT COUNT(*) FROM {_qualified(table)}")
            ).first()
            counts[table] = int(row[0]) if row else 0
    return counts
