"""Opt-in real Redis tests. Use a disposable server; never flush or enumerate its keys."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import httpx
import pytest
import redis

from flight_scanner.models import Evaluation
from flight_scanner.notify import FINISH, RELEASE, fingerprint, notify

pytestmark = pytest.mark.skipif(not os.environ.get("REDIS_TEST_URL"), reason="Needs a disposable REDIS_TEST_URL")


@pytest.fixture
def store(option):
    option = replace(option, evidence=option.evidence + " integration-" + uuid.uuid4().hex)
    client = redis.Redis.from_url(
        os.environ["REDIS_TEST_URL"], decode_responses=True, socket_connect_timeout=2, socket_timeout=2
    )
    key = "flight_alert:" + fingerprint(option)
    try:
        client.ping()
        yield client, option, key
    finally:
        client.delete(key)
        client.close()


def test_real_redis_atomic_delivery_and_expiry(store, monkeypatch):
    client, option, key = store
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/test")
    sent = []

    def post(*args, **kwargs):
        sent.append(kwargs["json"])
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(httpx, "post", post)
    evaluation = Evaluation(0.9, 0.1, 4, "SEND_URGENT_ALERT")
    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(lambda _: notify(option, evaluation, redis_client=client), range(3)))
    assert outcomes.count("SENT") == 1
    assert outcomes.count("DUPLICATE") == 2
    assert len(sent) == 1
    assert 21_590 <= client.ttl(key) <= 21_600
    client.pexpire(key, 1)
    import time

    time.sleep(0.01)
    assert notify(option, evaluation, redis_client=client) == "SENT"
    assert len(sent) == 2


def test_real_lua_cannot_release_or_finalize_another_owners_claim(store):
    client, _, key = store
    client.set(key, "claim:new", ex=60)
    assert client.eval(RELEASE, 1, key, "claim:old") == 0
    assert client.eval(FINISH, 1, key, "claim:old", "sent", 21_600) == 0
    assert client.get(key) == "claim:new"
    assert client.eval(FINISH, 1, key, "claim:new", "sent", 21_600) == "OK"
    assert client.get(key) == "sent"
