"""웹 API: 검색 요청을 받아 백그라운드에서 스캔하고 상태·결과를 돌려준다. 알림은 보내지 않는다(dry-run)."""

import asyncio
import json
import os
import re
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, ExitStack, asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .browser import daemon_ready, dedicated_browser
from .cli import process_results, run_jobs
from .evaluate import parse_evaluation
from .extract import cheapest_tab_price, extract_options
from .itinerary import DEFAULT_GEMINI_MODEL, Planner, Trip, gemini_planner, outbound_arrival
from .models import DEFAULT_TARGETS_KRW, ScanJob, ScanResult, generate_jobs

# 검색은 서버 전체에서 1건씩만 돌고, 에이전트 경로로 넘어가면 유료 호출이 생기므로 CLI(최대 90일)보다 작게 막는다.
# 2026-10-17 실측: 30건이 약 46초, 에이전트 경로 1건(18회 호출), 연속 2회 차단 없음.
MAX_JOBS = 30
WORKERS = 3
# Google Flights가 판매하는 범위(약 11개월) 밖의 날짜로 유료 검색을 돌리지 않는다(귀국일 기준).
MAX_DAYS_AHEAD = 330

# 작업 목록을 받아 process_results 형태의 행(dict) 목록을 돌려주는 함수.
Runner = Callable[[list[ScanJob]], list[dict]]
# 액세스 토큰을 확인해 사용자 id를 돌려준다. 유효하지 않은 토큰이면 None, 확인 서버 오류면 예외.
Authenticator = Callable[[str], str | None]

LOOPBACK_HOSTS = ["127.0.0.1", "localhost"]
# 인증을 켜지 않은 로컬 실행에서 모든 검색의 소유자로 쓴다.
LOCAL_USER = "local"
# 성공한 토큰 확인을 보관하는 시간. 화면이 2초마다 폴링하므로 매번 Supabase를 부르지 않는다.
AUTH_CACHE_SECONDS = 60


AirportCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$")]


class ScanRequest(BaseModel):
    # 엄격 모드: true·"1"·1.5 같은 값을 숫자로 조용히 변환하지 않고, 오타 필드도 무시하지 않고 거절한다.
    model_config = ConfigDict(strict=True, extra="forbid")

    origin: AirportCode = "ICN"
    destinations: list[AirportCode] = Field(
        default_factory=lambda: list(DEFAULT_TARGETS_KRW), min_length=1, max_length=MAX_JOBS
    )
    start: date = Field(strict=False)  # FastAPI는 JSON을 파싱한 뒤 검증하므로 날짜 문자열은 허용해야 한다
    days: int = Field(default=5, ge=1, le=MAX_JOBS)
    nights: int = Field(default=3, ge=1, le=30)
    target_price_krw: int | None = Field(default=None, gt=0)

    @field_validator("start", mode="before")
    @classmethod
    def date_without_time(cls, value: object) -> object:
        # lax 날짜 파싱은 시각이 붙은 문자열·유닉스 타임스탬프도 받으므로 YYYY-MM-DD 문자열만 남긴다.
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("start는 YYYY-MM-DD 형식이어야 합니다")
        return value


class ItineraryRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    scan_id: str
    # 서버가 가진 결과 행을 가리킨다. 날짜·시각을 클라이언트에서 받지 않는다.
    index: int = Field(ge=0)


def public_row(row: dict) -> dict:
    """화면에 필요 없는 공급자 사용량(usage)은 응답에 싣지 않는다. 공급자가 필드를 늘려도 그대로 새지 않게 한다."""
    public = {key: value for key, value in row.items() if key != "usage"}
    if isinstance(public.get("evaluation"), dict):
        public["evaluation"] = {key: value for key, value in public["evaluation"].items() if key != "usage"}
    return public


@dataclass
class Scan:
    id: str
    owner: str
    jobs: list[ScanJob]
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    error: str | None = None
    results: list[dict] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "job_count": len(self.jobs),
            "error": self.error,
        }


def supabase_authenticator(url: str, api_key: str) -> Authenticator:
    """Supabase Auth(/auth/v1/user)에 토큰을 물어 확인한다. 서명 방식(HS256·비대칭 키)과 무관하게 동작한다."""
    # ponytail: 프로세스 메모리 캐시라 로그아웃한 토큰도 최대 AUTH_CACHE_SECONDS 동안 통과한다.
    # 즉시 차단이 필요하면 캐시를 없앤다.
    cache: dict[str, tuple[str, float]] = {}
    lock = threading.Lock()

    def authenticate(token: str) -> str | None:
        now = time.monotonic()
        with lock:
            hit = cache.get(token)
        if hit is not None and hit[1] > now:
            return hit[0]
        response = httpx.get(
            f"{url.rstrip('/')}/auth/v1/user",
            headers={"apikey": api_key, "Authorization": f"Bearer {token}"},
            timeout=5,
        )
        # 429(요청 한도)는 토큰 문제가 아니므로 거절이 아니라 확인 실패(예외)로 둔다.
        if 400 <= response.status_code < 500 and response.status_code != 429:
            return None
        response.raise_for_status()
        user_id = str(response.json()["id"])
        with lock:
            for expired in [key for key, (_, until) in cache.items() if until <= now]:
                del cache[expired]
            cache[token] = (user_id, now + AUTH_CACHE_SECONDS)
        return user_id

    return authenticate


class WarmBrowser:
    """전용 Chrome을 검색 사이에 열어 두어 검색마다 드는 기동 시간(약 2초)을 없앤다.

    검색 전에 데몬·Chrome 상태를 확인해 죽었으면 다시 열고, 서버가 종료될 때 close()로 정리한다.
    """

    def __init__(self, open_browser: Callable[[], AbstractContextManager] = dedicated_browser) -> None:
        self._open_browser = open_browser
        self._stack: ExitStack | None = None
        # ensure()는 스캔 스레드, close()는 서버 종료(이벤트 루프)에서 불리므로 둘을 직렬화한다.
        self._lock = threading.Lock()
        self._closed = False

    def ensure(self) -> None:
        with self._lock:
            if self._closed:
                # 종료 뒤에 Chrome을 다시 띄우면 정리할 주체가 없어 고아 프로세스로 남는다.
                raise RuntimeError("Server is shutting down")
            if self._stack is not None and daemon_ready(os.environ.get("BU_NAME", "")):
                return
            self._close_stack()
            stack = ExitStack()
            stack.enter_context(self._open_browser())
            self._stack = stack

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._close_stack()

    def _close_stack(self) -> None:
        if self._stack is not None:
            stack, self._stack = self._stack, None
            stack.close()


def live_runner(browser: WarmBrowser) -> Runner:
    def run(jobs: list[ScanJob]) -> list[dict]:
        browser.ensure()
        return process_results(run_jobs(jobs, WORKERS), dry_run=True)

    return run


def fixture_runner(path: Path) -> Runner:
    """저장된 페이지 스냅샷을 재생한다. 브라우저·유료 API·네트워크를 쓰지 않는다."""
    fixture = json.loads(path.read_text())
    evaluation = parse_evaluation(fixture["evaluation"]) if "evaluation" in fixture else None

    def run(jobs: list[ScanJob]) -> list[dict]:
        results = []
        for job in jobs:
            options = extract_options(fixture["page"], job)
            status = "DONE" if options else "INVALID_RESULT"
            results.append(ScanResult(job, status, options, cheapest_tab_krw=cheapest_tab_price(fixture["page"], job)))
        return process_results(results, dry_run=True, fixture_evaluation=evaluation, offline=True)

    return run


def create_app(
    runner: Runner,
    *,
    requires_api_key: bool,
    today: date | None = None,
    on_shutdown: Callable[[], None] | None = None,
    planner: Planner | None = None,
    authenticate: Authenticator | None = None,
    allowed_hosts: list[str] | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """today는 출발일 검증 기준일이다. None이면 요청 시점의 오늘을 쓴다(fixture 재생·테스트용 고정값).

    on_shutdown은 서버 종료 시 호출된다(열어 둔 Chrome 정리).
    planner는 여행 코스 생성기다. None이면 코스 기능을 끈다.
    authenticate가 있으면 모든 /api 요청에 로그인 토큰을 요구하고 검색을 사용자별로 나눈다.
    allowed_hosts·cors_origins로 외부 접근을 여는 것은 인증이 있을 때만 허용한다.
    """
    hosts = allowed_hosts or LOOPBACK_HOSTS
    if authenticate is None and (set(hosts) - set(LOOPBACK_HOSTS) or cors_origins):
        raise ValueError("로그인 확인 없이 외부 호스트·출처를 열 수 없습니다")

    def current_user(authorization: Annotated[str | None, Header()] = None) -> str:
        if authenticate is None:
            return LOCAL_USER
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(401, "로그인이 필요합니다")
        try:
            user = authenticate(token)
        except Exception:
            # 확인 서버 오류는 통과시키지 않는다(fail-closed). 응답 본문은 남기지 않는다.
            raise HTTPException(503, "로그인을 확인하지 못했습니다. 잠시 뒤 다시 시도해 주세요") from None
        if user is None:
            raise HTTPException(401, "로그인이 만료되었습니다. 다시 로그인해 주세요")
        return user

    CurrentUser = Annotated[str, Depends(current_user)]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if on_shutdown is not None:
            # Chrome 기동 중이면 close()가 잠금을 수십 초 기다릴 수 있으므로 이벤트 루프 밖에서 기다린다.
            await asyncio.to_thread(on_shutdown)

    # 앱 단위 의존성이라 앞으로 추가하는 경로도 빠짐없이 로그인을 요구한다.
    app = FastAPI(title="flight-watch", lifespan=lifespan, dependencies=[Depends(current_user)])
    # 인증이 없으면 loopback 이름만 받아 DNS rebinding으로 외부 페이지가 호출하는 경로를 막는다.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    if cors_origins:
        # 토큰은 쿠키가 아니라 Authorization 헤더로 오므로 credentials는 켜지 않는다.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )
    # ponytail: 메모리 보관이라 재시작하면 사라지고 계속 쌓인다. 이력이 필요해지면 SQLite로 옮긴다.
    scans: dict[str, Scan] = {}
    # dedicated_browser()가 프로세스 전역 os.environ을 바꾸므로 스캔은 동시에 1건만 돌린다.
    busy = threading.Lock()
    # ponytail: 같은 여행 조건의 코스를 메모리에 보관해 무료 한도를 아낀다. 재시작하면 사라진다.
    itineraries: dict[Trip, dict] = {}

    def execute(scan: Scan) -> None:
        results: list[dict] = []
        status, error = "done", None
        try:
            scan.status = "running"
            results = [public_row(row) for row in runner(scan.jobs)]
        except Exception as exc:
            # 공급자 응답 본문이나 자격증명이 남지 않도록 예외 타입명만 기록한다.
            status, error = "failed", type(exc).__name__
        finally:
            scan.results, scan.error = results, error
            scan.finished_at = datetime.now(timezone.utc).isoformat()
            # 잠금을 먼저 풀고 종료 상태를 공개해야, 종료를 본 클라이언트의 다음 요청이 409를 받지 않는다.
            busy.release()
            scan.status = status

    @app.post("/api/scans", status_code=202)
    def start_scan(request: ScanRequest, user: CurrentUser) -> dict:
        origin = request.origin.upper()
        destinations = [code.upper() for code in request.destinations]
        price = request.target_price_krw
        if price is None and not set(destinations) <= set(DEFAULT_TARGETS_KRW):
            raise HTTPException(422, "FUK/NRT 외 노선은 target_price_krw가 필요합니다")
        targets = {dest: price if price is not None else DEFAULT_TARGETS_KRW[dest] for dest in destinations}
        try:
            jobs = generate_jobs(
                request.start, request.days, request.nights, origin=origin, destinations=targets, today=today
            )
        except (ValueError, OverflowError) as exc:
            # OverflowError: 9999-12-31처럼 귀국일 계산이 날짜 범위를 넘는 경우
            raise HTTPException(422, str(exc)) from None
        # 출발일만 보면 일수·박 수만큼 범위 밖으로 나가므로 가장 늦은 귀국일로 판단한다.
        if max(job.return_date for job in jobs) > (today or date.today()) + timedelta(days=MAX_DAYS_AHEAD):
            raise HTTPException(422, f"귀국일은 오늘부터 {MAX_DAYS_AHEAD}일 이내여야 합니다")
        if len(jobs) > MAX_JOBS:
            raise HTTPException(422, f"작업은 최대 {MAX_JOBS}개입니다(일수 × 목적지 수 = {len(jobs)})")
        if requires_api_key and not os.environ.get("TYPESAFE_API_KEY"):
            raise HTTPException(503, "TYPESAFE_API_KEY가 설정되지 않았습니다")
        if not busy.acquire(blocking=False):
            raise HTTPException(409, "이미 실행 중인 검색이 있습니다")
        scan = Scan(uuid.uuid4().hex, user, jobs)
        try:
            scans[scan.id] = scan
            # 스레드 시작 전에 응답을 만들어야 항상 queued로 돌려준다(빠른 runner는 응답 전에 끝날 수 있다).
            response = {**scan.summary(), "jobs": [asdict(job) for job in jobs]}
            threading.Thread(target=execute, args=(scan,), daemon=True).start()
        except BaseException:
            # 스레드가 시작되지 않으면 execute()가 잠금을 풀지 못하므로 여기서 되돌린다.
            scans.pop(scan.id, None)
            busy.release()
            raise
        return response

    @app.get("/api/config")
    def get_config() -> dict:
        # 화면이 기본 목표가·작업 상한을 따로 하드코딩하지 않도록 백엔드 값을 내려준다.
        return {
            "default_targets_krw": DEFAULT_TARGETS_KRW,
            "max_jobs": MAX_JOBS,
            "max_days_ahead": MAX_DAYS_AHEAD,
            "itinerary_enabled": planner is not None,
        }

    def find(scan_id: str, user: str) -> Scan:
        # 다른 사용자의 검색은 있는지조차 드러내지 않도록 같은 404로 답한다.
        scan = scans.get(scan_id)
        if scan is None or scan.owner != user:
            raise HTTPException(404, "검색을 찾을 수 없습니다")
        return scan

    @app.get("/api/scans/{scan_id}")
    def get_scan(scan_id: str, user: CurrentUser) -> dict:
        return find(scan_id, user).summary()

    @app.get("/api/scans/{scan_id}/results")
    def get_results(scan_id: str, user: CurrentUser) -> dict:
        scan = find(scan_id, user)
        return {"id": scan.id, "status": scan.status, "results": scan.results}

    @app.post("/api/itineraries")
    def plan_itinerary(request: ItineraryRequest, user: CurrentUser) -> dict:
        # 코스 생성은 브라우저·os.environ을 쓰지 않으므로 스캔 잠금(busy)과 무관하게 돈다.
        if planner is None:
            raise HTTPException(503, "GEMINI_API_KEY가 설정되지 않았습니다")
        scan = find(request.scan_id, user)
        if request.index >= len(scan.results) or "selected" not in scan.results[request.index]:
            raise HTTPException(422, "확인된 항공권이 있는 결과에만 코스를 만들 수 있습니다")
        row = scan.results[request.index]
        job = row["job"]
        arrival = outbound_arrival(row["selected"]["evidence"])
        trip = Trip(job["destination"], job["departure_date"], job["return_date"], arrival)
        if trip not in itineraries:
            try:
                itineraries[trip] = planner(trip).model_dump()
            except ValueError:
                raise HTTPException(502, "모델이 올바른 형식의 코스를 만들지 못했습니다. 다시 시도해 주세요") from None
            except Exception as exc:
                # 공급자 응답 본문이 남지 않도록 상태 코드·예외 타입명만 쓴다.
                if getattr(exc, "status_code", None) == 429 or getattr(exc, "code", None) == 429:
                    raise HTTPException(429, "Gemini 무료 사용 한도를 넘었습니다. 잠시 뒤 다시 시도해 주세요") from None
                raise HTTPException(502, f"코스 생성에 실패했습니다 ({type(exc).__name__})") from None
        return {"trip": {**asdict(trip), "nights": trip.nights}, "itinerary": itineraries[trip]}

    return app


def _env_list(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _access_options() -> dict:
    """Supabase 설정이 있으면 로그인을 켜고 배포용 호스트·출처를 연다. 없으면 지금처럼 loopback 전용이다."""
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    hosts, origins = _env_list("FLIGHT_WATCH_ALLOWED_HOSTS"), _env_list("FLIGHT_WATCH_CORS_ORIGINS")
    if not (url and key):
        # 값 하나를 빠뜨린 배포가 조용히 인증 없는 모드로 뜨지 않게 기동을 멈춘다.
        # 프록시가 Host를 loopback으로 바꾸면 TrustedHost만으로는 막지 못한다.
        if url or key or hosts or origins:
            raise RuntimeError("SUPABASE_URL과 SUPABASE_PUBLISHABLE_KEY를 모두 설정해야 외부 접근을 열 수 있습니다")
        return {}
    return {
        "authenticate": supabase_authenticator(url, key),
        "allowed_hosts": LOOPBACK_HOSTS + hosts,
        "cors_origins": origins,
    }


def _default_app() -> FastAPI:
    # 코스 생성은 키가 있을 때만 켠다(fixture 재생에서도 키를 직접 넣었을 때만 Gemini를 부른다).
    gemini_key = os.environ.get("GEMINI_API_KEY")
    planner = gemini_planner(gemini_key, os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)) if gemini_key else None
    access = _access_options()
    # 개발·E2E 확인용: 경로를 주면 브라우저와 유료 API 없이 fixture를 재생한다.
    fixture = os.environ.get("FLIGHT_WATCH_FIXTURE")
    if fixture:
        # 저장된 출발일이 지나도 재생할 수 있도록 기준일을 출발 전날로 고정한다.
        departure = date.fromisoformat(json.loads(Path(fixture).read_text())["job"]["departure_date"])
        return create_app(
            fixture_runner(Path(fixture)),
            requires_api_key=False,
            today=departure - timedelta(days=1),
            planner=planner,
            **access,
        )
    browser = WarmBrowser()
    return create_app(
        live_runner(browser), requires_api_key=True, on_shutdown=browser.close, planner=planner, **access
    )


app = _default_app()
