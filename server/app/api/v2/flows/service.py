import json
from pathlib import Path

from app.extensions import db
from app.models import AudioAsset, Business, Flow, FlowEdge, FlowNode, FlowVersion, WorkspaceMembership
from app.api.v2.tts.service import generate_tts_for_runtime_business

VALID_FLOW_STATUSES = {"draft", "published", "archived", "disabled"}
VALID_NODE_TYPES = {
    "play_audio",
    "say_text",
    "tts",
    "gather_input",
    "condition",
    "goto",
    "webhook",
    "transfer_call",
    "hangup",
    "wait",
    "set_variable",
    "record_control",
}
VALID_CONDITION_TYPES = {
    "always",
    "dtmf",
    "timeout",
    "invalid_input",
    "condition_matched",
    "condition_not_matched",
    "variable_match",
    "webhook_success",
    "webhook_failed",
    "transfer_connected",
    "retry_exceeded",
    "transfer_failed",
    "error",
}


def _materialize_tts_nodes_for_publish(actor_user, business, nodes_payload, node_rows_by_id=None):
    if not isinstance(nodes_payload, list):
        return None
    for node in nodes_payload:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("node_type") or "").strip().lower()
        if node_type not in {"say_text", "tts"}:
            continue
        cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
        existing_audio_asset_id = cfg.get("audio_asset_id")
        if existing_audio_asset_id:
            try:
                asset_id = int(existing_audio_asset_id)
            except (TypeError, ValueError):
                asset_id = None
            if asset_id is not None:
                asset = AudioAsset.query.filter_by(
                    id=asset_id,
                    business_id=business.id,
                    is_deleted=False,
                ).first()
                if asset is not None and str(asset.status or "").strip().lower() != "deleted":
                    asset_path = Path(str(asset.file_path or "").strip())
                    if asset_path.exists() and asset_path.is_file():
                        continue
            # Stale/missing asset reference; regenerate and rewrite node config.
            cfg.pop("audio_asset_id", None)
            cfg.pop("tts_request_id", None)
        text = str(cfg.get("text") or "").strip()
        if not text:
            continue
        tts_payload = {
            "text": text,
            "provider": cfg.get("provider"),
            "provider_variant": cfg.get("provider_variant"),
            "language": cfg.get("language"),
            "voice": cfg.get("voice"),
            "node_config": cfg,
            "node": node,
        }
        variables = cfg.get("variables") if isinstance(cfg.get("variables"), dict) else None
        tts_result, tts_error = generate_tts_for_runtime_business(
            business,
            tts_payload,
            variables=variables,
            created_by=actor_user.id,
        )
        if tts_error:
            return f"TTS pre-generation failed for node '{node.get('node_key') or node.get('id')}': {tts_error}"
        cfg["audio_asset_id"] = tts_result.get("audio_asset_id")
        if tts_result.get("tts_request_id") is not None:
            cfg["tts_request_id"] = tts_result.get("tts_request_id")
        if tts_result.get("source"):
            cfg["tts_source"] = tts_result.get("source")
        node["config"] = cfg
        node_id = node.get("id")
        if node_rows_by_id and node_id is not None:
            try:
                normalized_node_id = int(node_id)
            except (TypeError, ValueError):
                normalized_node_id = None
            if normalized_node_id is not None and normalized_node_id in node_rows_by_id:
                row = node_rows_by_id[normalized_node_id]
                row.config_json = json.dumps(cfg)
    return None


def _append_node_error(out, code, message, node_id=None):
    item = {"code": code, "message": message}
    if node_id is not None:
        item["node_id"] = node_id
    out.append(item)


def _edge_signature(source_node_id, condition_type, condition_value):
    normalized_type = str(condition_type or "").strip().lower()
    normalized_value = (str(condition_value or "").strip() or None)
    return int(source_node_id), normalized_type, normalized_value


def _validate_edge_rule_inputs(condition_type, condition_value):
    ctype = str(condition_type or "").strip().lower()
    cval = (str(condition_value or "").strip() or None)
    if ctype == "dtmf" and cval is None:
        return "MISSING_DTMF_CONDITION_VALUE", "dtmf edge requires non-empty condition_value"
    if ctype == "variable_match" and cval is None:
        return "MISSING_VARIABLE_MATCH_CONDITION_VALUE", "variable_match edge requires condition_value format key=value"
    if ctype == "variable_match" and "=" not in cval:
        return "INVALID_VARIABLE_MATCH_CONDITION_VALUE", "variable_match condition_value must be key=value"
    return None, None


def _validate_node_config(node_type, cfg, *, node_id=None):
    errors = []
    t = str(node_type or "").strip().lower()
    config = cfg if isinstance(cfg, dict) else {}

    if t == "play_audio":
        if not config.get("audio_asset_id"):
            _append_node_error(
                errors,
                "MISSING_PLAY_AUDIO_ASSET_ID",
                "play_audio node requires config.audio_asset_id",
                node_id=node_id,
            )
        return errors

    if t in {"say_text", "tts"}:
        if not str(config.get("text") or "").strip():
            _append_node_error(
                errors,
                "MISSING_TTS_TEXT",
                "say_text/tts node requires config.text",
                node_id=node_id,
            )
        return errors

    if t == "gather_input":
        max_digits = config.get("max_digits")
        timeout_seconds = config.get("timeout_seconds")
        try:
            md = int(max_digits)
            if md <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            _append_node_error(
                errors,
                "INVALID_GATHER_MAX_DIGITS",
                "gather_input node requires positive integer config.max_digits",
                node_id=node_id,
            )
        try:
            ts = int(timeout_seconds)
            if ts <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            _append_node_error(
                errors,
                "INVALID_GATHER_TIMEOUT",
                "gather_input node requires positive integer config.timeout_seconds",
                node_id=node_id,
            )
        allowed = config.get("allowed_inputs")
        if allowed is not None and not isinstance(allowed, list):
            _append_node_error(
                errors,
                "INVALID_GATHER_ALLOWED_INPUTS",
                "gather_input config.allowed_inputs must be an array when provided",
                node_id=node_id,
            )
        return errors

    if t == "condition":
        rules = config.get("rules")
        if not isinstance(rules, list) or len(rules) == 0:
            _append_node_error(
                errors,
                "MISSING_CONDITION_RULES",
                "condition node requires non-empty config.rules array",
                node_id=node_id,
            )
        match_mode = str(config.get("match_mode") or "all").strip().lower()
        if match_mode not in {"all", "any"}:
            _append_node_error(
                errors,
                "INVALID_CONDITION_MATCH_MODE",
                "condition config.match_mode must be one of: all, any",
                node_id=node_id,
            )
        return errors

    if t == "goto":
        has_key = bool(str(config.get("target_node_key") or "").strip())
        has_id = config.get("target_node_id") is not None
        if not has_key and not has_id:
            _append_node_error(
                errors,
                "MISSING_GOTO_TARGET",
                "goto node requires config.target_node_key or config.target_node_id",
                node_id=node_id,
            )
        return errors

    if t == "webhook":
        method = str(config.get("method") or "").strip().upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            _append_node_error(
                errors,
                "INVALID_WEBHOOK_METHOD",
                "webhook config.method must be one of GET, POST, PUT, PATCH, DELETE",
                node_id=node_id,
            )
        url = str(config.get("url") or "").strip().lower()
        if not (url.startswith("http://") or url.startswith("https://")):
            _append_node_error(
                errors,
                "MISSING_WEBHOOK_URL",
                "webhook node requires absolute http/https config.url",
                node_id=node_id,
            )
        try:
            timeout = int(config.get("timeout_seconds"))
            if timeout <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            _append_node_error(
                errors,
                "INVALID_WEBHOOK_TIMEOUT",
                "webhook node requires positive integer config.timeout_seconds",
                node_id=node_id,
            )
        return errors

    if t == "transfer_call":
        transfer_type = str(config.get("transfer_type") or "").strip().lower()
        if transfer_type not in {"agent", "queue", "department", "external_number"}:
            _append_node_error(
                errors,
                "INVALID_TRANSFER_TYPE",
                "transfer_call config.transfer_type must be one of: agent, queue, department, external_number",
                node_id=node_id,
            )
            return errors
        target_present = {
            "agent": bool(config.get("agent_id") or config.get("agent")),
            "queue": bool(config.get("queue_id") or config.get("queue")),
            "department": bool(config.get("department_id") or config.get("department")),
            "external_number": bool(config.get("number") or config.get("phone_number")),
        }[transfer_type]
        if not target_present:
            _append_node_error(
                errors,
                "MISSING_TRANSFER_TARGET",
                f"transfer_call node missing target for transfer_type={transfer_type}",
                node_id=node_id,
            )
        return errors

    if t == "wait":
        try:
            duration = int(config.get("duration_seconds"))
            if duration <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            _append_node_error(
                errors,
                "INVALID_WAIT_DURATION",
                "wait node requires positive integer config.duration_seconds",
                node_id=node_id,
            )
        return errors

    if t == "set_variable":
        if not str(config.get("key") or "").strip():
            _append_node_error(
                errors,
                "MISSING_SET_VARIABLE_KEY",
                "set_variable node requires config.key",
                node_id=node_id,
            )
        return errors

    if t == "record_control":
        action = str(config.get("action") or "").strip().lower()
        if action not in {"start", "stop", "pause", "resume"}:
            _append_node_error(
                errors,
                "INVALID_RECORD_CONTROL_ACTION",
                "record_control config.action must be one of: start, stop, pause, resume",
                node_id=node_id,
            )
        return errors

    return errors


def _active_membership(actor_user_id, business_id):
    return WorkspaceMembership.query.filter_by(
        user_id=actor_user_id, business_id=business_id, status="active"
    ).first()


def _can_view_business(actor_user, business):
    if actor_user.role == "superuser":
        return True
    if actor_user.role == "stuff" and business.owner_user_id == actor_user.id:
        return True
    return _active_membership(actor_user.id, business.id) is not None


def _can_manage_business(actor_user, business):
    if actor_user.role == "superuser":
        return True
    if actor_user.role == "stuff" and business.owner_user_id == actor_user.id:
        return True
    membership = _active_membership(actor_user.id, business.id)
    return membership is not None and membership.role in {"owner", "admin"}


def _parse_business_id(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _resolve_business_for_actor(actor_user, business_id, *, manage=False):
    normalized_id = _parse_business_id(business_id)
    if normalized_id is None:
        return None, "Invalid business_id"
    business = Business.query.get(normalized_id)
    if business is None:
        return None, "Business not found"
    allowed = _can_manage_business(actor_user, business) if manage else _can_view_business(actor_user, business)
    if not allowed:
        return None, "Insufficient permission for this business"
    return business, None


def _serialize_flow(flow):
    return {
        "id": flow.id,
        "business_id": flow.business_id,
        "name": flow.name,
        "description": flow.description,
        "status": flow.status,
        "version": flow.version,
        "start_node_id": flow.start_node_id,
        "published_at": flow.published_at.isoformat() if flow.published_at else None,
        "created_by": flow.created_by,
        "created_at": flow.created_at.isoformat() if flow.created_at else None,
        "updated_at": flow.updated_at.isoformat() if flow.updated_at else None,
    }


def _serialize_node(node):
    config = {}
    if node.config_json:
        try:
            parsed = json.loads(node.config_json)
            if isinstance(parsed, dict):
                config = parsed
        except json.JSONDecodeError:
            pass
    return {
        "id": node.id,
        "flow_id": node.flow_id,
        "business_id": node.business_id,
        "node_key": node.node_key,
        "node_type": node.node_type,
        "name": node.name,
        "config": config,
        "position_x": node.position_x,
        "position_y": node.position_y,
        "is_start": bool(node.is_start),
        "created_at": node.created_at.isoformat() if node.created_at else None,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
    }


def _serialize_edge(edge):
    return {
        "id": edge.id,
        "flow_id": edge.flow_id,
        "business_id": edge.business_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "condition_type": edge.condition_type,
        "condition_value": edge.condition_value,
        "priority": edge.priority,
        "label": edge.label,
        "created_at": edge.created_at.isoformat() if edge.created_at else None,
        "updated_at": edge.updated_at.isoformat() if edge.updated_at else None,
    }


def create_flow(actor_user, payload):
    business_id = payload.get("business_id")
    business, error = _resolve_business_for_actor(actor_user, business_id, manage=True)
    if error:
        return None, error

    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip() or None
    if not name:
        return None, "Missing required field: name"

    flow = Flow(
        business_id=business.id,
        name=name,
        description=description,
        status="draft",
        version=1,
        created_by=actor_user.id,
    )
    db.session.add(flow)
    db.session.commit()
    return _serialize_flow(flow), None


def create_and_publish_flow(actor_user, payload):
    payload = payload or {}
    flow_payload = payload.get("flow") if isinstance(payload.get("flow"), dict) else payload
    nodes_payload = payload.get("nodes")
    edges_payload = payload.get("edges")
    start_node_key = str(payload.get("start_node_key") or flow_payload.get("start_node_key") or "").strip() or None

    if not isinstance(nodes_payload, list) or len(nodes_payload) == 0:
        return None, "nodes must be a non-empty array"
    if not isinstance(edges_payload, list) or len(edges_payload) == 0:
        return None, "edges must be a non-empty array"

    business_id = flow_payload.get("business_id")
    business, error = _resolve_business_for_actor(actor_user, business_id, manage=True)
    if error:
        return None, error

    name = (flow_payload.get("name") or "").strip()
    description = (flow_payload.get("description") or "").strip() or None
    if not name:
        return None, "Missing required field: flow.name"

    seen_node_keys = set()
    for idx, item in enumerate(nodes_payload):
        if not isinstance(item, dict):
            return None, f"nodes[{idx}] must be an object"
        node_key = str(item.get("node_key") or "").strip()
        node_type = str(item.get("node_type") or "").strip()
        node_name = str(item.get("name") or "").strip()
        if not node_key or not node_type or not node_name:
            return None, f"nodes[{idx}] missing required fields: node_key, node_type, name"
        if node_type not in VALID_NODE_TYPES:
            return None, f"nodes[{idx}] has invalid node_type"
        if node_key in seen_node_keys:
            return None, f"Duplicate node_key in nodes payload: {node_key}"
        seen_node_keys.add(node_key)
        cfg = item.get("config") if isinstance(item.get("config"), dict) else {}
        config_errors = _validate_node_config(node_type, cfg)
        if config_errors:
            first = config_errors[0]
            return None, f"nodes[{idx}] {first['code']}: {first['message']}"

    if start_node_key and start_node_key not in seen_node_keys:
        return None, "start_node_key must reference an existing node_key in nodes array"

    node_key_to_id = {}
    flow = None
    published_row = None
    validation = None
    try:
        flow = Flow(
            business_id=business.id,
            name=name,
            description=description,
            status="draft",
            version=1,
            created_by=actor_user.id,
        )
        db.session.add(flow)
        db.session.flush()

        for idx, item in enumerate(nodes_payload):
            node_key = str(item.get("node_key") or "").strip()
            cfg = item.get("config") if isinstance(item.get("config"), dict) else {}
            is_start = bool(item.get("is_start", False))
            if start_node_key and node_key == start_node_key:
                is_start = True
            node = FlowNode(
                flow_id=flow.id,
                business_id=flow.business_id,
                node_key=node_key,
                node_type=str(item.get("node_type")).strip(),
                name=str(item.get("name")).strip(),
                config_json=json.dumps(cfg),
                position_x=float(item["position_x"]) if item.get("position_x") is not None else None,
                position_y=float(item["position_y"]) if item.get("position_y") is not None else None,
                is_start=is_start,
            )
            db.session.add(node)
            db.session.flush()
            node_key_to_id[node_key] = node.id
            if is_start:
                flow.start_node_id = node.id

        if flow.start_node_id is None and nodes_payload:
            first_key = str(nodes_payload[0].get("node_key") or "").strip()
            if first_key:
                first_node_id = node_key_to_id.get(first_key)
                if first_node_id is not None:
                    flow.start_node_id = first_node_id
                    FlowNode.query.filter_by(id=first_node_id).update({"is_start": True})

        seen_edge_signatures = set()
        for idx, item in enumerate(edges_payload):
            if not isinstance(item, dict):
                raise ValueError(f"edges[{idx}] must be an object")
            condition_type = str(item.get("condition_type") or "always").strip()
            if condition_type not in VALID_CONDITION_TYPES:
                raise ValueError(f"edges[{idx}] has invalid condition_type")

            condition_value = (str(item.get("condition_value") or "").strip() or None)
            edge_code, edge_msg = _validate_edge_rule_inputs(condition_type, condition_value)
            if edge_code:
                raise ValueError(f"edges[{idx}] {edge_code}: {edge_msg}")

            source_node_id = _parse_business_id(item.get("source_node_id"))
            target_node_id = _parse_business_id(item.get("target_node_id"))
            source_node_key = str(item.get("source_node_key") or "").strip() or None
            target_node_key = str(item.get("target_node_key") or "").strip() or None

            if source_node_id is None and source_node_key:
                source_node_id = node_key_to_id.get(source_node_key)
            if target_node_id is None and target_node_key:
                target_node_id = node_key_to_id.get(target_node_key)
            if source_node_id is None or target_node_id is None:
                raise ValueError(
                    f"edges[{idx}] must resolve source and target via source_node_id/source_node_key and target_node_id/target_node_key"
                )

            signature = _edge_signature(source_node_id, condition_type, condition_value)
            if signature in seen_edge_signatures:
                raise ValueError(
                    "DUPLICATE_EDGE_CONDITION: identical edge condition already exists for this source node"
                )
            seen_edge_signatures.add(signature)

            db.session.add(
                FlowEdge(
                    flow_id=flow.id,
                    business_id=flow.business_id,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    condition_type=condition_type,
                    condition_value=condition_value,
                    priority=int(item.get("priority", 100)),
                    label=(str(item.get("label") or "").strip() or None),
                )
            )

        db.session.flush()
        validation, validation_error = validate_flow(actor_user, flow.id)
        if validation_error:
            raise ValueError(validation_error)
        if not validation.get("valid"):
            return None, f"Flow validation failed: {json.dumps(validation, ensure_ascii=False)}"

        nodes, edges = _load_flow_graph(flow.id)
        sorted_nodes = sorted(nodes, key=lambda x: x.id)
        nodes_payload_out = [_serialize_node(n) for n in sorted_nodes]
        node_rows_by_id = {n.id: n for n in sorted_nodes}
        materialize_error = _materialize_tts_nodes_for_publish(
            actor_user,
            business,
            nodes_payload_out,
            node_rows_by_id=node_rows_by_id,
        )
        if materialize_error:
            return None, materialize_error
        edges_payload_out = [_serialize_edge(e) for e in sorted(edges, key=lambda x: (x.priority, x.id))]

        max_version = (
            db.session.query(db.func.max(FlowVersion.version_number))
            .filter(FlowVersion.flow_id == flow.id)
            .scalar()
        )
        next_version = int(max_version or 0) + 1
        snapshot = {
            "flow": _serialize_flow(flow),
            "nodes": nodes_payload_out,
            "edges": edges_payload_out,
        }
        FlowVersion.query.filter_by(flow_id=flow.id, is_active=True).update({"is_active": False})
        published_row = FlowVersion(
            flow_id=flow.id,
            business_id=flow.business_id,
            version_number=next_version,
            snapshot_json=json.dumps(snapshot),
            published_by=actor_user.id,
            is_active=True,
        )
        db.session.add(published_row)

        flow.status = "published"
        flow.version = next_version
        from datetime import datetime

        flow.published_at = datetime.utcnow()
        db.session.commit()
        return {
            "message": "Flow created and published successfully",
            "flow": _serialize_flow(flow),
            "flow_version": _serialize_flow_version(published_row),
            "validation": validation,
            "counts": {
                "nodes": len(nodes_payload_out),
                "edges": len(edges_payload_out),
            },
        }, None
    except ValueError as exc:
        db.session.rollback()
        return None, str(exc)
    except Exception:
        db.session.rollback()
        raise


def list_flows(actor_user, business_id=None, status=None):
    query = Flow.query
    if actor_user.role == "superuser":
        if business_id is not None:
            normalized = _parse_business_id(business_id)
            if normalized is None:
                return None, "Invalid business_id"
            query = query.filter(Flow.business_id == normalized)
    else:
        allowed_business_ids = set()
        owned = Business.query.filter_by(owner_user_id=actor_user.id).all()
        allowed_business_ids.update(b.id for b in owned)
        memberships = WorkspaceMembership.query.filter_by(user_id=actor_user.id, status="active").all()
        allowed_business_ids.update(m.business_id for m in memberships)
        if not allowed_business_ids:
            return [], None
        query = query.filter(Flow.business_id.in_(sorted(allowed_business_ids)))
        if business_id is not None:
            normalized = _parse_business_id(business_id)
            if normalized is None:
                return None, "Invalid business_id"
            if normalized not in allowed_business_ids:
                return [], None
            query = query.filter(Flow.business_id == normalized)

    if status:
        normalized_status = str(status).strip().lower()
        if normalized_status not in VALID_FLOW_STATUSES:
            return None, "Invalid status filter"
        query = query.filter(Flow.status == normalized_status)

    items = query.order_by(Flow.created_at.desc()).all()
    return [_serialize_flow(item) for item in items], None


def _resolve_flow_for_actor(actor_user, flow_id, *, manage=False):
    flow = Flow.query.get(flow_id)
    if flow is None:
        return None, "Flow not found"
    business = Business.query.get(flow.business_id)
    if business is None:
        return None, "Business not found"
    allowed = _can_manage_business(actor_user, business) if manage else _can_view_business(actor_user, business)
    if not allowed:
        return None, "Insufficient permission for this business"
    return flow, None


def get_flow(actor_user, flow_id):
    flow, error = _resolve_flow_for_actor(actor_user, flow_id, manage=False)
    if error:
        return None, error
    return _serialize_flow(flow), None


def update_flow(actor_user, flow_id, payload):
    flow, error = _resolve_flow_for_actor(actor_user, flow_id, manage=True)
    if error:
        return None, error
    if flow.status != "draft":
        return None, "Only draft flow can be edited"

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            return None, "name cannot be empty"
        flow.name = name
    if "description" in payload:
        flow.description = (payload.get("description") or "").strip() or None
    if "status" in payload:
        next_status = (payload.get("status") or "").strip().lower()
        if next_status not in VALID_FLOW_STATUSES:
            return None, "Invalid flow status"
        flow.status = next_status
    db.session.commit()
    return _serialize_flow(flow), None


def delete_flow(actor_user, flow_id):
    flow, error = _resolve_flow_for_actor(actor_user, flow_id, manage=True)
    if error:
        return None, error
    # Soft delete for draft lifecycle safety.
    flow.status = "archived"
    db.session.commit()
    return {"message": "Flow archived", "id": flow.id}, None


def _load_flow_graph(flow_id):
    nodes = FlowNode.query.filter_by(flow_id=flow_id).all()
    edges = FlowEdge.query.filter_by(flow_id=flow_id).all()
    return nodes, edges


def validate_flow(actor_user, flow_id):
    flow, error = _resolve_flow_for_actor(actor_user, flow_id, manage=True)
    if error:
        return None, error

    nodes, edges = _load_flow_graph(flow.id)
    node_ids = {n.id for n in nodes}
    issues = []
    warnings = []

    if not nodes:
        issues.append({"code": "NO_NODES", "message": "Flow has no nodes"})

    start_node = None
    if flow.start_node_id is None:
        start_nodes = [n for n in nodes if n.is_start]
        if len(start_nodes) == 1:
            start_node = start_nodes[0]
        elif len(start_nodes) > 1:
            issues.append({"code": "MULTIPLE_START_NODES", "message": "Multiple start nodes found"})
        else:
            issues.append({"code": "START_NODE_MISSING", "message": "Start node is not configured"})
    else:
        start_node = next((n for n in nodes if n.id == flow.start_node_id), None)
        if start_node is None:
            issues.append({"code": "INVALID_START_NODE", "message": "start_node_id does not exist in this flow"})

    # node config schema checks
    for node in nodes:
        cfg = {}
        if node.config_json:
            try:
                parsed = json.loads(node.config_json)
                cfg = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                issues.append(
                    {
                        "code": "INVALID_NODE_CONFIG_JSON",
                        "node_id": node.id,
                        "message": "node config_json is invalid JSON",
                    }
                )
                continue
        issues.extend(_validate_node_config(node.node_type, cfg, node_id=node.id))

    # edge integrity checks
    seen_signatures = set()
    for edge in edges:
        if edge.source_node_id not in node_ids:
            issues.append(
                {
                    "code": "INVALID_EDGE_SOURCE",
                    "edge_id": edge.id,
                    "message": "edge.source_node_id not found in flow nodes",
                }
            )
        sig = _edge_signature(edge.source_node_id, edge.condition_type, edge.condition_value)
        if sig in seen_signatures:
            issues.append(
                {
                    "code": "DUPLICATE_EDGE_CONDITION",
                    "edge_id": edge.id,
                    "message": "Duplicate edge condition exists for same source_node_id + condition_type + condition_value",
                }
            )
        else:
            seen_signatures.add(sig)
        if edge.target_node_id not in node_ids:
            issues.append(
                {
                    "code": "INVALID_EDGE_TARGET",
                    "edge_id": edge.id,
                    "message": "edge.target_node_id not found in flow nodes",
                }
            )

    # Reachability: orphan detection from start node.
    if start_node and not any(i["code"] == "INVALID_START_NODE" for i in issues):
        adjacency = {}
        for edge in edges:
            adjacency.setdefault(edge.source_node_id, []).append(edge.target_node_id)
        visited = set()
        stack = [start_node.id]
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            stack.extend(adjacency.get(cur, []))
        orphan_nodes = [n.id for n in nodes if n.id not in visited]
        if orphan_nodes:
            warnings.append(
                {
                    "code": "ORPHAN_NODES",
                    "message": "Some nodes are unreachable from start node",
                    "node_ids": orphan_nodes,
                }
            )

    # At least one terminal node in graph
    terminal_nodes = [n for n in nodes if n.node_type == "hangup"]
    if not terminal_nodes:
        warnings.append(
            {
                "code": "NO_TERMINAL_NODE",
                "message": "No hangup terminal node found",
            }
        )

    # Outgoing edge coverage: non-terminal nodes should have at least one outgoing edge.
    outgoing_by_source = {}
    for edge in edges:
        outgoing_by_source.setdefault(edge.source_node_id, []).append(edge)
    for node in nodes:
        if node.node_type == "hangup":
            continue
        if node.id not in outgoing_by_source:
            issues.append(
                {
                    "code": "MISSING_OUTGOING_EDGE",
                    "node_id": node.id,
                    "message": "Non-terminal node has no outgoing edges",
                }
            )

    # gather_input safety routes
    for node in nodes:
        if node.node_type != "gather_input":
            continue
        outgoing = outgoing_by_source.get(node.id, [])
        kinds = {str(e.condition_type or "").strip().lower() for e in outgoing}
        if "timeout" not in kinds:
            issues.append(
                {
                    "code": "MISSING_GATHER_TIMEOUT_EDGE",
                    "node_id": node.id,
                    "message": "gather_input node should define a timeout edge",
                }
            )
        if "invalid_input" not in kinds:
            issues.append(
                {
                    "code": "MISSING_GATHER_INVALID_INPUT_EDGE",
                    "node_id": node.id,
                    "message": "gather_input node should define an invalid_input edge",
                }
            )

    return {
        "flow_id": flow.id,
        "status": flow.status,
        "valid": len(issues) == 0,
        "errors": issues,
        "warnings": warnings,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
    }, None


def _serialize_flow_version(row):
    return {
        "id": row.id,
        "flow_id": row.flow_id,
        "business_id": row.business_id,
        "version_number": row.version_number,
        "published_by": row.published_by,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "is_active": bool(row.is_active),
    }


def publish_flow(actor_user, flow_id):
    flow, error = _resolve_flow_for_actor(actor_user, flow_id, manage=True)
    if error:
        return None, error
    if flow.status == "archived":
        return None, "Archived flow cannot be published"

    validation, validation_error = validate_flow(actor_user, flow_id)
    if validation_error:
        return None, validation_error
    if not validation.get("valid"):
        return None, "Flow validation failed"

    nodes, edges = _load_flow_graph(flow.id)
    sorted_nodes = sorted(nodes, key=lambda x: x.id)
    nodes_payload = [_serialize_node(n) for n in sorted_nodes]
    node_rows_by_id = {n.id: n for n in sorted_nodes}
    business = Business.query.get(flow.business_id)
    if business is None:
        return None, "Business not found"
    materialize_error = _materialize_tts_nodes_for_publish(
        actor_user,
        business,
        nodes_payload,
        node_rows_by_id=node_rows_by_id,
    )
    if materialize_error:
        db.session.rollback()
        return None, materialize_error
    edges_payload = [_serialize_edge(e) for e in sorted(edges, key=lambda x: (x.priority, x.id))]

    max_version = (
        db.session.query(db.func.max(FlowVersion.version_number))
        .filter(FlowVersion.flow_id == flow.id)
        .scalar()
    )
    next_version = int(max_version or 0) + 1

    snapshot = {
        "flow": _serialize_flow(flow),
        "nodes": nodes_payload,
        "edges": edges_payload,
    }

    FlowVersion.query.filter_by(flow_id=flow.id, is_active=True).update({"is_active": False})
    version_row = FlowVersion(
        flow_id=flow.id,
        business_id=flow.business_id,
        version_number=next_version,
        snapshot_json=json.dumps(snapshot),
        published_by=actor_user.id,
        is_active=True,
    )
    db.session.add(version_row)

    flow.status = "published"
    flow.version = next_version
    from datetime import datetime

    flow.published_at = datetime.utcnow()
    db.session.commit()

    return {
        "message": "Flow published successfully",
        "flow": _serialize_flow(flow),
        "flow_version": _serialize_flow_version(version_row),
        "validation": validation,
    }, None


def duplicate_flow(actor_user, flow_id, payload=None):
    payload = payload or {}
    source_flow, error = _resolve_flow_for_actor(actor_user, flow_id, manage=True)
    if error:
        return None, error

    source_nodes = FlowNode.query.filter_by(flow_id=source_flow.id).order_by(FlowNode.id.asc()).all()
    source_edges = FlowEdge.query.filter_by(flow_id=source_flow.id).order_by(FlowEdge.id.asc()).all()

    base_name = source_flow.name or "Flow"
    requested_name = (payload.get("name") or "").strip()
    new_name = requested_name or f"{base_name} (Copy)"
    new_description = (
        (payload.get("description") or "").strip()
        or source_flow.description
        or f"Duplicate of flow #{source_flow.id}"
    )

    duplicate = Flow(
        business_id=source_flow.business_id,
        name=new_name,
        description=new_description,
        status="draft",
        version=1,
        start_node_id=None,
        published_at=None,
        created_by=actor_user.id,
    )
    db.session.add(duplicate)
    db.session.flush()

    node_id_map = {}
    for n in source_nodes:
        copy_node = FlowNode(
            flow_id=duplicate.id,
            business_id=duplicate.business_id,
            node_key=f"{n.node_key}_copy_{duplicate.id}",
            node_type=n.node_type,
            name=n.name,
            config_json=n.config_json,
            position_x=n.position_x,
            position_y=n.position_y,
            is_start=bool(n.is_start),
        )
        db.session.add(copy_node)
        db.session.flush()
        node_id_map[n.id] = copy_node.id

    for e in source_edges:
        src = node_id_map.get(e.source_node_id)
        tgt = node_id_map.get(e.target_node_id)
        if src is None or tgt is None:
            continue
        db.session.add(
            FlowEdge(
                flow_id=duplicate.id,
                business_id=duplicate.business_id,
                source_node_id=src,
                target_node_id=tgt,
                condition_type=e.condition_type,
                condition_value=e.condition_value,
                priority=e.priority,
                label=e.label,
            )
        )

    if source_flow.start_node_id in node_id_map:
        duplicate.start_node_id = node_id_map[source_flow.start_node_id]
    else:
        copied_start = (
            FlowNode.query.filter_by(flow_id=duplicate.id, is_start=True)
            .order_by(FlowNode.id.asc())
            .first()
        )
        if copied_start is not None:
            duplicate.start_node_id = copied_start.id

    db.session.commit()

    return {
        "message": "Flow duplicated successfully",
        "source_flow_id": source_flow.id,
        "flow": _serialize_flow(duplicate),
        "stats": {
            "copied_nodes": len(source_nodes),
            "copied_edges": len(source_edges),
        },
    }, None


def create_flow_node(actor_user, flow_id, payload):
    flow, error = _resolve_flow_for_actor(actor_user, flow_id, manage=True)
    if error:
        return None, error
    if flow.status != "draft":
        return None, "Only draft flow can be edited"

    node_key = (payload.get("node_key") or "").strip()
    node_type = (payload.get("node_type") or "").strip()
    name = (payload.get("name") or "").strip()
    if not node_key or not node_type or not name:
        return None, "Missing required fields: node_key, node_type, name"
    if node_type not in VALID_NODE_TYPES:
        return None, "Invalid node_type"
    exists = FlowNode.query.filter_by(flow_id=flow.id, node_key=node_key).first()
    if exists is not None:
        return None, "node_key already exists in this flow"

    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    config_errors = _validate_node_config(node_type, config)
    if config_errors:
        first = config_errors[0]
        return None, f"{first['code']}: {first['message']}"
    node = FlowNode(
        flow_id=flow.id,
        business_id=flow.business_id,
        node_key=node_key,
        node_type=node_type,
        name=name,
        config_json=json.dumps(config),
        position_x=float(payload["position_x"]) if payload.get("position_x") is not None else None,
        position_y=float(payload["position_y"]) if payload.get("position_y") is not None else None,
        is_start=bool(payload.get("is_start", False)),
    )
    if node.is_start:
        FlowNode.query.filter_by(flow_id=flow.id, is_start=True).update({"is_start": False})
    db.session.add(node)
    db.session.flush()
    if node.is_start:
        flow.start_node_id = node.id
    db.session.commit()
    return _serialize_node(node), None


def list_flow_nodes(actor_user, flow_id):
    flow, error = _resolve_flow_for_actor(actor_user, flow_id, manage=False)
    if error:
        return None, error
    items = FlowNode.query.filter_by(flow_id=flow.id).order_by(FlowNode.id.asc()).all()
    return [_serialize_node(item) for item in items], None


def _resolve_node_for_actor(actor_user, node_id, *, manage=False):
    node = FlowNode.query.get(node_id)
    if node is None:
        return None, None, "Flow node not found"
    flow, error = _resolve_flow_for_actor(actor_user, node.flow_id, manage=manage)
    if error:
        return None, None, error
    return flow, node, None


def get_flow_node(actor_user, node_id):
    _, node, error = _resolve_node_for_actor(actor_user, node_id, manage=False)
    if error:
        return None, error
    return _serialize_node(node), None


def update_flow_node(actor_user, node_id, payload):
    flow, node, error = _resolve_node_for_actor(actor_user, node_id, manage=True)
    if error:
        return None, error
    if flow.status != "draft":
        return None, "Only draft flow can be edited"

    if "node_key" in payload:
        node_key = (payload.get("node_key") or "").strip()
        if not node_key:
            return None, "node_key cannot be empty"
        exists = FlowNode.query.filter(
            FlowNode.flow_id == flow.id,
            FlowNode.node_key == node_key,
            FlowNode.id != node.id,
        ).first()
        if exists is not None:
            return None, "node_key already exists in this flow"
        node.node_key = node_key
    if "node_type" in payload:
        node_type = (payload.get("node_type") or "").strip()
        if node_type not in VALID_NODE_TYPES:
            return None, "Invalid node_type"
        existing_config = {}
        if node.config_json:
            try:
                parsed = json.loads(node.config_json)
                if isinstance(parsed, dict):
                    existing_config = parsed
            except json.JSONDecodeError:
                return None, "INVALID_NODE_CONFIG_JSON: existing node config_json is invalid JSON"
        config_errors = _validate_node_config(node_type, existing_config, node_id=node.id)
        if config_errors:
            first = config_errors[0]
            return None, f"{first['code']}: {first['message']}"
        node.node_type = node_type
    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            return None, "name cannot be empty"
        node.name = name
    if "config" in payload:
        if not isinstance(payload.get("config"), dict):
            return None, "config must be an object"
        effective_node_type = node.node_type
        next_config = payload.get("config")
        config_errors = _validate_node_config(effective_node_type, next_config, node_id=node.id)
        if config_errors:
            first = config_errors[0]
            return None, f"{first['code']}: {first['message']}"
        node.config_json = json.dumps(next_config)
    if "position_x" in payload:
        node.position_x = float(payload["position_x"]) if payload.get("position_x") is not None else None
    if "position_y" in payload:
        node.position_y = float(payload["position_y"]) if payload.get("position_y") is not None else None
    if "is_start" in payload:
        is_start = bool(payload.get("is_start"))
        if is_start:
            FlowNode.query.filter_by(flow_id=flow.id, is_start=True).update({"is_start": False})
            flow.start_node_id = node.id
        elif flow.start_node_id == node.id:
            flow.start_node_id = None
        node.is_start = is_start

    db.session.commit()
    return _serialize_node(node), None


def delete_flow_node(actor_user, node_id):
    flow, node, error = _resolve_node_for_actor(actor_user, node_id, manage=True)
    if error:
        return None, error
    if flow.status != "draft":
        return None, "Only draft flow can be edited"

    # Delete related edges first.
    FlowEdge.query.filter(
        (FlowEdge.source_node_id == node.id) | (FlowEdge.target_node_id == node.id)
    ).delete(synchronize_session=False)
    if flow.start_node_id == node.id:
        flow.start_node_id = None
    db.session.delete(node)
    db.session.commit()
    return {"message": "Flow node deleted", "id": node.id}, None


def create_flow_edge(actor_user, flow_id, payload):
    flow, error = _resolve_flow_for_actor(actor_user, flow_id, manage=True)
    if error:
        return None, error
    if flow.status != "draft":
        return None, "Only draft flow can be edited"

    source_node_id = _parse_business_id(payload.get("source_node_id"))
    target_node_id = _parse_business_id(payload.get("target_node_id"))
    condition_type = (payload.get("condition_type") or "always").strip()
    condition_value = (payload.get("condition_value") or "").strip() or None
    label = (payload.get("label") or "").strip() or None
    priority = payload.get("priority", 100)
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        return None, "priority must be an integer"

    if not source_node_id or not target_node_id:
        return None, "Missing required fields: source_node_id, target_node_id"
    if condition_type not in VALID_CONDITION_TYPES:
        return None, "Invalid condition_type"
    edge_code, edge_msg = _validate_edge_rule_inputs(condition_type, condition_value)
    if edge_code:
        return None, f"{edge_code}: {edge_msg}"

    source_node = FlowNode.query.filter_by(id=source_node_id, flow_id=flow.id).first()
    target_node = FlowNode.query.filter_by(id=target_node_id, flow_id=flow.id).first()
    if source_node is None or target_node is None:
        return None, "source_node_id or target_node_id does not belong to this flow"
    signature = _edge_signature(source_node_id, condition_type, condition_value)
    duplicate = FlowEdge.query.filter_by(
        flow_id=flow.id,
        source_node_id=signature[0],
        condition_type=signature[1],
        condition_value=signature[2],
    ).first()
    if duplicate is not None:
        return None, "DUPLICATE_EDGE_CONDITION: identical edge condition already exists for this source node"

    edge = FlowEdge(
        flow_id=flow.id,
        business_id=flow.business_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        condition_type=condition_type,
        condition_value=condition_value,
        priority=priority,
        label=label,
    )
    db.session.add(edge)
    db.session.commit()
    return _serialize_edge(edge), None


def list_flow_edges(actor_user, flow_id):
    flow, error = _resolve_flow_for_actor(actor_user, flow_id, manage=False)
    if error:
        return None, error
    items = FlowEdge.query.filter_by(flow_id=flow.id).order_by(FlowEdge.priority.asc(), FlowEdge.id.asc()).all()
    return [_serialize_edge(item) for item in items], None


def _resolve_edge_for_actor(actor_user, edge_id, *, manage=False):
    edge = FlowEdge.query.get(edge_id)
    if edge is None:
        return None, None, "Flow edge not found"
    flow, error = _resolve_flow_for_actor(actor_user, edge.flow_id, manage=manage)
    if error:
        return None, None, error
    return flow, edge, None


def update_flow_edge(actor_user, edge_id, payload):
    flow, edge, error = _resolve_edge_for_actor(actor_user, edge_id, manage=True)
    if error:
        return None, error
    if flow.status != "draft":
        return None, "Only draft flow can be edited"

    next_condition_type = edge.condition_type
    next_condition_value = edge.condition_value
    next_source_node_id = edge.source_node_id

    if "condition_type" in payload:
        condition_type = (payload.get("condition_type") or "").strip()
        if condition_type not in VALID_CONDITION_TYPES:
            return None, "Invalid condition_type"
        next_condition_type = condition_type
    if "condition_value" in payload:
        next_condition_value = (payload.get("condition_value") or "").strip() or None
    if "priority" in payload:
        try:
            edge.priority = int(payload.get("priority"))
        except (TypeError, ValueError):
            return None, "priority must be an integer"
    if "label" in payload:
        edge.label = (payload.get("label") or "").strip() or None
    if "source_node_id" in payload:
        source_node_id = _parse_business_id(payload.get("source_node_id"))
        if not source_node_id:
            return None, "Invalid source_node_id"
        source_node = FlowNode.query.filter_by(id=source_node_id, flow_id=flow.id).first()
        if source_node is None:
            return None, "source_node_id does not belong to this flow"
        next_source_node_id = source_node_id
    if "target_node_id" in payload:
        target_node_id = _parse_business_id(payload.get("target_node_id"))
        if not target_node_id:
            return None, "Invalid target_node_id"
        target_node = FlowNode.query.filter_by(id=target_node_id, flow_id=flow.id).first()
        if target_node is None:
            return None, "target_node_id does not belong to this flow"
        edge.target_node_id = target_node_id

    edge_code, edge_msg = _validate_edge_rule_inputs(next_condition_type, next_condition_value)
    if edge_code:
        return None, f"{edge_code}: {edge_msg}"

    signature = _edge_signature(next_source_node_id, next_condition_type, next_condition_value)
    duplicate = (
        FlowEdge.query.filter_by(
            flow_id=flow.id,
            source_node_id=signature[0],
            condition_type=signature[1],
            condition_value=signature[2],
        )
        .filter(FlowEdge.id != edge.id)
        .first()
    )
    if duplicate is not None:
        return None, "DUPLICATE_EDGE_CONDITION: identical edge condition already exists for this source node"

    edge.source_node_id = next_source_node_id
    edge.condition_type = next_condition_type
    edge.condition_value = next_condition_value

    db.session.commit()
    return _serialize_edge(edge), None


def delete_flow_edge(actor_user, edge_id):
    flow, edge, error = _resolve_edge_for_actor(actor_user, edge_id, manage=True)
    if error:
        return None, error
    if flow.status != "draft":
        return None, "Only draft flow can be edited"
    db.session.delete(edge)
    db.session.commit()
    return {"message": "Flow edge deleted", "id": edge.id}, None
