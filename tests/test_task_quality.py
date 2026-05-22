import json
import subprocess
import sys

from pico.evaluation.benchmark_schema import load_benchmark, normalize_benchmark
from pico.evaluation.task_quality import check_benchmark_quality


def _task(task_id, fixture, hidden_fixture):
    return {
        "task_id": task_id,
        "suite": "picobench-core",
        "category": "bugfix",
        "repo": {"fixture": fixture, "hidden_fixture": hidden_fixture},
        "prompt": {"text": "Fix the public tests and run python -m pytest tests -q."},
        "execution": {"driver": "one_shot_cli", "max_steps": 12},
        "tests": {"public": ["python -m pytest tests -q"], "hidden": ["python -m pytest hidden_tests -q"]},
        "verifiers": [{"type": "evidence"}, {"type": "changed_paths", "any": ["app.py"]}],
        "expected": {"changed_paths": {"any": ["app.py"]}},
        "metadata": {
            "source": "synthetic",
            "contamination_risk": "low",
            "issue_clarity": "clear",
            "test_coverage": "medium",
        },
    }


def test_task_quality_accepts_repo_core_suite_phase2_floor():
    benchmark = load_benchmark("benchmarks/picobench-core-v1.yaml")

    report = check_benchmark_quality(benchmark, min_tasks=25, require_hidden=True)

    assert report.passed, [issue.to_dict() for issue in report.issues]
    assert report.task_count >= 25
    assert report.hidden_fixture_count == report.task_count


def test_task_quality_rejects_visible_hidden_tests_and_missing_metadata(tmp_path):
    visible = tmp_path / "fixtures" / "bad"
    hidden = tmp_path / "hidden" / "bad"
    (visible / "hidden_tests").mkdir(parents=True)
    hidden.mkdir(parents=True)
    (visible / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (hidden / "test_hidden.py").write_text("def test_hidden(): assert True\n", encoding="utf-8")
    payload = {
        "schema_version": 1,
        "suite": "picobench-core",
        "tasks": [_task("core_bad", "fixtures/bad", "hidden/bad")],
    }
    payload["tasks"][0]["metadata"].pop("test_coverage")
    benchmark = normalize_benchmark(payload, repo_root=tmp_path)

    report = check_benchmark_quality(benchmark, min_tasks=2, require_hidden=True)

    codes = {issue.code for issue in report.issues}
    assert "too_few_tasks" in codes
    assert "visible_hidden_tests" in codes
    assert "missing_metadata" in codes


def test_check_picobench_tasks_cli_writes_json(tmp_path):
    output = tmp_path / "quality.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_picobench_tasks.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--min-tasks",
            "25",
            "--json-output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["task_count"] >= 25
