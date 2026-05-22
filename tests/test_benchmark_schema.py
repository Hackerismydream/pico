import json

import pytest

from pico.evaluation.benchmark_schema import load_benchmark, normalize_benchmark


def _task(task_id, fixture="fixtures/demo"):
    return {
        "task_id": task_id,
        "suite": "picobench-core",
        "category": "bugfix",
        "repo": {"fixture": fixture},
        "prompt": {"text": "Fix the failing test."},
        "execution": {"driver": "one_shot_cli", "max_steps": 12},
        "tests": {"public": ["python -m pytest -q"]},
        "verifiers": [{"type": "command", "command": "python -V"}],
    }


def test_load_benchmark_normalizes_json_yaml_and_fixture_paths(tmp_path):
    fixture = tmp_path / "fixtures" / "demo"
    fixture.mkdir(parents=True)
    benchmark = tmp_path / "benchmarks" / "picobench-core-v1.yaml"
    benchmark.parent.mkdir()
    benchmark.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "suite": "picobench-core",
                "tasks": [_task("core_001")],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_benchmark(benchmark, repo_root=tmp_path)

    assert loaded.schema_version == 1
    assert loaded.suite == "picobench-core"
    assert loaded.tasks[0].task_id == "core_001"
    assert loaded.tasks[0].fixture_path == fixture.resolve()
    assert loaded.tasks[0].driver == "one_shot_cli"
    assert loaded.tasks[0].public_tests == ["python -m pytest -q"]


def test_repo_picobench_core_suite_has_ten_tasks():
    loaded = load_benchmark("benchmarks/picobench-core-v1.yaml")

    assert len(loaded.tasks) >= 25
    assert {f"core_{index:03d}" for index in range(1, 26)}.issubset({task.task_id for task in loaded.tasks})
    assert all(task.hidden_fixture_path and task.hidden_fixture_path.exists() for task in loaded.tasks)
    assert not any((task.fixture_path / "hidden_tests").exists() for task in loaded.tasks)


def test_repo_picobench_agentic_suite_delegates_priority_gates_to_v3_human_gate():
    loaded = load_benchmark("benchmarks/picobench-agentic-v1.yaml")

    assert [task.task_id for task in loaded.tasks] == [
        "R01",
        "R02",
        "R04",
        "R05",
        "S07",
        "S15",
        "S21",
        "S26",
        "S32",
        "S37",
        "S43",
        "S50",
    ]
    assert all(task.driver == "v3_human_gate" for task in loaded.tasks)
    assert {task.scenario_id for task in loaded.tasks} == {task.task_id for task in loaded.tasks}


def test_repo_picobench_agentic_native_suite_has_plan_skill_memory_examples():
    loaded = load_benchmark("benchmarks/picobench-agentic-native-v0.yaml")

    assert [task.task_id for task in loaded.tasks] == [
        "agentic_native_plan_001",
        "agentic_native_skill_001",
        "agentic_native_memory_001",
    ]
    assert {task.category for task in loaded.tasks} == {"plan_mode", "skill", "memory"}
    assert all(task.driver in {"repl", "one_shot_cli"} for task in loaded.tasks)


def test_normalize_benchmark_rejects_duplicate_task_ids(tmp_path):
    fixture = tmp_path / "fixtures" / "demo"
    fixture.mkdir(parents=True)

    with pytest.raises(ValueError, match="duplicate task_id"):
        normalize_benchmark(
            {
                "schema_version": 1,
                "suite": "picobench-core",
                "tasks": [_task("core_001"), _task("core_001")],
            },
            repo_root=tmp_path,
        )


def test_normalize_benchmark_rejects_invalid_driver_and_missing_fixture(tmp_path):
    payload = {
        "schema_version": 1,
        "suite": "picobench-core",
        "tasks": [_task("core_001", fixture="missing")],
    }

    with pytest.raises(ValueError, match="fixture does not exist"):
        normalize_benchmark(payload, repo_root=tmp_path)

    fixture = tmp_path / "fixtures" / "demo"
    fixture.mkdir(parents=True)
    payload["tasks"][0]["repo"]["fixture"] = "fixtures/demo"
    payload["tasks"][0]["execution"]["driver"] = "internal_runtime"

    with pytest.raises(ValueError, match="unsupported driver"):
        normalize_benchmark(payload, repo_root=tmp_path)
