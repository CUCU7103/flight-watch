"""웹 API 테스트. fixture 재생과 가짜 runner만 쓰며 유료 API·Chrome·네트워크를 쓰지 않는다."""

import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import date
from pathlib import Path

import httpx
import pytest
import redis
from fastapi.testclient import TestClient

from flight_scanner import api
from flight_scanner.api import MAX_JOBS, create_app, fixture_runner
from flight_scanner.models import Evaluation, ScanResult

FIXTURE = Path(__file__).parent / "fixtures/verified_roundtrip.json"
# fixture가 담은 작업: ICN → FUK, 2026-11-12 ~ 2026-11-15, 목표가 180,000원.
FIXTURE_REQUEST = {"origin": "icn", "destinations": ["fuk"], "start": "2026-11-12", "days": 1, "nights": 3}
# fixture 출발일이 지나도 테스트가 skip되지 않도록 "오늘"을 고정한다.
TODAY = date(2026, 10, 14)


def client_for(runner, *, requires_api_key=False) -> TestClient:
    app = create_app(runner, requires_api_key=requires_api_key, today=TODAY)
    return TestClient(app, base_url="http://localhost")


def wait_until_finished(client: TestClient, scan_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        scan = client.get(f"/api/scans/{scan_id}").json()
        if scan["status"] in {"done", "failed"}:
            return scan
        time.sleep(0.01)
    raise AssertionError("scan did not finish")


def test_fixture_scan_runs_end_to_end():
    client = client_for(fixture_runner(FIXTURE))

    started = client.post("/api/scans", json=FIXTURE_REQUEST)
    assert started.status_code == 202
    # fixture는 즉시 끝나지만 응답은 항상 queued여야 프론트가 폴링을 시작한다.
    assert (started.json()["status"], started.json()["job_count"]) == ("queued", 1)
    scan = wait_until_finished(client, started.json()["id"])
    assert scan["status"] == "done" and scan["finished_at"]

    [row] = client.get(f"/api/scans/{started.json()['id']}/results").json()["results"]
    assert row["selected"]["price_krw"] == 175_000
    assert row["action"] == "SEND_URGENT_ALERT"
    assert row["notification"] == "DRY_RUN"


def test_live_runner_never_sends_slack_or_touches_redis(monkeypatch, option):
    def forbidden(*args, **kwargs):
        raise AssertionError("웹 경로는 Slack·Redis를 쓰지 않는다")

    evaluation = Evaluation(0.95, 0.05, 4.5, "SEND_URGENT_ALERT")
    monkeypatch.setattr(api, "run_jobs", lambda jobs, workers: [ScanResult(job, "DONE", [option]) for job in jobs])
    monkeypatch.setattr("flight_scanner.cli.evaluate", lambda option: evaluation)
    monkeypatch.setattr(httpx, "post", forbidden)
    monkeypatch.setattr(redis.Redis, "from_url", forbidden)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

    [row] = api.live_runner(api.WarmBrowser(open_browser=nullcontext))([option.job])
    assert (row["action"], row["notification"]) == ("SEND_URGENT_ALERT", "DRY_RUN")


class FakeBrowserContext:
    """dedicated_browser() 대신 열고 닫힌 횟수를 센다."""

    def __init__(self):
        self.opened = self.closed = 0

    @contextmanager
    def open(self):
        self.opened += 1
        try:
            yield
        finally:
            self.closed += 1


@pytest.mark.parametrize("alive,expected_opens", [(True, 1), (False, 2)])
def test_warm_browser_reuses_a_live_browser_and_reopens_a_dead_one(monkeypatch, alive, expected_opens):
    fake = FakeBrowserContext()
    monkeypatch.setattr(api, "daemon_ready", lambda name: alive)
    browser = api.WarmBrowser(open_browser=fake.open)
    browser.ensure()
    browser.ensure()
    assert (fake.opened, fake.closed) == (expected_opens, expected_opens - 1)
    browser.close()
    assert fake.closed == fake.opened


def test_server_shutdown_closes_the_warm_browser(monkeypatch):
    fake = FakeBrowserContext()
    monkeypatch.setattr(api, "daemon_ready", lambda name: True)
    browser = api.WarmBrowser(open_browser=fake.open)
    app = create_app(
        lambda jobs: browser.ensure() or [], requires_api_key=False, today=TODAY, on_shutdown=browser.close
    )
    with TestClient(app, base_url="http://localhost") as client:
        wait_until_finished(client, client.post("/api/scans", json=FIXTURE_REQUEST).json()["id"])
        assert (fake.opened, fake.closed) == (1, 0)  # 검색이 끝나도 열어 둔다
    assert fake.closed == 1  # 서버 종료(lifespan) 때 정리한다


def test_second_scan_is_rejected_while_one_is_running():
    release = threading.Event()

    def blocking_runner(jobs):
        release.wait(5)
        return []

    client = client_for(blocking_runner)
    first = client.post("/api/scans", json=FIXTURE_REQUEST)
    assert client.post("/api/scans", json=FIXTURE_REQUEST).status_code == 409
    release.set()
    wait_until_finished(client, first.json()["id"])
    assert client.post("/api/scans", json=FIXTURE_REQUEST).status_code == 202


@pytest.mark.parametrize(
    "change",
    [
        {"destinations": ["KIX"]},  # FUK/NRT 외 노선인데 목표가가 없다
        {"destinations": ["KIX"], "target_price_krw": 0},
        {"target_price_krw": 0},  # 0을 기본 목표가로 바꿔치기하지 않는다
        {"target_price_krw": -1},
        {"start": "2020-01-01"},  # 과거 출발일
        {"nights": 0},
        {"origin": "FUK"},  # 출발지와 도착지가 같다
        {"origin": "SEOUL"},  # IATA 형식이 아니다
        {"days": MAX_JOBS + 1},  # 비용 가드
        {"destinations": []},
        {"destinations": ["FUK"] * (MAX_JOBS + 1)},
        {"destinations": ["FU1"]},
        {"days": True},  # 엄격한 타입: bool·문자열 숫자·실수·시각을 받지 않는다
        {"days": "1"},
        {"target_price_krw": 1.5},
        {"start": "2027-09-07"},  # 귀국일(09-10)이 기준일로부터 330일(09-09)을 넘는다
        {"start": "2026-11-12T00:00:00"},  # 시각이 붙은 날짜
        {"start": "1794441600"},  # 10자리 숫자 문자열
        {"start": 1794441600},  # 유닉스 타임스탬프
        {"start": "9999-12-31"},  # 날짜 계산이 넘쳐도 500이 아니라 422
        {"target_price": 1},  # 오타 필드를 조용히 무시하지 않는다
    ],
)
def test_invalid_requests_are_rejected_before_running(change):
    calls = []
    client = client_for(lambda jobs: calls.append(jobs) or [])
    assert client.post("/api/scans", json={**FIXTURE_REQUEST, **change}).status_code == 422
    assert calls == []


def test_foreign_host_header_is_rejected():
    # DNS rebinding으로 외부 페이지가 loopback 서버를 호출하는 경로를 막는다.
    calls = []
    client = client_for(lambda jobs: calls.append(jobs) or [])
    response = client.post("/api/scans", json=FIXTURE_REQUEST, headers={"Host": "attacker.example:8000"})
    assert response.status_code == 400
    assert calls == []


def test_return_date_on_the_limit_is_accepted():
    client = client_for(lambda jobs: [])
    assert client.post("/api/scans", json={**FIXTURE_REQUEST, "start": "2027-09-06"}).status_code == 202


def test_malformed_runner_rows_release_the_lock():
    client = client_for(lambda jobs: [None])
    scan = wait_until_finished(client, client.post("/api/scans", json=FIXTURE_REQUEST).json()["id"])
    assert scan["status"] == "failed"
    assert client.post("/api/scans", json=FIXTURE_REQUEST).status_code == 202


def test_warm_browser_refuses_to_reopen_after_shutdown(monkeypatch):
    fake = FakeBrowserContext()
    monkeypatch.setattr(api, "daemon_ready", lambda name: True)
    browser = api.WarmBrowser(open_browser=fake.open)
    browser.ensure()
    browser.close()
    with pytest.raises(RuntimeError):
        browser.ensure()  # 종료 중 실행 중이던 검색이 Chrome을 다시 띄워 고아로 남기지 않는다
    assert (fake.opened, fake.closed) == (1, 1)


def test_live_scan_requires_api_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    client = client_for(lambda jobs: [], requires_api_key=True)
    assert client.post("/api/scans", json=FIXTURE_REQUEST).status_code == 503


def test_runner_failure_is_recorded_by_type_only():
    def failing_runner(jobs):
        raise RuntimeError("provider body with secret")

    client = client_for(failing_runner)
    scan = wait_until_finished(client, client.post("/api/scans", json=FIXTURE_REQUEST).json()["id"])
    assert (scan["status"], scan["error"]) == ("failed", "RuntimeError")
    # 종료 상태가 보이는 시점에는 잠금이 이미 풀려 있어야 한다.
    assert client.post("/api/scans", json=FIXTURE_REQUEST).status_code == 202


def test_thread_start_failure_releases_the_lock(monkeypatch):
    class BrokenThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    client = client_for(lambda jobs: [])
    monkeypatch.setattr(api.threading, "Thread", BrokenThread)
    with pytest.raises(RuntimeError):
        client.post("/api/scans", json=FIXTURE_REQUEST)
    monkeypatch.undo()
    assert client.post("/api/scans", json=FIXTURE_REQUEST).status_code == 202


def test_results_do_not_expose_provider_usage():
    row = {"status": "DONE", "usage": [{"secret": "x"}], "evaluation": {"deal_quality": 4.0, "usage": {"secret": "x"}}}
    client = client_for(lambda jobs: [row])
    scan_id = client.post("/api/scans", json=FIXTURE_REQUEST).json()["id"]
    wait_until_finished(client, scan_id)
    [public] = client.get(f"/api/scans/{scan_id}/results").json()["results"]
    assert public == {"status": "DONE", "evaluation": {"deal_quality": 4.0}}


def test_config_shares_defaults_with_the_web():
    config = client_for(lambda jobs: []).get("/api/config").json()
    assert config == {
        "default_targets_krw": {"FUK": 180_000, "NRT": 250_000},
        "max_jobs": MAX_JOBS,
        "max_days_ahead": 330,
    }


def test_unknown_scan_is_not_found():
    client = client_for(lambda jobs: [])
    assert client.get("/api/scans/missing").status_code == 404
    assert client.get("/api/scans/missing/results").status_code == 404
