import json

from werkzeug.security import generate_password_hash

from app import create_app
from app.api.v2.flows.service import create_flow, create_flow_node, update_flow_node, validate_flow
from app.extensions import db
from app.models import Business, User


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


def _create_superuser(business_id, email="super@example.com"):
    user = User(
        business_id=business_id,
        full_name="Super User",
        email=email,
        password_hash=generate_password_hash("pass-123"),
        role="superuser",
        status="active",
    )
    db.session.add(user)
    db.session.flush()
    return user


def test_create_goto_node_is_allowed_and_validated():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        actor = _create_superuser(b1.id)
        db.session.commit()

        flow, err = create_flow(actor, {"business_id": b1.id, "name": "Flow A"})
        assert err is None
        node, node_err = create_flow_node(
            actor,
            flow["id"],
            {
                "node_key": "goto_1",
                "node_type": "goto",
                "name": "Goto",
                "config": {"target_node_key": "end"},
            },
        )
        assert node_err is None
        assert node["node_type"] == "goto"


def test_create_webhook_node_requires_valid_url_and_method():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        actor = _create_superuser(b1.id)
        db.session.commit()

        flow, err = create_flow(actor, {"business_id": b1.id, "name": "Flow B"})
        assert err is None

        _, node_err = create_flow_node(
            actor,
            flow["id"],
            {
                "node_key": "hook_1",
                "node_type": "webhook",
                "name": "Hook",
                "config": {"method": "FETCH", "url": "example.com"},
            },
        )
        assert node_err is not None
        assert "INVALID_WEBHOOK_METHOD" in node_err or "MISSING_WEBHOOK_URL" in node_err


def test_update_node_type_enforces_schema_for_new_type():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        actor = _create_superuser(b1.id)
        db.session.commit()

        flow, err = create_flow(actor, {"business_id": b1.id, "name": "Flow C"})
        assert err is None
        node, node_err = create_flow_node(
            actor,
            flow["id"],
            {
                "node_key": "play_1",
                "node_type": "play_audio",
                "name": "Play",
                "config": {"audio_asset_id": 123},
            },
        )
        assert node_err is None

        _, update_err = update_flow_node(
            actor,
            node["id"],
            {"node_type": "transfer_call"},
        )
        assert update_err is not None
        assert "INVALID_TRANSFER_TYPE" in update_err or "MISSING_TRANSFER_TARGET" in update_err


def test_validate_flow_returns_explicit_node_error_codes():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        actor = _create_superuser(b1.id)
        db.session.commit()

        flow, err = create_flow(actor, {"business_id": b1.id, "name": "Flow D"})
        assert err is None
        # insert invalid node directly to verify validate_flow catches node schema errors
        from app.models import FlowNode

        bad = FlowNode(
            flow_id=flow["id"],
            business_id=b1.id,
            node_key="wait_bad",
            node_type="wait",
            name="Wait Bad",
            config_json=json.dumps({"duration_seconds": 0}),
            is_start=True,
        )
        db.session.add(bad)
        db.session.flush()
        from app.models import Flow

        flow_row = Flow.query.get(flow["id"])
        flow_row.start_node_id = bad.id
        db.session.commit()

        report, report_err = validate_flow(actor, flow["id"])
        assert report_err is None
        assert report["valid"] is False
        codes = {e.get("code") for e in report["errors"]}
        assert "INVALID_WAIT_DURATION" in codes
