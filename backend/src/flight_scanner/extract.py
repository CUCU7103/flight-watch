"""Fail-closed verification of Google Flights search state and observed card scopes."""

import base64
import binascii
import re
from urllib.parse import parse_qs, urlparse

from .models import FlightOption, ScanJob

PRICE = re.compile(r"(?:₩|KRW\s*)(\d{1,3}(?:,\d{3})+|\d+)(?![\d,])")
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


def verified_search(page: dict, job: ScanJob) -> bool:
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
    actions = page.get("actions", [])
    return (
        any("ticket type" in a.get("label", "").lower() and a.get("value") == "Round trip" for a in actions)
        and any(re.search(r"\b1 (?:passenger|adult)\b", a.get("label", ""), re.I) for a in actions)
        and any(
            re.search(r"(?:cabin|seating) class", a.get("label", ""), re.I) and a.get("value") == "Economy"
            for a in actions
        )
    )


def extract_options(page: dict, job: ScanJob) -> list[FlightOption]:
    if not verified_search(page, job):
        return []
    options: list[FlightOption] = []
    seen = set()
    for action in page.get("actions", []):
        if "select flight" not in action.get("label", "").lower():
            continue
        guard = page.get("guards", {}).get(str(action.get("node")), [])
        if not guard or not isinstance(guard[-1], str):
            continue
        evidence = guard[-1].strip()
        if evidence in seen or not re.search(r"round[ -]trip", evidence, re.I):
            continue
        if re.search(r"one[ -]way|\bfrom\s+(?:₩|KRW)|\$|\bUSD\b", evidence, re.I):
            continue
        prices = {int(match.replace(",", "")) for match in PRICE.findall(evidence)}
        if len(prices) != 1 or not 0 < next(iter(prices)) <= 5_000_000:
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
            route_ok = bool(
                re.search(rf"\b{job.origin}\s*(?:->|→|–|—|to|-)\s*{job.destination}\b", evidence + "\n" + label)
            )
            departure = re.search(
                r"\bLeaves\b.+?\bon\s+[A-Za-z]+,?\s+([A-Za-z]+)\s+(\d{1,2})"
                r"(?:,\s*(\d{4}))?",
                label,
            )
            date_ok = bool(re.search(rf"\b{job.departure_date.isoformat()}\b", label)) or bool(
                departure
                and departure[1].lower() == MONTHS[job.departure_date.month - 1].lower()
                and int(departure[2]) == job.departure_date.day
                and (not departure[3] or int(departure[3]) == job.departure_date.year)
            )
            out_ok = route_ok and date_ok
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
                price_krw=next(iter(prices)),
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
