import json
from datetime import datetime
from unittest.mock import patch

from app import create_app
from app.api.v2.calls import service as call_service
from app.extensions import db
from app.models import Business, CallSession, SipTrunk
from fastagi.server import FastAGIHandler


def _create_business(*, allow_global=False):
    business = Business(
        name="Biz",
        slug="biz",
        owner_name="Owner",
        email="biz@example.com",
        status="active",
        allow_global_sip_fallback=allow_global,
    )
    db.session.add(business)
    db.session.flush()
    return business


def _create_trunk(*, business_id, name="trunk-1", max_calls=10):
    trunk = SipTrunk(
        business_id=business_id,
        scope="business",
        name=name,
        provider_name="Provider",
        type="ip",
        host="202.40.176.2",
        port=5060,
        username="u",
        password_encrypted="p",
        auth_type="userpass",
        transport="udp",
        from_user="09617179124",
        from_domain="202.40.176.2",
        context="outbound",
        status="active",
        max_concurrent_calls=max_calls,
        is_active=True,
    )
    db.session.add(trunk)
    db.session.flush()
    return trunk


def test_originate_builds_required_channel_variables():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        biz = _create_business()
        trunk = _create_trunk(business_id=biz.id)
        db.session.commit()

        captured = {}

        def _fake_originate(phone, channel_variables=None, action_id=None):
            captured["phone"] = phone
            captured["channel_variables"] = dict(channel_variables or {})
            captured["action_id"] = action_id
            return "Response: Success"

        with patch("app.api.v2.calls.service.originate_call", side_effect=_fake_originate):
            result, error = call_service.originate_call_for_business(
                phone="8801631596698",
                business_id=biz.id,
                sip_trunk_id=trunk.id,
                realtime_enabled=True,
                actor_user_id=None,
            )

        assert error is None
        assert result is not None
        vars_map = captured["channel_variables"]
        assert vars_map["TARGET_NUMBER"] == "8801631596698"
        assert vars_map["SIP_TRUNK_ID"] == trunk.id
        assert vars_map["BUSINESS_ID"] == biz.id
        assert vars_map["CALL_LOG_UUID"] == result["call_log_uuid"]
        assert vars_map["CALL_SESSION_ID"] == result["call_session_id"]
        assert vars_map["CALL_ACTION_ID"] == result["action_id"]
        assert vars_map["SIP_TRUNK_ENDPOINT"] == result["sip_endpoint"]


def test_retry_propagates_retry_channel_variables():
    app = create_app("testing")
    with app.app_context():
        db.drop_all()
        db.create_all()
        biz = _create_business()
        trunk = _create_trunk(business_id=biz.id)
        source = CallSession(
            business_id=biz.id,
            sip_trunk_id=trunk.id,
            call_direction="outbound",
            status="failed",
            phone_number="8801631596698",
            metadata_json=json.dumps({"retry_count": 0}),
            started_at=datetime.utcnow(),
            ended_at=datetime.utcnow(),
        )
        db.session.add(source)
        db.session.commit()

        captured = {}

        def _fake_originate(phone, channel_variables=None, action_id=None):
            captured["phone"] = phone
            captured["channel_variables"] = dict(channel_variables or {})
            captured["action_id"] = action_id
            return "Response: Success"

        with patch("app.api.v2.calls.service.originate_call", side_effect=_fake_originate):
            result, error = call_service.retry_call_session_for_business(
                source_call_session_id=source.id,
                business_id=biz.id,
                realtime_enabled=True,
                max_attempts=3,
            )

        assert error is None
        assert result is not None
        assert result["retry_of_call_session_id"] == source.id
        assert result["retry_count"] == 1
        assert captured["channel_variables"]["RETRY_COUNT"] == 1
        assert captured["channel_variables"]["RETRY_OF_CALL_SESSION_ID"] == source.id


def test_fastagi_required_context_validation():
    handler = FastAGIHandler.__new__(FastAGIHandler)
    context = {
        "call_session_id": "12",
        "business_id": "5",
        "target_number": "8801631596698",
        "sip_trunk_id": "",
        "sip_trunk_endpoint": "dialyra_b5_t1_test_ep",
    }
    missing = handler._validate_required_context(context)
    assert missing == ["SIP_TRUNK_ID"]

