from unittest.mock import patch

import requests

from app.api.v2.flows.node_executors import execute_node


class _Biz:
    id = 1


def _node(node_type, config=None):
    return {
        "id": 10,
        "node_type": node_type,
        "config": config or {},
    }


def test_executor_play_audio():
    result = execute_node(_Biz(), _node("play_audio", {"audio_asset_id": 123}), {})
    assert result.error is None
    assert result.runtime_action["type"] == "play_audio_asset"


def test_executor_say_text():
    with patch(
        "app.api.v2.flows.node_executors.say_text.generate_tts_for_runtime_business",
        return_value=({"audio_asset_id": 1, "tts_request_id": 2, "source": "cached"}, None),
    ):
        result = execute_node(_Biz(), _node("say_text", {"text": "hello"}), {})
    assert result.error is None
    assert result.runtime_action["type"] == "play_audio_asset"
    assert result.metadata["tts"]["source"] == "cached"


def test_executor_gather_input():
    result = execute_node(_Biz(), _node("gather_input", {"max_digits": 2, "timeout_seconds": 7}), {})
    assert result.error is None
    assert result.runtime_action["type"] == "collect_dtmf"
    assert result.runtime_action["max_digits"] == 2


def test_executor_condition():
    vars_ = {"language": "en"}
    result = execute_node(
        _Biz(),
        _node(
            "condition",
            {"rules": [{"field": "language", "operator": "equals", "value": "en"}], "match_mode": "all"},
        ),
        vars_,
    )
    assert result.error is None
    assert result.metadata["auto_result_type"] == "condition_matched"
    assert vars_["__condition_matched"] is True


def test_executor_set_variable():
    vars_ = {"name": "Tanjim"}
    result = execute_node(
        _Biz(),
        _node("set_variable", {"key": "greeting", "value": "Hi {{name}}"}),
        vars_,
    )
    assert result.error is None
    assert vars_["greeting"] == "Hi Tanjim"


def test_executor_goto():
    result = execute_node(_Biz(), _node("goto", {"target_node_key": "end"}), {})
    assert result.error is None
    assert result.metadata["goto_target_node_key"] == "end"


def test_executor_webhook_success_and_failure():
    class _Resp:
        status_code = 200
        text = "ok"

    with patch("app.api.v2.flows.node_executors.webhook.requests.request", return_value=_Resp()):
        vars_ = {}
        ok = execute_node(
            _Biz(),
            _node(
                "webhook",
                {"method": "GET", "url": "https://example.com", "save_response_as": "hook"},
            ),
            vars_,
        )
    assert ok.error is None
    assert ok.metadata["auto_result_type"] == "webhook_success"
    assert vars_["hook"]["status_code"] == 200

    with patch(
        "app.api.v2.flows.node_executors.webhook.requests.request",
        side_effect=requests.RequestException("timeout"),
    ):
        vars_ = {}
        bad = execute_node(
            _Biz(),
            _node(
                "webhook",
                {"method": "GET", "url": "https://example.com", "save_response_as": "hook"},
            ),
            vars_,
        )
    assert bad.error is None
    assert bad.metadata["auto_result_type"] == "webhook_failed"
    assert "error" in vars_["hook"]


def test_executor_webhook_json_response_mapping():
    class _Resp:
        status_code = 200
        text = '{"data":{"customer":{"name":"Tanjim"}}}'

        @staticmethod
        def json():
            return {"data": {"customer": {"name": "Tanjim", "tier": "gold"}}}

    with patch("app.api.v2.flows.node_executors.webhook.requests.request", return_value=_Resp()):
        vars_ = {}
        result = execute_node(
            _Biz(),
            _node(
                "webhook",
                {
                    "method": "GET",
                    "url": "https://example.com",
                    "response_mode": "json",
                    "save_response_as": "hook_json",
                    "response_json_path_map": {
                        "customer_name": "data.customer.name",
                        "customer_tier": "data.customer.tier",
                    },
                },
            ),
            vars_,
        )
    assert result.error is None
    assert result.metadata["auto_result_type"] == "webhook_success"
    assert vars_["hook_json"]["json"]["data"]["customer"]["name"] == "Tanjim"
    assert vars_["customer_name"] == "Tanjim"
    assert vars_["customer_tier"] == "gold"


def test_executor_webhook_json_parse_failure_is_safe():
    class _Resp:
        status_code = 200
        text = "not json"

        @staticmethod
        def json():
            raise ValueError("invalid json")

    with patch("app.api.v2.flows.node_executors.webhook.requests.request", return_value=_Resp()):
        vars_ = {}
        result = execute_node(
            _Biz(),
            _node(
                "webhook",
                {
                    "method": "GET",
                    "url": "https://example.com",
                    "response_mode": "json",
                    "save_response_as": "hook_json",
                    "response_json_path_map": {"customer_name": "data.customer.name"},
                },
            ),
            vars_,
        )
    assert result.error is None
    assert result.metadata["auto_result_type"] == "webhook_success"
    assert vars_["hook_json"]["json"] is None
    assert vars_["hook_json"]["json_parse_error"] is True
    assert vars_["customer_name"] is None


def test_executor_transfer_call():
    result = execute_node(
        _Biz(),
        _node("transfer_call", {"transfer_type": "queue", "queue_id": "q1", "timeout_seconds": 20}),
        {},
    )
    assert result.error is None
    assert result.runtime_action["type"] == "transfer_call"
    assert result.runtime_action["target"] == "q1"


def test_executor_wait_and_record_control():
    wait_result = execute_node(_Biz(), _node("wait", {"duration_seconds": 5}), {})
    assert wait_result.error is None
    assert wait_result.runtime_action["type"] == "wait"

    record_result = execute_node(_Biz(), _node("record_control", {"action": "start"}), {})
    assert record_result.error is None
    assert record_result.runtime_action["type"] == "record_control"


def test_executor_unknown_is_noop():
    result = execute_node(_Biz(), _node("not_a_real_node"), {})
    assert result.error is None
    assert result.runtime_action["type"] == "noop"
