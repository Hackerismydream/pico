"""Quality checks for PicoBench task suites."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .benchmark_schema import Benchmark, BenchmarkTask


REQUIRED_METADATA = {"source", "contamination_risk", "issue_clarity", "test_coverage"}


@dataclass(frozen=True)
class TaskQualityIssue:
    code: str
    message: str
    task_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "task_id": self.task_id,
            "details": self.details,
        }


@dataclass(frozen=True)
class TaskQualityReport:
    suite: str
    task_count: int
    hidden_fixture_count: int
    issues: list[TaskQualityIssue]

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "task_count": self.task_count,
            "hidden_fixture_count": self.hidden_fixture_count,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def check_benchmark_quality(
    benchmark: Benchmark,
    *,
    min_tasks: int = 0,
    require_hidden: bool = False,
    run_public_tests: bool = False,
    run_hidden_tests: bool = False,
    require_initial_failing: bool = False,
) -> TaskQualityReport:
    issues: list[TaskQualityIssue] = []
    if min_tasks and len(benchmark.tasks) < min_tasks:
        issues.append(
            TaskQualityIssue(
                code="too_few_tasks",
                message=f"benchmark has {len(benchmark.tasks)} tasks, expected at least {min_tasks}",
                details={"task_count": len(benchmark.tasks), "min_tasks": min_tasks},
            )
        )
    for task in benchmark.tasks:
        issues.extend(_check_task(task, require_hidden=require_hidden))
        if run_public_tests or run_hidden_tests:
            issues.extend(
                _check_executable_task(
                    task,
                    run_public_tests=run_public_tests,
                    run_hidden_tests=run_hidden_tests,
                    require_initial_failing=require_initial_failing,
                )
            )
    return TaskQualityReport(
        suite=benchmark.suite,
        task_count=len(benchmark.tasks),
        hidden_fixture_count=sum(1 for task in benchmark.tasks if task.hidden_fixture_path is not None),
        issues=issues,
    )


def _check_task(task: BenchmarkTask, *, require_hidden: bool) -> list[TaskQualityIssue]:
    issues: list[TaskQualityIssue] = []
    if require_hidden and task.hidden_fixture_path is None:
        issues.append(TaskQualityIssue("missing_hidden_fixture", "task has no hidden fixture", task.task_id))
    if (task.fixture_path / "hidden_tests").exists():
        issues.append(
            TaskQualityIssue(
                "visible_hidden_tests",
                "visible fixture must not contain hidden_tests",
                task.task_id,
                {"fixture": str(task.fixture_path)},
            )
        )
    hidden_path = task.hidden_fixture_path
    if hidden_path and _is_relative_to(hidden_path, task.fixture_path):
        issues.append(
            TaskQualityIssue(
                "hidden_fixture_inside_visible_fixture",
                "hidden fixture must be outside the visible fixture",
                task.task_id,
                {"fixture": task.fixture, "hidden_fixture": task.hidden_fixture},
            )
        )
    prompt_lower = task.prompt.lower()
    if "hidden_tests" in prompt_lower or "hidden test" in prompt_lower:
        issues.append(TaskQualityIssue("prompt_leaks_hidden_tests", "prompt mentions hidden tests", task.task_id))
    metadata = task.raw.get("metadata") or {}
    missing_metadata = sorted(REQUIRED_METADATA - set(metadata))
    if missing_metadata:
        issues.append(
            TaskQualityIssue(
                "missing_metadata",
                "task metadata is missing required fields",
                task.task_id,
                {"missing": missing_metadata},
            )
        )
    if not _has_evidence_verifier(task):
        issues.append(TaskQualityIssue("missing_evidence_verifier", "task should verify run evidence", task.task_id))
    if not _expected_changed_paths(task):
        issues.append(TaskQualityIssue("missing_expected_changed_paths", "task should declare expected changed paths", task.task_id))
    return issues


def _check_executable_task(
    task: BenchmarkTask,
    *,
    run_public_tests: bool,
    run_hidden_tests: bool,
    require_initial_failing: bool,
) -> list[TaskQualityIssue]:
    issues: list[TaskQualityIssue] = []
    public_expectation = _initial_expectation(task, "initial_public", require_initial_failing)
    hidden_expectation = _initial_expectation(task, "initial_hidden", require_initial_failing)
    if run_public_tests:
        with _workspace_copy(task.fixture_path) as workspace:
            results = [_run_command(command, workspace) for command in task.public_tests]
        public_passed = bool(results) and all(result["returncode"] == 0 for result in results)
        if public_expectation == "fail" and public_passed:
            issues.append(
                TaskQualityIssue(
                    "initial_all_green",
                    "public tests pass before the agent changes the fixture",
                    task.task_id,
                    {"commands": results},
                )
            )
        if public_expectation == "pass" and not public_passed:
            issues.append(
                TaskQualityIssue(
                    "public_tests_fail_initially",
                    "public tests failed during executable quality check",
                    task.task_id,
                    {"commands": results},
                )
            )
    if run_hidden_tests:
        if task.hidden_fixture_path is None:
            issues.append(TaskQualityIssue("missing_hidden_fixture", "cannot run hidden tests without hidden fixture", task.task_id))
        else:
            with _workspace_copy(task.fixture_path) as workspace:
                _inject_hidden_tests(task.hidden_fixture_path, workspace)
                results = [_run_command(command, workspace) for command in task.hidden_tests]
            hidden_passed = bool(results) and all(result["returncode"] == 0 for result in results)
            if hidden_expectation == "fail" and hidden_passed:
                issues.append(
                    TaskQualityIssue(
                        "hidden_initial_all_green",
                        "hidden tests pass before the agent changes the fixture",
                        task.task_id,
                        {"commands": results},
                    )
                )
            if hidden_expectation == "pass" and not hidden_passed:
                issues.append(
                    TaskQualityIssue(
                        "hidden_tests_fail_initially",
                        "hidden tests failed during executable quality check",
                        task.task_id,
                        {"commands": results},
                    )
                )
    return issues


def _initial_expectation(task: BenchmarkTask, key: str, require_initial_failing: bool) -> str:
    quality = task.raw.get("quality") or {}
    value = str(quality.get(key) or "").strip().lower()
    if value in {"pass", "fail", "either"}:
        return value
    return "fail" if require_initial_failing else "pass"


def _has_evidence_verifier(task: BenchmarkTask) -> bool:
    return any(spec.get("type") in {"evidence", "trace_consistency"} for spec in task.verifiers)


def _expected_changed_paths(task: BenchmarkTask) -> bool:
    changed = (task.expected.get("changed_paths") or {}) if isinstance(task.expected, dict) else {}
    return bool(changed.get("any") or changed.get("all"))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class _workspace_copy:
    def __init__(self, source: Path):
        self.source = source
        self.root: Path | None = None

    def __enter__(self) -> Path:
        self.root = Path(tempfile.mkdtemp(prefix="picobench-quality-"))
        shutil.copytree(self.source, self.root / "workspace")
        return self.root / "workspace"

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.root:
            shutil.rmtree(self.root, ignore_errors=True)


def _inject_hidden_tests(hidden_fixture: Path, workspace: Path) -> None:
    source = hidden_fixture / "hidden_tests" if (hidden_fixture / "hidden_tests").is_dir() else hidden_fixture
    destination = workspace / "hidden_tests"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _run_command(command: str, workspace: Path) -> dict[str, Any]:
    normalized = _normalize_command(command)
    try:
        completed = subprocess.run(
            normalized,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "command": command,
            "normalized_command": normalized,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "normalized_command": normalized,
            "returncode": 124,
            "stdout": str(exc.stdout or "")[-2000:],
            "stderr": str(exc.stderr or "")[-2000:],
        }


def _normalize_command(command: str) -> str:
    if command.startswith("python "):
        return f"{sys.executable} {command[len('python '):]}"
    return command
