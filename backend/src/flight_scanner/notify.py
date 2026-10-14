"""Redis claim ownership prevents concurrent duplicates; Slack has no exactly-once API."""

import hashlib
import json
import os
import uuid
from dataclasses import asdict
from urllib.parse import urlparse

import httpx
import redis

from .evaluate import route
from .models import Evaluation, FlightOption

TTL = 6 * 60 * 60
FINISH = """if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3]) else return 0 end"""
RELEASE = """if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1]) else return 0 end"""


def fingerprint(option: FlightOption) -> str:
    identity = {
        "source": "google_flights",
        "job": asdict(option.job),
        "adults": 1,
        "cabin": "economy",
        "price_krw": option.price_krw,
        "itinerary": " ".join(option.evidence.split()),
    }
    return hashlib.sha256(json.dumps(identity, default=str, sort_keys=True).encode()).hexdigest()


def notify(option: FlightOption, evaluation: Evaluation, *, dry_run: bool = False, redis_client=None) -> str:
    if route(evaluation, option) != "SEND_URGENT_ALERT":
        return "SKIPPED"
    if dry_run:
        return "DRY_RUN"
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    parsed = urlparse(webhook)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "hooks.slack.com"
        or parsed.port not in (None, 443)
        or not parsed.path.startswith("/services/")
        or parsed.username
        or parsed.password
    ):
        return "NOT_CONFIGURED"
    client = (
        redis_client
        if redis_client is not None
        else redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
            socket_connect_timeout=3,
            socket_timeout=3,
            decode_responses=True,
        )
    )
    key, token = "flight_alert:" + fingerprint(option), "claim:" + uuid.uuid4().hex
    delivery_started = False
    try:
        if not client.set(key, token, nx=True, ex=60):
            return "DUPLICATE"
        text = (
            f"✈️ {option.job.origin} → {option.job.destination} 왕복 특가\n"
            f"{option.job.departure_date} ~ {option.job.return_date} · 성인 1명 · 이코노미\n"
            f"왕복 총액 {option.price_krw:,}원 · 추천 {evaluation.deal_quality:.2f}/5\n"
            f"조회 {option.observed_at}\n{option.search_url}\n"
            "실시간 운임은 변동됩니다. 예약 사이트에서 최종 가격·수하물·일정을 다시 확인하세요."
        )
        try:
            delivery_started = True
            response = httpx.post(webhook, json={"text": text, "mrkdwn": False}, timeout=10, follow_redirects=False)
        except httpx.ConnectError:
            client.eval(RELEASE, 1, key, token)
            return "FAILED"
        except httpx.HTTPError:
            client.eval(FINISH, 1, key, token, "uncertain", TTL)
            return "UNCERTAIN"
        if response.status_code != 200:
            if 400 <= response.status_code < 500 and response.status_code != 408:
                client.eval(RELEASE, 1, key, token)
                return "FAILED"
            client.eval(FINISH, 1, key, token, "uncertain", TTL)
            return "UNCERTAIN"
        status = "SENT" if response.text.strip() == "ok" else "UNCERTAIN"
        if not client.eval(FINISH, 1, key, token, status.lower(), TTL):
            return "UNCERTAIN"
        return status
    except redis.RedisError:
        return "UNCERTAIN" if delivery_started else "DEFERRED"
    finally:
        if redis_client is None:
            client.close()
