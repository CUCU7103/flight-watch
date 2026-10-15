import json
from dataclasses import replace
from pathlib import Path

import pytest

from flight_scanner import cli
from flight_scanner.models import Evaluation, ScanResult

FIXTURE = Path(__file__).parent / "fixtures/verified_roundtrip.json"


def test_fixture_dry_run_is_end_to_end_and_never_uses_network(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Fixture replay must not use a paid API or Redis")

    monkeypatch.setattr(cli, "evaluate", forbidden)
    output = tmp_path / "result.json"
    assert cli.main(["--fixture", str(FIXTURE), "--dry-run", "--output", str(output)]) == 0
    payload = json.loads(output.read_text())
    assert payload["results"][0]["selected"]["price_krw"] == 175_000
    assert payload["results"][0]["notification"] == "DRY_RUN"
    assert payload["mode"] == "fixture"
    assert json.loads(capsys.readouterr().out)["results"][0]["action"] == "SEND_URGENT_ALERT"


def test_captured_fixture_replay_records_the_cheapest_tab_price(tmp_path, capsys):
    captured = Path(__file__).parent / "fixtures/captured_fuk_20261014.json"
    output = tmp_path / "result.json"
    cli.main(["--fixture", str(captured), "--dry-run", "--output", str(output)])
    assert json.loads(output.read_text())["results"][0]["cheapest_tab_krw"] == 381_300


def test_fixture_cannot_send_real_alert(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--fixture", str(FIXTURE), "--output", str(tmp_path / "out")])
    assert exc.value.code == 2


def test_fixture_without_evaluation_is_still_offline(tmp_path, monkeypatch, capsys):
    fixture = json.loads(FIXTURE.read_text())
    del fixture["evaluation"]
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture))
    calls = []

    def forbidden(*a):
        calls.append(True)
        raise AssertionError("Offline fixture must never evaluate live")

    monkeypatch.setattr(cli, "evaluate", forbidden)
    cli.main(["--fixture", str(path), "--dry-run", "--output", str(tmp_path / "output.json")])
    assert calls == []


@pytest.mark.parametrize("problem", ["evaluation", "FAILED", "UNCERTAIN", "DEFERRED", "NOT_CONFIGURED"])
def test_cli_downstream_failures_return_nonzero_and_preserve_result(tmp_path, monkeypatch, capsys, problem):
    from contextlib import nullcontext

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(cli, "dedicated_browser", nullcontext)
    monkeypatch.setattr(cli, "run_jobs", lambda *a: [])
    row = {"status": "DONE", "notification": problem if problem != "evaluation" else "SKIPPED"}
    if problem == "evaluation":
        row["evaluation_error"] = "ValueError"
    monkeypatch.setattr(cli, "process_results", lambda *a, **kw: [row])
    output = tmp_path / "output.json"
    assert cli.main(["--days", "1", "--output", str(output)]) == 1
    assert json.loads(output.read_text())["results"][0]["status"] == "DONE"


def test_failed_scan_is_recorded_without_aborting_neighbors(option, monkeypatch):
    jobs = [option.job, replace(option.job, destination="NRT")]

    def scan(job):
        if job.destination == "NRT":
            raise RuntimeError("secret")
        return ScanResult(job, "DONE", [option])

    monkeypatch.setattr(cli, "scan", scan)
    results = cli.run_jobs(jobs, 3)
    assert [r.status for r in results] == ["DONE", "ERROR"]
    assert results[1].error == "RuntimeError"


def test_above_target_and_unknown_conditions_skip_paid_evaluation(option, monkeypatch):
    def forbidden(*a):
        raise AssertionError("Must filter before evaluation")

    monkeypatch.setattr(cli, "evaluate", forbidden)
    results = [
        ScanResult(option.job, "DONE", [replace(option, price_krw=180_001)]),
        ScanResult(option.job, "DONE", [replace(option, return_verified=False)]),
    ]
    payload = cli.process_results(results, dry_run=True)
    assert [r["action"] for r in payload] == ["DISCARD", "SAVE_TO_DAILY_DIGEST"]


def test_evaluation_failure_is_saved_and_not_notified(option, monkeypatch):
    def unavailable(*a):
        raise ValueError("secret key in provider error")

    monkeypatch.setattr(cli, "evaluate", unavailable)
    rows = cli.process_results([ScanResult(option.job, "DONE", [option])], dry_run=True)
    assert rows[0]["action"] == "SAVE_TO_DAILY_DIGEST"
    assert rows[0]["evaluation_error"] == "ValueError"
    assert rows[0]["notification"] == "SKIPPED"


def test_verified_candidate_can_be_routed_in_dry_run(option, monkeypatch):
    monkeypatch.setattr(cli, "evaluate", lambda _: Evaluation(0.9, 0.1, 4, "SEND_URGENT_ALERT"))
    rows = cli.process_results([ScanResult(option.job, "DONE", [option])], dry_run=True)
    assert rows[0]["notification"] == "DRY_RUN"


def test_plan_only_creates_ten_jobs_without_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert cli.main(["--plan-only", "--output", str(tmp_path / "jobs.json")]) == 0
    assert len(json.loads(capsys.readouterr().out)["jobs"]) == 10


@pytest.mark.parametrize("workers", ["0", "4"])
def test_invalid_concurrency_is_rejected(workers):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--plan-only", "--workers", workers])
    assert exc.value.code == 2


def test_custom_route_plan(tmp_path):
    out = tmp_path / "plan.json"
    cli.main(
        [
            "--plan-only",
            "--origin",
            "gmp",
            "--destination",
            "kix",
            "--target-price",
            "150000",
            "--days",
            "1",
            "--output",
            str(out),
        ]
    )
    job = json.loads(out.read_text())["jobs"][0]
    assert (job["origin"], job["destination"], job["target_price_krw"]) == ("GMP", "KIX", 150000)
