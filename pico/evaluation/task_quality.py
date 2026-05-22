"""Quality checks for PicoBench task suites."""

from __future__ import annotations

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
