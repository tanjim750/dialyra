from werkzeug.security import generate_password_hash

from app import create_app
from app.api.v2.flows.service import (
    create_flow,
    create_flow_edge,
    create_flow_node,
    update_flow_edge,
    validate_flow,
)
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


def test_create_edge_rejects_duplicate_signature():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        actor = _create_superuser(b1.id)
        db.session.commit()

        flow, err = create_flow(actor, {"business_id": b1.id, "name": "Edge Flow"})
        assert err is None
        n1, _ = create_flow_node(actor, flow["id"], {"node_key": "a", "node_type": "gather_input", "name": "A", "config": {"max_digits": 1, "timeout_seconds": 5}})
        n2, _ = create_flow_node(actor, flow["id"], {"node_key": "b", "node_type": "hangup", "name": "B", "config": {"reason": "done"}})
        n3, _ = create_flow_node(actor, flow["id"], {"node_key": "c", "node_type": "hangup", "name": "C", "config": {"reason": "done"}})

        e1, e1_err = create_flow_edge(
            actor,
            flow["id"],
            {
                "source_node_id": n1["id"],
                "target_node_id": n2["id"],
                "condition_type": "dtmf",
                "condition_value": "1",
            },
        )
        assert e1_err is None
        assert e1["id"] is not None

        _, dup_err = create_flow_edge(
            actor,
            flow["id"],
            {
                "source_node_id": n1["id"],
                "target_node_id": n3["id"],
                "condition_type": "dtmf",
                "condition_value": "1",
            },
        )
        assert dup_err is not None
        assert "DUPLICATE_EDGE_CONDITION" in dup_err


def test_create_edge_requires_condition_value_for_dtmf_and_variable_match():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        actor = _create_superuser(b1.id)
        db.session.commit()

        flow, _ = create_flow(actor, {"business_id": b1.id, "name": "Edge Flow 2"})
        n1, _ = create_flow_node(actor, flow["id"], {"node_key": "a", "node_type": "gather_input", "name": "A", "config": {"max_digits": 1, "timeout_seconds": 5}})
        n2, _ = create_flow_node(actor, flow["id"], {"node_key": "b", "node_type": "hangup", "name": "B", "config": {"reason": "done"}})

        _, dtmf_err = create_flow_edge(
            actor,
            flow["id"],
            {
                "source_node_id": n1["id"],
                "target_node_id": n2["id"],
                "condition_type": "dtmf",
            },
        )
        assert dtmf_err is not None
        assert "MISSING_DTMF_CONDITION_VALUE" in dtmf_err

        _, vm_err = create_flow_edge(
            actor,
            flow["id"],
            {
                "source_node_id": n1["id"],
                "target_node_id": n2["id"],
                "condition_type": "variable_match",
                "condition_value": "language",
            },
        )
        assert vm_err is not None
        assert "INVALID_VARIABLE_MATCH_CONDITION_VALUE" in vm_err


def test_update_edge_rejects_duplicate_signature():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        actor = _create_superuser(b1.id)
        db.session.commit()

        flow, _ = create_flow(actor, {"business_id": b1.id, "name": "Edge Flow 3"})
        n1, _ = create_flow_node(actor, flow["id"], {"node_key": "a", "node_type": "gather_input", "name": "A", "config": {"max_digits": 1, "timeout_seconds": 5}})
        n2, _ = create_flow_node(actor, flow["id"], {"node_key": "b", "node_type": "hangup", "name": "B", "config": {"reason": "done"}})
        n3, _ = create_flow_node(actor, flow["id"], {"node_key": "c", "node_type": "hangup", "name": "C", "config": {"reason": "done"}})
        e1, _ = create_flow_edge(actor, flow["id"], {"source_node_id": n1["id"], "target_node_id": n2["id"], "condition_type": "dtmf", "condition_value": "1"})
        e2, _ = create_flow_edge(actor, flow["id"], {"source_node_id": n1["id"], "target_node_id": n3["id"], "condition_type": "dtmf", "condition_value": "2"})

        _, upd_err = update_flow_edge(actor, e2["id"], {"condition_value": "1"})
        assert upd_err is not None
        assert "DUPLICATE_EDGE_CONDITION" in upd_err


def test_validate_flow_edge_coverage_rules():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        b1 = _create_business("B1", "b1")
        actor = _create_superuser(b1.id)
        db.session.commit()

        flow, _ = create_flow(actor, {"business_id": b1.id, "name": "Edge Flow 4"})
        gather, _ = create_flow_node(
            actor,
            flow["id"],
            {
                "node_key": "menu",
                "node_type": "gather_input",
                "name": "Menu",
                "is_start": True,
                "config": {"max_digits": 1, "timeout_seconds": 5},
            },
        )
        end, _ = create_flow_node(
            actor,
            flow["id"],
            {"node_key": "end", "node_type": "hangup", "name": "End", "config": {"reason": "done"}},
        )
        create_flow_edge(
            actor,
            flow["id"],
            {
                "source_node_id": gather["id"],
                "target_node_id": end["id"],
                "condition_type": "dtmf",
                "condition_value": "1",
            },
        )

        report, report_err = validate_flow(actor, flow["id"])
        assert report_err is None
        assert report["valid"] is False
        codes = {item.get("code") for item in report["errors"]}
        assert "MISSING_GATHER_TIMEOUT_EDGE" in codes
        assert "MISSING_GATHER_INVALID_INPUT_EDGE" in codes
