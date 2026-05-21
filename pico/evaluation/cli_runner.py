"""Public-entry PicoBench runner."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .benchmark_schema import Benchmark, BenchmarkTask
from .report_card import build_report_card, write_report_card
from .run_evidence import RunEvidence
from .validators import (
    CommandVerifier,
    PytestVerifier,
    StopReasonVerifier,
    build_verifier,
    copy_evidence_bundle,
    evaluate_task,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CommandRecord:
    command: list[str]
    returncode: int
    duration_ms: int
    stdout_path: str
    stderr_path: str


class PicoBenchRunner:
    def __init__(
        self,
        benchmark: Benchmark,
        output_dir: str | Path,
        suite: str | None = None,
        task_ids: list[str] | None = None,
        pico_command: str = "uv run pico",
        provider: str | None = None,
        model: str | None = None,
        approval: str = "auto",
        sandbox: str = "best_effort",
        config: str | None = None,
        runs: int = 1,
        no_hidden_tests: bool = False,
        fail_fast: bool = False,
        keep_workspaces: bool = True,
    ):
        self.benchmark = benchmark
        self.output_dir = Path(output_dir).resolve()
        if _is_relative_to(self.output_dir, REPO_ROOT):
            raise ValueError("output-dir must be outside the Pico repo")
        self.suite = suite
        self.task_ids = set(task_ids or [])
        self.pico_command = pico_command
        self.provider = provider
        self.model = model
        self.approval = approval
        self.sandbox = sandbox
        self.config = config
        self.runs = runs
        self.no_hidden_tests = no_hidden_tests
        self.fail_fast = fail_fast
        self.keep_workspaces = keep_workspaces
        self.logs_dir = self.output_dir / "logs"
        self.workspaces_dir = self.output_dir / "workspaces"
        self.evidence_dir = self.output_dir / "evidence"
        self.failures_dir = self.output_dir / "failures"

    def run(self) -> dict[str, Any]:
        self._prepare_dirs()
        results = []
        selected = self._selected_tasks()
        for task in selected:
            for run_index in range(1, self.runs + 1):
                result = self._run_task(task, run_index)
                results.append(result)
                self._write_task_result(result)
                if self.fail_fast and not result["strict_pass"]:
                    summary = self._write_summary(results)
                    return summary
        return self._write_summary(results)

    def _selected_tasks(self) -> list[BenchmarkTask]:
        tasks = [task for task in self.benchmark.tasks if not self.suite or _suite_matches(task.suite, self.suite)]
        if self.task_ids:
            tasks = [task for task in tasks if task.task_id in self.task_ids]
        if not tasks:
            raise ValueError("no benchmark tasks selected")
        return tasks

    def _run_task(self, task: BenchmarkTask, run_index: int) -> dict[str, Any]:
        started = time.monotonic()
        workspace = self.workspaces_dir / f"{task.task_id}-run{run_index}"
        if workspace.exists():
            shutil.rmtree(workspace)
        shutil.copytree(task.fixture_path, workspace)
        self._git_init(workspace)
        command_record = self._run_pico(task, run_index, workspace)
        checks = []
        checks.append(
            _command_check(command_record.returncode == 0, "pico_command_exit_0", command_record)
        )
        checks.append(StopReasonVerifier().run(workspace))
        for command in task.public_tests:
            checks.append(CommandVerifier(command, name="public_test").run(workspace))
        if not self.no_hidden_tests:
            for command in task.hidden_tests:
                checks.append(PytestVerifier(command, hidden=True).run(workspace))
        for verifier_spec in task.verifiers:
            checks.append(build_verifier(verifier_spec).run(workspace))
        evaluation = evaluate_task(task.task_id, checks)
        evidence = RunEvidence.latest(workspace)
        evidence_path = self.evidence_dir / f"{task.task_id}-run{run_index}"
        copy_evidence_bundle(workspace, evidence_path)
        result = {
            "task_id": task.task_id,
            "title": task.title,
            "suite": task.suite,
            "category": task.category,
            "run_index": run_index,
            "strict_pass": evaluation.strict_pass,
            "score": evaluation.score,
            "failure_category": evaluation.failure_category,
            "tags": evaluation.tags,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "workspace": str(workspace),
            "evidence_path": str(evidence_path),
            "command": {
                "command": command_record.command,
                "returncode": command_record.returncode,
                "duration_ms": command_record.duration_ms,
                "stdout_path": command_record.stdout_path,
                "stderr_path": command_record.stderr_path,
            },
            "report": evidence.report,
            "checks": [check.to_dict() for check in evaluation.checks],
        }
        if not evaluation.strict_pass:
            self._write_failure(task, result)
        return result

    def _run_pico(self, task: BenchmarkTask, run_index: int, workspace: Path) -> CommandRecord:
        command = [*shlex.split(self.pico_command), "--cwd", str(workspace), "--approval", self.approval]
        stdin_text = None
        if self.sandbox:
            command.extend(["--sandbox", self.sandbox])
        command.extend(["--max-steps", str(task.max_steps)])
        if self.provider:
            command.extend(["--provider", self.provider])
        if self.model:
            command.extend(["--model", self.model])
        if self.config:
            command.extend(["--config", self.config])
        if task.driver == "repl":
            command.append("--repl")
            stdin_text = task.prompt + "\n/exit\n"
        elif task.driver in {"pty", "tui"}:
            command.extend(["--repl"])
            stdin_text = task.prompt + "\n/exit\n"
        else:
            command.append(task.prompt)
        stdout_path = self.logs_dir / f"{task.task_id}-run{run_index}.stdout.txt"
        stderr_path = self.logs_dir / f"{task.task_id}-run{run_index}.stderr.txt"
        command_path = self.logs_dir / f"{task.task_id}-run{run_index}.command.json"
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            input=stdin_text,
            timeout=task.timeout_sec,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        command_path.write_text(
            json.dumps(
                {
                    "command": command,
                    "returncode": completed.returncode,
                    "duration_ms": duration_ms,
                    "workspace": str(workspace),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return CommandRecord(
            command=command,
            returncode=completed.returncode,
            duration_ms=duration_ms,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
        )

    def _write_summary(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        summary = build_report_card(
            suite=self.suite or self.benchmark.suite,
            benchmark_suite=self.benchmark.suite,
            provider=self.provider,
            model=self.model,
            output_dir=self.output_dir,
            pico_commit=_git_value(["rev-parse", "HEAD"]),
            started_at=datetime.now().isoformat(timespec="seconds"),
            results=results,
        )
        write_report_card(summary, self.output_dir)
        return summary

    def _write_task_result(self, result: dict[str, Any]) -> None:
        with (self.output_dir / "task_results.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(result, sort_keys=True) + "\n")

    def _write_failure(self, task: BenchmarkTask, result: dict[str, Any]) -> None:
        lines = [
            f"# {task.task_id} Failure",
            "",
            f"- title: {task.title}",
            f"- category: {task.category}",
            f"- failure_category: {result.get('failure_category')}",
            f"- workspace: {result.get('workspace')}",
            f"- evidence: {result.get('evidence_path')}",
            "",
            "## Checks",
            "",
        ]
        for check in result["checks"]:
            lines.append(f"- [{'x' if check['passed'] else ' '}] {check['name']}: {check.get('message') or ''}")
        (self.failures_dir / f"{task.task_id}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _prepare_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for path in [self.logs_dir, self.workspaces_dir, self.evidence_dir, self.failures_dir]:
            path.mkdir(parents=True, exist_ok=True)
        task_results = self.output_dir / "task_results.jsonl"
        if task_results.exists():
            task_results.unlink()

    @staticmethod
    def _git_init(workspace: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        subprocess.run(["git", "add", "."], cwd=workspace, check=True)
        subprocess.run(
            ["git", "-c", "user.email=picobench@example.invalid", "-c", "user.name=PicoBench", "commit", "-qm", "initial fixture"],
            cwd=workspace,
            check=True,
        )


def _command_check(passed: bool, name: str, command: CommandRecord):
    from .validators import CheckResult

    return CheckResult(
        name=name,
        passed=passed,
        message="" if passed else f"command exited {command.returncode}",
        details={"command": command.command, "returncode": command.returncode},
        failure_category=None if passed else "runner_error",
    )


def _suite_matches(task_suite: str, selected: str) -> bool:
    return task_suite == selected or task_suite.endswith(f"-{selected}")


def _git_value(args: list[str]) -> str:
    try:
        completed = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=5)
        return completed.stdout.strip()
    except Exception:
        return ""


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False
