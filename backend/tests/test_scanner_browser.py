from datetime import date

import pytest

from flight_scanner.browser import validate_action
from flight_scanner.models import ScanJob


@pytest.fixture
def job():
    return ScanJob("ICN", "FUK", date(2026, 11, 12), date(2026, 11, 15), 180_000)


def test_valid_origin_input_is_allowed(job):
    page = {
        "url": "https://www.google.com/travel/flights",
        "actions": [{"id": "e1", "kind": "fill", "label": "Where from?", "node": 1}],
    }
    action = validate_action(job, page, {"choice": "e1", "text": "ICN"})
    assert action["node"] == 1


def test_accessible_field_label_whitespace_is_normalized(job):
    page = {
        "url": "https://www.google.com/travel/flights",
        "actions": [{"id": "e1", "kind": "fill", "label": "Where to? ", "node": 1}],
    }
    assert validate_action(job, page, {"choice": "e1", "text": "FUK"})["node"] == 1


@pytest.mark.parametrize(
    "label,text", [("Where from?", "FUK"), ("Where to?", "ICN"), ("Departure", "2026-11-15"), ("Password", "ICN")]
)
def test_incompatible_value_and_field_are_rejected(job, label, text):
    page = {
        "url": "https://www.google.com/travel/flights",
        "actions": [{"id": "e1", "kind": "fill", "label": label, "node": 1}],
    }
    with pytest.raises(ValueError):
        validate_action(job, page, {"choice": "e1", "text": text})


@pytest.mark.parametrize(
    "label", ["Book now", "Sign in", "Select flight", "Pay", "Continue to booking", "Subscribe", "Delete account"]
)
def test_purchase_and_account_actions_are_rejected(job, label):
    page = {
        "url": "https://www.google.com/travel/flights",
        "actions": [{"id": "e1", "kind": "click", "label": label, "node": 1}],
    }
    with pytest.raises(ValueError):
        validate_action(job, page, {"choice": "e1"})


def test_external_navigation_and_invented_targets_are_rejected(job):
    for url in ["https://evil.test/", "https://www.google.com/accounts", "http://www.google.com/travel/flights"]:
        with pytest.raises(ValueError):
            validate_action(job, {"url": url, "actions": []}, {"choice": "DONE"})
    with pytest.raises(ValueError):
        validate_action(job, {"url": "https://www.google.com/travel/flights", "actions": []}, {"choice": "e99"})


def _hanging_worker(job, connection):
    import time

    time.sleep(10)


def test_hard_deadline_terminates_worker(job, monkeypatch):
    import time

    from flight_scanner import browser

    monkeypatch.setenv("BU_CDP_WS", "ws://127.0.0.1:1/not-a-browser")
    monkeypatch.setenv("BU_NAME", "flight_scanner_test")
    monkeypatch.setattr(browser, "JOB_TIMEOUT", 0.1)
    monkeypatch.setattr(browser, "_worker", _hanging_worker)
    started = time.monotonic()
    assert browser.scan(job).status == "TIMEOUT"
    assert time.monotonic() - started < 4


def test_scanner_requires_owned_browser(job, monkeypatch):
    from flight_scanner.browser import scan

    monkeypatch.delenv("BU_CDP_WS", raising=False)
    assert scan(job).status == "ERROR"


def test_browser_context_pins_model_and_cleans_only_owned_processes(tmp_path, monkeypatch):
    import os
    from pathlib import Path

    from browser_harness import admin

    from flight_scanner import browser

    chrome = tmp_path / "fake-chrome"
    chrome.write_text("placeholder; never executed")
    monkeypatch.setenv("CHROME_PATH", str(chrome))
    monkeypatch.delenv("TYPESAFE_MODEL", raising=False)
    monkeypatch.setenv("BU_NAME", "existing-other-browser")
    monkeypatch.setenv("BU_BROWSER_ID", "existing-other-cloud-browser")
    monkeypatch.setenv("BH_CONFIG_DIR", str(tmp_path / "other-harness-config"))
    processes = []

    class OwnedProcess:
        def __init__(self):
            self.stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, **kwargs):
            return 0

    def launch(args, **kwargs):
        if args[0] == str(chrome):
            profile = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--user-data-dir=")))
            profile.mkdir(parents=True)
            (profile / "DevToolsActivePort").write_text("12345\n/devtools/browser/test")
        else:
            cloud_id = os.environ.get("BU_BROWSER_ID")
            config = os.environ.get("BH_CONFIG_DIR")
            assert cloud_id is None
            assert config.endswith("/harness")
        process = OwnedProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(browser.subprocess, "Popen", launch)
    monkeypatch.setattr(admin, "require_existing_daemon", lambda name: None)
    with browser.dedicated_browser():
        model = os.environ.get("TYPESAFE_MODEL")
        assert model == "jev-1.13.0"
        name = os.environ["BU_NAME"]
        assert name.startswith("flight_scanner_")
        ws = os.environ["BU_CDP_WS"]
        assert ws == "ws://127.0.0.1:12345/devtools/browser/test"
    model = os.environ.get("TYPESAFE_MODEL")
    name = os.environ["BU_NAME"]
    assert model is None
    assert name == "existing-other-browser"
    cloud_id = os.environ.get("BU_BROWSER_ID")
    assert cloud_id == "existing-other-cloud-browser"
    assert len(processes) == 2 and all(process.stopped for process in processes)


def test_autocomplete_waits_for_matching_observed_airport_without_retyping(monkeypatch):
    from unittest.mock import Mock

    from flight_scanner import browser

    empty = {"actions": [{"label": "Where else?", "kind": "fill", "value": "FUK"}]}
    ready = {"actions": [{"label": "Fukuoka (FUK)", "kind": "click", "role": "option"}]}
    connection = Mock(observe=Mock(side_effect=[empty, ready]))
    monkeypatch.setattr(browser.time, "sleep", lambda _: None)
    assert browser.settle_autocomplete(connection, empty, "FUK") == ready


def test_cached_harness_cannot_attach_to_another_namespace(job, monkeypatch):
    from flight_scanner.browser import _run_job
    from jev_ultrafast import Agent

    calls = []

    def forbidden(*a, **kw):
        calls.append(True)
        raise AssertionError("Must reject before browser construction")

    monkeypatch.setattr(Agent, "__init__", forbidden)
    monkeypatch.setenv("BU_NAME", "flight_scanner_different_from_imported_harness")
    assert _run_job(job, lambda _: None).status == "ERROR"
    assert calls == []


@pytest.mark.parametrize(
    "mode,expected",
    [("wait", "TIMEOUT"), ("captcha", "BLOCKED"), ("done", "INVALID_RESULT"), ("invalid", "INVALID_RESULT")],
)
def test_real_loop_terminates_without_trusting_done(job, runner, monkeypatch, mode, expected):
    from flight_scanner import browser
    from jev_ultrafast import Agent
    from jev_ultrafast import agent as loop
    from tests.test_agent import decision

    page = runner.state["page"]
    page["url"] = "https://www.google.com/travel/flights"
    if mode == "captcha":
        page["text"] = "Verify you are human"
    runner.browser = runner.state["browser"]
    runner.state["browser"].target = "owned-test-target"
    runner.input_values = job.input_values()
    selection = "wait" if mode == "wait" else "DONE" if mode == "done" else "e1"
    result_decision = decision(selection)
    if selection == "e1":
        result_decision["text"] = "ICN"  # The test page's 'Search' field is not a permitted flight field.
    monkeypatch.setattr(loop, "choose", lambda *a, **kw: result_decision)
    monkeypatch.setattr(Agent, "__new__", staticmethod(lambda *a, **kw: runner))
    monkeypatch.setattr(Agent, "__init__", lambda *a, **kw: None)
    result = browser._run_job(job, lambda _: None)
    assert result.status == expected
    if mode == "wait":
        assert len(runner.state["history"]) == 50
    elif mode in {"captcha", "invalid"}:
        assert runner.state["history"] == []
