"""여행 코스: 확인된 항공권의 도착 공항·날짜·도착 시각으로 Gemini에 일자별 코스를 받아 코드가 검증한다.

모델에는 코드가 만든 구조화 값만 보낸다. 화면 원문(evidence)은 신뢰할 수 없는 입력이라 넘기지 않는다.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .models import airport_name

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
# 카드 텍스트의 "5:25 PM – 6:50 PM" 형태. 익일 도착이면 두 번째 시각 뒤에 "+1"이 붙는다.
CLOCK = re.compile(r"\b(\d{1,2}:\d{2})\s*([AP]M)\s*(\+\d)?", re.I)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class Stop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: Literal["오전", "오후", "저녁"]
    place: Name
    note: Text


class Day(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: int
    title: Name
    stops: list[Stop] = Field(min_length=1, max_length=4)


class Itinerary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area: Name
    days: list[Day]


@dataclass(frozen=True)
class Trip:
    destination: str
    departure_date: date
    return_date: date
    # 가는 편 도착 시각(HH:MM, 현지). 읽지 못했거나 익일 도착이면 None.
    arrival_time: str | None

    @property
    def nights(self) -> int:
        return (self.return_date - self.departure_date).days


# 여행 정보를 받아 검증된 코스를 돌려주는 함수(api.create_app에 주입).
Planner = Callable[[Trip], Itinerary]


def outbound_arrival(evidence: str) -> str | None:
    """가는 편 카드 텍스트에서 도착 시각(두 번째 시각)을 24시간제로. 익일 도착·형식 불명이면 None."""
    clocks = CLOCK.findall(evidence)
    if len(clocks) < 2:
        return None
    clock, meridiem, next_day = clocks[1]
    if next_day:
        # ponytail: 익일 도착은 도착 날짜가 바뀌므로 시각을 버린다. 심야편을 다루게 되면 날짜도 옮긴다.
        return None
    return datetime.strptime(f"{clock} {meridiem.upper()}", "%I:%M %p").strftime("%H:%M")


def prompt(trip: Trip) -> str:
    arrival = f"{trip.arrival_time} 도착" if trip.arrival_time else "도착 시각 미확인(오후 도착으로 가정)"
    return (
        f"{airport_name(trip.destination)} 공항으로 가는 {trip.nights}박 {trip.nights + 1}일 "
        "여행 코스를 한국어로 짜 줘.\n"
        f"- 첫날({trip.departure_date.isoformat()}): {arrival}. 공항에서 시내까지 이동 시간을 빼고 계획한다.\n"
        f"- 마지막 날({trip.return_date.isoformat()}): 귀국편 출발 시각을 모르므로 "
        "오전 일정만 넣고 공항으로 이동한다.\n"
        "- 도착 공항에서 당일 이동할 수 있는 권역 안에서만 계획한다. 같은 나라의 먼 도시는 넣지 않는다.\n"
        "- 실제로 존재하는 대표 관광지·거리·음식만 쓴다. 확실하지 않은 장소는 넣지 않는다.\n"
        "- 가격, 예약, 운영 시간, URL은 쓰지 않는다.\n"
        f"- days는 day 1부터 {trip.nights + 1}까지 하루에 하나씩, 각 날 stops는 1~4개다."
    )


def parse_itinerary(text: str, trip: Trip) -> Itinerary:
    """모델 응답을 스키마와 일정 길이로 검증한다. 맞지 않으면 ValueError(pydantic 포함)."""
    itinerary = Itinerary.model_validate_json(text)
    if [day.day for day in itinerary.days] != list(range(1, trip.nights + 2)):
        raise ValueError("Itinerary days do not match the trip")
    return itinerary


def gemini_planner(api_key: str, model: str = DEFAULT_GEMINI_MODEL) -> Planner:
    from google import genai

    client = genai.Client(api_key=api_key)

    def plan(trip: Trip) -> Itinerary:
        # ponytail: SDK가 429·5XX를 백오프로 최대 4번 재시도해 한도 초과 안내가 수십 초 늦을 수 있다.
        # 공개 API에 재시도 설정이 없어 그대로 두고, 요청마다 시간 상한만 건다.
        interaction = client.interactions.create(
            model=model,
            timeout=20,
            input=prompt(trip),
            response_format={"type": "text", "mime_type": "application/json", "schema": Itinerary.model_json_schema()},
        )
        # 스트리밍을 켜지 않았으므로 Interaction이 오지만, SDK 반환 타입이 스트림과 합쳐져 있어 속성으로 읽는다.
        return parse_itinerary(getattr(interaction, "output_text", None) or "", trip)

    return plan
