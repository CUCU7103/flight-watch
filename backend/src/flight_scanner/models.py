"""Validated jobs and the small contract shared by the scanner stages."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

FLIGHTS_URL = "https://www.google.com/travel/flights?hl=en&curr=KRW&gl=kr"
DEFAULT_MODEL = "jev-1.13.0"
AIRPORTS = {"ICN": "Seoul Incheon", "FUK": "Fukuoka", "NRT": "Tokyo Narita"}
DEFAULT_TARGETS_KRW = {"FUK": 180_000, "NRT": 250_000}


def airport_name(code: str) -> str:
    return f"{AIRPORTS[code]} ({code})" if code in AIRPORTS else code


@dataclass(frozen=True)
class ScanJob:
    origin: str
    destination: str
    departure_date: date
    return_date: date
    target_price_krw: int

    def __post_init__(self) -> None:
        if (
            not all(re.fullmatch(r"[A-Z]{3}", code) for code in (self.origin, self.destination))
            or self.origin == self.destination
            or self.return_date <= self.departure_date
            or type(self.target_price_krw) is not int
            or self.target_price_krw <= 0
        ):
            raise ValueError("Invalid route, date order or KRW target")

    def input_values(self) -> dict[str, str]:
        return {
            "Where from?": self.origin,
            "Where to?": self.destination,
            "Departure": self.departure_date.isoformat(),
            "Return": self.return_date.isoformat(),
        }

    def goal(self) -> str:
        return (
            f"Find round-trip flights from {airport_name(self.origin)} to "
            f"{airport_name(self.destination)} departing {self.departure_date.isoformat()} "
            f"and returning {self.return_date.isoformat()} for one adult in economy. "
            f"Set the origin to the exact {self.origin} airport, replacing any prefilled city or all-airports option. "
            f"Set the destination to the exact {self.destination} airport, not a city/all-airports option. "
            "Use supplied values when typing. Stop when matching flight options and KRW round-trip prices "
            "are visible. Never select or book a flight, sign in, pay, or visit an external booking website."
        )


@dataclass(frozen=True)
class FlightOption:
    job: ScanJob
    price_krw: int
    evidence: str
    search_url: str
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    outbound_verified: bool = False
    return_verified: bool = False
    baggage_known: bool = False
    max_layover_hours: float | None = None
    airport_change: bool | None = None

    @property
    def conditions_complete(self) -> bool:
        return (
            self.outbound_verified
            and self.return_verified
            and self.baggage_known
            and self.max_layover_hours is not None
            and self.airport_change is not None
        )


@dataclass(frozen=True)
class Evaluation:
    is_real_promo: float
    has_hidden_trap: float
    deal_quality: float  # Human-facing scale: 1–5, HTTP Score is 0–4.
    next_action: str
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanResult:
    job: ScanJob
    status: str
    options: list[FlightOption] = field(default_factory=list)
    elapsed_ms: int = 0
    model_calls: int = 0
    usage: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # 검색 URL 직행이 실패해 에이전트로 넘어간 이유(진단용). 직행으로 끝나면 None.
    fallback_reason: str | None = None
    # 최저가 항공권의 오는 편을 확인하지 못한 이유(진단용). 확인했거나 결과가 없으면 None.
    return_reason: str | None = None
    # Cheapest 탭에 표시된 최저가(참고용). 옵션 최저가보다 낮으면 화면 밖에 조건이 다른 더 싼 항공권이 있다.
    cheapest_tab_krw: int | None = None


def generate_jobs(
    start: date,
    days: int,
    nights: int,
    *,
    origin: str = "ICN",
    destinations: dict[str, int] | None = None,
    today: date | None = None,
) -> list[ScanJob]:
    if start <= (today or date.today()) or not 1 <= days <= 90 or not 1 <= nights <= 30:
        raise ValueError("Departure must be in the future; days 1–90 and nights 1–30")
    return [
        ScanJob(origin, dest, start + timedelta(days=i), start + timedelta(days=i + nights), target)
        for i in range(days)
        for dest, target in (destinations or DEFAULT_TARGETS_KRW).items()
    ]
