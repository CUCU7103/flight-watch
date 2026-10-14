"""웹 API: 검색 요청을 받아 백그라운드에서 스캔하고 상태·결과를 돌려준다. 알림은 보내지 않는다(dry-run)."""

import json
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field

from .browser import dedicated_browser
from .cli import process_results, run_jobs
from .evaluate import parse_evaluation
from .extract import extract_options
from .models import DEFAULT_TARGETS_KRW, ScanJob, ScanResult, generate_jobs

# 웹은 버튼 한 번이 곧 유료 호출이므로 CLI(최대 90일)보다 작게 막는다.
MAX_JOBS = 10
WORKERS = 3

# 작업 목록을 받아 process_results 형태의 행(dict) 목록을 돌려주는 함수.
Runner = Callable[[list[ScanJob]], list[dict]]


class ScanRequest(BaseModel):
    origin: str = "ICN"
    destinations: list[str] = Field(default_factory=lambda: list(DEFAULT_TARGETS_KRW), min_length=1)
    start: date
    days: int = 5
    nights: int = 3
    target_price_krw: int | None = Field(default=None, gt=0)


@dataclass
class Scan:
    id: str
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


def live_runner(jobs: list[ScanJob]) -> list[dict]:
    with dedicated_browser():
        return process_results(run_jobs(jobs, WORKERS), dry_run=True)


def fixture_runner(path: Path) -> Runner:
    """저장된 페이지 스냅샷을 재생한다. 브라우저·유료 API·네트워크를 쓰지 않는다."""
    fixture = json.loads(path.read_text())
    evaluation = parse_evaluation(fixture["evaluation"]) if "evaluation" in fixture else None

    def run(jobs: list[ScanJob]) -> list[dict]:
        results = []
        for job in jobs:
            options = extract_options(fixture["page"], job)
            results.append(ScanResult(job, "DONE" if options else "INVALID_RESULT", options))
        return process_results(results, dry_run=True, fixture_evaluation=evaluation, offline=True)

    return run


def create_app(runner: Runner, *, requires_api_key: bool, today: date | None = None) -> FastAPI:
    """today는 출발일 검증 기준일이다. None이면 요청 시점의 오늘을 쓴다(fixture 재생·테스트용 고정값)."""
    app = FastAPI(title="flight-watch")
    # 인증이 없으므로 loopback 이름만 받아 DNS rebinding으로 외부 페이지가 호출하는 경로를 막는다.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    # ponytail: 메모리 보관이라 재시작하면 사라지고 계속 쌓인다. 이력이 필요해지면 SQLite로 옮긴다.
    scans: dict[str, Scan] = {}
    # dedicated_browser()가 프로세스 전역 os.environ을 바꾸므로 스캔은 동시에 1건만 돌린다.
    busy = threading.Lock()

    def execute(scan: Scan) -> None:
        results: list[dict] = []
        status, error = "done", None
        try:
            scan.status = "running"
            results = runner(scan.jobs)
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
    def start_scan(request: ScanRequest) -> dict:
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
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if len(jobs) > MAX_JOBS:
            raise HTTPException(422, f"작업은 최대 {MAX_JOBS}개입니다(일수 × 목적지 수 = {len(jobs)})")
        if requires_api_key and not os.environ.get("TYPESAFE_API_KEY"):
            raise HTTPException(503, "TYPESAFE_API_KEY가 설정되지 않았습니다")
        if not busy.acquire(blocking=False):
            raise HTTPException(409, "이미 실행 중인 검색이 있습니다")
        scan = Scan(uuid.uuid4().hex, jobs)
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

    def find(scan_id: str) -> Scan:
        if scan_id not in scans:
            raise HTTPException(404, "검색을 찾을 수 없습니다")
        return scans[scan_id]

    @app.get("/api/scans/{scan_id}")
    def get_scan(scan_id: str) -> dict:
        return find(scan_id).summary()

    @app.get("/api/scans/{scan_id}/results")
    def get_results(scan_id: str) -> dict:
        scan = find(scan_id)
        return {"id": scan.id, "status": scan.status, "results": scan.results}

    return app


def _default_app() -> FastAPI:
    # 개발·E2E 확인용: 경로를 주면 브라우저와 유료 API 없이 fixture를 재생한다.
    fixture = os.environ.get("FLIGHT_WATCH_FIXTURE")
    if fixture:
        # 저장된 출발일이 지나도 재생할 수 있도록 기준일을 출발 전날로 고정한다.
        departure = date.fromisoformat(json.loads(Path(fixture).read_text())["job"]["departure_date"])
        return create_app(fixture_runner(Path(fixture)), requires_api_key=False, today=departure - timedelta(days=1))
    return create_app(live_runner, requires_api_key=True)


app = _default_app()
