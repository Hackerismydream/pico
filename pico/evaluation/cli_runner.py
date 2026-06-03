"""Public-entry PicoBench runner."""

from __future__ import annotations

import json
import os
import pty
import select
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
    CheckResult,
    PytestVerifier,
    StopReasonVerifier,
    build_verifier,
    copy_evidence_bundle,
    evaluate_task,
)
from ..config import load_project_env


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_BENCHMARK_RUNS_DIR = REPO_ROOT / "_local" / "benchmark" / "runs"
LEGACY_PROVIDER_ENV_BRIDGES = (
    ("PICO_OPENAI_API_KEY", "OPENAI_API_KEY"),
    ("PICO_OPENAI_API_BASE", "OPENAI_API_BASE"),
    ("PICO_OPENAI_MODEL", "OPENAI_MODEL"),
    ("PICO_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    ("PICO_ANTHROPIC_API_BASE", "ANTHROPIC_API_BASE"),
    ("PICO_ANTHROPIC_MODEL", "ANTHROPIC_MODEL"),
    ("PICO_RIGHT_CODES_API_KEY", "RIGHT_CODES_API_KEY"),
    ("PICO_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
    ("PICO_DEEPSEEK_API_BASE", "DEEPSEEK_API_BASE"),
    ("PICO_DEEPSEEK_MODEL", "DEEPSEEK_MODEL"),
)


@dataclass(frozen=True)
class CommandRecord:
    command: list[str]
    returncode: int
    duration_ms: int
    stdout_path: str
    stderr_path: str
    timed_out: bool = False
    error: str = ""


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
        driver_override: str | None = None,
        max_steps_override: int | None = None,
        timeout_sec_override: int | None = None,
        pico_extra_args: list[str] | None = None,
    ):
        self.benchmark = benchmark
        self.output_dir = Path(output_dir).resolve()
        if not _output_dir_allowed(self.output_dir):
            raise ValueError("output-dir 必须在 Pico repo 之外，或 _local/benchmark/runs 下")
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
        self.driver_override = driver_override
        self.max_steps_override = max_steps_override
        self.timeout_sec_override = timeout_sec_override
        self.pico_extra_args = list(pico_extra_args or [])
        self.child_env = _child_env_with_project_provider_vars()
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
            raise ValueError("没有选中任何 benchmark 任务")
        return tasks

    def _run_task(self, task: BenchmarkTask, run_index: int) -> dict[str, Any]:
        started = time.monotonic()
        workspace = self.workspaces_dir / f"{task.task_id}-run{run_index}"
        if workspace.exists():
            shutil.rmtree(workspace)
        shutil.copytree(task.fixture_path, workspace)
        self._git_init(workspace)
        driver = self.driver_override or task.driver
        if driver == "tui" and os.environ.get("PICOBENCH_ENABLE_TUI") != "1":
            result = self._skipped_result(task, run_index, workspace, started, "tui driver 需要交互式终端 smoke 测试")
            if not self.keep_workspaces:
                shutil.rmtree(workspace, ignore_errors=True)
            return result
        if driver == "v3_human_gate":
            return self._run_v3_human_gate_task(task, run_index, workspace, started)
        if driver == "resume_cli":
            return self._run_resume_cli_task(task, run_index, workspace, started)
        command_record = self._run_pico(task, run_index, workspace)
        checks = []
        checks.append(
            _command_check(command_record.returncode == 0, "pico_command_exit_0", command_record)
        )
        checks.append(StopReasonVerifier().run(workspace))
        for command in task.public_tests:
            checks.append(CommandVerifier(command, name="public_test").run(workspace))
        if not self.no_hidden_tests:
            self._inject_hidden_tests(task, workspace)
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
            "evidence_mode": "native",
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
        if not self.keep_workspaces:
            shutil.rmtree(workspace, ignore_errors=True)
        return result

    def _run_resume_cli_task(self, task: BenchmarkTask, run_index: int, workspace: Path, started: float) -> dict[str, Any]:
        resume_spec = task.raw.get("resume") if isinstance(task.raw.get("resume"), dict) else {}
        first_prompt = str(resume_spec.get("first_prompt") or task.prompt).strip()
        resume_prompt = str(resume_spec.get("resume_prompt") or task.prompt).strip()
        first_steps = int(resume_spec.get("first_max_steps") or self.max_steps_override or task.max_steps)
        resume_steps = int(resume_spec.get("resume_max_steps") or self.max_steps_override or task.max_steps)

        first_command = self._run_pico(
            task,
            run_index,
            workspace,
            prompt_override=first_prompt,
            max_steps_override=first_steps,
            log_suffix=f"run{run_index}-first",
        )
        resume_command = self._run_pico(
            task,
            run_index,
            workspace,
            prompt_override=resume_prompt,
            extra_args=["--resume", "latest"],
            max_steps_override=resume_steps,
            log_suffix=f"run{run_index}-resume",
        )
        checks = [
            _command_check(first_command.returncode == 0, "pico_first_command_exit_0", first_command),
            _command_check(resume_command.returncode == 0, "pico_resume_command_exit_0", resume_command),
            _resume_two_pass_check(workspace, first_command, resume_command),
            StopReasonVerifier().run(workspace),
        ]
        for command in task.public_tests:
            checks.append(CommandVerifier(command, name="public_test").run(workspace))
        if not self.no_hidden_tests:
            self._inject_hidden_tests(task, workspace)
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
            "evidence_mode": "native",
            "command": {
                "command": resume_command.command,
                "returncode": resume_command.returncode,
                "duration_ms": resume_command.duration_ms,
                "stdout_path": resume_command.stdout_path,
                "stderr_path": resume_command.stderr_path,
            },
            "commands": {
                "first": first_command.__dict__,
                "resume": resume_command.__dict__,
            },
            "report": evidence.report,
            "checks": [check.to_dict() for check in evaluation.checks],
        }
        if not evaluation.strict_pass:
            self._write_failure(task, result)
        if not self.keep_workspaces:
            shutil.rmtree(workspace, ignore_errors=True)
        return result

    def _run_v3_human_gate_task(self, task: BenchmarkTask, run_index: int, workspace: Path, started: float) -> dict[str, Any]:
        scenario_id = task.scenario_id or task.task_id
        scenario_output = self.output_dir / "scenario_runs" / f"{task.task_id}-run{run_index}"
        command = [
            "uv",
            "run",
            "python",
            "scripts/run_v3_human_scenario_gate.py",
            "--suite",
            "full",
            "--scenario",
            scenario_id,
            "--output-dir",
            str(scenario_output),
        ]
        stdout_path = self.logs_dir / f"{task.task_id}-run{run_index}.stdout.txt"
        stderr_path = self.logs_dir / f"{task.task_id}-run{run_index}.stderr.txt"
        command_path = self.logs_dir / f"{task.task_id}-run{run_index}.command.json"
        try:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec_override or task.timeout_sec,
                env=self.child_env,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
            timed_out = False
            error = ""
        except subprocess.TimeoutExpired as exc:
            stdout = _decode_output(exc.stdout)
            stderr = _decode_output(exc.stderr) + f"\n{self.timeout_sec_override or task.timeout_sec}s 后超时"
            returncode = 124
            timed_out = True
            error = "timeout"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        command_path.write_text(
            json.dumps(
                {
                    "command": command,
                    "returncode": returncode,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "workspace": str(workspace),
                    "scenario_output": str(scenario_output),
                    "timed_out": timed_out,
                    "error": error,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        summary_path = scenario_output / "summary.json"
        scenario_summary = {}
        if summary_path.exists():
            scenario_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        passed = returncode == 0 and scenario_summary.get("failed", 1) == 0
        checks = [
            {
                "name": "v3_human_gate",
                "passed": passed,
                "message": "" if passed else f"scenario {scenario_id} 失败",
                "details": {"summary": scenario_summary, "returncode": returncode},
                "failure_category": None if passed else ("timeout" if timed_out else "runner_error"),
                "tags": [],
            }
        ]
        result = {
            "task_id": task.task_id,
            "title": task.title,
            "suite": task.suite,
            "category": task.category,
            "run_index": run_index,
            "strict_pass": passed,
            "score": 1.0 if passed else 0.0,
            "failure_category": None if passed else ("timeout" if timed_out else "runner_error"),
            "tags": [],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "workspace": str(workspace),
            "evidence_path": str(scenario_output),
            "evidence_mode": "delegated_human_gate",
            "command": {
                "command": command,
                "returncode": returncode,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "timed_out": timed_out,
                "error": error,
            },
            "report": scenario_summary,
            "checks": checks,
        }
        if not passed:
            self._write_failure(task, result)
        if not self.keep_workspaces:
            shutil.rmtree(workspace, ignore_errors=True)
        return result

    def _skipped_result(self, task: BenchmarkTask, run_index: int, workspace: Path, started: float, reason: str) -> dict[str, Any]:
        result = {
            "task_id": task.task_id,
            "title": task.title,
            "suite": task.suite,
            "category": task.category,
            "run_index": run_index,
            "strict_pass": False,
            "skipped": True,
            "skip_reason": reason,
            "score": 0.0,
            "failure_category": None,
            "tags": ["skipped"],
            "duration_ms": int((time.monotonic() - started) * 1000),
            "workspace": str(workspace),
            "evidence_path": "",
            "evidence_mode": "native",
            "command": {},
            "report": {},
            "checks": [],
        }
        return result

    def _run_pico(
        self,
        task: BenchmarkTask,
        run_index: int,
        workspace: Path,
        *,
        prompt_override: str | None = None,
        extra_args: list[str] | None = None,
        max_steps_override: int | None = None,
        log_suffix: str | None = None,
    ) -> CommandRecord:
        driver = self.driver_override or task.driver
        max_steps = max_steps_override or self.max_steps_override or task.max_steps
        timeout_sec = self.timeout_sec_override or task.timeout_sec
        command = [*shlex.split(self.pico_command), "--cwd", str(workspace), "--approval", self.approval]
        stdin_text = None
        if self.sandbox:
            command.extend(["--sandbox", self.sandbox])
        command.extend(["--max-steps", str(max_steps)])
        if self.provider:
            command.extend(["--provider", self.provider])
        if self.model:
            command.extend(["--model", self.model])
        if self.config:
            command.extend(["--config", self.config])
        command.extend(self.pico_extra_args)
        if extra_args:
            command.extend(extra_args)
        prompt = prompt_override if prompt_override is not None else task.prompt
        if driver == "repl":
            command.append("--repl")
            stdin_text = prompt + "\n/exit\n"
        elif driver == "pty":
            command.append("--repl")
            stdin_text = prompt + "\n/exit\n"
        else:
            command.append(prompt)
        suffix = log_suffix or f"run{run_index}"
        stdout_path = self.logs_dir / f"{task.task_id}-{suffix}.stdout.txt"
        stderr_path = self.logs_dir / f"{task.task_id}-{suffix}.stderr.txt"
        command_path = self.logs_dir / f"{task.task_id}-{suffix}.command.json"
        started = time.monotonic()
        try:
            if driver == "pty":
                completed = _run_pty(command, stdin_text or "", timeout_sec=timeout_sec, env=self.child_env)
            else:
                completed = subprocess.run(
                    command,
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    input=stdin_text,
                    timeout=timeout_sec,
                    env=self.child_env,
                )
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
            timed_out = False
            error = ""
        except subprocess.TimeoutExpired as exc:
            stdout = _decode_output(exc.stdout)
            stderr = _decode_output(exc.stderr) + f"\n{timeout_sec}s 后超时"
            returncode = 124
            timed_out = True
            error = "timeout"
        except FileNotFoundError as exc:
            stdout = ""
            stderr = str(exc)
            returncode = 127
            timed_out = False
            error = "file_not_found"
        except Exception as exc:  # noqa: BLE001 - runner records task-level failures.
            stdout = ""
            stderr = str(exc)
            returncode = 1
            timed_out = False
            error = type(exc).__name__
        duration_ms = int((time.monotonic() - started) * 1000)
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        command_path.write_text(
            json.dumps(
                {
                    "command": command,
                    "returncode": returncode,
                    "duration_ms": duration_ms,
                    "workspace": str(workspace),
                    "timed_out": timed_out,
                    "error": error,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return CommandRecord(
            command=command,
            returncode=returncode,
            duration_ms=duration_ms,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            timed_out=timed_out,
            error=error,
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
            f"# {task.task_id} 失败报告",
            "",
            f"- 标题: {task.title}",
            f"- 类别: {task.category}",
            f"- 失败类别: {result.get('failure_category')}",
            f"- 工作区: {result.get('workspace')}",
            f"- Evidence: {result.get('evidence_path')}",
            "",
            "## 检查项",
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
    def _inject_hidden_tests(task: BenchmarkTask, workspace: Path) -> None:
        if task.hidden_fixture_path is None:
            return
        source = task.hidden_fixture_path
        hidden_source = source / "hidden_tests" if (source / "hidden_tests").is_dir() else source
        destination = workspace / "hidden_tests"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(hidden_source, destination)

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
    return CheckResult(
        name=name,
        passed=passed,
        message="" if passed else (command.error or f"命令退出码 {command.returncode}"),
        details={
            "command": command.command,
            "returncode": command.returncode,
            "timed_out": command.timed_out,
            "error": command.error,
        },
        failure_category=None if passed else ("timeout" if command.timed_out else "runner_error"),
    )


def _resume_two_pass_check(workspace: Path, first_command: CommandRecord, resume_command: CommandRecord) -> CheckResult:
    run_dirs = _run_dirs(workspace)
    first_manifest = _read_json(run_dirs[0] / "run_manifest.json") if run_dirs else {}
    latest_manifest = _read_json(run_dirs[-1] / "run_manifest.json") if run_dirs else {}
    first_state = _read_json(run_dirs[0] / "task_state.json") if run_dirs else {}
    latest_state = _read_json(run_dirs[-1] / "task_state.json") if run_dirs else {}
    latest_report = _read_json(run_dirs[-1] / "report.json") if run_dirs else {}
    latest_prompt_metadata = latest_report.get("prompt_metadata") if isinstance(latest_report.get("prompt_metadata"), dict) else {}
    first_session_id = str(first_manifest.get("session_id") or "")
    latest_session_id = str(latest_manifest.get("session_id") or "")
    first_checkpoint_id = str(first_state.get("checkpoint_id") or "")
    latest_checkpoint_id = str(latest_state.get("checkpoint_id") or latest_report.get("checkpoint_id") or "")
    resume_status = str(latest_state.get("resume_status") or latest_prompt_metadata.get("resume_status") or "")
    checks = {
        "two_run_artifacts": len(run_dirs) >= 2,
        "first_command_no_resume": "--resume" not in first_command.command,
        "resume_command_uses_latest": _has_resume_latest(resume_command.command),
        "same_session": bool(first_session_id and first_session_id == latest_session_id),
        "checkpoint_seen": bool(first_checkpoint_id or latest_checkpoint_id),
        "resume_state_loaded": bool(resume_status and resume_status != "no-checkpoint"),
    }
    passed = all(checks.values())
    return CheckResult(
        name="resume_two_pass",
        passed=passed,
        message="" if passed else "two-pass resume evidence 不完整",
        details={
            "checks": checks,
            "run_dirs": [str(path) for path in run_dirs],
            "first_session_id": first_session_id,
            "latest_session_id": latest_session_id,
            "first_checkpoint_id": first_checkpoint_id,
            "latest_checkpoint_id": latest_checkpoint_id,
            "resume_status": resume_status,
            "first_command": first_command.command,
            "resume_command": resume_command.command,
        },
        failure_category=None if passed else "resume_lineage_failure",
    )


def _run_dirs(workspace: Path) -> list[Path]:
    root = workspace / ".pico" / "runs"
    if not root.exists():
        return []
    return sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _has_resume_latest(command: list[str]) -> bool:
    return any(left == "--resume" and right == "latest" for left, right in zip(command, command[1:]))


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


def _output_dir_allowed(path: str | Path) -> bool:
    resolved = Path(path).resolve()
    if not _is_relative_to(resolved, REPO_ROOT):
        return True
    return _is_relative_to(resolved, LOCAL_BENCHMARK_RUNS_DIR)


def _decode_output(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _child_env_with_project_provider_vars() -> dict[str, str]:
    env = os.environ.copy()
    for name, value in load_project_env(REPO_ROOT, override=False).items():
        env.setdefault(name, value)
    _bridge_legacy_provider_env(env)
    return env


def _bridge_legacy_provider_env(env: dict[str, str]) -> None:
    for legacy_name, canonical_name in LEGACY_PROVIDER_ENV_BRIDGES:
        value = env.get(legacy_name)
        if value and not env.get(canonical_name):
            env[canonical_name] = value


def _run_pty(command: list[str], stdin_text: str, timeout_sec: int, env: dict[str, str] | None = None):
    output: list[bytes] = []
    start = time.monotonic()
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        env=env,
    )
    os.close(slave_fd)
    if stdin_text:
        os.write(master_fd, stdin_text.encode("utf-8"))
    while process.poll() is None:
        if time.monotonic() - start > timeout_sec:
            process.kill()
            raise subprocess.TimeoutExpired(command, timeout_sec, output=b"".join(output))
        readable, _, _ = select.select([master_fd], [], [], 0.05)
        if master_fd in readable:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if chunk:
                output.append(chunk)
    while True:
        readable, _, _ = select.select([master_fd], [], [], 0)
        if master_fd not in readable:
            break
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        output.append(chunk)
    os.close(master_fd)
    return subprocess.CompletedProcess(
        command,
        process.returncode or 0,
        stdout=b"".join(output).decode("utf-8", errors="replace"),
        stderr="",
    )
