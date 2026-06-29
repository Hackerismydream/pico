"""Headless single-task runner backed by the kernel runtime."""

import argparse
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from .providers.clients import FakeModelClient
from .run_store import RunStore
from .runtime_kernel import (
    InvocationContext,
    RuntimeRunner,
    ToolPermissionPolicy,
    ToolRuntime,
)
from .runtime_projections import (
    project_final_answer,
    project_report,
    project_terminal_error,
    project_trace,
)
from .workspace import IGNORED_PATH_NAMES

HEADLESS_TASK_SCHEMA_VERSION = 1
DEFAULT_VERIFIER_TIMEOUT_SECONDS = 30
VERIFIER_ENV_ALLOWLIST = ("HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "TMPDIR", "TMP", "TEMP")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _slug(value):
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value).strip())
    text = "-".join(part for part in text.split("-") if part)
    return text[:48] or "task"


def _new_task_run_id(task_id):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"taskrun_{_slug(task_id)}_{stamp}_{uuid.uuid4().hex[:6]}"


def _sha256_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _relative(path, root):
    return str(Path(path).resolve().relative_to(Path(root).resolve()))


def _text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _resolve_spec_path(raw_path, spec_path):
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    return (spec_path.parent / path).resolve()


@dataclass(frozen=True)
class HeadlessTaskSpec:
    id: str
    prompt: str
    workspace: Path
    verifier_command: str
    verifier_timeout: int
    fake_model_outputs: list[str]
    allowed_tools: list[str]
    max_steps: int
    max_new_tokens: int
    spec_path: Path


@dataclass(frozen=True)
class HeadlessTaskRunResult:
    exit_code: int
    export: dict


def load_headless_task_spec(path):
    spec_path = Path(path).resolve()
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("headless task spec must be a JSON object")

    task_id = str(data.get("id", "")).strip()
    if not task_id:
        raise ValueError("headless task spec is missing id")

    prompt = str(data.get("prompt", "")).strip()
    if not prompt:
        raise ValueError(f"headless task {task_id} is missing prompt")

    workspace_value = data.get("workspace", data.get("fixture_repo", ""))
    if not str(workspace_value).strip():
        raise ValueError(f"headless task {task_id} is missing workspace")
    workspace = _resolve_spec_path(workspace_value, spec_path)
    if not workspace.is_dir():
        raise ValueError(f"headless task {task_id} workspace does not exist: {workspace}")

    verifier = data.get("verifier")
    verifier_timeout = DEFAULT_VERIFIER_TIMEOUT_SECONDS
    if isinstance(verifier, dict):
        verifier_command = str(verifier.get("command", "")).strip()
        if verifier.get("timeout_seconds") is not None:
            verifier_timeout = int(verifier["timeout_seconds"])
    else:
        verifier_command = str(verifier or "").strip()
    if not verifier_command:
        raise ValueError(f"headless task {task_id} is missing verifier")
    if verifier_timeout < 1:
        raise ValueError(f"headless task {task_id} verifier timeout must be positive")

    if "fake_model_outputs" in data:
        fake_model_outputs = _normalize_fake_outputs(data["fake_model_outputs"])
    elif "model_outputs" in data:
        fake_model_outputs = _normalize_fake_outputs(data["model_outputs"])
    else:
        fake_model_outputs = [os.environ.get("PICO_FAKE_MODEL_OUTPUT", "fake response")]

    allowed_tools = _normalize_allowed_tools(data.get("allowed_tools"))
    max_steps = int(data.get("max_steps", data.get("step_budget", 6)))
    if max_steps < 1:
        raise ValueError(f"headless task {task_id} max_steps must be positive")
    max_new_tokens = int(data.get("max_new_tokens", 512))
    if max_new_tokens < 1:
        raise ValueError(f"headless task {task_id} max_new_tokens must be positive")

    return HeadlessTaskSpec(
        id=task_id,
        prompt=prompt,
        workspace=workspace,
        verifier_command=verifier_command,
        verifier_timeout=verifier_timeout,
        fake_model_outputs=fake_model_outputs,
        allowed_tools=allowed_tools,
        max_steps=max_steps,
        max_new_tokens=max_new_tokens,
        spec_path=spec_path,
    )


def _normalize_fake_outputs(value):
    if not isinstance(value, list):
        raise ValueError("fake_model_outputs must be a list")
    return [str(item) for item in value]


def _normalize_allowed_tools(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("allowed_tools must be a list when provided")
    allowed_tools = []
    for item in value:
        name = str(item).strip()
        if not name:
            raise ValueError("allowed_tools contains an empty tool name")
        if name not in ToolRuntime.READ_ONLY_TOOL_NAMES:
            raise ValueError(f"headless task only supports kernel read-only tools: {name}")
        allowed_tools.append(name)
    return allowed_tools


class HeadlessTaskRunner:
    def __init__(self, runs_root):
        self.runs_root = Path(runs_root).resolve()
        self.store = RunStore(self.runs_root)

    def run(self, spec):
        task_run_id = _new_task_run_id(spec.id)
        run_dir = self.store.run_dir(task_run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        isolated_workspace = run_dir / "workspace"

        facts = self._build_facts(spec, task_run_id, run_dir, isolated_workspace)
        self.store.write_task_run_facts(task_run_id, facts)
        self._wal(task_run_id, "task_run_started", task_id=spec.id)

        runtime_info = self._empty_runtime_info()
        verifier_info = self._empty_verifier_info(spec)
        try:
            self._prepare_workspace(spec.workspace, isolated_workspace)
            self._wal(
                task_run_id,
                "workspace_prepared",
                source_workspace=str(spec.workspace),
                isolated_workspace=str(isolated_workspace),
            )
            runtime_info, runtime_result = self._run_runtime(spec, task_run_id, run_dir, isolated_workspace)
            if runtime_result.status != "completed":
                export = self._build_export(
                    spec,
                    task_run_id,
                    run_dir,
                    isolated_workspace,
                    status="infra_fail",
                    failure_kind="infrastructure",
                    failure_category="runtime_failed",
                    runtime_info=runtime_info,
                    verifier_info=verifier_info,
                )
                self._finish(task_run_id, export)
                return HeadlessTaskRunResult(exit_code=1, export=export)

            verifier_info = self._run_verifier(spec, task_run_id, run_dir, isolated_workspace, runtime_info)
            verifier_passed = verifier_info["exit_code"] == 0
            export = self._build_export(
                spec,
                task_run_id,
                run_dir,
                isolated_workspace,
                status="pass" if verifier_passed else "fail",
                failure_kind="" if verifier_passed else "benchmark",
                failure_category="" if verifier_passed else "verifier_failed",
                runtime_info=runtime_info,
                verifier_info=verifier_info,
            )
            self._finish(task_run_id, export)
            return HeadlessTaskRunResult(exit_code=0, export=export)
        except subprocess.TimeoutExpired as exc:
            verifier_info = {
                **verifier_info,
                "timed_out": True,
                "stdout": _text(exc.stdout),
                "stderr": _text(exc.stderr),
            }
            export = self._build_export(
                spec,
                task_run_id,
                run_dir,
                isolated_workspace,
                status="infra_fail",
                failure_kind="infrastructure",
                failure_category="verifier_timeout",
                runtime_info=runtime_info,
                verifier_info=verifier_info,
                infrastructure_error=f"verifier timed out after {spec.verifier_timeout}s",
            )
            self._finish(task_run_id, export)
            return HeadlessTaskRunResult(exit_code=1, export=export)
        except Exception as exc:
            export = self._build_export(
                spec,
                task_run_id,
                run_dir,
                isolated_workspace,
                status="infra_fail",
                failure_kind="infrastructure",
                failure_category="setup_failed",
                runtime_info=runtime_info,
                verifier_info=verifier_info,
                infrastructure_error=str(exc),
            )
            self._finish(task_run_id, export)
            return HeadlessTaskRunResult(exit_code=1, export=export)

    def _build_facts(self, spec, task_run_id, run_dir, isolated_workspace):
        return {
            "artifact_type": "headless-task-run-facts",
            "schema_version": HEADLESS_TASK_SCHEMA_VERSION,
            "task_run_id": task_run_id,
            "created_at": _now(),
            "task": {
                "id": spec.id,
                "prompt": spec.prompt,
                "prompt_sha256": "sha256:" + _sha256_text(spec.prompt),
                "spec_path": str(spec.spec_path),
            },
            "model": {
                "provider": "fake",
                "fake_output_count": len(spec.fake_model_outputs),
                "max_steps": spec.max_steps,
                "max_new_tokens": spec.max_new_tokens,
            },
            "policy": {
                "runtime": "kernel",
                "tool_policy": "headless_explicit_readonly_allowlist",
                "allowed_tools": list(spec.allowed_tools),
                "fail_closed": True,
            },
            "boundaries": {
                "source_workspace": str(spec.workspace),
                "isolated_workspace": str(isolated_workspace),
                "task_run_dir": str(run_dir),
                "verifier_visible_to_runtime": False,
            },
            "verifier": {
                "command": spec.verifier_command,
                "timeout_seconds": spec.verifier_timeout,
                "protected_boundary": True,
            },
        }

    def _prepare_workspace(self, source_workspace, isolated_workspace):
        if isolated_workspace.exists():
            shutil.rmtree(isolated_workspace)
        shutil.copytree(source_workspace, isolated_workspace, ignore=self._copy_ignore)

    @staticmethod
    def _copy_ignore(_directory, names):
        return sorted(name for name in names if name in IGNORED_PATH_NAMES)

    def _run_runtime(self, spec, task_run_id, run_dir, isolated_workspace):
        context = InvocationContext(
            user_message=spec.prompt,
            workspace_root=str(isolated_workspace),
            max_new_tokens=spec.max_new_tokens,
            max_steps=spec.max_steps,
        )
        self._wal(task_run_id, "runtime_started", runtime_run_id=context.invocation_id)
        runtime = self._build_tool_runtime(spec, isolated_workspace)
        result = RuntimeRunner(
            model_client=FakeModelClient(spec.fake_model_outputs),
            tool_runtime=runtime,
        ).run(context)
        runtime_store = RunStore(isolated_workspace / ".pico" / "runs")
        report = project_report(result.events)
        runtime_run_id = report["run_id"] or context.invocation_id
        runtime_events_path = runtime_store.write_runtime_events(runtime_run_id, result.events)
        trace_path = runtime_store.write_trace(runtime_run_id, project_trace(result.events))
        report_path = runtime_store.write_report(runtime_run_id, report)
        provider_calls = list(report.get("provider_calls", []))
        runtime_info = {
            "run_id": runtime_run_id,
            "status": result.status,
            "error_type": result.error_type,
            "error_message": result.error_message,
            "terminal_error": "" if result.status == "completed" else project_terminal_error(result.events),
            "final_answer": project_final_answer(result.events),
            "event_count": len(result.events),
            "event_type_counts": dict(Counter(event.type for event in result.events)),
            "provider_calls": provider_calls,
            "usage": _summarize_provider_usage(provider_calls),
            "cost": _summarize_provider_cost(provider_calls),
            "runtime_events_relpath": _relative(runtime_events_path, run_dir),
            "trace_relpath": _relative(trace_path, run_dir),
            "report_relpath": _relative(report_path, run_dir),
        }
        self._wal(
            task_run_id,
            "runtime_finished",
            runtime_run_id=runtime_run_id,
            status=result.status,
            event_count=len(result.events),
            runtime_events_relpath=runtime_info["runtime_events_relpath"],
        )
        return runtime_info, result

    def _build_tool_runtime(self, spec, isolated_workspace):
        base_runtime = ToolRuntime(isolated_workspace)
        tool_registry = {name: base_runtime.tool_registry[name] for name in spec.allowed_tools}
        return ToolRuntime(
            isolated_workspace,
            tool_registry=tool_registry,
            permission_policy=ToolPermissionPolicy.allow_readonly(
                "headless task allows explicitly listed read-only tools"
            ),
        )

    def _run_verifier(self, spec, task_run_id, run_dir, isolated_workspace, runtime_info):
        self._wal(task_run_id, "verifier_started", protected_boundary=True)
        env = self._verifier_env(spec, task_run_id, run_dir, isolated_workspace, runtime_info)
        completed = subprocess.run(
            spec.verifier_command,
            cwd=isolated_workspace,
            shell=True,
            capture_output=True,
            text=True,
            timeout=spec.verifier_timeout,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        verifier_info = {
            "command": spec.verifier_command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timeout_seconds": spec.verifier_timeout,
            "timed_out": False,
            "protected_boundary": True,
        }
        self._wal(
            task_run_id,
            "verifier_finished",
            protected_boundary=True,
            exit_code=completed.returncode,
        )
        return verifier_info

    def _verifier_env(self, spec, task_run_id, run_dir, isolated_workspace, runtime_info):
        env = {name: os.environ[name] for name in VERIFIER_ENV_ALLOWLIST if name in os.environ}
        env.update(
            {
                "PICO_TASK_ID": spec.id,
                "PICO_TASK_RUN_ID": task_run_id,
                "PICO_TASK_RUN_DIR": str(run_dir),
                "PICO_WORKSPACE": str(isolated_workspace),
                "PICO_FINAL_ANSWER": str(runtime_info.get("final_answer", "")),
                "PICO_RUNTIME_RUN_ID": str(runtime_info.get("run_id", "")),
                "PICO_RUNTIME_EVENTS": str(run_dir / runtime_info.get("runtime_events_relpath", "")),
            }
        )
        return env

    def _build_export(
        self,
        spec,
        task_run_id,
        run_dir,
        isolated_workspace,
        *,
        status,
        failure_kind,
        failure_category,
        runtime_info,
        verifier_info,
        infrastructure_error="",
    ):
        return {
            "artifact_type": "headless-task-run-export",
            "schema_version": HEADLESS_TASK_SCHEMA_VERSION,
            "task_run_id": task_run_id,
            "created_at": _now(),
            "status": status,
            "failure_kind": failure_kind,
            "failure_category": failure_category,
            "infrastructure_error": infrastructure_error,
            "task": {
                "id": spec.id,
                "spec_path": str(spec.spec_path),
                "prompt_sha256": "sha256:" + _sha256_text(spec.prompt),
            },
            "runtime": dict(runtime_info),
            "verifier": dict(verifier_info),
            "boundaries": {
                "source_workspace": str(spec.workspace),
                "isolated_workspace": str(isolated_workspace),
                "task_run_dir": str(run_dir),
                "verifier_visible_to_runtime": False,
            },
            "policy": {
                "runtime": "kernel",
                "model_provider": "fake",
                "tool_policy": "headless_explicit_readonly_allowlist",
                "allowed_tools": list(spec.allowed_tools),
                "fail_closed": True,
            },
            "artifacts": {
                "task_run_facts_relpath": _relative(self.store.task_run_facts_path(task_run_id), run_dir),
                "task_run_wal_relpath": _relative(self.store.task_run_wal_path(task_run_id), run_dir),
                "task_run_export_relpath": _relative(self.store.task_run_export_path(task_run_id), run_dir),
            },
        }

    @staticmethod
    def _empty_runtime_info():
        return {
            "run_id": "",
            "status": "",
            "error_type": "",
            "error_message": "",
            "terminal_error": "",
            "final_answer": "",
            "event_count": 0,
            "event_type_counts": {},
            "provider_calls": [],
            "usage": {},
            "cost": {},
            "runtime_events_relpath": "",
            "trace_relpath": "",
            "report_relpath": "",
        }

    @staticmethod
    def _empty_verifier_info(spec):
        return {
            "command": spec.verifier_command,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "timeout_seconds": spec.verifier_timeout,
            "timed_out": False,
            "protected_boundary": True,
        }

    def _wal(self, task_run_id, event, **payload):
        self.store.append_task_run_wal(
            task_run_id,
            {
                "event": event,
                "created_at": _now(),
                "task_run_id": task_run_id,
                **payload,
            },
        )

    def _finish(self, task_run_id, export):
        self.store.write_task_run_export(task_run_id, export)
        self._wal(
            task_run_id,
            "task_run_finished",
            status=export["status"],
            failure_kind=export["failure_kind"],
            failure_category=export["failure_category"],
        )


def build_headless_task_run_parser():
    parser = argparse.ArgumentParser(
        prog="pico headless task run",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Run one headless kernel-backed task spec with the fake provider.",
    )
    parser.add_argument("spec", help="Path to a headless task JSON spec.")
    parser.add_argument(
        "--runs-root",
        default=str(Path.cwd() / ".pico" / "headless" / "task-runs"),
        help="Directory where task-run artifacts and isolated workspaces are written.",
    )
    parser.add_argument(
        "--fake-output",
        dest="fake_outputs",
        action="append",
        default=None,
        help="Override spec fake_model_outputs. Repeat for multi-step fake provider runs.",
    )
    parser.add_argument("--max-steps", type=int, default=None, help="Override the task runtime step budget.")
    parser.add_argument("--max-new-tokens", type=int, default=None, help="Override the task model output token budget.")
    return parser


def run_headless_task_cli(argv):
    args = build_headless_task_run_parser().parse_args(argv)
    try:
        spec = load_headless_task_spec(args.spec)
        if args.fake_outputs is not None:
            spec = replace(spec, fake_model_outputs=list(args.fake_outputs))
        if args.max_steps is not None:
            spec = replace(spec, max_steps=int(args.max_steps))
        if args.max_new_tokens is not None:
            spec = replace(spec, max_new_tokens=int(args.max_new_tokens))
        result = HeadlessTaskRunner(args.runs_root).run(spec)
    except Exception as exc:
        print(f"headless_task_error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.export, indent=2, sort_keys=True))
    if result.exit_code != 0:
        message = result.export.get("runtime", {}).get("terminal_error") or result.export.get("infrastructure_error")
        if message:
            print(message, file=sys.stderr)
    return result.exit_code


def _summarize_provider_usage(provider_calls):
    totals = {}
    cache_hits = 0
    cache_observations = 0
    for call in provider_calls:
        metadata = dict(call.get("metadata", {}) or {})
        for key in ("input_tokens", "output_tokens", "total_tokens", "cached_tokens"):
            value = metadata.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            totals[key] = totals.get(key, 0) + value
        if "cache_hit" in metadata:
            cache_observations += 1
            if metadata.get("cache_hit") is True:
                cache_hits += 1
    if cache_observations:
        totals["cache_hits"] = cache_hits
        totals["cache_misses"] = cache_observations - cache_hits
    return totals


def _summarize_provider_cost(provider_calls):
    totals = {}
    for call in provider_calls:
        metadata = dict(call.get("metadata", {}) or {})
        for key in ("cost_usd", "estimated_cost_usd", "input_cost_usd", "output_cost_usd", "total_cost_usd"):
            value = metadata.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            totals[key] = totals.get(key, 0.0) + float(value)
    return totals
