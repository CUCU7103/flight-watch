"""여행 코스 테스트. 가짜 planner만 쓰며 Gemini·네트워크를 쓰지 않는다."""

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from flight_scanner.api import create_app, fixture_runner
from flight_scanner.itinerary import Itinerary, Trip, outbound_arrival, parse_itinerary, prompt

from .test_api import FIXTURE, FIXTURE_REQUEST, TODAY, wait_until_finished

TRIP = Trip("FUK", date(2026, 11, 12), date(2026, 11, 15), "18:50")


def itinerary_json(days: int) -> str:
    return json.dumps(
        {
            "area": "후쿠오카",
            "days": [
                {"day": n, "title": f"{n}일차", "stops": [{"slot": "오전", "place": "하카타", "note": "산책"}]}
                for n in range(1, days + 1)
            ],
        },
        ensure_ascii=False,
    )


def test_arrival_time_comes_from_the_captured_card_text():
    # 2026-10-14 실검색 캡처의 가는 편 카드 텍스트
    card = "5:25 PM\n\xa0–\xa0\n6:50 PM\nJin Air\n1 hr 25 min\nICN–FUK\nNonstop\n₩381,300\nround trip"
    assert outbound_arrival(card) == "18:50"


@pytest.mark.parametrize(
    "evidence",
    ["11:50 PM – 2:10 AM+1", "11:50 PM\n–\n2:10 AM\n+1", "Outbound: ICN -> FUK 2026-11-12 Nonstop", "6:50 PM"],
)
def test_next_day_or_unreadable_arrival_is_unknown(evidence):
    assert outbound_arrival(evidence) is None


def test_prompt_uses_only_structured_trip_values():
    text = prompt(TRIP)
    assert "Fukuoka (FUK)" in text and "3박 4일" in text and "18:50 도착" in text
    assert "도착 시각 미확인" in prompt(Trip("FUK", TRIP.departure_date, TRIP.return_date, None))


def test_itinerary_must_cover_every_day_of_the_trip():
    assert len(parse_itinerary(itinerary_json(4), TRIP).days) == 4
    with pytest.raises(ValueError):
        parse_itinerary(itinerary_json(3), TRIP)


@pytest.mark.parametrize(
    "broken",
    [
        "not json",
        itinerary_json(4).replace('"오전"', '"새벽"'),  # 허용하지 않은 시간대
        itinerary_json(4).replace('"area"', '"url": "https://example.com", "area"'),  # 추가 필드
        itinerary_json(4).replace('"산책"', '"' + "가" * 201 + '"'),  # 길이 상한
    ],
)
def test_malformed_model_output_is_rejected(broken):
    with pytest.raises(ValueError):
        parse_itinerary(broken, TRIP)


def scanned_client(planner):
    client = TestClient(
        create_app(fixture_runner(FIXTURE), requires_api_key=False, today=TODAY, planner=planner),
        base_url="http://localhost",
    )
    scan_id = client.post("/api/scans", json=FIXTURE_REQUEST).json()["id"]
    wait_until_finished(client, scan_id)
    return client, scan_id


def test_itinerary_is_built_from_the_server_row_and_cached():
    calls: list[Trip] = []

    def planner(trip: Trip) -> Itinerary:
        calls.append(trip)
        return parse_itinerary(itinerary_json(trip.nights + 1), trip)

    client, scan_id = scanned_client(planner)
    assert client.get("/api/config").json()["itinerary_enabled"] is True
    for _ in range(2):
        response = client.post("/api/itineraries", json={"scan_id": scan_id, "index": 0})
        assert response.status_code == 200
    # fixture 카드에는 시각이 없어 도착 시각은 미확인이다.
    assert calls == [Trip("FUK", date(2026, 11, 12), date(2026, 11, 15), None)]
    assert response.json()["trip"]["nights"] == 3 and len(response.json()["itinerary"]["days"]) == 4


def test_itinerary_requests_are_validated():
    client, scan_id = scanned_client(lambda trip: parse_itinerary(itinerary_json(trip.nights + 1), trip))
    assert client.post("/api/itineraries", json={"scan_id": "missing", "index": 0}).status_code == 404
    assert client.post("/api/itineraries", json={"scan_id": scan_id, "index": 1}).status_code == 422
    assert client.post("/api/itineraries", json={"scan_id": scan_id, "index": "0"}).status_code == 422


def test_itinerary_is_unavailable_without_a_planner():
    client, scan_id = scanned_client(None)
    assert client.post("/api/itineraries", json={"scan_id": scan_id, "index": 0}).status_code == 503


class QuotaError(Exception):
    status_code = 429


@pytest.mark.parametrize(
    "error,status",
    [(QuotaError("secret body"), 429), (ValueError("bad"), 502), (RuntimeError("secret body"), 502)],
)
def test_planner_failures_hide_provider_details(error, status):
    def planner(trip):
        raise error

    client, scan_id = scanned_client(planner)
    response = client.post("/api/itineraries", json={"scan_id": scan_id, "index": 0})
    assert response.status_code == status
    assert "secret" not in response.text
