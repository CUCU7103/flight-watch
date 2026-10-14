from dataclasses import replace
from datetime import date

import pytest

from flight_scanner.evaluate import evaluate, parse_evaluation, route
from flight_scanner.models import Evaluation, FlightOption, ScanJob


@pytest.fixture
def option():
    job = ScanJob("ICN", "FUK", date(2026, 11, 12), date(2026, 11, 15), 180_000)
    return FlightOption(
        job,
        175_000,
        "verified evidence",
        "https://www.google.com/travel/flights",
        outbound_verified=True,
        return_verified=True,
        baggage_known=True,
        max_layover_hours=0,
        airport_change=False,
    )


@pytest.fixture
def response():
    return {
        "model": "test",
        "usage": {"input_tokens": 20},
        "answers": {
            "is_real_promo": {"type": "noul", "noul": 0.9},
            "has_hidden_trap": {"type": "noul", "noul": 0.1},
            "deal_quality": {
                "type": "score",
                "score": 2.5,
                "confidence": 0.5,
                "probabilities": {"0": 0, "1": 0, "2": 0.5, "3": 0.5, "4": 0},
            },
            "next_action": {
                "type": "choice",
                "choice": "SEND_URGENT_ALERT",
                "confidence": 1,
                "probabilities": {"SEND_URGENT_ALERT": 1, "SAVE_TO_DAILY_DIGEST": 0, "DISCARD": 0},
            },
        },
    }


def test_score_is_converted_from_zero_based_scale(response):
    result = parse_evaluation(response)
    assert result.deal_quality == 3.5
    assert result.is_real_promo == 0.9


@pytest.mark.parametrize(
    "mutation", ["missing", "nan", "score_range", "unknown_action", "score_distribution", "boolean"]
)
def test_malformed_evaluation_is_rejected(response, mutation):
    if mutation == "missing":
        del response["answers"]["is_real_promo"]
    elif mutation == "nan":
        response["answers"]["has_hidden_trap"]["noul"] = float("nan")
    elif mutation == "score_range":
        response["answers"]["deal_quality"]["score"] = 9
    elif mutation == "unknown_action":
        response["answers"]["next_action"]["choice"] = "BOOK_NOW"
    elif mutation == "score_distribution":
        response["answers"]["deal_quality"]["probabilities"]["4"] = 1
    else:
        response["answers"]["is_real_promo"]["noul"] = True
    with pytest.raises(ValueError):
        parse_evaluation(response)


def test_gate_boundary_and_incomplete_evidence(option):
    evaluation = Evaluation(0.8, 0.2, 3.5, "SEND_URGENT_ALERT")
    assert route(evaluation, option) == "SEND_URGENT_ALERT"
    assert route(replace(evaluation, is_real_promo=0.79), option) == "SAVE_TO_DAILY_DIGEST"
    assert route(replace(evaluation, has_hidden_trap=0.21), option) == "SAVE_TO_DAILY_DIGEST"
    assert route(replace(evaluation, deal_quality=3.49), option) == "SAVE_TO_DAILY_DIGEST"
    assert route(evaluation, replace(option, price_krw=180_001)) == "DISCARD"
    assert route(evaluation, replace(option, baggage_known=False)) == "SAVE_TO_DAILY_DIGEST"
    assert route(evaluation, replace(option, max_layover_hours=8)) == "DISCARD"
    assert route(evaluation, replace(option, airport_change=True)) == "DISCARD"
    assert route(replace(evaluation, next_action="DISCARD"), option) == "DISCARD"


def test_evaluator_sends_only_scoped_option_and_uses_single_request(option, response, monkeypatch):
    from jev_ultrafast import model

    requests = []

    def post(url, key, body):
        requests.append(body)
        return response

    monkeypatch.setattr(model, "post_json", post)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    assert evaluate(option).deal_quality == 3.5
    assert len(requests) == 1
    assert requests[0]["state"]["evidence"] == "verified evidence"
    assert isinstance(requests[0]["questions"]["deal_quality"]["criteria"], list)
