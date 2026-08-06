from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from benchmarks.picobench.canonical import canonical_digest, to_primitive
from pico.token_wise.base import TokenStrategy
from pico.token_wise.cache_optimizer import CacheOptimizer
from pico.token_wise.system_and_tail_cache import SystemAndTailCacheStrategy

from .models import TokenWiseCostMeasurement
from .reducer import (
    CACHE_POLICIES,
    CACHE_POLICY_ADAPTIVE_4,
    CACHE_POLICY_NO_EXPLICIT,
    CACHE_POLICY_PROVIDER_AUTO,
    CACHE_POLICY_SYSTEM_AND_3,
    assess_tokenwise_cost_claim,
)

TASK_CORPUS_SCHEMA = "pico.picobench.tokenwise-cost.tasks.v1"
REPORT_SCHEMA = "pico.picobench.tokenwise-cost.report.v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-5"
DEFAULT_HARD_CAP_USD = 25.0
DEFAULT_MAX_PROVIDER_CALLS = 1_200

PRICE_SNAPSHOT = {
    "snapshot_id": "openrouter-anthropic-claude-sonnet-5-2026-08-06",
    "model": DEFAULT_MODEL,
    "input_usd_per_token": 0.000002,
    "output_usd_per_token": 0.00001,
    "cache_read_usd_per_token": 0.0000002,
    "cache_write_usd_per_token": 0.0000025,
    "cache_ttl": "5m",
    "source": "https://openrouter.ai/api/v1/models",
}


class CampaignError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveTask:
    task_id: str
    workload_class: str
    case_index: int
    turn_count: int
    seed_history_turns: int
    expected_tool_calls_per_turn: int
    user_prompts: tuple[str, ...]
    expected_outputs: tuple[str, ...]


@dataclass(frozen=True)
class TaskCorpus:
    schema: str
    tasks: tuple[LiveTask, ...]
    digest: str


@dataclass(frozen=True)
class ArmConfig:
    cache_policy: str
    strategy: TokenStrategy | None
    provider_auto_cache: bool


@dataclass(frozen=True)
class CampaignConfig:
    model: str = DEFAULT_MODEL
    repetitions: int = 3
    hard_cap_usd: float = DEFAULT_HARD_CAP_USD
    max_provider_calls: int = DEFAULT_MAX_PROVIDER_CALLS
    output_root: Path = Path(".pico/evidence/tokenwise-cost")

    def __post_init__(self) -> None:
        if self.model != DEFAULT_MODEL:
            raise ValueError(f"formal campaign model must be {DEFAULT_MODEL}")
        if self.repetitions != 3:
            raise ValueError("formal campaign requires exactly three repetitions")
        if self.hard_cap_usd <= 0:
            raise ValueError("hard_cap_usd must be positive")
        if self.max_provider_calls < 1:
            raise ValueError("max_provider_calls must be positive")


@dataclass
class CampaignBudget:
    hard_cap_usd: float
    max_provider_calls: int
    spent_usd: float = 0.0
    provider_calls: int = 0

    def reserve_call(self) -> None:
        if self.provider_calls >= self.max_provider_calls:
            raise CampaignError("provider call ceiling reached")
        if self.spent_usd >= self.hard_cap_usd:
            raise CampaignError("cost ceiling reached")

    def record_call(self, *, cost_usd: float) -> None:
        if cost_usd < 0:
            raise ValueError("cost_usd must not be negative")
        self.provider_calls += 1
        self.spent_usd += cost_usd


@dataclass(frozen=True)
class LiveTrialResult:
    task_id: str
    workload_class: str
    repetition: int
    cache_policy: str
    task_passed: bool
    usage_complete: bool
    cost_complete: bool
    requested_model: str
    actual_model: str | None
    fallback_used: bool
    fresh_input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    cost_usd: float
    provider_calls: int
    latency_ms: int
    findings: tuple[str, ...]

    def measurement(self) -> TokenWiseCostMeasurement:
        return TokenWiseCostMeasurement(
            task_id=self.task_id,
            workload_class=self.workload_class,
            repetition=self.repetition,
            cache_policy=self.cache_policy,
            task_passed=self.task_passed,
            usage_complete=self.usage_complete,
            cost_complete=self.cost_complete,
            requested_model=self.requested_model,
            actual_model=self.actual_model,
            fallback_used=self.fallback_used,
            fresh_input_tokens=self.fresh_input_tokens,
            cache_write_tokens=self.cache_write_tokens,
            cache_read_tokens=self.cache_read_tokens,
            output_tokens=self.output_tokens,
            cost_usd=self.cost_usd,
        )


def load_task_corpus(path: Path) -> TaskCorpus:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"cannot load task corpus: {path}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != TASK_CORPUS_SCHEMA:
        raise CampaignError("unsupported TokenWise task corpus schema")
    raw_tasks = raw.get("tasks")
    if not isinstance(raw_tasks, list):
        raise CampaignError("task corpus tasks must be a list")
    tasks = tuple(_parse_task(value) for value in raw_tasks)
    expected = {
        f"tw-{workload.replace('_', '-')}-{case_index}"
        for workload in (
            "stable_dialogue",
            "long_history",
            "tool_accumulation",
            "intra_turn_tool_chain",
        )
        for case_index in range(1, 4)
    }
    if {task.task_id for task in tasks} != expected or len(tasks) != len(expected):
        raise CampaignError("task corpus does not match the frozen 12-task matrix")
    return TaskCorpus(
        schema=TASK_CORPUS_SCHEMA,
        tasks=tasks,
        digest=canonical_digest(raw),
    )


def _parse_task(value: Any) -> LiveTask:
    if not isinstance(value, dict):
        raise CampaignError("task corpus entries must be objects")
    try:
        task = LiveTask(
            task_id=str(value["task_id"]),
            workload_class=str(value["workload_class"]),
            case_index=int(value["case_index"]),
            turn_count=int(value["turn_count"]),
            seed_history_turns=int(value["seed_history_turns"]),
            expected_tool_calls_per_turn=int(value["expected_tool_calls_per_turn"]),
            user_prompts=tuple(str(item) for item in value["user_prompts"]),
            expected_outputs=tuple(str(item) for item in value["expected_outputs"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CampaignError("invalid task corpus entry") from exc
    if task.turn_count < 1 or len(task.user_prompts) != task.turn_count:
        raise CampaignError(f"invalid turn shape for {task.task_id}")
    if len(task.expected_outputs) != task.turn_count:
        raise CampaignError(f"missing expected outputs for {task.task_id}")
    if task.seed_history_turns < 0 or task.expected_tool_calls_per_turn < 0:
        raise CampaignError(f"negative workload shape for {task.task_id}")
    return task


def build_arm(cache_policy: str) -> ArmConfig:
    if cache_policy == CACHE_POLICY_NO_EXPLICIT:
        return ArmConfig(cache_policy, None, False)
    if cache_policy == CACHE_POLICY_PROVIDER_AUTO:
        return ArmConfig(cache_policy, None, True)
    if cache_policy == CACHE_POLICY_SYSTEM_AND_3:
        return ArmConfig(cache_policy, SystemAndTailCacheStrategy(), False)
    if cache_policy == CACHE_POLICY_ADAPTIVE_4:
        return ArmConfig(cache_policy, CacheOptimizer(max_breakpoints=4), False)
    raise CampaignError(f"unknown cache policy: {cache_policy}")


def rotated_cache_policies(plan_digest: str, block_index: int) -> tuple[str, ...]:
    if len(plan_digest) != 64:
        raise ValueError("plan_digest must be a SHA-256 hex digest")
    offset = (int(plan_digest[:8], 16) + block_index) % len(CACHE_POLICIES)
    return CACHE_POLICIES[offset:] + CACHE_POLICIES[:offset]


def build_campaign_report(
    *,
    config: CampaignConfig,
    corpus: TaskCorpus,
    trials: tuple[LiveTrialResult, ...],
) -> dict[str, Any]:
    expected_workloads = {task.task_id: task.workload_class for task in corpus.tasks}
    claim = assess_tokenwise_cost_claim(
        tuple(trial.measurement() for trial in trials),
        expected_workloads=expected_workloads,
        repetitions=config.repetitions,
    )
    payload = {
        "schema": REPORT_SCHEMA,
        "campaign": {
            "model": config.model,
            "repetitions": config.repetitions,
            "hard_cap_usd": config.hard_cap_usd,
            "max_provider_calls": config.max_provider_calls,
            "task_corpus_digest": corpus.digest,
            "price_snapshot": PRICE_SNAPSHOT,
        },
        "claim": to_primitive(claim),
        "trials": [asdict(trial) for trial in trials],
    }
    payload["report_digest"] = canonical_digest(payload)
    return payload


__all__ = [
    "DEFAULT_HARD_CAP_USD",
    "DEFAULT_MAX_PROVIDER_CALLS",
    "DEFAULT_MODEL",
    "PRICE_SNAPSHOT",
    "ArmConfig",
    "CampaignBudget",
    "CampaignConfig",
    "CampaignError",
    "LiveTask",
    "LiveTrialResult",
    "TaskCorpus",
    "build_arm",
    "build_campaign_report",
    "load_task_corpus",
    "rotated_cache_policies",
]
