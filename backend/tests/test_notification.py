from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Lock

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from flight_scanner.models import Evaluation
from flight_scanner.notify import fingerprint, notify


class MemoryRedis:
    """Test-only Redis boundary with expiry and atomic compare-and-set."""

    def __init__(self):
        self.values = {}
        self.now = 0
        self.lock = Lock()

    def set(self, key, value, nx=False, ex=None):
        with self.lock:
            stored = self.values.get(key)
            if stored and stored[1] <= self.now:
                del self.values[key]
            if nx and key in self.values:
                return False
            self.values[key] = (value, self.now + ex)
            return True

    def eval(self, script, numkeys, key, token, *args):
        with self.lock:
            if self.values.get(key, (None, 0))[0] != token:
                return 0
            if args:
                self.values[key] = (args[0], self.now + int(args[1]))
            else:
                del self.values[key]
            return 1


@pytest.fixture
def evaluation():
    return Evaluation(0.9, 0.1, 4.0, "SEND_URGENT_ALERT")


@pytest.fixture
def delivery(monkeypatch):
    messages = []
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/test")

    def post(url, *, json, **kwargs):
        messages.append(json)
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(httpx, "post", post)
    return messages


def test_duplicate_and_simultaneous_delivery_send_once(option, evaluation, delivery):
    store = MemoryRedis()
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: notify(option, evaluation, redis_client=store), range(3)))
    assert results.count("SENT") == 1
    assert results.count("DUPLICATE") == 2
    assert len(delivery) == 1
    assert "175,000" in delivery[0]["text"]


def test_dry_run_does_not_claim_or_send(option, evaluation, delivery):
    store = MemoryRedis()
    assert notify(option, evaluation, dry_run=True, redis_client=store) == "DRY_RUN"
    assert store.values == {}
    assert delivery == []


def test_failed_http_can_retry_but_timeout_is_uncertain(option, evaluation, delivery, monkeypatch):
    store = MemoryRedis()
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Response(429))
    assert notify(option, evaluation, redis_client=store) == "FAILED"
    assert store.values == {}

    def timeout(*a, **kw):
        raise httpx.ReadTimeout("secret provider text")

    monkeypatch.setattr(httpx, "post", timeout)
    assert notify(option, evaluation, redis_client=store) == "UNCERTAIN"
    assert notify(option, evaluation, redis_client=store) == "DUPLICATE"


def test_redis_unavailable_defers_without_sending(option, evaluation, delivery):
    class BrokenRedis:
        def set(self, *a, **kw):
            raise RedisConnectionError("credential-containing error")

    assert notify(option, evaluation, redis_client=BrokenRedis()) == "DEFERRED"
    assert delivery == []


def test_redis_failure_after_webhook_is_uncertain_not_unsent(option, evaluation, delivery):
    class LateFailure(MemoryRedis):
        def eval(self, *args):
            raise RedisConnectionError("connection lost after webhook")

    assert notify(option, evaluation, redis_client=LateFailure()) == "UNCERTAIN"
    assert len(delivery) == 1


def test_webhook_5xx_is_uncertain_and_not_retried(option, evaluation, delivery, monkeypatch):
    calls = []

    def server_error(*a, **kw):
        calls.append(True)
        return httpx.Response(500)

    monkeypatch.setattr(httpx, "post", server_error)
    store = MemoryRedis()
    assert notify(option, evaluation, redis_client=store) == "UNCERTAIN"
    assert notify(option, evaluation, redis_client=store) == "DUPLICATE"
    assert len(calls) == 1


def test_expiry_allows_new_notification(option, evaluation, delivery):
    store = MemoryRedis()
    assert notify(option, evaluation, redis_client=store) == "SENT"
    store.now = 21_601
    assert notify(option, evaluation, redis_client=store) == "SENT"
    assert len(delivery) == 2


def test_return_date_is_part_of_fingerprint(option):
    from datetime import date

    changed = replace(option, job=replace(option.job, return_date=date(2026, 11, 16)))
    assert fingerprint(option) != fingerprint(changed)
    assert fingerprint(option) != fingerprint(replace(option, price_krw=174_000))


def test_notification_rechecks_gate_and_endpoint(option, evaluation, delivery, monkeypatch):
    store = MemoryRedis()
    assert notify(replace(option, baggage_known=False), evaluation, redis_client=store) == "SKIPPED"
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://evil.test/services/token")
    assert notify(option, evaluation, redis_client=store) == "NOT_CONFIGURED"
    assert delivery == []
