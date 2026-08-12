from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from benchmarks.picobench.canonical import canonical_digest

from .campaign import CampaignConfig, ExperimentArm, TaskDefinition, TrialRecord


class InstalledTrialExecutor:
    def __init__(self, config: CampaignConfig) -> None:
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("uv is required for installed Myna task-effect trials")
        self._uv_cache = Path(os.environ.get("UV_CACHE_DIR", Path.home() / ".cache" / "uv")).resolve()
        self._temporary = tempfile.TemporaryDirectory(prefix="picobench-myna-task-effect-")
        self._root = Path(self._temporary.name)
        self._model_cache = self._root / "model-cache"
        self._model_cache.mkdir()
        self._environment = self._root / "environment"
        self._run(
            (uv, "venv", "--python", "3.12", str(self._environment)),
            cwd=self._root,
        )
        self._run(
            (
                uv,
                "pip",
                "install",
                "--python",
                str(self._environment / "bin" / "python"),
                str(config.pico_wheel.resolve()),
                str(config.myna_wheel.resolve()),
            ),
            cwd=self._root,
        )
        self._python = self._environment / "bin" / "python"
        self._myna = self._environment / "bin" / "myna"
        self._worker = Path(__file__).with_name("worker.py").resolve()
        identity = self._worker_call({"worker_mode": "identity"}, self._root / "identity")
        self.identity = self._validate_identity(identity)

    def close(self) -> None:
        self._temporary.cleanup()

    def __enter__(self) -> InstalledTrialExecutor:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __call__(
        self,
        task: TaskDefinition,
        repetition: int,
        arm: ExperimentArm,
        config: CampaignConfig,
    ) -> TrialRecord:
        del config
        trial_root = self._root / "trials" / task.task_id / str(repetition) / arm.arm_id
        workspace = trial_root / "repository"
        workspace.mkdir(parents=True)
        source = workspace.joinpath(*PurePosixPath(task.source_path).parts)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(task.source_text, encoding="utf-8")
        self._run(("git", "init", "-q"), cwd=workspace)
        fixture_digest = canonical_digest(
            {
                "task_id": task.task_id,
                "source_path": task.source_path,
                "source_sha256": hashlib.sha256(task.source_text.encode()).hexdigest(),
            }
        )
        try:
            operations: tuple[str, ...] = ()
            if arm.arm_id == "memory_on":
                runtime_root = trial_root / "myna-runtime"
                self._run(
                    (
                        str(self._myna),
                        "init",
                        "--root",
                        str(runtime_root),
                        "--repo-key",
                        task.repository_id,
                        "--retrieval-profile",
                        "fastembed",
                        "--semantic-profile",
                        "none",
                        "--prefetch",
                    ),
                    cwd=workspace,
                )
            prime = self._worker_call(
                self._turn_spec(
                    task,
                    repetition=repetition,
                    arm=arm,
                    stage="prime",
                    workspace=workspace,
                    state_root=trial_root / "prime-state",
                    prompt=("Record this completed repository experience for later work.\n\n" + task.memory_text),
                ),
                trial_root / "prime-worker",
            )
            evaluation = self._worker_call(
                self._turn_spec(
                    task,
                    repetition=repetition,
                    arm=arm,
                    stage="evaluate",
                    workspace=workspace,
                    state_root=trial_root / "evaluation-state",
                    prompt=f"{task.recall_query}\n\n{task.evaluation_prompt}",
                ),
                trial_root / "evaluation-worker",
            )
            if arm.arm_id == "memory_on":
                operations = tuple(prime.get("myna_operations", ())) + tuple(evaluation.get("myna_operations", ()))
            metrics = _tool_metrics(evaluation.get("tool_events"))
            passed, findings = _verify_trial(task, workspace, evaluation)
            recall_hits = evaluation.get("recall_hits")
            cross_repository = bool(
                isinstance(recall_hits, list)
                and any(
                    isinstance(hit, dict)
                    and isinstance(hit.get("metadata"), dict)
                    and hit["metadata"].get("repo_key") != task.repository_id
                    for hit in recall_hits
                )
            )
            control_isolated = bool(
                arm.arm_id == "memory_on"
                or (
                    prime.get("backend_module") is None
                    and evaluation.get("backend_module") is None
                    and prime.get("memory_backend_build_calls") == 0
                    and evaluation.get("memory_backend_build_calls") == 0
                )
            )
            if not control_isolated:
                findings = (*findings, "memory_off_control_touched_backend")
                passed = False
            return TrialRecord(
                task_id=task.task_id,
                task_class=task.task_class,
                repetition=repetition,
                arm_id=arm.arm_id,
                status="passed" if passed else "task_failed",
                workspace_digest=fixture_digest,
                repository_reads=metrics["repository_reads"],
                tool_calls=metrics["tool_calls"],
                memory_hits=int(evaluation.get("memory_hits", 0) or 0),
                myna_operations=operations,
                stale_memory_used=bool(task.task_class == "stale_conflict" and evaluation.get("used_memory") is True),
                cross_repository_memory=cross_repository,
                findings=findings,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            treatment = arm.arm_id == "memory_on"
            return TrialRecord(
                task_id=task.task_id,
                task_class=task.task_class,
                repetition=repetition,
                arm_id=arm.arm_id,
                status="task_failed" if treatment else "infrastructure_failure",
                workspace_digest=fixture_digest,
                repository_reads=0,
                tool_calls=0,
                memory_hits=0,
                myna_operations=(("start",) if treatment else ()),
                findings=(f"trial_execution_failed:{type(exc).__name__}",),
            )

    def _turn_spec(
        self,
        task: TaskDefinition,
        *,
        repetition: int,
        arm: ExperimentArm,
        stage: str,
        workspace: Path,
        state_root: Path,
        prompt: str,
    ) -> dict[str, Any]:
        return {
            "worker_mode": "turn",
            "arm_id": arm.arm_id,
            "stage": stage,
            "task_id": task.task_id,
            "task_class": task.task_class,
            "source_path": task.source_path,
            "output_path": task.output_path,
            "workspace": str(workspace),
            "state_root": str(state_root),
            "prompt": prompt,
            "session_id": f"{task.task_id}-{stage}-{repetition}",
            "message_id": f"{task.task_id}-{stage}-{repetition}",
            "timeout_seconds": 180,
        }

    def _worker_call(
        self,
        spec: dict[str, Any],
        root: Path,
        *,
        environment_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        root.mkdir(parents=True, exist_ok=True)
        spec_path = root / "spec.json"
        spec_path.write_text(
            json.dumps(spec, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        completed = self._run(
            (str(self._python), "-I", str(self._worker), str(spec_path)),
            cwd=root,
            environment_overrides=environment_overrides,
        )
        try:
            value = json.loads(completed.stdout.splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError("installed worker returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError("installed worker receipt must be an object")
        return value

    def _run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        environment_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "PYTHONPATH",
                "PICO_HOME",
                "MYNA_HOME",
                "MYNA_MODEL_CACHE",
            }
        }
        environment.update(
            {
                "HOME": str(self._root / "home"),
                "MYNA_MODEL_CACHE": str(self._model_cache),
                "PICO_HOME": str(self._root / "pico-home"),
                "PYTHONPATH": "",
                "UV_CACHE_DIR": str(self._uv_cache),
            }
        )
        environment.update(environment_overrides or {})
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"command failed with exit {completed.returncode}: {Path(argv[0]).name}")
        return completed

    def _validate_identity(self, identity: dict[str, Any]) -> dict[str, Any]:
        entries = identity.get("entry_points")
        if ["myna", "myna.integrations.pico"] not in entries:
            raise RuntimeError("installed Myna plugin entry point is missing")
        environment = self._environment.resolve()
        for name in ("pico", "myna"):
            record = identity.get(name)
            if not isinstance(record, dict):
                raise RuntimeError(f"installed {name} identity is missing")
            location = Path(str(record.get("location", ""))).resolve()
            if not location.is_relative_to(environment):
                raise RuntimeError(f"{name} did not resolve from the isolated environment")
        return {
            "entry_points": entries,
            "myna_version": identity["myna"]["version"],
            "pico_version": identity["pico"]["version"],
            "python": identity["python"],
        }


def _tool_metrics(raw_events: object) -> dict[str, int]:
    events = raw_events if isinstance(raw_events, list) else []
    completed = [event for event in events if isinstance(event, dict) and event.get("phase") == "complete"]
    reads = [event for event in completed if event.get("name") == "read_file" and event.get("failed") is not True]
    return {
        "repository_reads": len(reads),
        "tool_calls": len(completed),
    }


def _verify_trial(
    task: TaskDefinition,
    workspace: Path,
    evaluation: dict[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    findings: list[str] = []
    if evaluation.get("terminal") != "completed":
        findings.append("turn_not_completed")
    artifact = workspace.joinpath(*PurePosixPath(task.output_path).parts)
    try:
        value = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = None
    if value != {"task_id": task.task_id, "value": task.expected_value}:
        findings.append("result_artifact_mismatch")
    allowed = {task.source_path, task.output_path}
    observed = {
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
        if path.is_file() and not path.is_relative_to(workspace / ".git")
    }
    unexpected = sorted(observed - allowed)
    if unexpected:
        findings.append("unexpected_workspace_mutation")
    return not findings, tuple(findings)


__all__ = ["InstalledTrialExecutor"]
