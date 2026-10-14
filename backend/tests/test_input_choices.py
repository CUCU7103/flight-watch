"""Regression coverage for replacing the text helper in the scanner path."""

from unittest.mock import Mock

import pytest

from jev_ultrafast import model
from tests.test_agent import choice, page


def input_page():
    result = page()
    result["actions"][0]["label"] = "Where from? "
    return result


def test_one_request_selects_known_value_without_text_helper(monkeypatch):
    requests = []

    def post(_url, _key, body):
        requests.append(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1"], "1"),
                "text_to_type": choice(["1", "NONE"], "1"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    result = model.choose(input_page(), "Search flights", [], input_values={"Where from?": "ICN", "Where to?": "FUK"})
    assert result["text"] == "ICN"
    assert result["choice"] == "e1"
    assert len(requests) == 1
    assert requests[0]["questions"]["text_to_type"]["criteria"]["1"]["input_value"] == "ICN"
    assert "type_text_target" not in requests[0]["questions"]


@pytest.mark.parametrize("selected", ["invented", "NONE"])
def test_missing_or_unoffered_value_never_executes(monkeypatch, selected):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1"], "1"),
                "text_to_type": choice(["1", "NONE"], selected),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError):
        model.choose(input_page(), "Search flights", [], input_values={"Where from?": "ICN"})


def test_unused_value_head_does_not_block_click(monkeypatch):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "click_target": choice(["1", "2"], "2"),
                "text_to_type": {"invalid": True},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    assert model.choose(input_page(), "Search flights", [], input_values={"Where from?": "ICN"})["choice"] == "e3"


def test_agent_consumes_decision_value_and_never_calls_helper(runner, monkeypatch):
    from jev_ultrafast import agent as loop

    runner.input_values = {"Where from?": "ICN"}
    runner.state["decision"]["text"] = "ICN"
    helper = Mock(side_effect=AssertionError("No text generation allowed"))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"][-1]["text"] == "ICN"
    assert runner.state["text_calls"] == []


def test_agent_rejects_value_outside_own_job(runner):
    runner.input_values = {"Where from?": "ICN"}
    runner.state["decision"]["text"] = "evil input"
    with pytest.raises(ValueError):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"] == []


@pytest.mark.parametrize("fresh,expected", [(True, "BLOCKED"), (False, "CLICK")])
def test_no_progress_target_is_excluded_only_for_unchanged_snapshot(monkeypatch, fresh, expected):
    p = page()
    p["excluded_actions"] = {"fingerprint": p["fingerprint"] if fresh else "old", "ids": ["e3"]}

    def post(_url, _key, body):
        candidates = body["questions"]["click_target"]["criteria"]
        target = next((key for key, value in candidates.items() if "Go" in value["element"]), None)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK" if target else "BLOCKED"),
                "click_target": choice(candidates, target) if target else {},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    assert model.choose(p, "Search", [])["operation"] == expected
