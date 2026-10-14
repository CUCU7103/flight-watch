"""Synthetic fixtures: false prices and incomplete itineraries must fail closed."""

import base64
from copy import deepcopy
from datetime import date

import pytest

from flight_scanner.extract import extract_options
from flight_scanner.models import ScanJob, generate_jobs


def field(number, text):
    data = text.encode() if isinstance(text, str) else text
    assert len(data) < 128
    return bytes([number * 8 + 2, len(data)]) + data


def search_url(dep="2026-11-12", ret="2026-11-15", origin="ICN", dest="FUK", adults=1, cabin=1):
    def leg(day, orig, dst):
        return field(2, day) + field(13, field(2, orig)) + field(14, field(2, dst))

    payload = (
        field(3, leg(dep, origin, dest)) + field(3, leg(ret, dest, origin)) + bytes([16, 2, 64, adults, 72, cabin])
    )
    return "https://www.google.com/travel/flights/search?curr=KRW&tfs=" + base64.urlsafe_b64encode(payload).decode()


@pytest.fixture
def job():
    return ScanJob("ICN", "FUK", date(2026, 11, 12), date(2026, 11, 15), 180_000)


@pytest.fixture
def snapshot():
    return {
        "url": search_url(),
        "title": "Flights",
        "text": "Calendar ₩70,000. From ₩90,000",
        "actions": [
            {"id": "type", "kind": "click", "label": "Change ticket type. Round trip", "value": "Round trip"},
            {"id": "adults", "kind": "click", "label": "1 passenger", "value": ""},
            {"id": "cabin", "kind": "click", "label": "Change cabin class. Economy", "value": "Economy"},
            {
                "id": "flight1",
                "kind": "click",
                "node": 10,
                "label": "Select flight. ICN -> FUK 2026-11-12. ₩175,000 round trip",
            },
        ],
        "guards": {"10": ["Select flight. ICN to FUK. ₩175,000 round trip. Nonstop. 2 hr. Carry-on bag included."]},
    }


def test_generate_ten_future_jobs():
    jobs = generate_jobs(date(2026, 11, 12), 5, 3, today=date(2026, 10, 14))
    assert len(jobs) == 10
    assert jobs[0].return_date == date(2026, 11, 15)
    assert {j.target_price_krw for j in jobs} == {180_000, 250_000}


@pytest.mark.parametrize("days,nights", [(0, 3), (5, 0), (-1, 2), (5, -1), (91, 3)])
def test_invalid_scan_ranges_rejected(days, nights):
    with pytest.raises(ValueError):
        generate_jobs(date(2026, 11, 12), days, nights, today=date(2026, 10, 14))


def test_past_departure_rejected():
    with pytest.raises(ValueError):
        generate_jobs(date(2026, 10, 13), 5, 3, today=date(2026, 10, 14))


@pytest.mark.parametrize("adults,cabin", [(0, 1), (2, 1), (1, 2)])
def test_query_passenger_and_cabin_must_match_even_if_ui_looks_correct(job, snapshot, adults, cabin):
    snapshot["url"] = search_url(adults=adults, cabin=cabin)
    assert extract_options(snapshot, job) == []


def test_extract_only_scoped_round_trip_price(job, snapshot):
    options = extract_options(snapshot, job)
    assert len(options) == 1
    assert options[0].price_krw == 175_000
    assert options[0].conditions_complete is False
    assert options[0].evidence.startswith("Select flight")


@pytest.mark.parametrize("price", ["₩175,000", "KRW 175,000", "KRW 175000"])
def test_price_formats(job, snapshot, price):
    snapshot["guards"]["10"][-1] = f"Select flight. {price} round trip"
    assert extract_options(snapshot, job)[0].price_krw == 175_000


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_date",
        "wrong_airport",
        "one_way",
        "two_adults",
        "wrong_currency",
        "no_results",
        "bad_url",
        "ambiguous_card",
    ],
)
def test_unverified_results_do_not_become_candidates(job, snapshot, mutation):
    if mutation == "wrong_date":
        snapshot["url"] = search_url(dep="2026-11-13")
    elif mutation == "wrong_airport":
        snapshot["url"] = search_url(origin="GMP")
    elif mutation == "one_way":
        snapshot["actions"][0]["value"] = "One way"
    elif mutation == "two_adults":
        snapshot["actions"][1]["label"] = "2 passengers"
    elif mutation == "wrong_currency":
        snapshot["guards"]["10"][-1] = "Select flight. $175 round trip"
    elif mutation == "no_results":
        snapshot["actions"] = snapshot["actions"][:3]
    elif mutation == "bad_url":
        snapshot["url"] = "https://evil.test/travel/flights/search"
    else:
        snapshot["guards"]["10"][-1] = "Select flight. ₩175,000 round trip. Another flight ₩90,000 round trip"
    assert extract_options(snapshot, job) == []


def test_missing_total_fare_basis_is_rejected(job, snapshot):
    snapshot["guards"]["10"][-1] = "Select flight ₩175,000 per person one way"
    assert extract_options(snapshot, job) == []


def test_card_scope_without_price_does_not_fall_back_to_global_min(job, snapshot):
    snapshot["guards"]["10"][-1] = "Flight details without price"
    assert extract_options(snapshot, job) == []


def test_current_google_seating_class_label_is_recognized(job, snapshot):
    snapshot["actions"][2]["label"] = "Change seating class. Economy"
    assert extract_options(snapshot, job)[0].price_krw == 175_000


def test_same_scope_deduplicates_options(job, snapshot):
    extra = deepcopy(snapshot["actions"][-1])
    extra["id"] = "flight2"
    snapshot["actions"].append(extra)
    assert len(extract_options(snapshot, job)) == 1


def test_incomplete_or_malformed_tfs_is_rejected(job, snapshot):
    snapshot["url"] = "https://www.google.com/travel/flights/search?tfs=___"
    assert extract_options(snapshot, job) == []


def test_full_observed_itinerary_verifies_conditions(job, snapshot):
    snapshot["guards"]["10"][-1] = (
        "Select flight. KRW 175000 round trip\n"
        "Outbound: ICN -> FUK 2026-11-12 Nonstop\n"
        "Return: FUK -> ICN 2026-11-15 Nonstop\n"
        "Baggage: carry-on included; checked bag included."
    )
    option = extract_options(snapshot, job)[0]
    assert option.conditions_complete is True
    assert option.max_layover_hours == 0
    assert option.airport_change is False


def test_other_itinerary_conditions_do_not_verify_return(job, snapshot):
    snapshot["guards"]["10"][-1] = (
        "Select flight. KRW 175000 round trip\n"
        "Outbound: ICN -> FUK 2026-11-12 Nonstop\n"
        "Return: FUK -> ICN 2026-11-16 Nonstop\n"
        "Baggage: carry-on included; checked bag included."
    )
    assert extract_options(snapshot, job) == []


def test_card_date_is_required_even_when_query_dates_match(job, snapshot):
    snapshot["actions"][-1]["label"] = "Select flight ICN -> FUK"
    assert extract_options(snapshot, job) == []


def test_card_explicit_wrong_departure_is_rejected(job, snapshot):
    snapshot["actions"][-1]["label"] = "Select flight ICN -> FUK 2026-11-13"
    assert extract_options(snapshot, job) == []


def test_malformed_date_cannot_match_by_prefix(job, snapshot):
    snapshot["actions"][-1]["label"] = "Select flight ICN -> FUK 2026-11-120"
    assert extract_options(snapshot, job) == []


def test_incomplete_button_label_does_not_hide_complete_label_in_same_card(job, snapshot):
    full = deepcopy(snapshot["actions"][-1])
    full["id"] = "full-label"
    snapshot["actions"][-1]["label"] = "Select flight"
    snapshot["actions"].append(full)
    assert extract_options(snapshot, job)[0].price_krw == 175_000


def test_captured_google_outbound_cards_bind_route_date_and_price(job):
    import json
    from pathlib import Path

    captured = json.loads((Path(__file__).parent / "fixtures/captured_fuk_20261014.json").read_text())
    options = extract_options(captured["page"], job)
    assert options[0].price_krw == 381_300
    assert options[0].outbound_verified is True
    assert options[0].return_verified is False
    assert options[0].conditions_complete is False
