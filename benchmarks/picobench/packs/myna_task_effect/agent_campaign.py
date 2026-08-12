from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from benchmarks.picobench.budget import ProviderBudgetConfig, ProviderBudgetLedger
from benchmarks.picobench.canonical import canonical_digest
from benchmarks.picobench.verifier import require_normalized_relative_path
from pico.utils.portable_lock import file_lock

from .campaign import (
    ARM_MEMORY_OFF,
    ARM_MEMORY_ON,
    TASK_CLASSES,
    ExperimentArm,
    TaskCorpus,
    TaskDefinition,
    _append_jsonl,
    _freeze_json,
    _interval,
    _per_task_values,
    _write_json,
    arm_order,
)

AGENT_TASK_SCHEMA = "pico.picobench.myna-agent-task-effect.tasks.v1"
_AGENT_TASK_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_EXPECTED_LIFECYCLE = ("start", "store", "stop", "start", "recall", "store", "stop")
_PASS_NONINFERIORITY_FLOOR = -0.05
_MIN_CONCORDANT_COVERAGE = 0.80
_MIN_TOOL_CALL_REDUCTION_PERCENT = 15.0
_MIN_INPUT_TOKEN_REDUCTION_PERCENT = 10.0
_MIN_CAPABILITY_DELTA_PP = 10.0
_AGENT_INVENTORY_PATHS = (
    "manifest.json",
    "candidate-receipt.json",
    "raw-outcomes.jsonl",
    "aggregate.json",
    "verifier-report.json",
    "claim-eligibility.json",
    "provider-budget.jsonl",
    "provider-budget.high-water.json",
    "provider-budget-approval.json",
    "provider-budget-report.json",
)


@dataclass(frozen=True)
class AgentTrialRecord:
    task_id: str
    task_class: str
    repetition: int
    arm_id: str
    status: str
    workspace_digest: str
    tool_calls: int
    input_tokens: int
    output_tokens: int
    provider_calls: int
    memory_hits: int
    myna_operations: tuple[str, ...]
    stale_memory_used: bool = False
    cross_repository_memory: bool = False
    findings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status == "passed"


@dataclass(frozen=True)
class AgentCampaignConfig:
    corpus_path: Path
    output_root: Path
    pico_wheel: Path
    myna_wheel: Path
    pico_commit: str
    myna_commit: str
    provider_name: str
    model: str
    provider_api_base: str | None = None
    repetitions: int = 2
    seed: int = 20260812
    max_tool_iterations: int = 4
    max_attempts_per_call: int = 2
    max_input_tokens_per_call: int = 8_192
    max_output_tokens_per_call: int = 512
    context_window_tokens: int = 8_192
    input_cache_miss_usd_per_million: float = 0.14
    output_usd_per_million: float = 0.28
    conservative_usd_to_cny_multiplier: float = 7.5
    hard_cap_cny: float = 10.0
    bootstrap_samples: int = 2_000
    bootstrap_seed: int = 20260812

    def __post_init__(self) -> None:
        if self.repetitions < 2 or self.repetitions % 2:
            raise ValueError("agent repetitions must be positive and even")
        for name in ("pico_commit", "myna_commit"):
            value = getattr(self, name)
            if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a lowercase full commit SHA")
        for path in (self.corpus_path, self.pico_wheel, self.myna_wheel):
            if not Path(path).is_file():
                raise ValueError(f"campaign input is missing: {Path(path).name}")
        limits = (
            self.max_tool_iterations,
            self.max_attempts_per_call,
            self.max_input_tokens_per_call,
            self.max_output_tokens_per_call,
            self.context_window_tokens,
            self.bootstrap_samples,
        )
        if any(value < 1 for value in limits) or self.hard_cap_cny <= 0:
            raise ValueError("agent campaign limits must be positive")
        if self.maximum_cost_cny > self.hard_cap_cny:
            raise ValueError("agent campaign worst-case cost exceeds the hard cap")
        if self.provider_name != "deepseek" or self.model != "deepseek/deepseek-v4-flash":
            raise ValueError("agent campaign is frozen to deepseek/deepseek-v4-flash")

    @property
    def planned_evaluation_trials(self) -> int:
        return 12 * self.repetitions * 2

    @property
    def max_logical_calls_per_trial(self) -> int:
        return self.max_tool_iterations + 1

    @property
    def maximum_provider_attempts(self) -> int:
        return self.planned_evaluation_trials * self.max_logical_calls_per_trial * self.max_attempts_per_call

    @property
    def maximum_cost_cny(self) -> float:
        usd_per_attempt = (
            self.max_input_tokens_per_call / 1_000_000 * self.input_cache_miss_usd_per_million
            + self.max_output_tokens_per_call / 1_000_000 * self.output_usd_per_million
        )
        return usd_per_attempt * self.conservative_usd_to_cny_multiplier * self.maximum_provider_attempts

    def manifest(self, corpus: TaskCorpus) -> dict[str, Any]:
        if corpus.schema != AGENT_TASK_SCHEMA:
            raise ValueError("agent campaign requires the agent task corpus")
        return {
            "schema": "pico.picobench.myna-agent-task-effect.manifest.v1",
            "definition_kind": corpus.definition_kind,
            "task_corpus_digest": corpus.digest,
            "treatment_axis": {
                "control": {"memory_backend": None},
                "treatment": {"memory_backend": "myna"},
            },
            "candidate": {
                "pico_commit": self.pico_commit,
                "pico_wheel_sha256": _sha256(self.pico_wheel),
                "myna_commit": self.myna_commit,
                "myna_wheel_sha256": _sha256(self.myna_wheel),
            },
            "execution": {
                "provider": self.provider_name,
                "model": self.model,
                "provider_api_base_digest": canonical_digest(self.provider_api_base or "provider-default"),
                "provider_calls_paid": "approval_required",
                "planned_evaluation_trials": self.planned_evaluation_trials,
                "repetitions": self.repetitions,
                "seed": self.seed,
                "max_tool_iterations": self.max_tool_iterations,
                "max_logical_calls_per_trial": self.max_logical_calls_per_trial,
                "max_attempts_per_call": self.max_attempts_per_call,
                "context_window_tokens": self.context_window_tokens,
            },
            "budget": {
                "maximum_provider_attempts": self.maximum_provider_attempts,
                "max_input_tokens_per_call": self.max_input_tokens_per_call,
                "max_output_tokens_per_call": self.max_output_tokens_per_call,
                "maximum_cost_cny": round(self.maximum_cost_cny, 6),
                "hard_cap_cny": self.hard_cap_cny,
                "input_cache_miss_usd_per_million": self.input_cache_miss_usd_per_million,
                "output_usd_per_million": self.output_usd_per_million,
                "conservative_usd_to_cny_multiplier": self.conservative_usd_to_cny_multiplier,
            },
            "analysis": {
                "bootstrap_unit": "task",
                "bootstrap_samples": self.bootstrap_samples,
                "bootstrap_seed": self.bootstrap_seed,
                "confidence_level": 0.95,
                "exploratory_task_count": True,
            },
            "claim_policy": {
                "pass_noninferiority_floor": _PASS_NONINFERIORITY_FLOOR,
                "minimum_concordant_coverage": _MIN_CONCORDANT_COVERAGE,
                "minimum_tool_call_reduction_percent": _MIN_TOOL_CALL_REDUCTION_PERCENT,
                "minimum_input_token_reduction_percent": _MIN_INPUT_TOKEN_REDUCTION_PERCENT,
                "minimum_capability_delta_pp": _MIN_CAPABILITY_DELTA_PP,
                "general_agent_claim_allowed": False,
            },
        }


def load_agent_task_corpus(path: Path) -> TaskCorpus:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid agent task-effect corpus: {path}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != AGENT_TASK_SCHEMA:
        raise ValueError("unsupported agent task-effect task schema")
    if raw.get("definition_kind") != "agent" or not isinstance(raw.get("tasks"), list):
        raise ValueError("agent corpus requires an agent task list")
    tasks = tuple(_parse_agent_task(row) for row in raw["tasks"])
    if len(tasks) != 12 or len({task.task_id for task in tasks}) != 12:
        raise ValueError("agent corpus requires exactly twelve unique tasks")
    counts = {task_class: 0 for task_class in TASK_CLASSES}
    for task in tasks:
        counts[task.task_class] += 1
    if set(counts.values()) != {3}:
        raise ValueError("agent corpus requires three tasks per task class")
    if len({task.repository_id for task in tasks}) < 4:
        raise ValueError("agent corpus requires at least four repositories")
    return TaskCorpus(schema=AGENT_TASK_SCHEMA, definition_kind="agent", tasks=tasks)


def build_agent_report(
    *,
    corpus: TaskCorpus,
    trials: tuple[AgentTrialRecord, ...],
    repetitions: int,
    bootstrap_samples: int = 2_000,
    bootstrap_seed: int = 20260812,
) -> dict[str, Any]:
    if corpus.schema != AGENT_TASK_SCHEMA or repetitions < 1:
        raise ValueError("invalid agent report inputs")
    task_by_id = {task.task_id: task for task in corpus.tasks}
    grouped: dict[tuple[str, int], dict[str, AgentTrialRecord]] = {}
    axis_valid = True
    for trial in trials:
        if (
            trial.task_id not in task_by_id
            or trial.task_class != task_by_id[trial.task_id].task_class
            or trial.repetition < 0
            or trial.repetition >= repetitions
            or trial.arm_id not in {"memory_off", "memory_on"}
        ):
            axis_valid = False
            continue
        by_arm = grouped.setdefault((trial.task_id, trial.repetition), {})
        if trial.arm_id in by_arm:
            axis_valid = False
        by_arm[trial.arm_id] = trial

    expected_pairs = len(corpus.tasks) * repetitions
    valid_pairs: list[tuple[AgentTrialRecord, AgentTrialRecord]] = []
    complete_pairs = 0
    lifecycle_complete = True
    for task in corpus.tasks:
        for repetition in range(repetitions):
            by_arm = grouped.get((task.task_id, repetition), {})
            if set(by_arm) != {"memory_off", "memory_on"}:
                axis_valid = False
                continue
            complete_pairs += 1
            control = by_arm["memory_off"]
            treatment = by_arm["memory_on"]
            pair_axis_valid = not control.myna_operations and bool(treatment.myna_operations)
            lifecycle_complete &= treatment.myna_operations == _EXPECTED_LIFECYCLE
            axis_valid &= pair_axis_valid
            terminal = control.status != "infrastructure_failure" and treatment.status != "infrastructure_failure"
            if pair_axis_valid and terminal and control.workspace_digest == treatment.workspace_digest:
                valid_pairs.append((control, treatment))

    ship_complete = complete_pairs == expected_pairs and len(trials) == expected_pairs * 2
    measurement_valid = bool(ship_complete and axis_valid and len(valid_pairs) == expected_pairs)
    denominator = len(valid_pairs)
    control_passes = sum(control.passed for control, _ in valid_pairs)
    treatment_passes = sum(treatment.passed for _, treatment in valid_pairs)
    pass_delta_pp = 100.0 * (treatment_passes - control_passes) / denominator if denominator else 0.0
    pass_interval = _interval(
        _per_task_values(valid_pairs, lambda control, treatment: float(treatment.passed) - float(control.passed)),
        samples=bootstrap_samples,
        seed=bootstrap_seed,
    )
    concordant = tuple(
        (control, treatment) for control, treatment in valid_pairs if control.passed and treatment.passed
    )
    tool_reductions = _reductions(concordant, "tool_calls")
    token_reductions = _reductions(concordant, "input_tokens")
    tool_interval = _interval(tool_reductions, samples=bootstrap_samples, seed=bootstrap_seed + 1)
    token_interval = _interval(token_reductions, samples=bootstrap_samples, seed=bootstrap_seed + 2)
    tool_reduction = _mean_reduction(tool_reductions)
    token_reduction = _mean_reduction(token_reductions)
    concordant_coverage = len(concordant) / denominator if denominator else 0.0
    stale_regressions = sum(
        treatment.stale_memory_used and control.passed and not treatment.passed for control, treatment in valid_pairs
    )
    cross_repository_events = sum(treatment.cross_repository_memory for _, treatment in valid_pairs)
    safe = stale_regressions == 0 and cross_repository_events == 0
    capability_eligible = bool(
        measurement_valid
        and lifecycle_complete
        and pass_delta_pp >= _MIN_CAPABILITY_DELTA_PP
        and pass_interval is not None
        and pass_interval["lower"] > 0.0
        and safe
    )
    efficiency_eligible = bool(
        measurement_valid
        and lifecycle_complete
        and pass_interval is not None
        and pass_interval["lower"] >= _PASS_NONINFERIORITY_FLOOR
        and concordant_coverage >= _MIN_CONCORDANT_COVERAGE
        and tool_reduction >= _MIN_TOOL_CALL_REDUCTION_PERCENT
        and token_reduction >= _MIN_INPUT_TOKEN_REDUCTION_PERCENT
        and tool_interval is not None
        and tool_interval["lower"] > 0.0
        and token_interval is not None
        and token_interval["lower"] > 0.0
        and safe
    )
    return {
        "schema": "pico.picobench.myna-agent-task-effect.report.v1",
        "task_corpus_digest": corpus.digest,
        "measurement": {
            "planned_pairs": expected_pairs,
            "complete_pairs": complete_pairs,
            "valid_pairs": denominator,
            "axis_valid": axis_valid,
            "lifecycle_complete": lifecycle_complete,
            "exploratory_task_count": len(corpus.tasks) < 30,
        },
        "capability": {
            "control_passes": control_passes,
            "treatment_passes": treatment_passes,
            "verified_pass_delta_pp": round(pass_delta_pp, 6),
            "paired_bootstrap_95_ci": pass_interval,
        },
        "efficiency": {
            "concordant_pass_pairs": len(concordant),
            "concordant_pair_coverage": round(concordant_coverage, 6),
            "successful_task_tool_call_reduction_percent": round(tool_reduction, 6),
            "tool_call_paired_bootstrap_95_ci": tool_interval,
            "successful_task_input_token_reduction_percent": round(token_reduction, 6),
            "input_token_paired_bootstrap_95_ci": token_interval,
        },
        "safety": {
            "stale_memory_caused_regressions": stale_regressions,
            "cross_repository_memory_events": cross_repository_events,
        },
        "claim": {
            "ship_complete": ship_complete,
            "measurement_valid": measurement_valid,
            "capability_claim_eligible": capability_eligible,
            "efficiency_claim_eligible": efficiency_eligible,
            "positive_claim_eligible": capability_eligible or efficiency_eligible,
            "general_agent_claim_eligible": False,
            "eligible_scope": "frozen_lightweight_task_pack",
        },
    }


AgentTrialExecutor = Callable[
    [TaskDefinition, int, ExperimentArm, AgentCampaignConfig],
    AgentTrialRecord,
]


def run_agent_campaign(
    config: AgentCampaignConfig,
    *,
    approval_digest: str,
    approved_cny: float,
    execute_paid: bool,
    trial_executor: AgentTrialExecutor,
) -> dict[str, Any]:
    corpus = load_agent_task_corpus(config.corpus_path)
    manifest = config.manifest(corpus)
    expected_digest = canonical_digest(manifest)
    if not execute_paid:
        raise ValueError("paid execution approval is required")
    if approval_digest != expected_digest:
        raise ValueError("paid execution approval digest does not match the frozen plan")
    if not math.isfinite(approved_cny) or approved_cny < config.maximum_cost_cny or approved_cny > config.hard_cap_cny:
        raise ValueError("approved CNY does not cover the frozen plan within its hard cap")
    identity = getattr(trial_executor, "identity", None)
    if not isinstance(identity, Mapping) or not identity:
        raise ValueError("installed candidate identity is required")
    output = Path(config.output_root)
    output.mkdir(parents=True, exist_ok=True)
    with file_lock(output / ".run.lock", blocking=False):
        _freeze_json(output / "manifest.json", manifest)
        _freeze_json(
            output / "candidate-receipt.json",
            {
                "schema": "pico.picobench.myna-agent-task-effect.candidate-receipt.v1",
                "identity": dict(identity),
                "identity_digest": canonical_digest(identity),
            },
        )
        _verify_agent_inventory(output)
        ledger, budget_config = _prepare_agent_budget(
            config,
            output=output,
            approval_digest=approval_digest,
        )
        configure_budget = getattr(trial_executor, "configure_budget", None)
        if callable(configure_budget):
            configure_budget(ledger.path, budget_config)
        records = _read_agent_trial_journal(output / "raw-outcomes.jsonl")
        expected = {
            (task.task_id, repetition, arm.arm_id)
            for task in corpus.tasks
            for repetition in range(config.repetitions)
            for arm in (ARM_MEMORY_OFF, ARM_MEMORY_ON)
        }
        if set(records) - expected:
            raise ValueError("raw outcomes contain trials outside the frozen agent plan")
        for task in corpus.tasks:
            for repetition in range(config.repetitions):
                for arm in arm_order(task.task_id, repetition, seed=config.seed):
                    key = (task.task_id, repetition, arm.arm_id)
                    if key in records:
                        continue
                    record = trial_executor(task, repetition, arm, config)
                    _validate_agent_trial(record, task=task, repetition=repetition, arm=arm)
                    _append_jsonl(output / "raw-outcomes.jsonl", asdict(record))
                    records[key] = record
        ordered = tuple(records[key] for key in sorted(records))
        report = build_agent_report(
            corpus=corpus,
            trials=ordered,
            repetitions=config.repetitions,
            bootstrap_samples=config.bootstrap_samples,
            bootstrap_seed=config.bootstrap_seed,
        )
        budget = ledger.snapshot()
        if (
            budget.request_attempts != sum(record.provider_calls for record in ordered)
            or not budget.accounting_complete
        ):
            raise ValueError("Provider budget evidence does not match agent Trial records")
        _write_json(output / "provider-budget-report.json", asdict(budget))
        _write_agent_derived(output, report)
        return report


def verify_agent_evidence(output_root: Path, *, corpus_path: Path) -> dict[str, Any]:
    output = Path(output_root)
    _verify_agent_inventory(output)
    try:
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("agent evidence manifest is invalid") from exc
    corpus = load_agent_task_corpus(corpus_path)
    execution = manifest.get("execution")
    if not isinstance(execution, dict) or not isinstance(execution.get("repetitions"), int):
        raise ValueError("agent evidence execution plan is invalid")
    records = tuple(_read_agent_trial_journal(output / "raw-outcomes.jsonl").values())
    analysis = manifest.get("analysis")
    if not isinstance(analysis, dict):
        raise ValueError("agent evidence analysis plan is invalid")
    report = build_agent_report(
        corpus=corpus,
        trials=records,
        repetitions=execution["repetitions"],
        bootstrap_samples=int(analysis.get("bootstrap_samples", 0)),
        bootstrap_seed=int(analysis.get("bootstrap_seed", 0)),
    )
    observed = json.loads((output / "aggregate.json").read_text(encoding="utf-8"))
    gates = {
        "manifest_bound": _verify_agent_manifest(output, manifest, corpus),
        "candidate_identity_bound": _verify_candidate_receipt(output),
        "aggregate_reproduces": observed == report,
        "claim_reproduces": json.loads((output / "claim-eligibility.json").read_text(encoding="utf-8"))
        == report["claim"],
        "measurement_valid": report["claim"]["measurement_valid"],
        "budget_accounting_complete": _verify_agent_budget(output, records),
        "verifier_report_reproduces": json.loads((output / "verifier-report.json").read_text(encoding="utf-8"))
        == _verifier_report(report),
    }
    return {
        "schema": "pico.picobench.myna-agent-task-effect.offline-verifier.v1",
        "passed": all(gates.values()),
        "gates": gates,
        "recomputed_report": report,
    }


def _prepare_agent_budget(
    config: AgentCampaignConfig,
    *,
    output: Path,
    approval_digest: str,
) -> tuple[ProviderBudgetLedger, ProviderBudgetConfig]:
    ledger_path = output / "provider-budget.jsonl"
    approval_path = output / "provider-budget-approval.json"
    base = _agent_budget_config(config)
    if approval_path.exists():
        try:
            receipt = json.loads(approval_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Provider budget approval receipt is invalid") from exc
        if receipt.get("approval_digest") != approval_digest:
            raise ValueError("Provider budget approval receipt does not match")
        prefix = receipt.get("ledger_prefix")
        if not isinstance(prefix, dict):
            raise ValueError("Provider budget approval prefix is invalid")
    else:
        if ledger_path.exists() or ledger_path.with_suffix(".high-water.json").exists():
            raise ValueError("Provider budget evidence exists without its approval receipt")
        bootstrap = ProviderBudgetLedger(ledger_path, base).snapshot()
        prefix = {
            "event_count": bootstrap.ledger_event_count,
            "digest": bootstrap.ledger_digest,
            "charged_cny": bootstrap.provider_charged_cny,
        }
        _freeze_json(
            approval_path,
            {
                "schema": "pico.picobench.myna-agent-task-effect.budget-approval.v1",
                "approval_digest": approval_digest,
                "ledger_prefix": prefix,
            },
        )
    approved = ProviderBudgetConfig(
        **{
            **asdict(base),
            "approval_digest": approval_digest,
            "ledger_prefix_event_count": int(prefix["event_count"]),
            "ledger_prefix_digest": str(prefix["digest"]),
            "ledger_prefix_charged_cny": float(prefix["charged_cny"]),
        }
    )
    return ProviderBudgetLedger(ledger_path, approved), approved


def _agent_budget_config(config: AgentCampaignConfig) -> ProviderBudgetConfig:
    return ProviderBudgetConfig(
        hard_cap_cny=config.hard_cap_cny,
        external_service_reserve_cny=0.0,
        max_total_request_attempts=config.maximum_provider_attempts,
        max_input_tokens_per_call=config.max_input_tokens_per_call,
        max_output_tokens_per_call=config.max_output_tokens_per_call,
        input_cache_miss_usd_per_million=config.input_cache_miss_usd_per_million,
        output_usd_per_million=config.output_usd_per_million,
        conservative_usd_to_cny_multiplier=config.conservative_usd_to_cny_multiplier,
    )


def _verify_agent_budget(output: Path, records: tuple[AgentTrialRecord, ...]) -> bool:
    try:
        receipt = json.loads((output / "provider-budget-approval.json").read_text(encoding="utf-8"))
        report = json.loads((output / "provider-budget-report.json").read_text(encoding="utf-8"))
        high_water = json.loads((output / "provider-budget.high-water.json").read_text(encoding="utf-8"))
        events = [
            json.loads(line) for line in (output / "provider-budget.jsonl").read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return bool(
        receipt.get("approval_digest") == report.get("approval_digest")
        and report.get("request_attempts") == sum(record.provider_calls for record in records)
        and report.get("accounting_complete") is True
        and report.get("open_reservations") == 0
        and report.get("ledger_event_count") == len(events)
        and report.get("ledger_digest") == canonical_digest(events)
        and report.get("high_water_digest") == canonical_digest(high_water)
        and high_water.get("event_count") == len(events)
        and high_water.get("ledger_digest") == report.get("ledger_digest")
        and report.get("request_attempts", -1) <= report.get("request_attempt_lifetime_ceiling", -2)
        and report.get("total_committed_cny", math.inf) <= report.get("hard_cap_cny", -math.inf)
    )


def _verify_agent_manifest(output: Path, manifest: dict[str, Any], corpus: TaskCorpus) -> bool:
    try:
        receipt = json.loads((output / "provider-budget-approval.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    execution = manifest.get("execution")
    policy = manifest.get("claim_policy")
    return bool(
        manifest.get("schema") == "pico.picobench.myna-agent-task-effect.manifest.v1"
        and manifest.get("definition_kind") == "agent"
        and manifest.get("task_corpus_digest") == corpus.digest
        and manifest.get("treatment_axis")
        == {"control": {"memory_backend": None}, "treatment": {"memory_backend": "myna"}}
        and isinstance(execution, dict)
        and execution.get("provider") == "deepseek"
        and execution.get("model") == "deepseek/deepseek-v4-flash"
        and execution.get("planned_evaluation_trials") == len(corpus.tasks) * execution.get("repetitions", 0) * 2
        and isinstance(policy, dict)
        and policy.get("general_agent_claim_allowed") is False
        and receipt.get("approval_digest") == canonical_digest(manifest)
    )


def _verify_candidate_receipt(output: Path) -> bool:
    try:
        receipt = json.loads((output / "candidate-receipt.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    identity = receipt.get("identity")
    return bool(
        receipt.get("schema") == "pico.picobench.myna-agent-task-effect.candidate-receipt.v1"
        and isinstance(identity, dict)
        and identity
        and receipt.get("identity_digest") == canonical_digest(identity)
    )


def _write_agent_derived(output: Path, report: dict[str, Any]) -> None:
    _write_json(output / "aggregate.json", report)
    _write_json(output / "verifier-report.json", _verifier_report(report))
    _write_json(output / "claim-eligibility.json", report["claim"])
    _write_json(
        output / "inventory.json",
        {
            "schema": "pico.picobench.myna-agent-task-effect.inventory.v1",
            "files": [{"path": relative, "sha256": _sha256(output / relative)} for relative in _AGENT_INVENTORY_PATHS],
        },
    )


def _verifier_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "pico.picobench.myna-agent-task-effect.verifier.v1",
        "measurement": report["measurement"],
        "safety": report["safety"],
        "passed": report["claim"]["measurement_valid"],
    }


def _read_agent_trial_journal(path: Path) -> dict[tuple[str, int, str], AgentTrialRecord]:
    if not path.exists():
        return {}
    records: dict[tuple[str, int, str], AgentTrialRecord] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            raw = json.loads(line)
            raw["myna_operations"] = tuple(raw.get("myna_operations", ()))
            raw["findings"] = tuple(raw.get("findings", ()))
            record = AgentTrialRecord(**raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid agent raw outcome at line {line_number}") from exc
        key = (record.task_id, record.repetition, record.arm_id)
        if key in records:
            raise ValueError("agent raw outcomes contain a duplicate trial")
        records[key] = record
    return records


def _validate_agent_trial(
    record: AgentTrialRecord,
    *,
    task: TaskDefinition,
    repetition: int,
    arm: ExperimentArm,
) -> None:
    if (
        record.task_id != task.task_id
        or record.task_class != task.task_class
        or record.repetition != repetition
        or record.arm_id != arm.arm_id
    ):
        raise ValueError("agent executor returned a record outside the planned trial")
    if record.status not in {"passed", "task_failed", "infrastructure_failure"}:
        raise ValueError("agent executor returned an unknown status")
    for name in ("tool_calls", "input_tokens", "output_tokens", "provider_calls", "memory_hits"):
        value = getattr(record, name)
        if isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} must not be negative")


def _verify_agent_inventory(output: Path) -> None:
    path = output / "inventory.json"
    if not path.exists():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw["files"]
        observed = {row["path"]: row["sha256"] for row in rows}
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("agent evidence inventory is invalid") from exc
    if raw.get("schema") != "pico.picobench.myna-agent-task-effect.inventory.v1":
        raise ValueError("agent evidence inventory schema is invalid")
    if set(observed) != set(_AGENT_INVENTORY_PATHS) or len(rows) != len(_AGENT_INVENTORY_PATHS):
        raise ValueError("agent evidence inventory file set is invalid")
    for relative in _AGENT_INVENTORY_PATHS:
        artifact = output / relative
        if not artifact.is_file() or observed[relative] != _sha256(artifact):
            raise ValueError(f"agent evidence digest changed: {relative}")


def _reductions(
    pairs: tuple[tuple[AgentTrialRecord, AgentTrialRecord], ...],
    field: str,
) -> dict[str, tuple[float, ...]]:
    eligible = tuple((control, treatment) for control, treatment in pairs if getattr(control, field) > 0)
    return _per_task_values(
        eligible,
        lambda control, treatment: (
            100.0 * (getattr(control, field) - getattr(treatment, field)) / getattr(control, field)
        ),
    )


def _mean_reduction(values: dict[str, tuple[float, ...]]) -> float:
    flattened = [value for task_values in values.values() for value in task_values]
    return mean(flattened) if flattened else 0.0


def _parse_agent_task(raw: Any) -> TaskDefinition:
    if not isinstance(raw, dict):
        raise ValueError("agent task entries must be objects")
    keys = (
        "task_id",
        "task_class",
        "repository_id",
        "source_path",
        "source_text",
        "memory_text",
        "recall_query",
        "evaluation_prompt",
        "output_path",
        "expected_value",
    )
    fields = {key: raw.get(key) for key in keys}
    if any(not isinstance(value, str) or not value.strip() for value in fields.values()):
        raise ValueError("agent task fields must be non-empty strings")
    if fields["task_class"] not in TASK_CLASSES:
        raise ValueError("unknown agent task class")
    if _AGENT_TASK_ID.fullmatch(fields["task_id"]) is None:
        raise ValueError("task_id must be a lowercase path-safe identifier")
    fields["repository_id"] = require_normalized_relative_path(fields["repository_id"], field_name="repository_id")
    fields["source_path"] = require_normalized_relative_path(fields["source_path"], field_name="source_path")
    fields["output_path"] = require_normalized_relative_path(fields["output_path"], field_name="output_path")
    if fields["source_path"] == fields["output_path"]:
        raise ValueError("source and output paths must differ")
    if fields["expected_value"] in fields["evaluation_prompt"]:
        raise ValueError("evaluation prompt leaks the expected value")
    if fields["expected_value"] not in fields["source_text"]:
        raise ValueError("expected value must remain independently discoverable")
    if fields["task_id"] not in fields["source_text"]:
        raise ValueError("source evidence must be bound to task_id")
    if fields["task_class"] in {"fact", "experience"} and fields["expected_value"] not in fields["memory_text"]:
        raise ValueError("positive agent tasks require useful prior Memory")
    return TaskDefinition(**fields)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_live_subject() -> tuple[str, str, str, str | None]:
    from pico.config.loader import load_config

    base = load_config()
    model = base.agents.defaults.model
    provider_name = base.get_provider_name(model)
    provider = base.get_provider(model)
    if provider_name != "deepseek" or model != "deepseek/deepseek-v4-flash":
        raise RuntimeError("agent task-effect plan is frozen to deepseek/deepseek-v4-flash")
    if provider is None or not provider.api_key:
        raise RuntimeError("configured agent task-effect Provider credential is unavailable")
    return provider_name, model, provider.api_key, provider.api_base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan, run, or verify the Pico Harness Memory Agent A/B")
    parser.add_argument("command", choices=("plan", "run", "verify"))
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--pico-wheel", type=Path)
    parser.add_argument("--myna-wheel", type=Path)
    parser.add_argument("--pico-commit")
    parser.add_argument("--myna-commit")
    parser.add_argument("--approval-digest")
    parser.add_argument("--approved-cny", type=float)
    args = parser.parse_args(argv)
    if args.command == "verify":
        result = verify_agent_evidence(args.output_root, corpus_path=args.corpus)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    if not all((args.pico_wheel, args.myna_wheel, args.pico_commit, args.myna_commit)):
        parser.error("plan and run require both wheels and full source commits")
    provider_name, model, api_key, api_base = _load_live_subject()
    config = AgentCampaignConfig(
        corpus_path=args.corpus,
        output_root=args.output_root,
        pico_wheel=args.pico_wheel,
        myna_wheel=args.myna_wheel,
        pico_commit=args.pico_commit,
        myna_commit=args.myna_commit,
        provider_name=provider_name,
        model=model,
        provider_api_base=api_base,
    )
    corpus = load_agent_task_corpus(config.corpus_path)
    manifest = config.manifest(corpus)
    approval_digest = canonical_digest(manifest)
    if args.command == "plan":
        config.output_root.mkdir(parents=True, exist_ok=True)
        _freeze_json(config.output_root / "manifest.json", manifest)
        print(f"manifest: {config.output_root / 'manifest.json'}")
        print(f"approval_digest: {approval_digest}")
        print(f"planned_evaluation_trials: {config.planned_evaluation_trials}")
        print(f"maximum_provider_attempts: {config.maximum_provider_attempts}")
        print(f"maximum_cost_cny: {config.maximum_cost_cny:.6f}")
        print(f"hard_cap_cny: {config.hard_cap_cny:.2f}")
        return 0
    if args.approval_digest is None or args.approved_cny is None:
        parser.error("run requires --approval-digest and --approved-cny")
    from .agent_runner import InstalledAgentTrialExecutor

    with InstalledAgentTrialExecutor(
        config,
        provider_api_key=api_key,
        provider_api_base=api_base,
    ) as executor:
        report = run_agent_campaign(
            config,
            approval_digest=args.approval_digest,
            approved_cny=args.approved_cny,
            execute_paid=os.environ.get("PICO_BENCH_EXECUTE_PAID") == "1",
            trial_executor=executor,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


__all__ = [
    "AGENT_TASK_SCHEMA",
    "AgentCampaignConfig",
    "AgentTrialRecord",
    "build_agent_report",
    "load_agent_task_corpus",
    "run_agent_campaign",
    "verify_agent_evidence",
]


if __name__ == "__main__":
    raise SystemExit(main())
