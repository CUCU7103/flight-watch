import json
import os
from datetime import date
from pathlib import Path

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
    monkeypatch.setattr(browser, "_daemon_ready", lambda name: True)
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


@pytest.mark.skipif(
    not os.environ.get("FLIGHT_WATCH_CHROME_TEST"), reason="실제 headless Chrome이 필요하다: FLIGHT_WATCH_CHROME_TEST=1"
)
def test_dedicated_browser_can_reopen_in_the_same_process():
    # 웹 API는 한 프로세스에서 검색마다 컨텍스트를 새로 연다. 두 번째 컨텍스트도 데몬을 찾아야 한다.
    from flight_scanner import browser

    for _ in range(2):
        with browser.dedicated_browser():
            assert os.environ["BU_NAME"].startswith("flight_scanner_")


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


CAPTURED = Path(__file__).parent / "fixtures/captured_fuk_20261014.json"


def captured_page() -> dict:
    return json.loads(CAPTURED.read_text())["page"]


def test_search_url_reproduces_the_url_google_generated(job):
    from flight_scanner.extract import search_url, verified_search

    page = captured_page()
    assert search_url(job) == page["url"]
    assert verified_search({**page, "url": search_url(job)}, job)


def direct_runner(runner, job, pages):
    """검색 URL로 바로 연 에이전트를 흉내 낸다. observe는 pages를 차례로 돌려준다."""
    runner.state["page"] = pages[0]
    runner.state["browser"].observe.side_effect = [*pages[1:], *[pages[-1]] * 50]
    runner.state["browser"].target = "owned-test-target"
    runner.browser = runner.state["browser"]
    runner.input_values = job.input_values()
    return runner


def forbidden_model(*a, **kw):
    raise AssertionError("검증된 결과 페이지에서는 모델을 호출하지 않는다")


def run_with(runner, monkeypatch, job, choose=forbidden_model):
    from flight_scanner import browser
    from jev_ultrafast import Agent
    from jev_ultrafast import agent as loop

    opened = []
    monkeypatch.setattr(loop, "choose", choose)
    monkeypatch.setattr(browser.time, "sleep", lambda _: None)
    monkeypatch.setattr(Agent, "__new__", staticmethod(lambda cls, url, *a, **kw: opened.append(url) or runner))
    monkeypatch.setattr(Agent, "__init__", lambda *a, **kw: None)
    return browser._run_job(job, lambda _: None), opened


def test_verified_results_page_finishes_without_model_calls(job, runner, monkeypatch):
    from flight_scanner.extract import search_url

    page = captured_page()
    result, opened = run_with(direct_runner(runner, job, [page, page]), monkeypatch, job)
    assert opened == [search_url(job)]
    assert (result.status, result.model_calls) == ("DONE", 0)
    assert min(option.price_krw for option in result.options) == 381_300


def test_partially_loaded_results_wait_until_stable(job, runner, monkeypatch):
    page = captured_page()
    cards = [i for i, a in enumerate(page["actions"]) if "select flight" in a["label"].lower()]
    partial = {**page, "actions": [a for i, a in enumerate(page["actions"]) if i not in cards[1:]]}
    result, _ = run_with(direct_runner(runner, job, [partial, page, page]), monkeypatch, job)
    assert result.status == "DONE"
    assert len(result.options) > 1  # 첫 관측의 카드 1장에서 멈추지 않는다


def test_captcha_on_results_page_is_blocked(job, runner, monkeypatch):
    page = {**captured_page(), "text": "Our systems have detected unusual traffic"}
    result, _ = run_with(direct_runner(runner, job, [page]), monkeypatch, job)
    assert (result.status, result.model_calls) == ("BLOCKED", 0)


def test_unverified_results_fall_back_to_the_agent(job, runner, monkeypatch):
    from flight_scanner import browser
    from flight_scanner.extract import search_url
    from tests.test_agent import decision

    # 결과 URL이지만 카드·검색 조건을 확인할 수 없는 페이지(에이전트 루프용 필드는 갖춘 가짜 페이지)
    page = {**runner.state["page"], "url": search_url(job)}
    monkeypatch.setattr(browser, "DIRECT_RESULTS_TIMEOUT", 0)
    calls = []
    choose = lambda *a, **kw: calls.append(True) or decision("DONE")  # noqa: E731
    result, _ = run_with(direct_runner(runner, job, [page]), monkeypatch, job, choose)
    # 에이전트가 DONE을 말해도 결과는 독립적으로 검증되므로 INVALID_RESULT다.
    assert calls and result.status == "INVALID_RESULT"
