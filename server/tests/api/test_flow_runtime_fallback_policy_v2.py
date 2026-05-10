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


def _create_flow(business_id, edges):
    flow = Flow(
        business_id=business_id,
        name="FallbackPolicyFlow",
        status="published",
        version=1,
        start_node_id=101,
    )
    db.session.add(flow)
    db.session.flush()
    snapshot = {
        "flow": {"id": flow.id, "start_node_id": 101},
        "nodes": [
            {"id": 101, "node_key": "start", "node_type": "gather_input", "name": "Start", "config": {"max_digits": 1, "timeout_seconds": 5}},
            {"id": 201, "node_key": "exact", "node_type": "hangup", "name": "Exact", "config": {"reason": "exact"}},
            {"id": 202, "node_key": "typed", "node_type": "hangup", "name": "Typed", "config": {"reason": "typed"}},
            {"id": 203, "node_key": "err", "node_type": "hangup", "name": "Error", "config": {"reason": "error"}},
            {"id": 204, "node_key": "always", "node_type": "hangup", "name": "Always", "config": {"reason": "always"}},
        ],
        "edges": edges,
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


def test_fallback_policy_exact_over_error_over_always():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-fallback-v2-1")
        flow = _create_flow(
            b1.id,
            [
                {"id": 1, "source_node_id": 101, "target_node_id": 201, "condition_type": "dtmf", "condition_value": "1", "priority": 5},
                {"id": 2, "source_node_id": 101, "target_node_id": 203, "condition_type": "error", "condition_value": None, "priority": 1},
                {"id": 3, "source_node_id": 101, "target_node_id": 204, "condition_type": "always", "condition_value": None, "priority": 1},
            ],
        )

    c = app.test_client()
    c.post("/api/v2/internal/flow/resolve-next", json={"call_session_id": "fpol-1", "flow_id": flow.id}, headers={"X-Dialyra-Access-Token": token})
    r = c.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "fpol-1", "flow_id": flow.id, "current_node_id": 101, "result_type": "dtmf", "value": "1"},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert r.status_code == 200
    assert r.get_json()["next_node_id"] == 201


def test_fallback_policy_error_over_always_when_no_exact():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-fallback-v2-2")
        flow = _create_flow(
            b1.id,
            [
                {"id": 11, "source_node_id": 101, "target_node_id": 203, "condition_type": "error", "condition_value": None, "priority": 2},
                {"id": 12, "source_node_id": 101, "target_node_id": 204, "condition_type": "always", "condition_value": None, "priority": 1},
            ],
        )

    c = app.test_client()
    c.post("/api/v2/internal/flow/resolve-next", json={"call_session_id": "fpol-2", "flow_id": flow.id}, headers={"X-Dialyra-Access-Token": token})
    r = c.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "fpol-2", "flow_id": flow.id, "current_node_id": 101, "result_type": "timeout"},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert r.status_code == 200
    assert r.get_json()["next_node_id"] == 203
