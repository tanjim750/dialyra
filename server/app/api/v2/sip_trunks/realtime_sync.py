from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache

from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import create_engine, text

from app.extensions import db


def _slug(value: str) -> str:
    import re

    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized or "trunk"


def _ids(trunk):
    business_part = trunk.business_id if trunk.business_id is not None else "global"
    base = f"dialyra_b{business_part}_t{trunk.id}_{_slug(trunk.name)}"
    return {
        "base": base,
        "endpoint": f"{base}_ep",
        "aor": f"{base}_aor",
        "auth": f"{base}_auth",
        "registration": f"{base}_reg",
        "identify": f"{base}_ident",
    }


def _unseal_secret(value):
    if not value:
        return None
    serializer = URLSafeSerializer(current_app.config["SECRET_KEY"], salt="sip-trunk-password")
    try:
        return serializer.loads(value)
    except BadSignature:
        return None


def _resolve_transport_id(trunk_transport):
    value = (trunk_transport or "").strip().lower()
    if value.startswith("transport-"):
        return value
    if value == "udp":
        return (current_app.config.get("PJSIP_TRANSPORT_NAME") or "transport-udp").strip()
    if value in {"tcp", "tls"}:
        return f"transport-{value}"
    return (current_app.config.get("PJSIP_TRANSPORT_NAME") or "transport-udp").strip()


@lru_cache(maxsize=4)
def _external_engine(dsn: str):
    return create_engine(dsn, future=True)


@contextmanager
def _realtime_conn(write: bool = False):
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

    # Fallback to app DB/session if no dedicated realtime DSN is configured.
    yield db.session


def _qualified_table(table_name: str) -> str:
    schema = (current_app.config.get("SIP_REALTIME_SCHEMA") or "public").strip()
    if schema and schema != "public":
        return f'{schema}.{table_name}'
    return table_name


def _table_exists(conn, table_name):
    schema = (current_app.config.get("SIP_REALTIME_SCHEMA") or "public").strip()
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema=:schema AND table_name=:table
            LIMIT 1
            """
        ),
        {"schema": schema, "table": table_name},
    ).first()
    return row is not None


def _column_exists(conn, table_name, column_name):
    schema = (current_app.config.get("SIP_REALTIME_SCHEMA") or "public").strip()
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema=:schema
              AND table_name=:table
              AND column_name=:column
            LIMIT 1
            """
        ),
        {"schema": schema, "table": table_name, "column": column_name},
    ).first()
    return row is not None


def ensure_realtime_ready():
    required = [
        "ps_endpoints",
        "ps_aors",
        "ps_auths",
        "ps_registrations",
        "ps_endpoint_id_ips",
    ]
    with _realtime_conn(write=False) as conn:
        missing = [t for t in required if not _table_exists(conn, t)]
    return missing


def upsert_trunk(trunk):
    ids = _ids(trunk)
    password = _unseal_secret(trunk.password_encrypted) or ""
    transport_id = _resolve_transport_id(trunk.transport)

    ps_aors = _qualified_table("ps_aors")
    ps_endpoints = _qualified_table("ps_endpoints")
    ps_auths = _qualified_table("ps_auths")
    ps_reg = _qualified_table("ps_registrations")
    ps_ident = _qualified_table("ps_endpoint_id_ips")

    needs_auth = (
        (trunk.type == "registration")
        or (
            trunk.type == "ip"
            and (trunk.auth_type or "").strip().lower() == "userpass"
            and (trunk.username or "").strip() != ""
            and password != ""
        )
    )

    with _realtime_conn(write=True) as conn:
        has_dtmf_mode = _column_exists(conn, "ps_endpoints", "dtmf_mode")

        conn.execute(
            text(
                f"""
                INSERT INTO {ps_aors} (id, contact)
                VALUES (:id, :contact)
                ON CONFLICT (id) DO UPDATE SET
                  contact = EXCLUDED.contact
                """
            ),
            {"id": ids["aor"], "contact": f"sip:{trunk.host}:{trunk.port}"},
        )

        endpoint_params = {
            "id": ids["endpoint"],
            "transport": transport_id,
            "aors": ids["aor"],
            "context": trunk.context or "outbound",
            "from_user": trunk.from_user or trunk.username or "",
            "from_domain": trunk.from_domain or trunk.host,
            "auth": ids["auth"] if needs_auth else "",
            "outbound_auth": ids["auth"] if needs_auth else "",
        }

        if has_dtmf_mode:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {ps_endpoints}
                    (id, transport, aors, auth, outbound_auth, context, disallow, allow, from_user, from_domain, direct_media, rtp_symmetric, force_rport, rewrite_contact, dtmf_mode)
                    VALUES
                    (:id, :transport, :aors, :auth, :outbound_auth, :context, 'all', 'ulaw,alaw', :from_user, :from_domain, 'no', 'yes', 'yes', 'yes', 'auto')
                    ON CONFLICT (id) DO UPDATE SET
                      transport=EXCLUDED.transport,
                      aors=EXCLUDED.aors,
                      auth=EXCLUDED.auth,
                      outbound_auth=EXCLUDED.outbound_auth,
                      context=EXCLUDED.context,
                      disallow=EXCLUDED.disallow,
                      allow=EXCLUDED.allow,
                      from_user=EXCLUDED.from_user,
                      from_domain=EXCLUDED.from_domain,
                      direct_media=EXCLUDED.direct_media,
                      rtp_symmetric=EXCLUDED.rtp_symmetric,
                      force_rport=EXCLUDED.force_rport,
                      rewrite_contact=EXCLUDED.rewrite_contact,
                      dtmf_mode=EXCLUDED.dtmf_mode
                    """
                ),
                endpoint_params,
            )
        else:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {ps_endpoints}
                    (id, transport, aors, auth, outbound_auth, context, disallow, allow, from_user, from_domain, direct_media, rtp_symmetric, force_rport, rewrite_contact)
                    VALUES
                    (:id, :transport, :aors, :auth, :outbound_auth, :context, 'all', 'ulaw,alaw', :from_user, :from_domain, 'no', 'yes', 'yes', 'yes')
                    ON CONFLICT (id) DO UPDATE SET
                      transport=EXCLUDED.transport,
                      aors=EXCLUDED.aors,
                      auth=EXCLUDED.auth,
                      outbound_auth=EXCLUDED.outbound_auth,
                      context=EXCLUDED.context,
                      disallow=EXCLUDED.disallow,
                      allow=EXCLUDED.allow,
                      from_user=EXCLUDED.from_user,
                      from_domain=EXCLUDED.from_domain,
                      direct_media=EXCLUDED.direct_media,
                      rtp_symmetric=EXCLUDED.rtp_symmetric,
                      force_rport=EXCLUDED.force_rport,
                      rewrite_contact=EXCLUDED.rewrite_contact
                    """
                ),
                endpoint_params,
            )

        if needs_auth:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {ps_auths} (id, auth_type, username, password)
                    VALUES (:id, 'userpass', :username, :password)
                    ON CONFLICT (id) DO UPDATE SET
                      username=EXCLUDED.username,
                      password=EXCLUDED.password
                    """
                ),
                {"id": ids["auth"], "username": trunk.username or "", "password": password},
            )

        if trunk.type == "registration":
            conn.execute(
                text(
                    f"""
                    INSERT INTO {ps_reg}
                    (id, transport, outbound_auth, server_uri, client_uri, contact_user, retry_interval, forbidden_retry_interval, expiration)
                    VALUES
                    (:id, :transport, :outbound_auth, :server_uri, :client_uri, :contact_user, 60, 300, 3600)
                    ON CONFLICT (id) DO UPDATE SET
                      transport=EXCLUDED.transport,
                      outbound_auth=EXCLUDED.outbound_auth,
                      server_uri=EXCLUDED.server_uri,
                      client_uri=EXCLUDED.client_uri,
                      contact_user=EXCLUDED.contact_user
                    """
                ),
                {
                    "id": ids["registration"],
                    "transport": transport_id,
                    "outbound_auth": ids["auth"],
                    "server_uri": f"sip:{trunk.host}:{trunk.port}",
                    "client_uri": f"sip:{trunk.username or ''}@{trunk.host}",
                    "contact_user": trunk.from_user or trunk.username or "",
                },
            )
            conn.execute(text(f"DELETE FROM {ps_ident} WHERE id=:id"), {"id": ids["identify"]})
        else:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {ps_ident} (id, endpoint, match)
                    VALUES (:id, :endpoint, :match)
                    ON CONFLICT (id) DO UPDATE SET
                      endpoint=EXCLUDED.endpoint,
                      match=EXCLUDED.match
                    """
                ),
                {"id": ids["identify"], "endpoint": ids["endpoint"], "match": trunk.host},
            )
            conn.execute(text(f"DELETE FROM {ps_reg} WHERE id=:id"), {"id": ids["registration"]})
            if not needs_auth:
                conn.execute(text(f"DELETE FROM {ps_auths} WHERE id=:id"), {"id": ids["auth"]})


def delete_trunk(trunk):
    ids = _ids(trunk)
    ps_endpoints = _qualified_table("ps_endpoints")
    ps_aors = _qualified_table("ps_aors")
    ps_auths = _qualified_table("ps_auths")
    ps_reg = _qualified_table("ps_registrations")
    ps_ident = _qualified_table("ps_endpoint_id_ips")

    with _realtime_conn(write=True) as conn:
        conn.execute(text(f"DELETE FROM {ps_reg} WHERE id=:id"), {"id": ids["registration"]})
        conn.execute(text(f"DELETE FROM {ps_auths} WHERE id=:id"), {"id": ids["auth"]})
        conn.execute(text(f"DELETE FROM {ps_ident} WHERE id=:id"), {"id": ids["identify"]})
        conn.execute(text(f"DELETE FROM {ps_endpoints} WHERE id=:id"), {"id": ids["endpoint"]})
        conn.execute(text(f"DELETE FROM {ps_aors} WHERE id=:id"), {"id": ids["aor"]})


def _row_exists(conn, table, row_id):
    qualified = _qualified_table(table)
    row = conn.execute(
        text(f"SELECT 1 FROM {qualified} WHERE id=:id LIMIT 1"),
        {"id": row_id},
    ).first()
    return row is not None


def trunk_sync_snapshot(trunk):
    ids = _ids(trunk)
    with _realtime_conn(write=False) as conn:
        rows = {
            "ps_endpoints": _row_exists(conn, "ps_endpoints", ids["endpoint"]),
            "ps_aors": _row_exists(conn, "ps_aors", ids["aor"]),
            "ps_auths": _row_exists(conn, "ps_auths", ids["auth"]),
            "ps_registrations": _row_exists(conn, "ps_registrations", ids["registration"]),
            "ps_endpoint_id_ips": _row_exists(conn, "ps_endpoint_id_ips", ids["identify"]),
        }
    return {"ids": ids, "rows": rows}


def realtime_health():
    required = [
        "ps_endpoints",
        "ps_aors",
        "ps_auths",
        "ps_registrations",
        "ps_endpoint_id_ips",
    ]
    missing = ensure_realtime_ready()
    counts = {}
    if not missing:
        with _realtime_conn(write=False) as conn:
            for table in required:
                qualified = _qualified_table(table)
                row = conn.execute(text(f"SELECT COUNT(*) FROM {qualified}")).first()
                counts[table] = int(row[0]) if row else 0
    return {
        "ready": len(missing) == 0,
        "missing_tables": missing,
        "counts": counts,
    }
