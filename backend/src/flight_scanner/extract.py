"""Fail-closed verification of Google Flights search state and observed card scopes."""

import base64
import binascii
import re
from datetime import date
from urllib.parse import parse_qs, urlparse

from .models import FlightOption, ScanJob

PRICE = re.compile(r"(?:₩|KRW\s*)(\d{1,3}(?:,\d{3})+|\d+)(?![\d,])")
# "Cheapest from 381300 South Korean won Learn more ..." 형태의 탭 라벨(2026-10-14 캡처).
CHEAPEST_TAB = re.compile(r"^Cheapest\s+from\s+(\d+)\s+South Korean won\b")
# "Layover (1 of 1) is a 2 hr 45 min layover at ..." (2026-10-17 캡처). 밤샘 경유의 "overnight"는 실측 전 가정이다.
LAYOVER = re.compile(r"Layover \((\d+) of (\d+)\) is an? (?:(\d+) hr ?)?(?:(\d+) min ?)?(?:overnight )?layover at ")
MONTHS = "January February March April May June July August September October November December".split()


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError("Invalid protobuf varint")


def _fields(data: bytes) -> dict[int, list]:
    fields: dict[int, list] = {}
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError("Invalid protobuf tag")
        value: int | bytes
        if wire == 0:
            value, offset = _varint(data, offset)
        elif wire == 2:
            length, offset = _varint(data, offset)
            if offset + length > len(data):
                raise ValueError("Truncated protobuf")
            value, offset = data[offset : offset + length], offset + length
        elif wire in {1, 5}:
            size = 8 if wire == 1 else 4
            if offset + size > len(data):
                raise ValueError("Truncated protobuf")
            value, offset = data[offset : offset + size], offset + size
        else:
            raise ValueError("Unsupported protobuf wire type")
        fields.setdefault(number, []).append(value)
    return fields


def _encode_varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 127:
        encoded.append(value & 127 | 128)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _encode_field(number: int, value: int | bytes) -> bytes:
    if isinstance(value, int):
        return _encode_varint(number << 3) + _encode_varint(value)
    return _encode_varint(number << 3 | 2) + _encode_varint(len(value)) + value


def search_url(job: ScanJob) -> str:
    """결과 페이지로 바로 가는 검색 URL. verified_search가 읽는 tfs 형식을 거꾸로 만든다.

    필드 구성은 2026-10-14 Google이 실제로 만든 URL(tests/fixtures/captured_fuk_20261014.json)과 같다.
    의미를 확인한 필드는 2(왕복), 3(구간: 날짜·출발·도착), 8(성인 1명), 9(이코노미)뿐이고 나머지는 그대로 재현한다.
    """

    def leg(day, origin: str, destination: str) -> bytes:
        def airport(code: str) -> bytes:
            return _encode_field(1, 1) + _encode_field(2, code.encode())

        return (
            _encode_field(2, day.isoformat().encode())
            + _encode_field(13, airport(origin))
            + _encode_field(14, airport(destination))
        )

    payload = b"".join(
        [
            _encode_field(1, 28),
            _encode_field(2, 2),
            _encode_field(3, leg(job.departure_date, job.origin, job.destination)),
            _encode_field(3, leg(job.return_date, job.destination, job.origin)),
            _encode_field(8, 1),
            _encode_field(9, 1),
            _encode_field(14, 1),
            _encode_field(16, _encode_field(1, 2**64 - 1)),
            _encode_field(19, 1),
        ]
    )
    tfs = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"https://www.google.com/travel/flights/search?tfs={tfs}&hl=en&gl=kr&curr=KRW"


def _verified_search_url(page: dict, job: ScanJob) -> bool:
    """검색 URL(tfs)이 이 작업의 왕복·성인 1명·일반석·두 구간인지. 화면 컨트롤은 보지 않는다."""
    parsed = urlparse(page.get("url", ""))
    if parsed.scheme != "https" or parsed.hostname != "www.google.com" or parsed.path != "/travel/flights/search":
        return False
    try:
        encoded = parse_qs(parsed.query)["tfs"][0]
        if len(encoded) > 20_000:
            return False
        payload = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        # shortcut: Google's undocumented tfs protobuf; fail closed and update fixtures when its schema changes.
        search = _fields(payload)
        if search.get(2) != [2] or search.get(8) != [1] or search.get(9) != [1]:
            return False  # Current observed schema: round trip, one adult, economy.
        legs = []
        for raw in search[3]:
            leg = _fields(raw)
            legs.append((leg[2][0].decode(), _fields(leg[13][0])[2][0].decode(), _fields(leg[14][0])[2][0].decode()))
        if legs != [
            (job.departure_date.isoformat(), job.origin, job.destination),
            (job.return_date.isoformat(), job.destination, job.origin),
        ]:
            return False
    except (KeyError, ValueError, IndexError, TypeError, AttributeError, UnicodeError, binascii.Error):
        return False
    return True


def verified_search(page: dict, job: ScanJob) -> bool:
    if not _verified_search_url(page, job):
        return False
    actions = page.get("actions", [])
    return (
        any("ticket type" in a.get("label", "").lower() and a.get("value") == "Round trip" for a in actions)
        and any(re.search(r"\b1 (?:passenger|adult)\b", a.get("label", ""), re.I) for a in actions)
        and any(
            re.search(r"(?:cabin|seating) class", a.get("label", ""), re.I) and a.get("value") == "Economy"
            for a in actions
        )
    )


def cheapest_tab_price(page: dict, job: ScanJob) -> int | None:
    """Cheapest 탭 라벨의 최저가. 화면 안의 카드보다 싼 항공권이 있는지 알려 주는 참고값이다.

    이 가격은 조건(공항 변경·수하물 등)을 확인할 수 없으므로 옵션으로 만들거나 판정에 쓰지 않는다.
    다른 노선·날짜의 값이 이 작업에 붙지 않도록 검색 조건이 검증된 페이지에서만 읽는다.
    """
    if not verified_search(page, job):
        return None
    for action in page.get("actions", []):
        if action.get("role") == "tab" and (match := CHEAPEST_TAB.match(action.get("label", ""))):
            return int(match[1])
    return None


def card_evidence(page: dict, action: dict) -> str | None:
    """항공권 카드("Select flight")가 감싼 화면 텍스트. 카드가 아니거나 읽을 수 없으면 None."""
    if "select flight" not in action.get("label", "").lower():
        return None
    guard = page.get("guards", {}).get(str(action.get("node")), [])
    if not guard or not isinstance(guard[-1], str):
        return None
    return guard[-1].strip()


def _card_price(evidence: str) -> int | None:
    """원화 왕복 합계가 정확히 하나로 읽히는 카드의 가격. 편도·"from" 가격·외화면 None."""
    if not re.search(r"round[ -]trip", evidence, re.I):
        return None
    if re.search(r"one[ -]way|\bfrom\s+(?:₩|KRW)|\$|\bUSD\b", evidence, re.I):
        return None
    prices = {int(match.replace(",", "")) for match in PRICE.findall(evidence)}
    if len(prices) != 1 or not 0 < next(iter(prices)) <= 5_000_000:
        return None
    return next(iter(prices))


def _route_shown(text: str, origin: str, destination: str) -> bool:
    return bool(re.search(rf"\b{origin}\s*(?:->|→|–|—|to|-)\s*{destination}\b", text))


def _leaves_on(label: str, day: date) -> bool:
    departure = re.search(
        r"\bLeaves\b.+?\bon\s+[A-Za-z]+,?\s+([A-Za-z]+)\s+(\d{1,2})"
        r"(?:,\s*(\d{4}))?",
        label,
    )
    return bool(re.search(rf"\b{day.isoformat()}\b", label)) or bool(
        departure
        and departure[1].lower() == MONTHS[day.month - 1].lower()
        and int(departure[2]) == day.day
        and (not departure[3] or int(departure[3]) == day.year)
    )


def layover_hours(label: str) -> float | None:
    """카드 라벨에서 가장 긴 경유 시간. 직항이면 0, 경유 문구를 전부 읽지 못하면 None(fail-closed).

    "1 stop flight with ... Layover (1 of 1) is a 2 hr 45 min layover at ..." 형태(2026-10-17 캡처)만 읽는다.
    """
    if re.search(r"\bNonstop flight\b", label):
        return None if "Layover" in label else 0.0
    stops = re.search(r"\b(\d+) stops? flight\b", label)
    layovers = LAYOVER.findall(label)
    if not stops or [(int(index), int(total)) for index, total, _, _ in layovers] != [
        (index, int(stops[1])) for index in range(1, int(stops[1]) + 1)
    ]:
        return None
    hours = [int(hour or 0) + int(minute or 0) / 60 for _, _, hour, minute in layovers]
    return max(hours) if all(hours) else None


def return_prices(page: dict, job: ScanJob) -> list[tuple[int, str]]:
    """가는 편을 고른 뒤 나오는 오는 편 목록에서 검증된 (왕복 합계, 카드 라벨)을 싼 순으로 돌려준다.

    가는 편을 누르면 목록으로 스크롤돼 검색 컨트롤이 관측에서 빠지므로(2026-10-17 실측) 조건은 URL로만 확인한다.
    누르기 전 같은 탭의 결과 페이지는 check_return이 컨트롤까지 검증한다.
    """
    if not _verified_search_url(page, job) or not re.search(r"returning flights", page.get("text", ""), re.I):
        return []
    returns = []
    for action in page.get("actions", []):
        evidence = card_evidence(page, action)
        price = _card_price(evidence) if evidence else None
        label = action.get("label", "")
        if (
            evidence
            and price
            and _route_shown(evidence + "\n" + label, job.destination, job.origin)
            and _leaves_on(label, job.return_date)
        ):
            returns.append((price, label))
    return sorted(returns)


def extract_options(page: dict, job: ScanJob) -> list[FlightOption]:
    if not verified_search(page, job):
        return []
    options: list[FlightOption] = []
    seen = set()
    for action in page.get("actions", []):
        evidence = card_evidence(page, action)
        if evidence is None or evidence in seen:
            continue
        price = _card_price(evidence)
        if price is None:
            continue
        # shortcut: only labelled full nonstop itineraries verify conditions; expand after capturing real layouts.
        outbound = re.search(r"^Outbound:\s*(.+)$", evidence, re.I | re.M)
        inbound = re.search(r"^Return:\s*(.+)$", evidence, re.I | re.M)
        out_ok = bool(
            outbound
            and re.search(
                rf"\b{job.origin}\s*(?:->|→)\s*{job.destination}\s+{job.departure_date.isoformat()}\b",
                outbound[1],
            )
        )
        in_ok = bool(
            inbound
            and re.search(
                rf"\b{job.destination}\s*(?:->|→)\s*{job.origin}\s+{job.return_date.isoformat()}\b",
                inbound[1],
            )
        )
        if (outbound and not out_ok) or (inbound and not in_ok):
            continue
        if not outbound:
            label = action.get("label", "")
            out_ok = _route_shown(evidence + "\n" + label, job.origin, job.destination) and _leaves_on(
                label, job.departure_date
            )
        if not out_ok:
            continue
        seen.add(evidence)
        nonstop = bool(
            out_ok
            and in_ok
            and outbound
            and inbound
            and re.search(r"\bnonstop\b", outbound[1], re.I)
            and re.search(r"\bnonstop\b", inbound[1], re.I)
        )
        baggage = bool(
            re.search(
                r"^Baggage:\s*carry-on included;\s*checked bag included\.?$",
                evidence,
                re.I | re.M,
            )
        )
        options.append(
            FlightOption(
                job=job,
                price_krw=price,
                evidence=evidence,
                search_url=page["url"],
                outbound_verified=out_ok,
                return_verified=in_ok,
                baggage_known=baggage,
                max_layover_hours=0 if nonstop else None,
                airport_change=False if nonstop else None,
            )
        )
    return sorted(options, key=lambda option: option.price_krw)
