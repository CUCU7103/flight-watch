"""Generate → isolated scan → deterministic filter → evaluation → notification."""

import argparse
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from .browser import dedicated_browser, scan
from .evaluate import evaluate, parse_evaluation, route, violates_hard_rules
from .extract import cheapest_tab_price, extract_options
from .models import DEFAULT_TARGETS_KRW, Evaluation, ScanJob, ScanResult, generate_jobs
from .notify import notify


def run_jobs(jobs: list[ScanJob], workers: int) -> list[ScanResult]:
    if not 1 <= workers <= 3:
        raise ValueError("workers must be 1–3")

    def safe_scan(job: ScanJob) -> ScanResult:
        try:
            return scan(job)
        except Exception as exc:
            return ScanResult(job, "ERROR", error=type(exc).__name__)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(safe_scan, jobs))


def process_results(
    results: list[ScanResult], *, dry_run: bool, fixture_evaluation: Evaluation | None = None, offline: bool = False
) -> list[dict]:
    if offline and not dry_run:
        raise ValueError("Offline replay cannot send alerts")
    rows = []
    for result in results:
        row = {**asdict(result), "action": "DISCARD", "notification": "SKIPPED"}
        if result.status != "DONE" or not result.options:
            rows.append(row)
            continue
        option = min(result.options, key=lambda item: item.price_krw)
        row["selected"] = asdict(option)
        # 확인된 조건이 하드 룰에 걸리면 평가(유료) 없이 버린다. 수하물 미확인으로 평가를 못 해도 적용된다.
        if not violates_hard_rules(option):
            row["action"] = "SAVE_TO_DAILY_DIGEST"
            if option.conditions_complete and (not offline or fixture_evaluation is not None):
                try:
                    evaluation = fixture_evaluation or evaluate(option)
                    row["evaluation"] = asdict(evaluation)
                    row["action"] = route(evaluation, option)
                    if row["action"] == "SEND_URGENT_ALERT":
                        row["notification"] = notify(option, evaluation, dry_run=dry_run)
                except Exception as exc:
                    row["evaluation_error"] = type(exc).__name__
        rows.append(row)
    return rows


def _write_output(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".scan-", delete=False) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2, default=str, allow_nan=False)
            file.write("\n")
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verified ICN round-trip fare scanner (no booking)")
    parser.add_argument("--start", type=date.fromisoformat, default=date.today() + timedelta(days=7))
    parser.add_argument("--days", type=int, default=5)
    parser.add_argument("--nights", type=int, default=3)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--origin", default="ICN", type=str.upper, help="IATA 출발 공항 코드")
    parser.add_argument(
        "--destination", nargs="+", type=str.upper, help="IATA 도착 공항 코드(여러 개 가능). 기본 FUK NRT"
    )
    parser.add_argument("--target-price", type=int, help="KRW 목표가. FUK/NRT 외 노선은 필수")
    parser.add_argument(
        "--dry-run", action="store_true", help="Live mode still calls Jev; never sends Slack or claims Redis"
    )
    parser.add_argument("--plan-only", action="store_true", help="Generate jobs only; no browser or API")
    parser.add_argument("--fixture", type=Path, help="Offline synthetic/captured snapshot replay; requires --dry-run")
    parser.add_argument("--output", type=Path, default=Path("artifacts/scans/latest.json"))
    args = parser.parse_args(argv)
    if args.fixture and (not args.dry_run or args.plan_only):
        parser.error("--fixture requires --dry-run and cannot be combined with --plan-only")
    try:
        if args.fixture:
            fixture = json.loads(args.fixture.read_text())
            fields = fixture["job"]
            job = ScanJob(
                fields["origin"],
                fields["destination"],
                date.fromisoformat(fields["departure_date"]),
                date.fromisoformat(fields["return_date"]),
                fields["target_price_krw"],
            )
            options = extract_options(fixture["page"], job)
            evaluation = parse_evaluation(fixture["evaluation"]) if "evaluation" in fixture else None
            payload = {
                "mode": "fixture",
                "fixture_kind": fixture.get("fixture_kind", "unverified"),
                "results": process_results(
                    [
                        ScanResult(
                            job,
                            "DONE" if options else "INVALID_RESULT",
                            options,
                            cheapest_tab_krw=cheapest_tab_price(fixture["page"], job),
                        )
                    ],
                    dry_run=True,
                    fixture_evaluation=evaluation,
                    offline=True,
                ),
            }
        else:
            destinations = args.destination or list(DEFAULT_TARGETS_KRW)
            if not args.target_price and not set(destinations) <= set(DEFAULT_TARGETS_KRW):
                parser.error("--target-price is required for destinations other than FUK/NRT")
            targets = {dest: args.target_price or DEFAULT_TARGETS_KRW[dest] for dest in destinations}
            jobs = generate_jobs(args.start, args.days, args.nights, origin=args.origin, destinations=targets)
            if args.plan_only:
                payload = {"mode": "plan", "jobs": [asdict(job) for job in jobs]}
            else:
                if not os.environ.get("TYPESAFE_API_KEY"):
                    parser.error("TYPESAFE_API_KEY is required for live scans")
                with dedicated_browser():
                    results = run_jobs(jobs, args.workers)
                    payload = {
                        "mode": "live-dry-run" if args.dry_run else "live",
                        "results": process_results(results, dry_run=args.dry_run),
                    }
        _write_output(args.output, payload)
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Scanner failed ({type(exc).__name__}); check configuration and browser availability.\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False))
    failures = {"FAILED", "UNCERTAIN", "DEFERRED", "NOT_CONFIGURED"}
    return int(
        any(
            row["status"] != "DONE" or "evaluation_error" in row or row.get("notification") in failures
            for row in payload.get("results", [])
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
