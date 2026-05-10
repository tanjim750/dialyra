import hashlib
import json
from datetime import datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import Business, BusinessAccessToken, Flow, FlowVersion


def _create_business(name="Biz", slug="biz"):
    business = Business(
        name=name,
        slug=slug,
        owner_name="Owner",
        email=f"{slug}@example.com",
        status="active",
    )
    db.session.add(business)
    db.session.flush()
    return business


def _issue_access_token(business_id, scopes, raw_token="raw-runtime-token"):
    token_model = BusinessAccessToken(
        business_id=business_id,
        name="runtime-token",
        token_prefix="dialyra_live_test",
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        scopes=json.dumps(scopes),
        is_active=True,
        expires_at=datetime.utcnow() + timedelta(days=1),
        created_by=None,
    )
    db.session.add(token_model)
    db.session.commit()
    return raw_token


def _create_flow_with_condition(business_id, condition_type, condition_value=None):
    flow = Flow(
        business_id=business_id,
        name=f"Edge {condition_type}",
        status="published",
        version=1,
        start_node_id=101,
    )
    db.session.add(flow)
    db.session.flush()
    snapshot = {
        "flow": {"id": flow.id, "start_node_id": 101},
        "nodes": [
            {
                "id": 101,
                "node_key": "start",
                "node_type": "gather_input",
                "name": "Start",
                "config": {"max_digits": 1, "timeout_seconds": 5, "allowed_inputs": ["1", "2"]},
            },
            {
                "id": 102,
                "node_key": "end",
                "node_type": "hangup",
                "name": "End",
                "config": {"reason": "ok"},
            },
        ],
        "edges": [
            {
                "id": 501,
                "source_node_id": 101,
                "target_node_id": 102,
                "condition_type": condition_type,
                "condition_value": condition_value,
                "priority": 1,
            }
        ],
    }
    version = FlowVersion(
        flow_id=flow.id,
        business_id=business_id,
        version_number=1,
        snapshot_json=json.dumps(snapshot),
        is_active=True,
    )
    db.session.add(version)
    db.session.commit()
    return flow


def _start_session(client, token, flow_id, call_session_id):
    return client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": call_session_id, "flow_id": flow_id},
        headers={"X-Dialyra-Access-Token": token},
    )


def test_runtime_edge_condition_matrix():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-edge-matrix")

        flows = {
            "dtmf": _create_flow_with_condition(b1.id, "dtmf", "1"),
            "timeout": _create_flow_with_condition(b1.id, "timeout"),
            "invalid_input": _create_flow_with_condition(b1.id, "invalid_input"),
            "webhook_success": _create_flow_with_condition(b1.id, "webhook_success"),
            "webhook_failed": _create_flow_with_condition(b1.id, "webhook_failed"),
            "retry_exceeded": _create_flow_with_condition(b1.id, "retry_exceeded"),
            "transfer_failed": _create_flow_with_condition(b1.id, "transfer_failed"),
            "error": _create_flow_with_condition(b1.id, "error"),
            "condition_matched": _create_flow_with_condition(b1.id, "condition_matched"),
            "condition_not_matched": _create_flow_with_condition(b1.id, "condition_not_matched"),
            "transfer_connected": _create_flow_with_condition(b1.id, "transfer_connected"),
            "variable_match": _create_flow_with_condition(b1.id, "variable_match", "language=en"),
        }

    client = app.test_client()

    for idx, (result_type, flow) in enumerate(flows.items(), start=1):
        call_id = f"call-edge-{idx}"
        first = _start_session(client, token, flow.id, call_id)
        assert first.status_code == 200

        payload = {
            "call_session_id": call_id,
            "flow_id": flow.id,
            "current_node_id": 101,
            "result_type": result_type,
        }
        if result_type == "dtmf":
            payload["value"] = "1"
        if result_type == "variable_match":
            payload["variables"] = {"language": "en"}
        if result_type in {"condition_matched", "condition_not_matched"}:
            payload["value"] = "1" if result_type == "condition_matched" else "0"

        second = client.post(
            "/api/v2/internal/flow/resolve-next",
            json=payload,
            headers={"X-Dialyra-Access-Token": token},
        )
        assert second.status_code == 200, (result_type, second.get_json())
        body = second.get_json()
        assert body["next_node_id"] == 102, (result_type, body)
        assert body["runtime_action"]["type"] == "hangup"
