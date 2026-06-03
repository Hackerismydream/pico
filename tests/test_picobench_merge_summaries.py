import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_merge_picobench_summaries_later_input_replaces_task(tmp_path):
    base = tmp_path / "base"
    retry = tmp_path / "retry"
    output = tmp_path / "merged"
    _write_summary(
        base,
        [
            _result("core_001", True, None),
            _result("core_056", False, "provider_insufficient_balance"),
        ],
    )
    _write_summary(retry, [_result("core_056", True, None)])

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/merge_picobench_summaries.py",
            "--input-dir",
            str(base),
            "--input-dir",
            str(retry),
            "--output-dir",
            str(output),
            "--expected-task-count",
            "2",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["task_count"] == 2
    assert payload["strict_failed"] == 0
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["strict_passed"] == 2
    manifest = json.loads((output / "merge_manifest.json").read_text(encoding="utf-8"))
    assert manifest["replaced_tasks"] == ["core_056"]
    assert manifest["task_sources"]["core_056"].endswith("retry/summary.json")


def test_merge_picobench_summaries_fails_expected_count_mismatch(tmp_path):
    base = tmp_path / "base"
    output = tmp_path / "merged"
    _write_summary(base, [_result("core_001", True, None)])

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/merge_picobench_summaries.py",
            "--input-dir",
            str(base),
            "--output-dir",
            str(output),
            "--expected-task-count",
            "100",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["task_count"] == 1


def _write_summary(path: Path, results: list[dict]):
    path.mkdir(parents=True)
    summary = {
        "suite": "core",
        "benchmark_suite": "picobench-core",
        "provider": "deepseek",
        "model": "",
        "pico_commit": "abc123",
        "started_at": "2026-05-29T00:00:00",
        "results": results,
    }
    (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def _result(task_id: str, strict_pass: bool, failure_category: str | None):
    return {
        "task_id": task_id,
        "title": task_id,
        "suite": "core",
        "category": "harness",
        "run_index": 1,
        "strict_pass": strict_pass,
        "failure_category": failure_category,
        "evidence_mode": "native",
        "evidence_path": f"/tmp/evidence/{task_id}",
        "duration_ms": 1,
        "command": {"command": ["uv", "run", "pico", "--provider", "deepseek", "fix"]},
        "checks": [
            {"name": "public_test", "passed": strict_pass},
            {"name": "report_trace_session_consistency", "passed": True},
        ],
        "report": {"tool_steps": 1, "cost_usd": 0.0},
    }
