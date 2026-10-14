"""웹 API 테스트. fixture 재생과 가짜 runner만 쓰며 유료 API·Chrome·네트워크를 쓰지 않는다."""

import threading
import time
from datetime import date
from pathlib import Path

import httpx
import pytest
import redis
from fastapi.testclient import TestClient

from flight_scanner import cli
from flight_scanner.api import MAX_JOBS, create_app, fixture_runner

FIXTURE = Path(__file__).parent / "fixtures/verified_roundtrip.json"
# fixture가 담은 작업: ICN → FUK, 2026-11-12 ~ 2026-11-15, 목표가 180,000원.
FIXTURE_REQUEST = {"origin": "icn", "destinations": ["fuk"], "start": "2026-11-12", "days": 1, "nights": 3}


@pytest.fixture(autouse=True)
def future_fixture_date():
    if date.fromisoformat(FIXTURE_REQUEST["start"]) <= date.today():
        pytest.skip("fixture 출발일이 지나 generate_jobs가 거부한다")


def wait_until_finished(client: TestClient, scan_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        scan = client.get(f"/api/scans/{scan_id}").json()
        if scan["status"] in {"done", "failed"}:
            return scan
        time.sleep(0.01)
    raise AssertionError("scan did not finish")


def test_fixture_scan_runs_end_to_end_without_sending_alerts(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("웹 MVP는 유료 평가·Slack·Redis를 쓰지 않는다")

    monkeypatch.setattr(cli, "evaluate", forbidden)
    monkeypatch.setattr(httpx, "post", forbidden)
    monkeypatch.setattr(redis.Redis, "from_url", forbidden)
    client = TestClient(create_app(fixture_runner(FIXTURE), requires_api_key=False))

    started = client.post("/api/scans", json=FIXTURE_REQUEST)
    assert started.status_code == 202
    assert started.json()["job_count"] == 1
    assert wait_until_finished(client, started.json()["id"])["status"] == "done"

    [row] = client.get(f"/api/scans/{started.json()['id']}/results").json()["results"]
    assert row["selected"]["price_krw"] == 175_000
    assert row["action"] == "SEND_URGENT_ALERT"
    assert row["notification"] == "DRY_RUN"


def test_second_scan_is_rejected_while_one_is_running():
    release = threading.Event()

    def blocking_runner(jobs):
        release.wait(5)
        return []

    client = TestClient(create_app(blocking_runner, requires_api_key=False))
    first = client.post("/api/scans", json=FIXTURE_REQUEST)
    assert client.post("/api/scans", json=FIXTURE_REQUEST).status_code == 409
    release.set()
    wait_until_finished(client, first.json()["id"])
    assert client.post("/api/scans", json=FIXTURE_REQUEST).status_code == 202


@pytest.mark.parametrize(
    "change",
    [
        {"destinations": ["KIX"]},  # FUK/NRT 외 노선인데 목표가가 없다
        {"start": "2020-01-01"},  # 과거 출발일
        {"nights": 0},
        {"origin": "FUK"},  # 출발지와 도착지가 같다
        {"origin": "SEOUL"},  # IATA 형식이 아니다
        {"days": MAX_JOBS + 1},  # 비용 가드
        {"destinations": []},
    ],
)
def test_invalid_requests_are_rejected_before_running(change):
    calls = []
    client = TestClient(create_app(lambda jobs: calls.append(jobs) or [], requires_api_key=False))
    assert client.post("/api/scans", json={**FIXTURE_REQUEST, **change}).status_code == 422
    assert calls == []


def test_live_scan_requires_api_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    client = TestClient(create_app(lambda jobs: [], requires_api_key=True))
    assert client.post("/api/scans", json=FIXTURE_REQUEST).status_code == 503


def test_runner_failure_is_recorded_by_type_only():
    def failing_runner(jobs):
        raise RuntimeError("provider body with secret")

    client = TestClient(create_app(failing_runner, requires_api_key=False))
    scan = wait_until_finished(client, client.post("/api/scans", json=FIXTURE_REQUEST).json()["id"])
    assert (scan["status"], scan["error"]) == ("failed", "RuntimeError")
    # 실패 뒤에도 잠금이 풀려 다음 검색을 받을 수 있다.
    assert client.post("/api/scans", json=FIXTURE_REQUEST).status_code == 202


def test_unknown_scan_is_not_found():
    client = TestClient(create_app(lambda jobs: [], requires_api_key=False))
    assert client.get("/api/scans/missing").status_code == 404
    assert client.get("/api/scans/missing/results").status_code == 404
