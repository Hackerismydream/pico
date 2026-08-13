from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from benchmarks.picobench.budget import ProviderBudgetConfig
from benchmarks.picobench.canonical import canonical_digest

from .agent_campaign import AgentCampaignConfig, AgentTrialRecord
from .campaign import ExperimentArm, TaskDefinition
from .runner import InstalledTrialExecutor, _tool_metrics, _verify_trial


class InstalledAgentTrialExecutor(InstalledTrialExecutor):
    def __init__(
        self,
        config: AgentCampaignConfig,
        *,
        provider_api_key: str,
        provider_api_base: str | None,
    ) -> None:
        if not provider_api_key:
            raise ValueError("live task-effect Provider credential is required")
        super().__init__(config)
        self._agent_config = config
        self._provider_api_key = provider_api_key
        if provider_api_base != config.provider_api_base:
            raise ValueError("live task-effect Provider endpoint does not match the frozen campaign")
        self._provider_api_base = provider_api_base
        self._budget_path: Path | None = None
        self._budget_config: ProviderBudgetConfig | None = None
        self._benchmark_root = Path(__file__).resolve().parents[4]

    def configure_budget(self, path: Path, config: ProviderBudgetConfig) -> None:
        self._budget_path = Path(path).resolve()
        self._budget_config = config

    def __call__(
        self,
        task: TaskDefinition,
        repetition: int,
        arm: ExperimentArm,
        config: AgentCampaignConfig,
    ) -> AgentTrialRecord:
        if config != self._agent_config or self._budget_path is None or self._budget_config is None:
            raise ValueError("agent executor does not match the frozen campaign")
        trial_root = self._root / "agent-trials" / task.task_id / str(repetition) / arm.arm_id
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
        phase = "workspace_setup"
        try:
            if arm.arm_id == "memory_on":
                phase = "memory_initialize"
                self._run(
                    (
                        str(self._myna),
                        "init",
                        "--root",
                        str(trial_root / "myna-runtime"),
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
            phase = "prime"
            prime = self._worker_call(
                self._turn_spec(
                    task,
                    repetition=repetition,
                    arm=arm,
                    stage="prime",
                    workspace=workspace,
                    state_root=trial_root / "prime-state",
                    prompt="Record this completed repository experience for later work.\n\n" + task.memory_text,
                ),
                trial_root / "prime-worker",
            )
            prime_failure = _worker_failure(prime)
            if prime_failure is not None:
                return _failed_trial_record(
                    task=task,
                    repetition=repetition,
                    arm=arm,
                    fixture_digest=fixture_digest,
                    failure_receipt=prime_failure,
                    prime=prime,
                )
            phase = "evaluation"
            evaluation_spec = self._turn_spec(
                task,
                repetition=repetition,
                arm=arm,
                stage="evaluate",
                workspace=workspace,
                state_root=trial_root / "evaluation-state",
                prompt=(
                    f"{task.recall_query}\n\n{task.evaluation_prompt}\n"
                    f"Current repository evidence, when needed, is at {task.source_path}. "
                    f"Use repository tools when needed. Write exactly one JSON object to {task.output_path} "
                    f'with schema {{"task_id":"{task.task_id}","value":"<answer>"}}. '
                    "Do not modify any other file."
                ),
            )
            evaluation_spec.update(self._live_spec(task, repetition, arm))
            evaluation = self._worker_call(
                evaluation_spec,
                trial_root / "evaluation-worker",
                environment_overrides={"PICO_BENCH_PROVIDER_API_KEY": self._provider_api_key},
            )
            evaluation_failure = _worker_failure(evaluation)
            if evaluation_failure is not None:
                return _failed_trial_record(
                    task=task,
                    repetition=repetition,
                    arm=arm,
                    fixture_digest=fixture_digest,
                    failure_receipt=evaluation_failure,
                    prime=prime,
                    evaluation=evaluation,
                )
            operations = (
                tuple(prime.get("myna_operations", ())) + tuple(evaluation.get("myna_operations", ()))
                if arm.arm_id == "memory_on"
                else ()
            )
            operation_receipt = (
                tuple(prime.get("memory_operation_receipt", ())) + tuple(evaluation.get("memory_operation_receipt", ()))
                if arm.arm_id == "memory_on"
                else ()
            )
            metrics = _tool_metrics(evaluation.get("tool_events"))
            passed, findings = _verify_trial(task, workspace, evaluation)
            receipt = _verification_receipt(task, workspace, evaluation)
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
            memory_hits = int(evaluation.get("memory_hits", 0) or 0)
            failure_class = None if passed else ("infrastructure" if not control_isolated else "task")
            return AgentTrialRecord(
                task_id=task.task_id,
                task_class=task.task_class,
                repetition=repetition,
                arm_id=arm.arm_id,
                status=(
                    "passed"
                    if passed
                    else "infrastructure_failure"
                    if failure_class == "infrastructure"
                    else "task_failed"
                ),
                workspace_digest=fixture_digest,
                tool_calls=metrics["tool_calls"],
                input_tokens=int(evaluation.get("input_tokens", 0) or 0),
                output_tokens=int(evaluation.get("output_tokens", 0) or 0),
                provider_calls=int(evaluation.get("provider_calls", 0) or 0),
                memory_hits=memory_hits,
                myna_operations=operations,
                failure_class=failure_class,
                failure_receipt=(
                    None
                    if passed
                    else {
                        "schema": "pico.picobench.myna-agent-task-effect.failure-receipt.v2",
                        "failure_class": failure_class,
                        "phase": "verification",
                        "error": {
                            "code": "verification_failed",
                            "message": ",".join(findings) or "Task verifier rejected the result",
                            "type": "VerificationFailure",
                        },
                    }
                ),
                memory_operation_receipt=operation_receipt,
                stale_memory_used=bool(task.task_class == "stale_conflict" and not passed and memory_hits),
                cross_repository_memory=cross_repository,
                findings=findings,
                verification_receipt=receipt,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            failure_class = "memory_backend" if phase == "memory_initialize" else "infrastructure"
            return AgentTrialRecord(
                task_id=task.task_id,
                task_class=task.task_class,
                repetition=repetition,
                arm_id=arm.arm_id,
                status="task_failed" if failure_class == "memory_backend" else "infrastructure_failure",
                workspace_digest=fixture_digest,
                tool_calls=0,
                input_tokens=0,
                output_tokens=0,
                provider_calls=0,
                memory_hits=0,
                myna_operations=(),
                failure_class=failure_class,
                failure_receipt={
                    "schema": "pico.picobench.myna-agent-task-effect.failure-receipt.v2",
                    "failure_class": failure_class,
                    "phase": phase,
                    "error": {
                        "code": type(exc).__name__,
                        "message": str(exc),
                        "type": type(exc).__name__,
                    },
                },
                findings=(f"trial_execution_failed:{type(exc).__name__}",),
            )

    def _live_spec(
        self,
        task: TaskDefinition,
        repetition: int,
        arm: ExperimentArm,
    ) -> dict[str, object]:
        if self._budget_path is None or self._budget_config is None:
            raise ValueError("agent budget is not configured")
        budget = asdict(self._budget_config)
        return {
            "provider_mode": "live",
            "provider_name": self._agent_config.provider_name,
            "provider_api_base": self._provider_api_base,
            "model": self._agent_config.model,
            "benchmark_root": str(self._benchmark_root),
            "trial_id": f"{task.task_id}:{repetition}:{arm.arm_id}",
            "max_tool_iterations": self._agent_config.max_tool_iterations,
            "max_logical_calls_per_trial": self._agent_config.max_logical_calls_per_trial,
            "max_attempts_per_call": self._agent_config.max_attempts_per_call,
            "max_input_tokens_per_call": self._agent_config.max_input_tokens_per_call,
            "max_output_tokens_per_call": self._agent_config.max_output_tokens_per_call,
            "context_window_tokens": self._agent_config.context_window_tokens,
            "budget": {
                "ledger_path": str(self._budget_path),
                "hard_cap_cny": budget["hard_cap_cny"],
                "maximum_provider_attempts": budget["max_total_request_attempts"],
                "input_cache_miss_usd_per_million": budget["input_cache_miss_usd_per_million"],
                "output_usd_per_million": budget["output_usd_per_million"],
                "conservative_usd_to_cny_multiplier": budget["conservative_usd_to_cny_multiplier"],
                "approval_digest": budget["approval_digest"],
                "ledger_prefix_event_count": budget["ledger_prefix_event_count"],
                "ledger_prefix_digest": budget["ledger_prefix_digest"],
                "ledger_prefix_charged_cny": budget["ledger_prefix_charged_cny"],
            },
        }


__all__ = ["InstalledAgentTrialExecutor"]


def _worker_failure(result: dict[str, object]) -> dict[str, object] | None:
    receipt = result.get("failure_receipt")
    if isinstance(receipt, dict) and receipt.get("failure_class") in {
        "provider",
        "transport",
        "budget",
        "infrastructure",
        "memory_backend",
    }:
        return receipt
    if result.get("terminal") != "completed":
        return {
            "schema": "pico.picobench.myna-agent-task-effect.failure-receipt.v2",
            "failure_class": "infrastructure",
            "phase": "worker_turn",
            "error": {
                "code": "missing_failure_receipt",
                "message": "Worker Turn did not complete without a classified failure",
                "type": "WorkerEvidenceFailure",
            },
        }
    return None


def _failed_trial_record(
    *,
    task: TaskDefinition,
    repetition: int,
    arm: ExperimentArm,
    fixture_digest: str,
    failure_receipt: dict[str, object],
    prime: dict[str, object],
    evaluation: dict[str, object] | None = None,
) -> AgentTrialRecord:
    evaluation = evaluation or {}
    failure_class = str(failure_receipt["failure_class"])
    operation_receipt = (
        tuple(prime.get("memory_operation_receipt", ())) + tuple(evaluation.get("memory_operation_receipt", ()))
        if arm.arm_id == "memory_on"
        else ()
    )
    operations = tuple(
        row["operation"]
        for row in operation_receipt
        if isinstance(row, dict) and row.get("outcome") == "succeeded" and isinstance(row.get("operation"), str)
    )
    metrics = _tool_metrics(evaluation.get("tool_events"))
    return AgentTrialRecord(
        task_id=task.task_id,
        task_class=task.task_class,
        repetition=repetition,
        arm_id=arm.arm_id,
        status=(
            "task_failed"
            if failure_class == "memory_backend"
            else "provider_failure"
            if failure_class in {"provider", "transport", "budget"}
            else "infrastructure_failure"
        ),
        workspace_digest=fixture_digest,
        tool_calls=metrics["tool_calls"],
        input_tokens=int(evaluation.get("input_tokens", 0) or 0),
        output_tokens=int(evaluation.get("output_tokens", 0) or 0),
        provider_calls=int(evaluation.get("provider_calls", 0) or 0),
        memory_hits=int(evaluation.get("memory_hits", 0) or 0),
        myna_operations=operations,
        failure_class=failure_class,
        failure_receipt=failure_receipt,
        memory_operation_receipt=operation_receipt,
        findings=(f"{failure_class}_failure",),
    )


def _verification_receipt(
    task: TaskDefinition,
    workspace: Path,
    evaluation: dict[str, object],
) -> dict[str, object]:
    artifact = workspace.joinpath(*PurePosixPath(task.output_path).parts)
    try:
        payload = artifact.read_bytes()
        observed = json.loads(payload)
        artifact_sha256 = hashlib.sha256(payload).hexdigest()
    except (OSError, ValueError):
        observed = None
        artifact_sha256 = None
    allowed = {task.source_path, task.output_path}
    observed_paths = {
        path.relative_to(workspace).as_posix()
        for path in workspace.rglob("*")
        if path.is_file() and not path.is_relative_to(workspace / ".git")
    }
    return {
        "schema": "pico.picobench.myna-agent-task-effect.verification-receipt.v2",
        "terminal": evaluation.get("terminal"),
        "artifact_sha256": artifact_sha256,
        "observed": observed,
        "unexpected_workspace_paths": sorted(observed_paths - allowed),
    }
