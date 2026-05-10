import hashlib
import json
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from app.extensions import db
from app.models import Business, BusinessAccessToken, Flow, FlowRuntimeSession, FlowVersion


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


def _create_published_flow(business_id):
    flow = Flow(
        business_id=business_id,
        name="Runtime Flow",
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
                "node_key": "welcome",
                "node_type": "gather_input",
                "name": "Welcome Menu",
                "config": {"max_digits": 1, "timeout_seconds": 5, "allowed_inputs": ["1", "2"]},
            },
            {
                "id": 102,
                "node_key": "done",
                "node_type": "hangup",
                "name": "Done",
                "config": {"reason": "ok"},
            },
        ],
        "edges": [
            {
                "id": 501,
                "source_node_id": 101,
                "target_node_id": 102,
                "condition_type": "dtmf",
                "condition_value": "1",
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
    return flow, version


def test_runtime_resolve_observability_and_transition_matrix():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow, _ = _create_published_flow(b1.id)
        token = _issue_access_token(
            b1.id, ["flow:resolve", "fastagi:runtime", "events:write"], raw_token="tok-matrix"
        )

    client = app.test_client()
    headers = {"X-Dialyra-Access-Token": token}

    first = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-matrix-1", "flow_id": flow.id},
        headers=headers,
    )
    assert first.status_code == 200
    body1 = first.get_json()
    assert body1["runtime_action"]["type"] == "collect_dtmf"
    assert body1["created_session"] is True
    assert body1["observability"]["trace_id"]
    assert body1["observability"]["event_type"] == "node.entered"

    second = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={
            "call_session_id": "call-matrix-1",
            "flow_id": flow.id,
            "current_node_id": 101,
            "result_type": "dtmf",
            "value": "1",
        },
        headers=headers,
    )
    assert second.status_code == 200
    body2 = second.get_json()
    assert body2["next_node_id"] == 102
    assert body2["runtime_action"]["type"] == "hangup"
    assert body2["observability"]["event_type"] == "edge.selected"


def test_runtime_resolve_fallback_mode_returns_safe_action():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow, _ = _create_published_flow(b1.id)
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-fallback")

    client = app.test_client()
    headers = {"X-Dialyra-Access-Token": token}

    # Create session first
    seed = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-fallback-1", "flow_id": flow.id},
        headers=headers,
    )
    assert seed.status_code == 200

    # Send unmatched DTMF and request fallback
    resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={
            "call_session_id": "call-fallback-1",
            "flow_id": flow.id,
            "current_node_id": 101,
            "result_type": "dtmf",
            "value": "9",
            "use_fallback": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "accepted_with_fallback"
    assert body["fallback_used"] is True
    assert body["runtime_action"]["type"] == "hangup"
    assert body["observability"]["event_type"] == "fallback"


def test_runtime_event_endpoints_scope_and_observability_payload():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow, _ = _create_published_flow(b1.id)
        full_token = _issue_access_token(
            b1.id, ["flow:resolve", "fastagi:runtime", "events:write"], raw_token="tok-events-full"
        )
        limited_token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-events-limited")

    client = app.test_client()

    # seed runtime session
    seed = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-events-1", "flow_id": flow.id},
        headers={"X-Dialyra-Access-Token": full_token},
    )
    assert seed.status_code == 200

    # missing scope on node-completed
    denied = client.post(
        "/api/v2/internal/calls/call-events-1/node-completed",
        json={"node_id": 101},
        headers={"X-Dialyra-Access-Token": limited_token},
    )
    assert denied.status_code == 403

    completed = client.post(
        "/api/v2/internal/calls/call-events-1/node-completed",
        json={"node_id": 101, "trace_id": "trace-node-complete"},
        headers={"X-Dialyra-Access-Token": full_token},
    )
    assert completed.status_code == 200
    completed_body = completed.get_json()
    assert completed_body["event"] == "node.completed"
    assert completed_body["event_id"] is not None
    assert completed_body["created_at"] is not None
    assert completed_body["trace_id"] == "trace-node-complete"

    runtime_error = client.post(
        "/api/v2/internal/calls/call-events-1/runtime-error",
        json={"message": "playback missing"},
        headers={"X-Dialyra-Access-Token": full_token},
    )
    assert runtime_error.status_code == 200
    err_body = runtime_error.get_json()
    assert err_body["event"] == "runtime.error"
    assert err_body["trace_id"]

    with app.app_context():
        session = FlowRuntimeSession.query.filter_by(call_session_id="call-events-1").first()
        assert session is not None


def test_runtime_canary_skip_returns_legacy_fallback_action():
    app = create_app("testing")
    app.config["FLOW_RUNTIME_CANARY_ENABLED"] = True
    app.config["FLOW_RUNTIME_CANARY_PERCENT"] = 0
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow, _ = _create_published_flow(b1.id)
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-canary-skip")

    client = app.test_client()
    resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-canary-1", "flow_id": flow.id},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "canary_skipped"
    assert body["runtime_action"]["type"] == "legacy_fallback"
    assert body["observability"]["event_type"] == "canary.skip"
    assert body["observability"]["canary"]["enabled"] is True
    assert body["observability"]["canary"]["allowed"] is False


def test_runtime_canary_force_bypass_allows_resolution():
    app = create_app("testing")
    app.config["FLOW_RUNTIME_CANARY_ENABLED"] = True
    app.config["FLOW_RUNTIME_CANARY_PERCENT"] = 0
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow, _ = _create_published_flow(b1.id)
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-canary-force")

    client = app.test_client()
    resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-canary-2", "flow_id": flow.id, "force_canary": True},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "accepted"
    assert body["runtime_action"]["type"] == "collect_dtmf"
    assert body["observability"]["canary"]["forced"] is True


def test_condition_node_auto_progression_to_hangup():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow = Flow(
            business_id=b1.id,
            name="Condition Flow",
            status="published",
            version=1,
            start_node_id=201,
        )
        db.session.add(flow)
        db.session.flush()
        snapshot = {
            "flow": {"id": flow.id, "start_node_id": 201},
            "nodes": [
                {
                    "id": 201,
                    "node_key": "check_lang",
                    "node_type": "condition",
                    "name": "Check Language",
                    "config": {
                        "rules": [{"field": "language", "operator": "equals", "value": "en"}],
                        "match_mode": "all",
                    },
                },
                {
                    "id": 202,
                    "node_key": "end_yes",
                    "node_type": "hangup",
                    "name": "Yes End",
                    "config": {"reason": "matched"},
                },
                {
                    "id": 203,
                    "node_key": "end_no",
                    "node_type": "hangup",
                    "name": "No End",
                    "config": {"reason": "not_matched"},
                },
            ],
            "edges": [
                {
                    "id": 601,
                    "source_node_id": 201,
                    "target_node_id": 202,
                    "condition_type": "condition_matched",
                    "condition_value": None,
                    "priority": 1,
                },
                {
                    "id": 602,
                    "source_node_id": 201,
                    "target_node_id": 203,
                    "condition_type": "condition_not_matched",
                    "condition_value": None,
                    "priority": 1,
                },
            ],
        }
        version = FlowVersion(
            flow_id=flow.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot),
            is_active=True,
        )
        db.session.add(version)
        db.session.commit()
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-condition")

    client = app.test_client()
    resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-condition-1", "flow_id": flow.id, "variables": {"language": "en"}},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["next_node_id"] == 202
    assert body["runtime_action"]["type"] == "hangup"
    assert body["variables"]["__condition_matched"] is True


def test_set_variable_and_goto_auto_progression():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow = Flow(
            business_id=b1.id,
            name="Set And Goto",
            status="published",
            version=1,
            start_node_id=301,
        )
        db.session.add(flow)
        db.session.flush()
        snapshot = {
            "flow": {"id": flow.id, "start_node_id": 301},
            "nodes": [
                {
                    "id": 301,
                    "node_key": "set_lang",
                    "node_type": "set_variable",
                    "name": "Set",
                    "config": {"key": "language", "value": "bn"},
                },
                {
                    "id": 302,
                    "node_key": "jump",
                    "node_type": "goto",
                    "name": "Jump",
                    "config": {"target_node_key": "end"},
                },
                {
                    "id": 303,
                    "node_key": "end",
                    "node_type": "hangup",
                    "name": "End",
                    "config": {"reason": "done"},
                },
            ],
            "edges": [
                {
                    "id": 701,
                    "source_node_id": 301,
                    "target_node_id": 302,
                    "condition_type": "always",
                    "condition_value": None,
                    "priority": 1,
                }
            ],
        }
        version = FlowVersion(
            flow_id=flow.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot),
            is_active=True,
        )
        db.session.add(version)
        db.session.commit()
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-set-goto")

    client = app.test_client()
    resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-set-goto-1", "flow_id": flow.id},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["next_node_id"] == 303
    assert body["runtime_action"]["type"] == "hangup"
    assert body["variables"]["language"] == "bn"


def test_webhook_node_success_auto_progression():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow = Flow(
            business_id=b1.id,
            name="Webhook Flow",
            status="published",
            version=1,
            start_node_id=401,
        )
        db.session.add(flow)
        db.session.flush()
        snapshot = {
            "flow": {"id": flow.id, "start_node_id": 401},
            "nodes": [
                {
                    "id": 401,
                    "node_key": "hook",
                    "node_type": "webhook",
                    "name": "Webhook",
                    "config": {
                        "method": "POST",
                        "url": "https://example.com/hook",
                        "body_template": {"phone": "{{customer_number}}"},
                        "save_response_as": "hook_result",
                    },
                },
                {
                    "id": 402,
                    "node_key": "end_ok",
                    "node_type": "hangup",
                    "name": "End Ok",
                    "config": {"reason": "hook_ok"},
                },
                {
                    "id": 403,
                    "node_key": "end_fail",
                    "node_type": "hangup",
                    "name": "End Fail",
                    "config": {"reason": "hook_fail"},
                },
            ],
            "edges": [
                {
                    "id": 801,
                    "source_node_id": 401,
                    "target_node_id": 402,
                    "condition_type": "webhook_success",
                    "condition_value": None,
                    "priority": 1,
                },
                {
                    "id": 802,
                    "source_node_id": 401,
                    "target_node_id": 403,
                    "condition_type": "webhook_failed",
                    "condition_value": None,
                    "priority": 1,
                },
            ],
        }
        version = FlowVersion(
            flow_id=flow.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot),
            is_active=True,
        )
        db.session.add(version)
        db.session.commit()
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-webhook-success")

    class _Resp:
        status_code = 200
        text = '{"ok":true}'

    with patch("app.api.v2.flows.node_executors.webhook.requests.request", return_value=_Resp()):
        client = app.test_client()
        resp = client.post(
            "/api/v2/internal/flow/resolve-next",
            json={"call_session_id": "call-webhook-1", "flow_id": flow.id, "variables": {"customer_number": "8801"}},
            headers={"X-Dialyra-Access-Token": token},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["next_node_id"] == 402
        assert body["runtime_action"]["type"] == "hangup"
        assert body["variables"]["hook_result"]["status_code"] == 200


def test_webhook_node_request_failure_auto_progression():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow = Flow(
            business_id=b1.id,
            name="Webhook Flow Fail",
            status="published",
            version=1,
            start_node_id=501,
        )
        db.session.add(flow)
        db.session.flush()
        snapshot = {
            "flow": {"id": flow.id, "start_node_id": 501},
            "nodes": [
                {
                    "id": 501,
                    "node_key": "hook",
                    "node_type": "webhook",
                    "name": "Webhook",
                    "config": {
                        "method": "GET",
                        "url": "https://example.com/hook",
                        "save_response_as": "hook_result",
                    },
                },
                {
                    "id": 503,
                    "node_key": "end_fail",
                    "node_type": "hangup",
                    "name": "End Fail",
                    "config": {"reason": "hook_fail"},
                },
            ],
            "edges": [
                {
                    "id": 902,
                    "source_node_id": 501,
                    "target_node_id": 503,
                    "condition_type": "webhook_failed",
                    "condition_value": None,
                    "priority": 1,
                },
            ],
        }
        version = FlowVersion(
            flow_id=flow.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot),
            is_active=True,
        )
        db.session.add(version)
        db.session.commit()
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-webhook-fail")

    with patch(
        "app.api.v2.flows.node_executors.webhook.requests.request",
        side_effect=__import__("requests").RequestException("timeout"),
    ):
        client = app.test_client()
        resp = client.post(
            "/api/v2/internal/flow/resolve-next",
            json={"call_session_id": "call-webhook-2", "flow_id": flow.id},
            headers={"X-Dialyra-Access-Token": token},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["next_node_id"] == 503
        assert body["runtime_action"]["type"] == "hangup"
        assert "error" in body["variables"]["hook_result"]


def test_transfer_call_node_returns_runtime_action():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow = Flow(
            business_id=b1.id,
            name="Transfer Flow",
            status="published",
            version=1,
            start_node_id=601,
        )
        db.session.add(flow)
        db.session.flush()
        snapshot = {
            "flow": {"id": flow.id, "start_node_id": 601},
            "nodes": [
                {
                    "id": 601,
                    "node_key": "xfer",
                    "node_type": "transfer_call",
                    "name": "Transfer",
                    "config": {
                        "transfer_type": "queue",
                        "queue_id": "support_q",
                        "timeout_seconds": 25,
                        "fallback_node_key": "agent_unavailable",
                    },
                }
            ],
            "edges": [],
        }
        version = FlowVersion(
            flow_id=flow.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot),
            is_active=True,
        )
        db.session.add(version)
        db.session.commit()
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-transfer")

    client = app.test_client()
    resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-transfer-1", "flow_id": flow.id},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["runtime_action"]["type"] == "transfer_call"
    assert body["runtime_action"]["transfer_type"] == "queue"
    assert body["runtime_action"]["target"] == "support_q"
    assert body["runtime_action"]["timeout_seconds"] == 25


def test_transfer_call_invalid_config_returns_fallback_when_requested():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow = Flow(
            business_id=b1.id,
            name="Transfer Flow Invalid",
            status="published",
            version=1,
            start_node_id=701,
        )
        db.session.add(flow)
        db.session.flush()
        snapshot = {
            "flow": {"id": flow.id, "start_node_id": 701},
            "nodes": [
                {
                    "id": 701,
                    "node_key": "xfer",
                    "node_type": "transfer_call",
                    "name": "Transfer",
                    "config": {
                        "transfer_type": "queue"
                    },
                }
            ],
            "edges": [],
        }
        version = FlowVersion(
            flow_id=flow.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot),
            is_active=True,
        )
        db.session.add(version)
        db.session.commit()
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-transfer-invalid")

    client = app.test_client()
    resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-transfer-2", "flow_id": flow.id, "use_fallback": True},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "accepted_with_fallback"
    assert body["runtime_action"]["type"] == "hangup"


def test_wait_node_returns_wait_runtime_action():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow = Flow(
            business_id=b1.id,
            name="Wait Flow",
            status="published",
            version=1,
            start_node_id=801,
        )
        db.session.add(flow)
        db.session.flush()
        snapshot = {
            "flow": {"id": flow.id, "start_node_id": 801},
            "nodes": [
                {
                    "id": 801,
                    "node_key": "wait_3s",
                    "node_type": "wait",
                    "name": "Wait",
                    "config": {"duration_seconds": 3},
                }
            ],
            "edges": [],
        }
        version = FlowVersion(
            flow_id=flow.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot),
            is_active=True,
        )
        db.session.add(version)
        db.session.commit()
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-wait")

    client = app.test_client()
    resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-wait-1", "flow_id": flow.id},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["runtime_action"]["type"] == "wait"
    assert body["runtime_action"]["duration_seconds"] == 3


def test_record_control_node_returns_action_and_invalid_config_fallback():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow_ok = Flow(
            business_id=b1.id,
            name="Record Control Flow OK",
            status="published",
            version=1,
            start_node_id=901,
        )
        db.session.add(flow_ok)
        db.session.flush()
        snapshot_ok = {
            "flow": {"id": flow_ok.id, "start_node_id": 901},
            "nodes": [
                {
                    "id": 901,
                    "node_key": "rec_start",
                    "node_type": "record_control",
                    "name": "Record Start",
                    "config": {"action": "start"},
                }
            ],
            "edges": [],
        }
        version_ok = FlowVersion(
            flow_id=flow_ok.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot_ok),
            is_active=True,
        )
        db.session.add(version_ok)
        db.session.commit()
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-record")

    client = app.test_client()
    ok_resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-record-1", "flow_id": flow_ok.id},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert ok_resp.status_code == 200
    ok_body = ok_resp.get_json()
    assert ok_body["runtime_action"]["type"] == "record_control"
    assert ok_body["runtime_action"]["action"] == "start"

    with app.app_context():
        flow_bad = Flow(
            business_id=b1.id,
            name="Record Control Flow Bad",
            status="published",
            version=1,
            start_node_id=902,
        )
        db.session.add(flow_bad)
        db.session.flush()
        snapshot_bad = {
            "flow": {"id": flow_bad.id, "start_node_id": 902},
            "nodes": [
                {
                    "id": 902,
                    "node_key": "rec_bad",
                    "node_type": "record_control",
                    "name": "Record Bad",
                    "config": {"action": "begin"},
                }
            ],
            "edges": [],
        }
        version_bad = FlowVersion(
            flow_id=flow_bad.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot_bad),
            is_active=True,
        )
        db.session.add(version_bad)
        db.session.commit()

    bad_resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-record-2", "flow_id": flow_bad.id, "use_fallback": True},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert bad_resp.status_code == 200
    bad_body = bad_resp.get_json()
    assert bad_body["status"] == "accepted_with_fallback"
    assert bad_body["runtime_action"]["type"] == "hangup"


def test_runtime_node_type_rollout_disable_returns_fallback():
    app = create_app("testing")
    app.config["FLOW_RUNTIME_ENABLED_NODE_TYPES"] = "gather_input,hangup"
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow = Flow(
            business_id=b1.id,
            name="Rollout Disable Wait",
            status="published",
            version=1,
            start_node_id=1001,
        )
        db.session.add(flow)
        db.session.flush()
        snapshot = {
            "flow": {"id": flow.id, "start_node_id": 1001},
            "nodes": [
                {
                    "id": 1001,
                    "node_key": "wait_node",
                    "node_type": "wait",
                    "name": "Wait",
                    "config": {"duration_seconds": 2},
                }
            ],
            "edges": [],
        }
        version = FlowVersion(
            flow_id=flow.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot),
            is_active=True,
        )
        db.session.add(version)
        db.session.commit()
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-rollout-disable")

    client = app.test_client()
    resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={
            "call_session_id": "call-rollout-disable-1",
            "flow_id": flow.id,
            "use_fallback": True,
        },
        headers={"X-Dialyra-Access-Token": token},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "accepted_with_fallback"
    assert body["runtime_action"]["type"] == "hangup"
    assert "Node type disabled by rollout" in body["warning"]


def test_runtime_explicit_node_flag_overrides_allowlist():
    app = create_app("testing")
    app.config["FLOW_RUNTIME_ENABLED_NODE_TYPES"] = "wait,hangup"
    app.config["FLOW_RUNTIME_ENABLE_WAIT"] = "false"
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow = Flow(
            business_id=b1.id,
            name="Rollout Explicit Flag",
            status="published",
            version=1,
            start_node_id=1101,
        )
        db.session.add(flow)
        db.session.flush()
        snapshot = {
            "flow": {"id": flow.id, "start_node_id": 1101},
            "nodes": [
                {
                    "id": 1101,
                    "node_key": "wait_node",
                    "node_type": "wait",
                    "name": "Wait",
                    "config": {"duration_seconds": 2},
                }
            ],
            "edges": [],
        }
        version = FlowVersion(
            flow_id=flow.id,
            business_id=b1.id,
            version_number=1,
            snapshot_json=json.dumps(snapshot),
            is_active=True,
        )
        db.session.add(version)
        db.session.commit()
        token = _issue_access_token(b1.id, ["flow:resolve"], raw_token="tok-rollout-override")

    client = app.test_client()
    resp = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={
            "call_session_id": "call-rollout-override-1",
            "flow_id": flow.id,
            "use_fallback": True,
        },
        headers={"X-Dialyra-Access-Token": token},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "accepted_with_fallback"
    assert body["runtime_action"]["type"] == "hangup"
    assert "Node type disabled by rollout" in body["warning"]


def test_transfer_event_endpoint_validates_and_logs():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow, _ = _create_published_flow(b1.id)
        token = _issue_access_token(
            b1.id, ["flow:resolve", "events:write"], raw_token="tok-transfer-event"
        )

    client = app.test_client()
    seed = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-transfer-event-1", "flow_id": flow.id},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert seed.status_code == 200

    bad = client.post(
        "/api/v2/internal/calls/call-transfer-event-1/transfer-event",
        json={"event_type": "transfer_timeout"},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert bad.status_code == 400
    bad_body = bad.get_json()
    assert "allowed_event_types" in bad_body

    ok = client.post(
        "/api/v2/internal/calls/call-transfer-event-1/transfer-event",
        json={"event_type": "transfer_failed", "cause": "agent_busy"},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert ok.status_code == 200
    ok_body = ok.get_json()
    assert ok_body["event"] == "transfer_failed"
    assert ok_body["event_id"] is not None


def test_wait_and_record_verification_endpoints():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        flow, _ = _create_published_flow(b1.id)
        token = _issue_access_token(
            b1.id, ["flow:resolve", "events:write"], raw_token="tok-wait-record-event"
        )

    client = app.test_client()
    seed = client.post(
        "/api/v2/internal/flow/resolve-next",
        json={"call_session_id": "call-wait-record-1", "flow_id": flow.id},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert seed.status_code == 200

    bad_wait = client.post(
        "/api/v2/internal/calls/call-wait-record-1/wait-event",
        json={"event_type": "wait_timeout"},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert bad_wait.status_code == 400

    ok_wait = client.post(
        "/api/v2/internal/calls/call-wait-record-1/wait-event",
        json={"event_type": "wait_completed", "duration_ms": 3200},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert ok_wait.status_code == 200
    assert ok_wait.get_json()["event"] == "wait_completed"

    bad_record = client.post(
        "/api/v2/internal/calls/call-wait-record-1/record-event",
        json={"event_type": "record_begin"},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert bad_record.status_code == 400

    ok_record = client.post(
        "/api/v2/internal/calls/call-wait-record-1/record-event",
        json={"event_type": "recording_started", "recording_id": "rec_1"},
        headers={"X-Dialyra-Access-Token": token},
    )
    assert ok_record.status_code == 200
    assert ok_record.get_json()["event"] == "recording_started"
