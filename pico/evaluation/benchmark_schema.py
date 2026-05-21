"""PicoBench task schema loader.

This module is intentionally data-only. L1/L2/L3/L4 runners can import it
without importing the Pico runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

SUPPORTED_DRIVERS = {
    "one_shot_cli",
    "repl",
    "pty",
    "tui",
    "v3_human_gate",
}

SUPPORTED_CATEGORIES = {
    "bugfix",
    "feature",
    "refactor",
    "test_generation",
    "test_repair",
    "documentation",
    "configuration",
    "cli_behavior",
    "security_fix",
    "tool_policy",
    "sandbox",
    "memory",
    "resume",
    "skill",
    "subagent",
    "plan_mode",
    "tui",
    "provider",
    "evidence",
}

SUPPORTED_VERIFIERS = {
    "command",
    "pytest",
    "hidden_pytest",
    "forbidden_paths",
    "changed_paths",
    "evidence",
    "trace_consistency",
    "secret_redaction",
}


@dataclass(frozen=True)
class BenchmarkTask:
    task_id: str
    suite: str
    title: str
    category: str
    fixture: str
    fixture_path: Path
    hidden_fixture: str
    hidden_fixture_path: Path | None
    prompt: str
    driver: str
    max_steps: int
    timeout_sec: int
    public_tests: list[str] = field(default_factory=list)
    hidden_tests: list[str] = field(default_factory=list)
    verifiers: list[dict[str, Any]] = field(default_factory=list)
    expected: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def scenario_id(self) -> str:
        scenario = self.raw.get("scenario") or {}
        if isinstance(scenario, dict):
            return str(scenario.get("id") or "").strip()
        return str(scenario or "").strip()


@dataclass(frozen=True)
class Benchmark:
    schema_version: int
    suite: str
    tasks: list[BenchmarkTask]
    raw: dict[str, Any]


def load_benchmark(path: str | Path, repo_root: str | Path | None = None) -> Benchmark:
    path = Path(path)
    if repo_root is None:
        repo_root = path.resolve().parent.parent
    return normalize_benchmark(_load_mapping(path), repo_root=repo_root)


def normalize_benchmark(data: dict[str, Any], repo_root: str | Path) -> Benchmark:
    if not isinstance(data, dict):
        raise ValueError("benchmark must be a mapping")
    schema_version = int(data.get("schema_version", 0))
    if schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {schema_version}")
    suite = _required_text(data, "suite")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("benchmark tasks must be a non-empty list")

    repo_root = Path(repo_root).resolve()
    seen: set[str] = set()
    normalized_tasks = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"task at index {index} must be a mapping")
        normalized = _normalize_task(task, default_suite=suite, repo_root=repo_root, index=index)
        if normalized.task_id in seen:
            raise ValueError(f"duplicate task_id: {normalized.task_id}")
        seen.add(normalized.task_id)
        normalized_tasks.append(normalized)
    return Benchmark(schema_version=schema_version, suite=suite, tasks=normalized_tasks, raw=dict(data))


def _normalize_task(task: dict[str, Any], default_suite: str, repo_root: Path, index: int) -> BenchmarkTask:
    task_id = _text(task.get("task_id", task.get("id", "")))
    if not task_id:
        raise ValueError(f"task at index {index} is missing task_id")
    suite = _text(task.get("suite")) or default_suite
    category = _required_text(task, "category")
    if category not in SUPPORTED_CATEGORIES:
        raise ValueError(f"task {task_id} has unsupported category: {category}")

    repo = _required_mapping(task, "repo", task_id)
    fixture = _required_text(repo, "fixture")
    fixture_path = (repo_root / fixture).resolve()
    if not fixture_path.is_dir():
        raise ValueError(f"task {task_id} fixture does not exist: {fixture}")
    hidden_fixture = _text(repo.get("hidden_fixture"))
    hidden_tests = task.get("hidden_tests") if isinstance(task.get("hidden_tests"), dict) else {}
    if not hidden_fixture and isinstance(hidden_tests, dict):
        hidden_fixture = _text(hidden_tests.get("source"))
    hidden_fixture_path = None
    if hidden_fixture:
        hidden_fixture_path = (repo_root / hidden_fixture).resolve()
        if not hidden_fixture_path.is_dir():
            raise ValueError(f"task {task_id} hidden fixture does not exist: {hidden_fixture}")

    prompt = _prompt_text(task, task_id)
    execution = _required_mapping(task, "execution", task_id)
    driver = _required_text(execution, "driver")
    if driver not in SUPPORTED_DRIVERS:
        raise ValueError(f"task {task_id} has unsupported driver: {driver}")
    max_steps = int(execution.get("max_steps", 0))
    if max_steps < 1:
        raise ValueError(f"task {task_id} execution.max_steps must be positive")
    timeout_sec = int(execution.get("timeout_sec", 300))
    if timeout_sec < 1:
        raise ValueError(f"task {task_id} execution.timeout_sec must be positive")

    tests = task.get("tests") or {}
    if not isinstance(tests, dict):
        raise ValueError(f"task {task_id} tests must be a mapping")
    public_tests = _string_list(tests.get("public") or [])
    if not public_tests:
        raise ValueError(f"task {task_id} tests.public must be non-empty")
    hidden_tests = _string_list(tests.get("hidden") or [])

    verifiers = _verifiers(task, task_id)
    title = _text(task.get("title")) or task_id
    return BenchmarkTask(
        task_id=task_id,
        suite=suite,
        title=title,
        category=category,
        fixture=fixture,
        fixture_path=fixture_path,
        hidden_fixture=hidden_fixture,
        hidden_fixture_path=hidden_fixture_path,
        prompt=prompt,
        driver=driver,
        max_steps=max_steps,
        timeout_sec=timeout_sec,
        public_tests=public_tests,
        hidden_tests=hidden_tests,
        verifiers=verifiers,
        expected=dict(task.get("expected") or {}),
        raw=dict(task),
    )


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except Exception as exc:
            raise ValueError(
                f"{path} is not JSON and PyYAML is not installed; use JSON-compatible YAML"
            ) from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def _verifiers(task: dict[str, Any], task_id: str) -> list[dict[str, Any]]:
    raw = task.get("verifiers")
    if raw is None:
        raw = []
    if isinstance(raw, dict):
        items = []
        for group, value in raw.items():
            if isinstance(value, list):
                items.extend(value)
            else:
                items.append({"type": str(group), **(value if isinstance(value, dict) else {})})
        raw = items
    if not isinstance(raw, list):
        raise ValueError(f"task {task_id} verifiers must be a list or mapping")
    verifiers = []
    for index, verifier in enumerate(raw):
        if isinstance(verifier, str):
            verifier = {"type": verifier}
        if not isinstance(verifier, dict):
            raise ValueError(f"task {task_id} verifier at index {index} must be a mapping")
        verifier_type = _required_text(verifier, "type")
        if verifier_type not in SUPPORTED_VERIFIERS:
            raise ValueError(f"task {task_id} has unsupported verifier type: {verifier_type}")
        verifiers.append(dict(verifier))
    return verifiers


def _prompt_text(task: dict[str, Any], task_id: str) -> str:
    prompt = task.get("prompt")
    if isinstance(prompt, str):
        return prompt.strip()
    if isinstance(prompt, dict):
        text = _required_text(prompt, "text")
        return text
    raise ValueError(f"task {task_id} prompt must be a string or mapping")


def _required_mapping(data: dict[str, Any], key: str, task_id: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"task {task_id} {key} must be a mapping")
    return value


def _required_text(data: dict[str, Any], key: str) -> str:
    value = _text(data.get(key))
    if not value:
        raise ValueError(f"missing required field: {key}")
    return value


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("expected a list")
    return [str(item).strip() for item in value if str(item).strip()]
