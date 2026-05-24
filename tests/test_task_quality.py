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

    report = check_benchmark_quality(benchmark, min_tasks=30, require_hidden=True)

    assert report.passed, [issue.to_dict() for issue in report.issues]
    assert report.task_count >= 30
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
    output = tmp_path / "nested" / "quality.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_picobench_tasks.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--min-tasks",
            "30",
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
    assert payload["task_count"] >= 30


def test_check_picobench_tasks_cli_runs_executable_subset(tmp_path):
    output = tmp_path / "quality-exec.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_picobench_tasks.py",
            "--benchmark",
            "benchmarks/picobench-core-v1.yaml",
            "--task",
            "core_011",
            "--min-tasks",
            "1",
            "--run-public-tests",
            "--run-hidden-tests",
            "--require-initial-failing",
            "--json-output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["task_count"] == 1


def test_task_quality_executable_checks_detect_initial_all_green(tmp_path):
    fixture = tmp_path / "fixtures" / "green"
    hidden = tmp_path / "hidden" / "green"
    (fixture / "tests").mkdir(parents=True)
    (hidden / "hidden_tests").mkdir(parents=True)
    (fixture / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (fixture / "tests" / "test_app.py").write_text(
        "from app import value\n\n\ndef test_value():\n    assert value() == 1\n",
        encoding="utf-8",
    )
    (hidden / "hidden_tests" / "test_app_edge.py").write_text(
        "from app import value\n\n\ndef test_value_edge():\n    assert value() == 1\n",
        encoding="utf-8",
    )
    benchmark = normalize_benchmark(
        {
            "schema_version": 1,
            "suite": "picobench-core",
            "tasks": [_task("core_green", "fixtures/green", "hidden/green")],
        },
        repo_root=tmp_path,
    )

    report = check_benchmark_quality(
        benchmark,
        min_tasks=1,
        require_hidden=True,
        run_public_tests=True,
        run_hidden_tests=True,
        require_initial_failing=True,
    )

    codes = {issue.code for issue in report.issues}
    assert "initial_all_green" in codes


def test_task_quality_respects_per_task_initial_expectations(tmp_path):
    fixture = tmp_path / "fixtures" / "mixed"
    hidden = tmp_path / "hidden" / "mixed" / "hidden_tests"
    (fixture / "tests").mkdir(parents=True)
    hidden.mkdir(parents=True)
    (fixture / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (fixture / "tests" / "test_public.py").write_text("def test_public(): assert True\n", encoding="utf-8")
    (hidden / "test_hidden.py").write_text("def test_hidden(): assert False\n", encoding="utf-8")
    payload = {
        "schema_version": 1,
        "suite": "picobench-core",
        "tasks": [_task("core_mixed", "fixtures/mixed", "hidden/mixed")],
    }
    payload["tasks"][0]["quality"] = {"initial_public": "pass", "initial_hidden": "fail"}
    benchmark = normalize_benchmark(payload, repo_root=tmp_path)

    report = check_benchmark_quality(
        benchmark,
        run_public_tests=True,
        run_hidden_tests=True,
        require_initial_failing=True,
    )

    assert report.passed, [issue.to_dict() for issue in report.issues]


def test_task_quality_executable_checks_accept_initial_failing_task(tmp_path):
    fixture = tmp_path / "fixtures" / "red"
    hidden = tmp_path / "hidden" / "red"
    (fixture / "tests").mkdir(parents=True)
    (hidden / "hidden_tests").mkdir(parents=True)
    (fixture / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (fixture / "tests" / "test_app.py").write_text(
        "from app import value\n\n\ndef test_value():\n    assert value() == 2\n",
        encoding="utf-8",
    )
    (hidden / "hidden_tests" / "test_app_edge.py").write_text(
        "from app import value\n\n\ndef test_value_edge():\n    assert value() == 3\n",
        encoding="utf-8",
    )
    benchmark = normalize_benchmark(
        {
            "schema_version": 1,
            "suite": "picobench-core",
            "tasks": [_task("core_red", "fixtures/red", "hidden/red")],
        },
        repo_root=tmp_path,
    )

    report = check_benchmark_quality(
        benchmark,
        min_tasks=1,
        require_hidden=True,
        run_public_tests=True,
        run_hidden_tests=True,
        require_initial_failing=True,
    )

    assert report.passed, [issue.to_dict() for issue in report.issues]
