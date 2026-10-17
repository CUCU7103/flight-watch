"""Dedicated Chrome profile, bounded worker processes, and safe observed actions."""

import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from .extract import (
    card_evidence,
    cheapest_tab_price,
    extract_options,
    layover_hours,
    return_prices,
    search_url,
    verified_search,
)
from .models import DEFAULT_MODEL, FLIGHTS_URL, FlightOption, ScanJob, ScanResult

JOB_TIMEOUT = 120
MAX_STEPS = 50
# 검색 URL로 바로 연 결과 페이지가 검증·안정될 때까지 기다리는 시간. 넘기면 Jev 에이전트로 넘어간다.
DIRECT_RESULTS_TIMEOUT = 8
# 결과가 단계적으로 그려지다 잠깐 멈춘 화면을 완료로 보지 않도록, 같은 결과를 이만큼 연속 관측해야 끝낸다.
STABLE_OBSERVATIONS = 3
SEARCH_FORM_TIMEOUT = 15
# 가는 편을 고른 뒤 오는 편 목록이 검증·안정될 때까지 기다리는 시간. 넘기면 오는 편을 미확인으로 둔다.
RETURN_RESULTS_TIMEOUT = 8
BLOCKED_PAGE = re.compile(r"captcha|unusual traffic|verify you are human", re.I)


def wait_for_direct_results(browser, page: dict, job: ScanJob) -> tuple[str, dict, str | None]:
    """결과 페이지에서 옵션이 검증되고 STABLE_OBSERVATIONS번 연속 같으면 모델 호출 없이 끝낸다.

    (상태, 마지막 관측 페이지, 대체 사유)를 돌려준다. DONE이면 호출자가 그 페이지에서 옵션을 읽는다.
    상태가 ""이면 호출자가 빈 검색 폼에서 에이전트를 처음부터 돌리고, 진단용으로 대체 사유를 남긴다.
    사유에는 페이지 본문이나 전체 URL 없이 경로와 개수만 담는다.
    """
    from jev_ultrafast.browser import StalePage

    deadline = time.monotonic() + DIRECT_RESULTS_TIMEOUT
    previous, stable = None, 0
    while True:
        # 차단 페이지는 /sorry/ 등 다른 경로로 바뀌므로 경로 확인보다 먼저 본다.
        if BLOCKED_PAGE.search(page.get("text", "")):
            return "BLOCKED", page, None
        path = urlparse(page.get("url", "")).path
        if path != "/travel/flights/search":
            return "", page, f"left_results:{path[:100]}"
        options = extract_options(page, job)
        current = sorted((option.price_krw, option.evidence) for option in options)
        stable = stable + 1 if options and current == previous else 1
        if options and stable >= STABLE_OBSERVATIONS:
            return "DONE", page, None
        if time.monotonic() >= deadline:
            if options:
                return "", page, f"unstable:{len(options)}"
            return "", page, "no_options" if verified_search(page, job) else "search_unverified"
        previous = current
        time.sleep(0.3)
        try:
            page = browser.observe(screenshot=False)
        except StalePage:
            previous = None  # 같은 이전 페이지를 다시 세어 안정으로 오판하지 않는다.


def check_return(browser, page: dict, job: ScanJob, option: FlightOption) -> tuple[FlightOption, str | None]:
    """최저가 가는 편을 코드가 직접 골라 오는 편 목록을 열고, 같은 왕복 합계의 오는 편으로 일정·경유를 확인한다.

    누르는 것은 검증된 결과 페이지에서 방금 관측한 가는 편 카드 하나뿐이다. 오는 편 카드를 누르면 예약 옵션
    (항공사 외부 링크) 페이지로 넘어가므로 누르지 않는다. 확인하지 못하면 가는 편 결과는 그대로 두고
    (원래 옵션, 사유)를 돌려준다. 사유에는 페이지 본문 없이 경로·개수만 담는다.
    """
    from jev_ultrafast.browser import StalePage

    try:
        if option.return_verified:
            return option, None  # 오는 편까지 정해진 카드를 누르면 예약 옵션 페이지로 넘어간다.
        card = next(
            (a for a in page.get("actions", []) if card_evidence(page, a) == option.evidence),
            None,
        )
        if not verified_search(page, job) or card is None or type(card.get("node")) is not int:
            return option, "outbound_unverified"
        if not browser.fresh(page, card):
            return option, "outbound_stale"
        # jev의 act는 카드 링크 위에 겹친 내용 요소 때문에 가려졌다고 거절하므로, 확인한 노드를 DOM에서 직접 누른다.
        # hit-test를 건너뛰는 대신, 카드를 감싼 링크가 있으면 에이전트 경로처럼 flights 검색 안인지 먼저 확인한다.
        clicked = browser.evaluate(
            "(() => { const e=window.__jevFast?.nodes.get("
            + str(card["node"])
            + """);
              if (!e?.isConnected || e.getAttribute('role') !== 'link') return false;
              const raw=e.closest('a[href]')?.getAttribute('href');
              if (raw) { try { const u=new URL(raw,location.href);
                if (u.protocol!=='https:' || u.hostname!=='www.google.com' ||
                    !u.pathname.startsWith('/travel/flights')) return false; } catch { return false; } }
              e.click(); return true; })()"""
        )
        if clicked is not True:
            return option, "outbound_click_failed"
        deadline = time.monotonic() + RETURN_RESULTS_TIMEOUT
        previous: list[tuple[int, str]] = []
        stable = 0
        while True:
            if time.monotonic() >= deadline:
                return option, f"return_unstable:{len(previous)}" if previous else "return_unverified"
            time.sleep(0.3)
            try:
                current = browser.observe(screenshot=False)
            except StalePage:
                previous, stable = [], 0
                continue
            parsed = urlparse(current.get("url", ""))
            if parsed.hostname != "www.google.com" or parsed.path != "/travel/flights/search":
                return option, f"left_results:{parsed.path[:100]}"
            # 일부 조합(2026-10-17 FUK 11-19→11-26 실측)은 Google이 오는 편 목록 대신 오류를 띄운다.
            if "Oops, something went wrong" in current.get("text", ""):
                return option, "return_error"
            returns = return_prices(current, job)
            stable = stable + 1 if returns and returns == previous else 1
            if returns and stable >= STABLE_OBSERVATIONS:
                break
            previous = returns
        price = returns[0][0]
        # 가는 편 카드의 "From" 가격은 오는 편 중 최저 조합의 합계다. 다르면 다른 조합을 본 것이므로 확인하지 않는다.
        if price != option.price_krw:
            return option, "return_price_mismatch"
        labels = [label for amount, label in returns if amount == price]
        # 별도 발권은 편도 두 장의 합계라 한쪽이 지연·결항돼도 다른 쪽이 보호되지 않으므로 왕복으로 확정하지 않는다.
        if any("Separate tickets" in label for label in [card["label"], *labels]):
            return option, "separate_tickets"
        # 같은 최저가 오는 편이 여럿이면 라벨 순서가 아니라 경유가 가장 짧은 편으로 판정한다.
        cheapest = [layover_hours(label) for label in labels]
        return_layover = min((hours for hours in cheapest if hours is not None), default=None)
        outbound_layover = layover_hours(card["label"])
        layover = None if outbound_layover is None or return_layover is None else max(outbound_layover, return_layover)
        # 공항 변경 문구는 아직 실측하지 못해, 양쪽 모두 직항일 때만 변경 없음으로 확정한다.
        confirmed = replace(
            option, return_verified=True, max_layover_hours=layover, airport_change=False if layover == 0 else None
        )
        return confirmed, None
    except Exception as exc:
        # 부가 확인이 실패했다고 이미 검증한 가는 편 결과(DONE)를 잃지 않는다.
        return option, f"error:{type(exc).__name__}"


def settle_autocomplete(browser, page: dict, value: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if any(
            action.get("kind") == "click" and re.search(rf"\b{re.escape(value)}\b", action.get("label", ""))
            for action in page["actions"]
        ):
            return page
        time.sleep(0.1)
        page = browser.observe(screenshot=False)
    return page


def open_search_form(browser) -> dict:
    """직접 경로가 실패하면 같은 탭을 빈 검색 폼으로 옮긴다.

    이미 채워진 결과 페이지에서 시작하면 에이전트가 입력할 값이 없어 막히므로, 원래 흐름을 처음부터 돌린다.
    """
    from jev_ultrafast.browser import StalePage

    # 폼을 열지 못하면 엉뚱한 페이지에서 유료 모델을 부르지 않도록 오류로 끝낸다.
    # ERR_ABORTED는 페이지가 스스로 다른 이동을 시작한 경우에도 나므로, 아래에서 폼이 열리는지 마저 확인한다.
    if browser.call("Page.navigate", url=FLIGHTS_URL).get("errorText") not in {None, "net::ERR_ABORTED"}:
        raise RuntimeError("Search form navigation failed")
    deadline = time.monotonic() + SEARCH_FORM_TIMEOUT
    while True:
        try:
            # ERR_ABORTED면 지금 문서가 우리가 연 문서가 아닐 수 있으므로 호스트까지 확인한다.
            if browser.evaluate(
                "location.hostname === 'www.google.com' && location.pathname === '/travel/flights'"
                " && document.readyState === 'complete'"
            ):
                return browser.observe(screenshot=False)
        except StalePage:
            pass  # 이동 중에는 문서가 바뀌어 평가·관측이 실패할 수 있다.
        if time.monotonic() >= deadline:
            page = browser.observe(screenshot=False)
            # 차단 페이지(/sorry/ 등)로 넘어갔으면 호출자가 BLOCKED로 분류하도록 그 페이지를 돌려준다.
            if BLOCKED_PAGE.search(page.get("text", "")):
                return page
            raise RuntimeError("Search form did not load")
        time.sleep(0.05)


def validate_action(job: ScanJob, page: dict, decision: dict) -> dict | None:
    parsed = urlparse(page.get("url", ""))
    if parsed.scheme != "https" or parsed.hostname != "www.google.com" or not parsed.path.startswith("/travel/flights"):
        raise ValueError("Navigation outside permitted flight search")
    if decision["choice"] in {"DONE", "BLOCKED"}:
        return None
    action = next((a for a in page.get("actions", []) if a["id"] == decision["choice"]), None)
    if not action or action["kind"] not in {"click", "fill", "select", "scroll", "wait"}:
        raise ValueError("Unobserved or unsupported action")
    label = action.get("label", "").strip()
    if re.search(r"book|sign in|log in|payment|\bpay\b|select flight|subscribe|delete|account", label, re.I):
        raise ValueError("Booking and account actions are not permitted")
    if action["kind"] == "fill":
        fields = {
            "Where from?": job.origin,
            "Where to?": job.destination,
            "Departure": job.departure_date.isoformat(),
            "Return": job.return_date.isoformat(),
        }
        if label not in fields or decision.get("text") != fields[label]:
            raise ValueError("Field and input value are incompatible")
    if action["kind"] == "click":
        allowed = re.search(
            r"^(?:Open )?(?:Where from\?|Where to\?|Departure|Return)|"
            r"^(?:Search|Done|Round trip|Economy|1 passenger|Change ticket type|Change cabin class|"
            r"Change seating class|Next month|Previous month|Next|Previous|Cheapest|Best|Flights)\b|"
            rf"\b(?:{job.origin}|{job.destination})\b|"
            r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s|"
            r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d",
            label,
            re.I,
        )
        if not allowed and action.get("role") != "gridcell":
            raise ValueError("Click is outside the search-control allowlist")
    return action


def _run_job(job: ScanJob, report_target) -> ScanResult:
    from browser_harness import helpers

    from jev_ultrafast import Agent
    from jev_ultrafast.browser import StalePage

    if os.environ.get("BU_NAME") is not None and helpers.NAME != os.environ["BU_NAME"]:
        return ScanResult(job, "ERROR", error="Harness namespace mismatch; use a fresh scanner process")
    started = time.monotonic()
    result = ScanResult(job, "ERROR")
    try:
        # 결과 페이지로 바로 연다. 검증되면 모델 호출 없이 끝나고, 아니면 같은 탭에서 에이전트가 이어서 조작한다.
        with Agent(search_url(job), job.goal(), input_values=job.input_values()) as agent:
            report_target(agent.browser.target)
            invalid = 0
            for step in range(MAX_STEPS):
                if step == 0:
                    status, page, result.fallback_reason = wait_for_direct_results(
                        agent.browser, agent.state["page"], job
                    )
                    if status:
                        result.status = status
                        if status == "DONE":
                            result.options = extract_options(page, job)
                            result.cheapest_tab_krw = cheapest_tab_price(page, job)
                            result.options[0], result.return_reason = check_return(
                                agent.browser, page, job, result.options[0]
                            )
                        break
                    agent.state["page"] = open_search_form(agent.browser)
                if time.monotonic() - started >= JOB_TIMEOUT:
                    result.status = "TIMEOUT"
                    break
                if BLOCKED_PAGE.search(agent.state["page"]["text"]):
                    result.status = "BLOCKED"
                    break
                try:
                    agent.command("predict")
                    page, decision = agent.state["page"], agent.state["decision"]
                    action = validate_action(job, page, decision)
                    if action and action["kind"] in {"click", "select", "fill"}:
                        node = action["node"]
                        if type(node) is not int:
                            raise ValueError("Invalid observed node")
                        safe = agent.browser.evaluate(
                            """(() => {
                          const e=window.__jevFast?.nodes.get("""
                            + str(node)
                            + """);
                          if (!e) return false;
                          const raw=e.closest('a[href]')?.getAttribute('href') || e.form?.getAttribute('action');
                          if (!raw) return true;
                          try { const u=new URL(raw,location.href);
                            return u.protocol==='https:' && u.hostname==='www.google.com' &&
                              u.pathname.startsWith('/travel/flights'); } catch { return false; }
                        })()"""
                        )
                        if safe is not True:
                            raise ValueError("Target links outside permitted search")
                except StalePage:
                    agent.state["page"] = agent.browser.observe(screenshot=False)
                    continue
                except ValueError:
                    agent.state["decision"] = None
                    invalid += 1
                    if invalid >= 2:
                        result.status, result.error = (
                            "INVALID_RESULT",
                            "Two invalid decisions; no unsafe action executed",
                        )
                        break
                    continue
                invalid = 0
                try:
                    snapshot = agent.command("act", {"fingerprint": page["fingerprint"]})
                    if action and action["kind"] == "fill" and decision.get("text") in {job.origin, job.destination}:
                        agent.state["page"] = settle_autocomplete(agent.browser, snapshot["page"], decision["text"])
                    if action and action["kind"] != "wait" and agent.state["history"][-1]["page_changed"] is False:
                        current = agent.state["page"]
                        excluded = page.get("excluded_actions", {})
                        ids = excluded.get("ids", []) if excluded.get("fingerprint") == current["fingerprint"] else []
                        current["excluded_actions"] = {
                            "fingerprint": current["fingerprint"],
                            "ids": [*ids, decision["choice"]],
                        }
                except StalePage:
                    agent.state["page"] = agent.browser.observe(screenshot=False)
                    agent.state["status"] = "ready"
                    continue
                if snapshot["status"] in {"done", "blocked"}:
                    result.status = snapshot["status"].upper()
                    if result.status == "DONE":
                        result.options = extract_options(snapshot["page"], job)
                        result.cheapest_tab_krw = cheapest_tab_price(snapshot["page"], job)
                        if not result.options:
                            result.status = "INVALID_RESULT"
                        # 상위 프로세스가 JOB_TIMEOUT에 끊으면 검증한 결과까지 잃으므로 시간이 남을 때만 확인한다.
                        # 상위 시계는 spawn·import 시간만큼 먼저 흐르므로 대기 시간 외에 15초를 남긴다.
                        elif time.monotonic() - started < JOB_TIMEOUT - RETURN_RESULTS_TIMEOUT - 15:
                            result.options[0], result.return_reason = check_return(
                                agent.browser, snapshot["page"], job, result.options[0]
                            )
                        else:
                            result.return_reason = "no_time"
                    break
            else:
                result.status = "TIMEOUT"
            result.model_calls = len(agent.state["decisions"])
            result.usage = [d.get("usage", {}) for d in agent.state["decisions"]]
    except Exception as exc:
        result.status, result.error = "ERROR", type(exc).__name__  # Do not persist provider bodies or credentials.
    result.elapsed_ms = round((time.monotonic() - started) * 1000)
    return result


def _worker(job: ScanJob, connection) -> None:
    try:
        result = _run_job(job, lambda target: connection.send(("target", target)))
        connection.send(("result", result))
    finally:
        connection.close()


def _close_target(target: str) -> None:
    from websockets.sync.client import connect

    ws = os.environ.get("BU_CDP_WS")
    if not ws:
        return
    try:
        with connect(ws, open_timeout=2) as socket:
            socket.send(json.dumps({"id": 1, "method": "Target.closeTarget", "params": {"targetId": target}}))
            socket.recv(timeout=2)
    except Exception:
        pass  # The dedicated browser is also terminated at the end of this run.


def scan(job: ScanJob) -> ScanResult:
    if not os.environ.get("BU_CDP_WS") or not os.environ.get("BU_NAME", "").startswith("flight_scanner_"):
        return ScanResult(job, "ERROR", error="Run inside the scanner's dedicated_browser context")
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(job, child))
    target = None
    started = time.monotonic()
    try:
        process.start()
        child.close()
        while time.monotonic() - started < JOB_TIMEOUT:
            if parent.poll(0.1):
                kind, value = parent.recv()
                if kind == "result":
                    return value
                target = value
            if not process.is_alive():
                return ScanResult(job, "ERROR", error="Worker stopped without a result")
        return ScanResult(job, "TIMEOUT", elapsed_ms=round((time.monotonic() - started) * 1000))
    except (EOFError, OSError):
        return ScanResult(job, "ERROR", error="Worker connection failed")
    finally:
        if process.pid:
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join()
        if target:
            _close_target(target)
        parent.close()
        child.close()


def daemon_ready(name: str) -> bool:
    # browser_harness._ipc는 import 시점의 BH_RUNTIME_DIR로 소켓 경로를 고정한다. 한 프로세스(웹 API)에서
    # 컨텍스트를 다시 열면 이미 지워진 첫 폴더를 보게 되므로, 현재 환경변수로 새로 import하는 자식에서 확인한다.
    try:
        check = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from browser_harness.admin import require_existing_daemon as ready; ready(sys.argv[1])",
                name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return False  # 멈춘 데몬은 죽은 것으로 보고 호출자가 다시 띄우게 한다.
    return check.returncode == 0


@contextmanager
def dedicated_browser():
    """Own every process/profile in this context; never attach to the user's Chrome."""
    chrome = os.environ.get("CHROME_PATH") or shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome and sys.platform == "darwin":
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not chrome or not Path(chrome).is_file():
        raise RuntimeError("Chrome not found; set CHROME_PATH")
    keys = (
        "BU_NAME",
        "BU_CDP_WS",
        "BU_CDP_URL",
        "BH_HOME",
        "BH_CONFIG_DIR",
        "BH_RUNTIME_DIR",
        "BH_TMP_DIR",
        "BH_AGENT_WORKSPACE",
        "TYPESAFE_MODEL",
        "BU_BROWSER_ID",
    )
    previous = {key: os.environ.get(key) for key in keys}
    with tempfile.TemporaryDirectory(prefix="flight-scanner-") as folder:
        root = Path(folder)
        browser = daemon = None
        try:
            profile = root / "profile"
            browser = subprocess.Popen(
                [
                    chrome,
                    "--headless=new",
                    "--remote-debugging-port=0",
                    "--remote-debugging-address=127.0.0.1",
                    f"--user-data-dir={profile}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            port_file = profile / "DevToolsActivePort"
            deadline = time.monotonic() + 15
            while not port_file.exists():
                if browser.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Dedicated Chrome did not start")
                time.sleep(0.1)
            port, path = port_file.read_text().splitlines()[:2]
            ws = f"ws://127.0.0.1:{int(port)}{path}"
            os.environ.update(
                BU_NAME="flight_scanner_" + root.name.replace("-", "_"),
                BU_CDP_WS=ws,
                BU_CDP_URL=f"http://127.0.0.1:{port}",
                BH_HOME=str(root / "harness"),
                BH_CONFIG_DIR=str(root / "harness"),
                BH_RUNTIME_DIR=str(root / "runtime"),
                BH_TMP_DIR=str(root / "tmp"),
                BH_AGENT_WORKSPACE=str(root / "workspace"),
            )
            os.environ.setdefault("TYPESAFE_MODEL", DEFAULT_MODEL)
            # An inherited cloud ID makes harness shutdown stop that unrelated billable browser.
            os.environ.pop("BU_BROWSER_ID", None)
            daemon = subprocess.Popen(
                [sys.executable, "-m", "browser_harness.daemon"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            deadline = time.monotonic() + 15
            while not daemon_ready(os.environ["BU_NAME"]):
                if daemon.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Dedicated browser harness did not start")
                time.sleep(0.1)
            yield
        finally:
            for process in (daemon, browser):
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
