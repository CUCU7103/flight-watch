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
from pathlib import Path
from urllib.parse import urlparse

from .extract import extract_options, search_url
from .models import DEFAULT_MODEL, FlightOption, ScanJob, ScanResult

JOB_TIMEOUT = 120
MAX_STEPS = 50
# 검색 URL로 바로 연 결과 페이지가 검증·안정될 때까지 기다리는 시간. 넘기면 Jev 에이전트로 넘어간다.
DIRECT_RESULTS_TIMEOUT = 8
BLOCKED_PAGE = re.compile(r"captcha|unusual traffic|verify you are human", re.I)


def wait_for_direct_results(browser, page: dict, job: ScanJob) -> tuple[str, list[FlightOption], dict]:
    """결과 페이지에서 옵션이 검증되고 연속 두 번 같으면 모델 호출 없이 끝낸다.

    (상태, 옵션, 마지막 관측 페이지)를 돌려준다. 상태가 ""이면 호출자가 마지막 페이지에서 에이전트를 이어 간다.
    """
    deadline = time.monotonic() + DIRECT_RESULTS_TIMEOUT
    previous = None
    while urlparse(page.get("url", "")).path == "/travel/flights/search":
        if BLOCKED_PAGE.search(page.get("text", "")):
            return "BLOCKED", [], page
        options = extract_options(page, job)
        # 로딩 중에 일부 카드만 보고 끝내지 않도록 같은 결과가 두 번 관측될 때까지 기다린다.
        current = sorted((option.price_krw, option.evidence) for option in options)
        if options and current == previous:
            return "DONE", options, page
        if time.monotonic() >= deadline:
            break
        previous = current
        time.sleep(0.3)
        page = browser.observe(screenshot=False)
    return "", [], page


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
                    status, options, agent.state["page"] = wait_for_direct_results(
                        agent.browser, agent.state["page"], job
                    )
                    if status:
                        result.status, result.options = status, options
                        break
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
                        if not result.options:
                            result.status = "INVALID_RESULT"
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


def _daemon_ready(name: str) -> bool:
    # browser_harness._ipc는 import 시점의 BH_RUNTIME_DIR로 소켓 경로를 고정한다. 한 프로세스(웹 API)에서
    # 컨텍스트를 다시 열면 이미 지워진 첫 폴더를 보게 되므로, 현재 환경변수로 새로 import하는 자식에서 확인한다.
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
            while not _daemon_ready(os.environ["BU_NAME"]):
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
