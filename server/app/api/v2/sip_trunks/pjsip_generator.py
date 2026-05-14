import re
from pathlib import Path

HEADER = "; ===== Dialyra managed PJSIP config ====="
FOOTER = "; ===== End Dialyra managed PJSIP config ====="


def _slug(value):
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized or "trunk"


def trunk_prefix(trunk):
    return f"dialyra-b{trunk.business_id}-t{trunk.id}-{_slug(trunk.name)}"


def render_trunk_block(trunk, transport_name="transport-udp"):
    prefix = trunk_prefix(trunk)
    endpoint = f"{prefix}-endpoint"
    aor = f"{prefix}-aor"
    auth = f"{prefix}-auth"
    identify = f"{prefix}-identify"
    registration = f"{prefix}-registration"

    lines = [f"; SIP trunk #{trunk.id} ({trunk.name})", ""]
    if trunk.type == "registration":
        lines.extend(
            [
                f"[{auth}]",
                "type=auth",
                f"auth_type={trunk.auth_type or 'userpass'}",
                f"username={trunk.username or ''}",
                f"password={trunk.password_encrypted or ''}",
                "",
                f"[{aor}]",
                "type=aor",
                f"contact=sip:{trunk.host}:{trunk.port}",
                "",
                f"[{endpoint}]",
                "type=endpoint",
                f"transport={transport_name}",
                f"context={trunk.context or 'outbound'}",
                "disallow=all",
                "allow=ulaw,alaw",
                f"outbound_auth={auth}",
                f"aors={aor}",
                f"from_user={trunk.from_user or trunk.username or ''}",
                f"from_domain={trunk.from_domain or trunk.host}",
                "dtmf_mode=auto",
                "direct_media=no",
                "rtp_symmetric=yes",
                "force_rport=yes",
                "rewrite_contact=yes",
                "",
                f"[{registration}]",
                "type=registration",
                f"transport={transport_name}",
                f"outbound_auth={auth}",
                f"server_uri=sip:{trunk.host}:{trunk.port}",
                f"client_uri=sip:{trunk.username or ''}@{trunk.host}",
                f"contact_user={trunk.from_user or trunk.username or ''}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"[{aor}]",
                "type=aor",
                f"contact=sip:{trunk.host}:{trunk.port}",
                "",
                f"[{endpoint}]",
                "type=endpoint",
                f"transport={transport_name}",
                f"context={trunk.context or 'outbound'}",
                "disallow=all",
                "allow=ulaw,alaw",
                f"aors={aor}",
                f"from_domain={trunk.from_domain or trunk.host}",
                "dtmf_mode=auto",
                "direct_media=no",
                "rtp_symmetric=yes",
                "force_rport=yes",
                "rewrite_contact=yes",
                "",
                f"[{identify}]",
                "type=identify",
                f"endpoint={endpoint}",
                f"match={trunk.host}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_full_config(trunks, transport_name="transport-udp"):
    parts = [
        f"[{transport_name}]",
        "type=transport",
        "protocol=udp",
        "bind=0.0.0.0:5060",
        "",
        HEADER,
        "",
    ]
    for trunk in trunks:
        parts.append(render_trunk_block(trunk, transport_name=transport_name))
    parts.extend([FOOTER, ""])
    return "\n".join(parts)


def write_config(config_path, trunks, transport_name="transport-udp"):
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_content = render_full_config(trunks, transport_name=transport_name)
    path.write_text(new_content, encoding="utf-8")
    return str(path)
