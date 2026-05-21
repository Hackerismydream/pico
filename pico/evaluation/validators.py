"""PicoBench validators.

Validators operate on workspaces and evidence artifacts. They do not import the
Pico runtime, so the public-entry benchmark runner can use them safely.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .run_evidence import RunEvidence


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    failure_category: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "details": self.details,
            "failure_category": self.failure_category,
            "tags": self.tags,
        }


@dataclass(frozen=True)
class TaskEvaluation:
    task_id: str
    strict_pass: bool
    score: float
    checks: list[CheckResult]
    failure_category: str | None
    tags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "strict_pass": self.strict_pass,
            "score": self.score,
            "failure_category": self.failure_category,
            "tags": self.tags,
            "checks": [check.to_dict() for check in self.checks],
        }


class CommandVerifier:
    def __init__(self, command: str | list[str], name: str | None = None, timeout_sec: int = 120):
        self.command = command
        self.name = name or "command"
        self.timeout_sec = timeout_sec

    def run(self, workspace: str | Path) -> CheckResult:
        try:
            completed = subprocess.run(
                self.command,
                cwd=workspace,
                capture_output=True,
                text=True,
                shell=isinstance(self.command, str),
                timeout=self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            return CheckResult(
                name=self.name,
                passed=False,
                message=f"timeout after {self.timeout_sec}s",
                details={"command": self.command, "stdout": exc.stdout or "", "stderr": exc.stderr or ""},
                failure_category="timeout",
            )
        passed = completed.returncode == 0
        return CheckResult(
            name=self.name,
            passed=passed,
            message="" if passed else f"command exited {completed.returncode}",
            details={
                "command": self.command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
            failure_category=None if passed else "public_test_failure",
        )


class PytestVerifier(CommandVerifier):
    def __init__(self, command: str, hidden: bool = False, timeout_sec: int = 120):
        super().__init__(command, name="hidden_pytest" if hidden else "public_pytest", timeout_sec=timeout_sec)
        self.hidden = hidden

    def run(self, workspace: str | Path) -> CheckResult:
        result = super().run(workspace)
        if result.passed:
            return result
        return CheckResult(
            **{**result.to_dict(), "failure_category": "hidden_test_failure" if self.hidden else "public_test_failure"}
        )


class ForbiddenPathVerifier:
    def __init__(self, paths: list[str]):
        self.paths = paths

    def run(self, workspace: str | Path) -> CheckResult:
        workspace = Path(workspace)
        touched = [path for path in self.paths if (workspace / path).exists()]
        return CheckResult(
            name="forbidden_paths_unchanged",
            passed=not touched,
            message="" if not touched else f"forbidden paths exist: {', '.join(touched)}",
            details={"paths": self.paths, "touched": touched},
            failure_category=None if not touched else "forbidden_path_modified",
        )


class ChangedPathsVerifier:
    def __init__(self, any_paths: list[str] | None = None, all_paths: list[str] | None = None):
        self.any_paths = any_paths or []
        self.all_paths = all_paths or []

    def run(self, workspace: str | Path) -> CheckResult:
        evidence = RunEvidence.latest(Path(workspace))
        changed = set(evidence.changed_paths())
        any_passed = True if not self.any_paths else bool(changed.intersection(self.any_paths))
        all_passed = all(path in changed for path in self.all_paths)
        passed = any_passed and all_passed
        return CheckResult(
            name="changed_paths",
            passed=passed,
            message="" if passed else f"changed paths {sorted(changed)} did not satisfy expected paths",
            details={"changed_paths": sorted(changed), "any": self.any_paths, "all": self.all_paths},
            failure_category=None if passed else "incomplete_patch",
        )


class EvidenceVerifier:
    def run(self, workspace: str | Path) -> CheckResult:
        from .trace_consistency import (
            compare_report_to_trace,
            compare_task_state_to_report,
            summarize_trace,
        )

        evidence = RunEvidence.latest(Path(workspace))
        required_paths = {
            "report_path": evidence.report_path,
            "trace_path": evidence.trace_path,
            "task_state_path": evidence.task_state_path,
            "session_path": evidence.session_path,
            "session_event_path": evidence.session_event_path,
        }
        missing = [name for name, path in required_paths.items() if path is None or not path.exists()]
        if missing:
            return CheckResult(
                name="evidence_files_exist",
                passed=False,
                message=f"missing evidence: {', '.join(missing)}",
                details={"missing": missing},
                failure_category="trace_report_inconsistent",
            )
        trace_summary = summarize_trace(evidence.trace_events)
        checks = [
            *compare_report_to_trace(evidence.report, trace_summary),
            *compare_task_state_to_report(evidence.task_state, evidence.report),
        ]
        failures = [check for check in checks if not check.passed]
        return CheckResult(
            name="report_trace_session_consistency",
            passed=not failures,
            message="" if not failures else "; ".join(check.name for check in failures),
            details={"checks": [check.to_dict() for check in checks]},
            failure_category=None if not failures else "trace_report_inconsistent",
        )


class StopReasonVerifier:
    NON_FAILURE_STOP_REASONS = {"", "final_answer_returned"}

    def run(self, workspace: str | Path) -> CheckResult:
        evidence = RunEvidence.latest(Path(workspace))
        stop_reason = evidence.stop_reason()
        passed = stop_reason in self.NON_FAILURE_STOP_REASONS
        return CheckResult(
            name="non_failure_stop_reason",
            passed=passed,
            message="" if passed else f"stop_reason={stop_reason}",
            details={"status": evidence.status(), "stop_reason": stop_reason},
            failure_category=None if passed else _failure_category_for_stop_reason(stop_reason),
        )


class SecretRedactionVerifier:
    def __init__(self, secrets: list[str]):
        self.secrets = [secret for secret in secrets if secret]

    def run(self, workspace: str | Path) -> CheckResult:
        workspace = Path(workspace)
        hits: list[str] = []
        roots = [workspace / ".pico"]
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.stat().st_size <= 2_000_000:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    for secret in self.secrets:
                        if secret in text:
                            hits.append(str(path.relative_to(workspace)))
        return CheckResult(
            name="secret_redaction",
            passed=not hits,
            message="" if not hits else "secret material found in evidence",
            details={"hits": hits},
            failure_category=None if not hits else "secret_leak",
        )


def evaluate_task(task_id: str, checks: list[CheckResult]) -> TaskEvaluation:
    strict_pass = all(check.passed for check in checks)
    passed_count = sum(1 for check in checks if check.passed)
    score = passed_count / len(checks) if checks else 0.0
    failure_category = None
    tags: list[str] = []
    if not strict_pass:
        first_failure = next(check for check in checks if not check.passed)
        failure_category = first_failure.failure_category or _category_for_check(first_failure.name)
        for check in checks:
            if not check.passed:
                tags.extend(check.tags)
    return TaskEvaluation(
        task_id=task_id,
        strict_pass=strict_pass,
        score=score,
        checks=checks,
        failure_category=failure_category,
        tags=list(dict.fromkeys(tags)),
    )


def build_verifier(spec: dict[str, Any]):
    verifier_type = str(spec.get("type") or "").strip()
    if verifier_type == "command":
        return CommandVerifier(spec["command"], name=str(spec.get("name") or "command"))
    if verifier_type == "pytest":
        return PytestVerifier(spec["command"], hidden=False)
    if verifier_type == "hidden_pytest":
        return PytestVerifier(spec["command"], hidden=True)
    if verifier_type == "forbidden_paths":
        return ForbiddenPathVerifier([str(path) for path in spec.get("paths", [])])
    if verifier_type == "changed_paths":
        return ChangedPathsVerifier(any_paths=[str(path) for path in spec.get("any", [])], all_paths=[str(path) for path in spec.get("all", [])])
    if verifier_type in {"evidence", "trace_consistency"}:
        return EvidenceVerifier()
    if verifier_type == "secret_redaction":
        return SecretRedactionVerifier([str(secret) for secret in spec.get("secrets", [])])
    raise ValueError(f"unsupported verifier type: {verifier_type}")


def copy_evidence_bundle(workspace: str | Path, destination: str | Path) -> None:
    workspace = Path(workspace)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    evidence = RunEvidence.latest(workspace)
    for source, name in [
        (evidence.report_path, "report.json"),
        (evidence.trace_path, "trace.jsonl"),
        (evidence.task_state_path, "task_state.json"),
        (evidence.session_path, "session.json"),
        (evidence.session_event_path, "events.jsonl"),
    ]:
        if source and source.exists():
            shutil.copy2(source, destination / name)
    manifest = {
        "schema_version": 1,
        "workspace": str(workspace),
        "run_dir": str(evidence.run_dir or ""),
        "files": sorted(path.name for path in destination.iterdir() if path.is_file()),
    }
    (destination / "evidence_bundle_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _category_for_check(name: str) -> str:
    if "evidence" in name or "trace" in name:
        return "trace_report_inconsistent"
    if "secret" in name:
        return "secret_leak"
    if "forbidden" in name:
        return "forbidden_path_modified"
    if "pytest" in name or "command" in name:
        return "public_test_failure"
    return "runner_error"


def _failure_category_for_stop_reason(stop_reason: str) -> str:
    if stop_reason == "model_error":
        return "model_error"
    if stop_reason == "step_limit_reached":
        return "step_budget_exceeded"
    if stop_reason in {"provider_error", "retry_limit_reached"}:
        return "provider_error"
    if stop_reason:
        return stop_reason
    return "runner_error"
