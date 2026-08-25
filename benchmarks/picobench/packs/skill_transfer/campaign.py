from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from benchmarks.picobench.budget import ProviderBudgetConfig, ProviderBudgetLedger
from benchmarks.picobench.canonical import canonical_digest
from benchmarks.picobench.statistics import clustered_bootstrap_interval
from pico.utils.portable_lock import file_lock

CORPUS_SCHEMA = "pico.picobench.skill-transfer.tasks.v1"
TRIAL_SCHEMA = "pico.picobench.skill-transfer.trial.v1"
NEGATIVE_SCHEMA = "pico.picobench.skill-transfer.negative.v1"
MANIFEST_SCHEMA = "pico.picobench.skill-transfer.manifest.v1"
REPORT_SCHEMA = "pico.picobench.skill-transfer.report.v1"
OFFLINE_SCHEMA = "pico.picobench.skill-transfer.offline-verifier.v1"
_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_SHA = re.compile(r"[0-9a-f]{40}")
_ARMS = ("control", "treatment")
_ARTIFACT_PATHS = (
    "manifest.json",
    "candidate-receipt.json",
    "candidate-preparation-report.json",
    "raw-outcomes.jsonl",
    "hard-negative-outcomes.jsonl",
    "aggregate.json",
    "verifier-report.json",
    "claim-eligibility.json",
    "provider-budget.jsonl",
    "provider-budget.high-water.json",
    "provider-budget-approval.json",
    "provider-budget-report.json",
)
_INVENTORY = (*_ARTIFACT_PATHS, "inventory.json")


@dataclass(frozen=True)
class LearningInstance:
    instance_id: str
    result: str
    verification: str


@dataclass(frozen=True)
class HeldOutInstance:
    instance_id: str
    prompt: str
    fixture: dict[str, Any]


@dataclass(frozen=True)
class HardNegative:
    instance_id: str
    query: str


@dataclass(frozen=True)
class AbilityDefinition:
    ability_id: str
    goal: str
    learning: tuple[LearningInstance, ...]
    held_out: tuple[HeldOutInstance, ...]
    hard_negatives: tuple[HardNegative, ...]


@dataclass(frozen=True)
class SkillTransferCorpus:
    schema: str
    abilities: tuple[AbilityDefinition, ...]

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True)
class TrialRecord:
    task_id: str
    ability_id: str
    repetition: int
    arm_id: Literal["control", "treatment"]
    status: str
    workspace_digest: str
    active_revision_id: str | None
    injected_skill_ids: tuple[str, ...]
    source_experience_ids: tuple[str, ...]
    tool_calls: int
    turns: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    provider_calls: int
    estimated_cost_cny: float
    verification_receipt: dict[str, Any] | None
    failure_class: str | None = None
    schema: str = TRIAL_SCHEMA

    @property
    def passed(self) -> bool:
        return self.status == "passed"


@dataclass(frozen=True)
class NegativeRecord:
    instance_id: str
    ability_id: str
    active_revision_id: str
    recalled_revision_ids: tuple[str, ...]
    schema: str = NEGATIVE_SCHEMA


@dataclass(frozen=True)
class CampaignConfig:
    corpus_path: Path
    output_root: Path
    pico_wheel: Path
    myna_wheel: Path
    pico_commit: str
    myna_commit: str
    provider: str = "deepseek"
    model: str = "deepseek/deepseek-v4-flash"
    repetitions: int = 2
    seed: int = 20260825
    bootstrap_samples: int = 5_000
    max_tool_iterations: int = 5
    max_attempts_per_call: int = 2
    max_input_tokens_per_call: int = 16_384
    max_output_tokens_per_call: int = 1_024
    input_cache_miss_usd_per_million: float = 0.14
    output_usd_per_million: float = 0.28
    conservative_usd_to_cny_multiplier: float = 7.5
    hard_cap_cny: float = 25.0

    def __post_init__(self) -> None:
        if self.repetitions != 2:
            raise ValueError("skill transfer v1 requires exactly two repetitions")
        if self.provider != "deepseek" or self.model != "deepseek/deepseek-v4-flash":
            raise ValueError("skill transfer v1 is frozen to deepseek/deepseek-v4-flash")
        for name in ("pico_commit", "myna_commit"):
            if _SHA.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be a lowercase full commit SHA")
        for path in (self.corpus_path, self.pico_wheel, self.myna_wheel):
            if not path.is_file():
                raise ValueError(f"campaign input is missing: {path.name}")
        if self.maximum_cost_cny > self.hard_cap_cny:
            raise ValueError("skill transfer v1 worst-case cost exceeds its hard cap")

    @property
    def planned_trials(self) -> int:
        return 24 * self.repetitions * 2

    @property
    def maximum_provider_attempts(self) -> int:
        extraction_attempts = self.maximum_candidate_attempts
        task_attempts = self.planned_trials * (self.max_tool_iterations + 1) * self.max_attempts_per_call
        return extraction_attempts + task_attempts

    @property
    def maximum_candidate_attempts(self) -> int:
        return 6 * self.max_attempts_per_call

    @property
    def maximum_candidate_cost_cny(self) -> float:
        usd = self.maximum_candidate_attempts * (
            self.max_input_tokens_per_call / 1_000_000 * self.input_cache_miss_usd_per_million
            + self.max_output_tokens_per_call / 1_000_000 * self.output_usd_per_million
        )
        return usd * self.conservative_usd_to_cny_multiplier

    @property
    def maximum_cost_cny(self) -> float:
        usd = self.maximum_provider_attempts * (
            self.max_input_tokens_per_call / 1_000_000 * self.input_cache_miss_usd_per_million
            + self.max_output_tokens_per_call / 1_000_000 * self.output_usd_per_million
        )
        return usd * self.conservative_usd_to_cny_multiplier

    def manifest(self, corpus: SkillTransferCorpus) -> dict[str, Any]:
        split_digests = corpus_split_digests(corpus)
        return {
            "schema": MANIFEST_SCHEMA,
            "task_corpus_digest": corpus.digest,
            "treatment_axis": {
                "control": "same verified experiences; derived Skill unavailable",
                "treatment": "same verified experiences; exact accepted Skill revision active",
            },
            "sealed_inputs": {
                "learning_projection_digest": split_digests["learning"],
                "held_out_projection_digest": split_digests["held_out"],
                "hard_negative_projection_digest": split_digests["hard_negatives"],
                "candidate_worker_receives_learning_projection_only": True,
            },
            "candidate": {
                "pico_commit": self.pico_commit,
                "pico_wheel_sha256": _sha256(self.pico_wheel),
                "myna_commit": self.myna_commit,
                "myna_wheel_sha256": _sha256(self.myna_wheel),
            },
            "execution": {
                "provider": self.provider,
                "model": self.model,
                "repetitions": self.repetitions,
                "seed": self.seed,
                "planned_primary_pairs": 48,
                "planned_primary_trials": self.planned_trials,
                "planned_hard_negatives": 24,
                "max_tool_iterations": self.max_tool_iterations,
                "max_attempts_per_call": self.max_attempts_per_call,
                "skill_extraction": {
                    "max_output_tokens": self.max_output_tokens_per_call,
                    "prompt_revision": "myna-skill-extractor-v1",
                    "thinking": "disabled",
                },
            },
            "analysis": {
                "bootstrap_unit": "held_out_instance",
                "bootstrap_samples": self.bootstrap_samples,
                "bootstrap_seed": self.seed,
                "confidence_level": 0.95,
            },
            "budget": {
                "maximum_candidate_attempts": self.maximum_candidate_attempts,
                "maximum_candidate_cost_cny": round(self.maximum_candidate_cost_cny, 6),
                "maximum_provider_attempts": self.maximum_provider_attempts,
                "maximum_cost_cny": round(self.maximum_cost_cny, 6),
                "hard_cap_cny": self.hard_cap_cny,
                "max_input_tokens_per_call": self.max_input_tokens_per_call,
                "max_output_tokens_per_call": self.max_output_tokens_per_call,
                "input_cache_miss_usd_per_million": self.input_cache_miss_usd_per_million,
                "output_usd_per_million": self.output_usd_per_million,
                "conservative_usd_to_cny_multiplier": self.conservative_usd_to_cny_multiplier,
            },
            "claim_policy": {
                "requires_all_48_valid_pairs": True,
                "requires_instance_disjoint": True,
                "requires_all_24_hard_negatives": True,
                "requires_provenance_complete": True,
                "requires_task_clustered_ci_lower_above_zero": True,
                "requires_zero_treatment_regressions": True,
                "general_agent_claim_allowed": False,
            },
        }


def load_corpus(path: Path) -> SkillTransferCorpus:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("invalid skill transfer corpus") from error
    if not isinstance(raw, dict) or raw.get("schema") != CORPUS_SCHEMA or not isinstance(raw.get("abilities"), list):
        raise ValueError("unsupported skill transfer corpus schema")
    abilities = tuple(_ability(item) for item in raw["abilities"])
    if len(abilities) != 6 or len({item.ability_id for item in abilities}) != 6:
        raise ValueError("skill transfer v1 requires six unique ability families")
    all_ids: list[str] = []
    for ability in abilities:
        if len(ability.learning) != 3 or len(ability.held_out) != 4 or len(ability.hard_negatives) != 4:
            raise ValueError("each ability requires 3 learning, 4 held-out, and 4 hard-negative instances")
        all_ids.extend(item.instance_id for item in (*ability.learning, *ability.held_out, *ability.hard_negatives))
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("learning, held-out, and hard-negative instance ids must be disjoint")
    return SkillTransferCorpus(schema=CORPUS_SCHEMA, abilities=abilities)


def build_report(
    *,
    corpus: SkillTransferCorpus,
    trials: tuple[TrialRecord, ...],
    negatives: tuple[NegativeRecord, ...],
    candidate_receipt: dict[str, Any],
    repetitions: int = 2,
    bootstrap_samples: int = 5_000,
    bootstrap_seed: int = 20260825,
) -> dict[str, Any]:
    held_out = {item.instance_id: (ability, item) for ability in corpus.abilities for item in ability.held_out}
    learning_ids = {item.instance_id for ability in corpus.abilities for item in ability.learning}
    held_out_ids = set(held_out)
    negative_ids = {item.instance_id for ability in corpus.abilities for item in ability.hard_negatives}
    instance_disjoint = not (learning_ids & held_out_ids or learning_ids & negative_ids or held_out_ids & negative_ids)
    revisions = candidate_receipt.get("active_revisions", {})
    learning_provenance = candidate_receipt.get("source_learning_instance_ids", {})
    experience_provenance = candidate_receipt.get("source_experience_ids", {})
    experience_maps = candidate_receipt.get("learning_experience_maps", {})
    candidate_input_sealed = candidate_receipt.get("candidate_input_digest") == corpus_split_digests(corpus)["learning"]
    admission_precheck_complete = _candidate_admission_valid(corpus, candidate_receipt)
    provenance_complete = (
        isinstance(revisions, dict)
        and isinstance(learning_provenance, dict)
        and isinstance(experience_provenance, dict)
        and isinstance(experience_maps, dict)
    )
    for ability in corpus.abilities:
        expected_learning = sorted(item.instance_id for item in ability.learning)
        provenance_complete &= (
            isinstance(revisions.get(ability.ability_id), str)
            and sorted(learning_provenance.get(ability.ability_id, [])) == expected_learning
            and len(experience_provenance.get(ability.ability_id, [])) == 3
            and len(set(experience_provenance.get(ability.ability_id, []))) == 3
            and isinstance(experience_maps.get(ability.ability_id), dict)
            and sorted(experience_maps.get(ability.ability_id, {})) == expected_learning
            and sorted(experience_maps.get(ability.ability_id, {}).values())
            == sorted(experience_provenance.get(ability.ability_id, []))
        )

    grouped: dict[tuple[str, int], dict[str, TrialRecord]] = {}
    axis_valid = True
    resource_complete = True
    verification_receipts_valid = True
    for trial in trials:
        expected = held_out.get(trial.task_id)
        if (
            expected is None
            or trial.ability_id != expected[0].ability_id
            or trial.repetition not in range(repetitions)
            or trial.arm_id not in _ARMS
            or trial.schema != TRIAL_SCHEMA
        ):
            axis_valid = False
            continue
        by_arm = grouped.setdefault((trial.task_id, trial.repetition), {})
        if trial.arm_id in by_arm:
            axis_valid = False
        by_arm[trial.arm_id] = trial
        resource_complete &= all(
            value >= 0
            for value in (
                trial.tool_calls,
                trial.turns,
                trial.latency_ms,
                trial.input_tokens,
                trial.output_tokens,
                trial.provider_calls,
                trial.estimated_cost_cny,
            )
        )
        receipt = trial.verification_receipt
        verification_receipts_valid &= bool(
            not trial.passed
            or (
                isinstance(receipt, dict)
                and receipt.get("schema") == "pico.picobench.skill-transfer.verification.v1"
                and receipt.get("fixture") == expected[1].fixture
                and receipt.get("passed") is True
                and receipt.get("smoke_fixture_unchanged") is True
                and receipt.get("unexpected_workspace_paths") == []
            )
        )

    valid_pairs: list[tuple[TrialRecord, TrialRecord]] = []
    complete_pairs = 0
    for task_id, (ability, _task) in held_out.items():
        revision = revisions.get(ability.ability_id)
        expected_sources = tuple(sorted(experience_provenance.get(ability.ability_id, [])))
        for repetition in range(repetitions):
            arms = grouped.get((task_id, repetition), {})
            if set(arms) != set(_ARMS):
                axis_valid = False
                continue
            complete_pairs += 1
            control, treatment = arms["control"], arms["treatment"]
            pair_axis = (
                control.workspace_digest == treatment.workspace_digest
                and control.active_revision_id is None
                and control.injected_skill_ids == ()
                and treatment.active_revision_id == revision
                and treatment.injected_skill_ids == (revision,)
                and tuple(sorted(treatment.source_experience_ids)) == expected_sources
                and control.failure_class not in {"provider", "transport", "budget", "infrastructure"}
                and treatment.failure_class not in {"provider", "transport", "budget", "infrastructure"}
            )
            axis_valid &= pair_axis
            if pair_axis:
                valid_pairs.append((control, treatment))

    negative_by_id = {item.instance_id: item for item in negatives if item.schema == NEGATIVE_SCHEMA}
    hard_negative_complete = len(negative_by_id) == 24 and set(negative_by_id) == negative_ids
    incorrect_injections = 0
    for ability in corpus.abilities:
        revision = revisions.get(ability.ability_id)
        for item in ability.hard_negatives:
            observed = negative_by_id.get(item.instance_id)
            if observed is None or observed.ability_id != ability.ability_id or observed.active_revision_id != revision:
                hard_negative_complete = False
                continue
            incorrect_injections += int(bool(observed.recalled_revision_ids))

    expected_pairs = 24 * repetitions
    ship_complete = complete_pairs == expected_pairs and len(trials) == expected_pairs * 2
    measurement_valid = bool(
        ship_complete
        and len(valid_pairs) == expected_pairs
        and axis_valid
        and instance_disjoint
        and provenance_complete
        and hard_negative_complete
        and resource_complete
        and verification_receipts_valid
        and candidate_input_sealed
        and admission_precheck_complete
    )
    deltas_by_task: dict[str, list[float]] = {}
    for control, treatment in valid_pairs:
        deltas_by_task.setdefault(control.task_id, []).append(float(treatment.passed) - float(control.passed))
    task_deltas = {task_id: tuple(values) for task_id, values in deltas_by_task.items()}
    interval = (
        asdict(clustered_bootstrap_interval(task_deltas, samples=bootstrap_samples, seed=bootstrap_seed))
        if task_deltas
        else None
    )
    control_passes = sum(control.passed for control, _ in valid_pairs)
    treatment_passes = sum(treatment.passed for _, treatment in valid_pairs)
    regressions = sum(control.passed and not treatment.passed for control, treatment in valid_pairs)
    pass_delta_pp = 100 * (treatment_passes - control_passes) / len(valid_pairs) if valid_pairs else 0.0
    positive = bool(
        measurement_valid
        and incorrect_injections == 0
        and regressions == 0
        and interval is not None
        and interval["lower"] > 0
    )
    return {
        "schema": REPORT_SCHEMA,
        "task_corpus_digest": corpus.digest,
        "measurement": {
            "planned_pairs": expected_pairs,
            "complete_pairs": complete_pairs,
            "valid_pairs": len(valid_pairs),
            "axis_valid": axis_valid,
            "instance_disjoint": instance_disjoint,
            "provenance_complete": provenance_complete,
            "resource_observations_complete": resource_complete,
            "verification_receipts_valid": verification_receipts_valid,
            "candidate_input_sealed": candidate_input_sealed,
            "admission_precheck_complete": admission_precheck_complete,
        },
        "capability": {
            "control_passes": control_passes,
            "treatment_passes": treatment_passes,
            "verified_pass_delta_pp": round(pass_delta_pp, 6),
            "task_clustered_bootstrap_95_ci": interval,
            "treatment_regressions": regressions,
        },
        "safety": {
            "hard_negative_complete": hard_negative_complete,
            "hard_negative_total": len(negative_by_id),
            "incorrect_skill_injections": incorrect_injections,
        },
        "resources": _resource_report(valid_pairs),
        "claim": {
            "ship_complete": ship_complete,
            "measurement_valid": measurement_valid,
            "positive_claim_eligible": positive,
            "general_agent_claim_eligible": False,
            "eligible_scope": "skill_transfer_v1_six_ability_pack",
        },
    }


def verify_evidence(output_root: Path, *, corpus_path: Path) -> dict[str, Any]:
    output = output_root.resolve()
    missing = [name for name in _INVENTORY if not (output / name).is_file()]
    if missing:
        raise ValueError(f"skill transfer evidence inventory is incomplete: {missing}")
    _verify_inventory(output)
    manifest = _json(output / "manifest.json")
    candidate = _json(output / "candidate-receipt.json")
    corpus = load_corpus(corpus_path)
    trials = tuple(_trial(item) for item in _jsonl(output / "raw-outcomes.jsonl"))
    negatives = tuple(_negative(item) for item in _jsonl(output / "hard-negative-outcomes.jsonl"))
    analysis = manifest.get("analysis", {})
    report = build_report(
        corpus=corpus,
        trials=trials,
        negatives=negatives,
        candidate_receipt=candidate,
        repetitions=int(manifest.get("execution", {}).get("repetitions", 0)),
        bootstrap_samples=int(analysis.get("bootstrap_samples", 0)),
        bootstrap_seed=int(analysis.get("bootstrap_seed", 0)),
    )
    gates = {
        "manifest_schema": manifest.get("schema") == MANIFEST_SCHEMA,
        "manifest_corpus_bound": manifest.get("task_corpus_digest") == corpus.digest,
        "aggregate_reproduces": _json(output / "aggregate.json") == report,
        "claim_reproduces": _json(output / "claim-eligibility.json") == report["claim"],
        "verifier_reproduces": _json(output / "verifier-report.json") == _verifier_report(report),
        "measurement_valid": report["claim"]["measurement_valid"],
        "budget_accounting_complete": _verify_budget(output, manifest, trials, candidate),
        "candidate_runtime_snapshots_bound": _verify_candidate_snapshots(output, corpus, candidate),
    }
    return {"schema": OFFLINE_SCHEMA, "passed": all(gates.values()), "gates": gates, "recomputed_report": report}


def plan(config: CampaignConfig) -> dict[str, Any]:
    corpus = load_corpus(config.corpus_path)
    manifest = config.manifest(corpus)
    return {"manifest": manifest, "approval_digest": canonical_digest(manifest)}


def run_campaign(
    config: CampaignConfig,
    *,
    approval_digest: str,
    approved_cny: float,
    execute_paid: bool,
    provider_api_key: str,
    provider_api_base: str | None,
    prepare_only: bool = False,
) -> dict[str, Any]:
    from .runner import InstalledSkillTransferExecutor

    corpus = load_corpus(config.corpus_path)
    manifest = config.manifest(corpus)
    expected_digest = canonical_digest(manifest)
    if not execute_paid or approval_digest != expected_digest:
        raise ValueError("paid execution requires the exact frozen approval digest")
    required_approval = float(manifest["budget"]["maximum_candidate_cost_cny" if prepare_only else "maximum_cost_cny"])
    if not math.isfinite(approved_cny) or approved_cny < required_approval or approved_cny > config.hard_cap_cny:
        raise ValueError("approved CNY must cover the frozen maximum within the hard cap")
    output = config.output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with file_lock(output / ".run.lock", blocking=False):
        _freeze_json(output / "manifest.json", manifest)
        ledger, budget_config = _prepare_budget(
            config,
            output=output,
            approval_digest=approval_digest,
            maximum_provider_attempts=(
                config.maximum_candidate_attempts if prepare_only else config.maximum_provider_attempts
            ),
        )
        with InstalledSkillTransferExecutor(
            config,
            provider_api_key=provider_api_key,
            provider_api_base=provider_api_base,
        ) as executor:
            executor.configure_budget(ledger.path, budget_config)
            candidate_path = output / "candidate-receipt.json"
            snapshot_root = output / "candidate-runtimes"
            if candidate_path.exists():
                candidate = _json(candidate_path)
                executor.load_candidates(corpus, candidate, snapshot_root=snapshot_root)
            else:
                candidate = executor.prepare_candidates(corpus, snapshot_root=snapshot_root)
                _freeze_json(candidate_path, candidate)
            if not _candidate_admission_valid(corpus, candidate):
                raise ValueError("frozen Skill candidate failed held-out admission precheck")
            preparation_path = output / "candidate-preparation-report.json"
            if preparation_path.exists():
                preparation = _json(preparation_path)
            else:
                preparation = _candidate_preparation_report(
                    config,
                    corpus,
                    candidate,
                    ledger.snapshot(),
                    approval_digest=approval_digest,
                    approved_cny=approved_cny,
                )
                _freeze_json(preparation_path, preparation)
            if prepare_only:
                return preparation
            records = _trial_journal(output / "raw-outcomes.jsonl")
            expected = {
                (task.instance_id, repetition, arm_id)
                for ability in corpus.abilities
                for task in ability.held_out
                for repetition in range(config.repetitions)
                for arm_id in _ARMS
            }
            if set(records) - expected:
                raise ValueError("raw outcomes contain trials outside skill_transfer_v1")
            for ability in corpus.abilities:
                for task in ability.held_out:
                    for repetition in range(config.repetitions):
                        for arm_id in _arm_order(task.instance_id, repetition, seed=config.seed):
                            key = (task.instance_id, repetition, arm_id)
                            if key in records:
                                continue
                            record = executor.run_trial(ability, task, repetition, arm_id)
                            _append_jsonl(output / "raw-outcomes.jsonl", asdict(record))
                            records[key] = record
            negative_path = output / "hard-negative-outcomes.jsonl"
            negatives = _negative_journal(negative_path)
            if len(negatives) < 24:
                for record in executor.hard_negatives(corpus):
                    if record.instance_id in negatives:
                        continue
                    _append_jsonl(negative_path, asdict(record))
                    negatives[record.instance_id] = record
        ordered = tuple(records[key] for key in sorted(records))
        ordered_negatives = tuple(negatives[key] for key in sorted(negatives))
        report = build_report(
            corpus=corpus,
            trials=ordered,
            negatives=ordered_negatives,
            candidate_receipt=candidate,
            repetitions=config.repetitions,
            bootstrap_samples=config.bootstrap_samples,
            bootstrap_seed=config.seed,
        )
        budget = ledger.snapshot()
        expected_attempts = sum(item.provider_calls for item in ordered) + int(
            candidate.get("extractor", {}).get("provider_request_attempts", 0)
        )
        if budget.request_attempts != expected_attempts or not budget.accounting_complete:
            raise ValueError("Provider budget evidence does not match Skill transfer records")
        _write_json(output / "provider-budget-report.json", asdict(budget))
        _write_json(output / "aggregate.json", report)
        _write_json(output / "claim-eligibility.json", report["claim"])
        _write_json(output / "verifier-report.json", _verifier_report(report))
        _write_json(
            output / "inventory.json",
            {
                "schema": "pico.picobench.skill-transfer.inventory.v1",
                "files": [{"path": relative, "sha256": _sha256(output / relative)} for relative in _ARTIFACT_PATHS],
            },
        )
        return report


def _candidate_preparation_report(
    config: CampaignConfig,
    corpus: SkillTransferCorpus,
    candidate: dict[str, Any],
    budget: Any,
    *,
    approval_digest: str,
    approved_cny: float,
) -> dict[str, Any]:
    revisions = candidate.get("active_revisions", {})
    skills = candidate.get("skills", {})
    if not isinstance(revisions, dict) or not isinstance(skills, dict):
        raise ValueError("candidate receipt does not contain reviewable Skill content")
    reviewable = []
    for ability in corpus.abilities:
        skill = skills.get(ability.ability_id)
        if not isinstance(skill, dict) or skill.get("revision_id") != revisions.get(ability.ability_id):
            raise ValueError("candidate receipt Skill content does not match the active revision")
        reviewable.append(
            {
                "ability_id": ability.ability_id,
                "goal": ability.goal,
                "skill_id": skill.get("skill_id"),
                "revision_id": skill["revision_id"],
                "content": skill.get("content"),
                "learning_instance_ids": [item.instance_id for item in ability.learning],
                "source_experience_ids": candidate["source_experience_ids"][ability.ability_id],
            }
        )
    exact_matches = sum(
        candidate["held_out_admission_precheck"].get(item.instance_id) == [revisions.get(ability.ability_id)]
        for ability in corpus.abilities
        for item in ability.held_out
    )
    return {
        "schema": "pico.picobench.skill-transfer.candidate-preparation.v1",
        "status": "candidate_ready",
        "approval_digest": approval_digest,
        "candidate_input_digest": candidate.get("candidate_input_digest"),
        "skills": reviewable,
        "admission": {"exact_revision_matches": exact_matches, "expected": 24, "passed": exact_matches == 24},
        "budget": {
            "approved_cny": approved_cny,
            "maximum_stage_cost_cny": round(config.maximum_candidate_cost_cny, 6),
            "request_attempts": budget.request_attempts,
            "charged_cny": budget.provider_charged_cny,
        },
        "planned_primary_trials_remaining": config.planned_trials,
    }


def _prepare_budget(
    config: CampaignConfig,
    *,
    output: Path,
    approval_digest: str,
    maximum_provider_attempts: int,
) -> tuple[ProviderBudgetLedger, ProviderBudgetConfig]:
    ledger_path = output / "provider-budget.jsonl"
    approval_path = output / "provider-budget-approval.json"
    base = ProviderBudgetConfig(
        hard_cap_cny=config.hard_cap_cny,
        external_service_reserve_cny=0.0,
        max_total_request_attempts=maximum_provider_attempts,
        max_input_tokens_per_call=config.max_input_tokens_per_call,
        max_output_tokens_per_call=config.max_output_tokens_per_call,
        input_cache_miss_usd_per_million=config.input_cache_miss_usd_per_million,
        output_usd_per_million=config.output_usd_per_million,
        conservative_usd_to_cny_multiplier=config.conservative_usd_to_cny_multiplier,
    )
    if approval_path.exists():
        receipt = _json(approval_path)
        if receipt.get("approval_digest") != approval_digest or not isinstance(receipt.get("ledger_prefix"), dict):
            raise ValueError("Provider budget approval receipt does not match")
        prefix = receipt["ledger_prefix"]
    else:
        if ledger_path.exists() or ledger_path.with_suffix(".high-water.json").exists():
            raise ValueError("Provider budget evidence exists without approval")
        snapshot = ProviderBudgetLedger(ledger_path, base).snapshot()
        prefix = {"event_count": snapshot.ledger_event_count, "digest": snapshot.ledger_digest, "charged_cny": 0.0}
        _freeze_json(
            approval_path,
            {
                "schema": "pico.picobench.skill-transfer.budget-approval.v1",
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


def _verify_budget(
    output: Path,
    manifest: dict[str, Any],
    trials: tuple[TrialRecord, ...],
    candidate: dict[str, Any],
) -> bool:
    try:
        budget = manifest["budget"]
        approval = _json(output / "provider-budget-approval.json")
        prefix = approval["ledger_prefix"]
        config = ProviderBudgetConfig(
            hard_cap_cny=float(budget["hard_cap_cny"]),
            external_service_reserve_cny=0.0,
            max_total_request_attempts=int(budget["maximum_provider_attempts"]),
            max_input_tokens_per_call=int(budget["max_input_tokens_per_call"]),
            max_output_tokens_per_call=int(budget["max_output_tokens_per_call"]),
            input_cache_miss_usd_per_million=float(budget["input_cache_miss_usd_per_million"]),
            output_usd_per_million=float(budget["output_usd_per_million"]),
            conservative_usd_to_cny_multiplier=float(budget["conservative_usd_to_cny_multiplier"]),
            approval_digest=approval["approval_digest"],
            ledger_prefix_event_count=int(prefix["event_count"]),
            ledger_prefix_digest=str(prefix["digest"]),
            ledger_prefix_charged_cny=float(prefix["charged_cny"]),
        )
        snapshot = ProviderBudgetLedger(output / "provider-budget.jsonl", config).snapshot()
        report = _json(output / "provider-budget-report.json")
        expected_attempts = sum(item.provider_calls for item in trials) + int(
            candidate.get("extractor", {}).get("provider_request_attempts", 0)
        )
        return bool(
            approval["approval_digest"] == canonical_digest(manifest)
            and snapshot.accounting_complete
            and snapshot.request_attempts == expected_attempts
            and report == asdict(snapshot)
        )
    except (KeyError, TypeError, ValueError):
        return False


def _candidate_admission_valid(corpus: SkillTransferCorpus, candidate: dict[str, Any]) -> bool:
    observed = candidate.get("held_out_admission_precheck")
    revisions = candidate.get("active_revisions")
    if (
        candidate.get("candidate_frozen_before_admission_precheck") is not True
        or not isinstance(observed, dict)
        or not isinstance(revisions, dict)
    ):
        return False
    expected_ids = {item.instance_id for ability in corpus.abilities for item in ability.held_out}
    if set(observed) != expected_ids:
        return False
    return all(
        observed.get(item.instance_id) == [revisions.get(ability.ability_id)]
        for ability in corpus.abilities
        for item in ability.held_out
    )


def _verify_candidate_snapshots(
    output: Path,
    corpus: SkillTransferCorpus,
    candidate: dict[str, Any],
) -> bool:
    digests = candidate.get("runtime_snapshot_digests")
    if not isinstance(digests, dict):
        return False
    try:
        return all(
            digests.get(ability.ability_id)
            == {
                arm_id: directory_digest(output / "candidate-runtimes" / ability.ability_id / f"{arm_id}-runtime")
                for arm_id in _ARMS
            }
            for ability in corpus.abilities
        )
    except OSError:
        return False


def _verify_inventory(output: Path) -> None:
    try:
        inventory = _json(output / "inventory.json")
        rows = inventory["files"]
        observed = {row["path"]: row["sha256"] for row in rows}
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("skill transfer inventory is invalid") from error
    if (
        inventory.get("schema") != "pico.picobench.skill-transfer.inventory.v1"
        or set(observed) != set(_ARTIFACT_PATHS)
        or len(rows) != len(_ARTIFACT_PATHS)
    ):
        raise ValueError("skill transfer inventory file set is invalid")
    for relative in _ARTIFACT_PATHS:
        if not (output / relative).is_file() or observed[relative] != _sha256(output / relative):
            raise ValueError(f"skill transfer evidence digest changed: {relative}")


def _ability(value: object) -> AbilityDefinition:
    if not isinstance(value, dict) or _ID.fullmatch(str(value.get("ability_id", ""))) is None:
        raise ValueError("invalid ability definition")
    goal = value.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("ability goal must not be empty")
    return AbilityDefinition(
        ability_id=str(value["ability_id"]),
        goal=goal,
        learning=tuple(LearningInstance(**item) for item in value.get("learning", [])),
        held_out=tuple(HeldOutInstance(**item) for item in value.get("held_out", [])),
        hard_negatives=tuple(HardNegative(**item) for item in value.get("hard_negatives", [])),
    )


def _trial(value: dict[str, Any]) -> TrialRecord:
    return TrialRecord(
        **{
            **value,
            "injected_skill_ids": tuple(value.get("injected_skill_ids", ())),
            "source_experience_ids": tuple(value.get("source_experience_ids", ())),
        }
    )


def _negative(value: dict[str, Any]) -> NegativeRecord:
    return NegativeRecord(**{**value, "recalled_revision_ids": tuple(value.get("recalled_revision_ids", ()))})


def _trial_journal(path: Path) -> dict[tuple[str, int, str], TrialRecord]:
    records: dict[tuple[str, int, str], TrialRecord] = {}
    if not path.exists():
        return records
    for value in _jsonl(path):
        record = _trial(value)
        key = (record.task_id, record.repetition, record.arm_id)
        if key in records:
            raise ValueError("raw outcomes contain a duplicate Trial")
        records[key] = record
    return records


def _negative_journal(path: Path) -> dict[str, NegativeRecord]:
    records: dict[str, NegativeRecord] = {}
    if not path.exists():
        return records
    for value in _jsonl(path):
        record = _negative(value)
        if record.instance_id in records:
            raise ValueError("hard-negative outcomes contain a duplicate instance")
        records[record.instance_id] = record
    return records


def _arm_order(task_id: str, repetition: int, *, seed: int) -> tuple[str, str]:
    digest = hashlib.sha256(f"{seed}:{task_id}:{repetition}".encode()).digest()[0]
    return _ARMS if digest % 2 == 0 else tuple(reversed(_ARMS))  # type: ignore[return-value]


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _freeze_json(path: Path, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise ValueError(f"frozen evidence conflicts: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resource_report(pairs: list[tuple[TrialRecord, TrialRecord]]) -> dict[str, Any]:
    def arm_mean(index: int, field: str) -> float:
        return round(mean(float(getattr(pair[index], field)) for pair in pairs), 6) if pairs else 0.0

    return {
        field: {"control_mean": arm_mean(0, field), "treatment_mean": arm_mean(1, field)}
        for field in (
            "tool_calls",
            "turns",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "provider_calls",
            "estimated_cost_cny",
        )
    }


def _verifier_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "pico.picobench.skill-transfer.verifier.v1",
        "passed": bool(report["claim"]["measurement_valid"]),
        "gates": {
            "all_pairs_valid": report["measurement"]["valid_pairs"] == 48,
            "instance_disjoint": report["measurement"]["instance_disjoint"],
            "provenance_complete": report["measurement"]["provenance_complete"],
            "hard_negatives_complete": report["safety"]["hard_negative_complete"],
            "resource_observations_complete": report["measurement"]["resource_observations_complete"],
            "verification_receipts_valid": report["measurement"]["verification_receipts_valid"],
            "candidate_input_sealed": report["measurement"]["candidate_input_sealed"],
            "admission_precheck_complete": report["measurement"]["admission_precheck_complete"],
        },
    }


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not all(isinstance(item, dict) for item in rows):
        raise ValueError(f"expected JSON objects: {path.name}")
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_digest(root: Path) -> str:
    if not root.is_dir():
        raise OSError(f"candidate runtime snapshot is missing: {root}")
    return canonical_digest(
        {path.relative_to(root).as_posix(): _sha256(path) for path in sorted(root.rglob("*")) if path.is_file()}
    )


def learning_projection(ability: AbilityDefinition) -> dict[str, Any]:
    return {
        "ability_id": ability.ability_id,
        "goal": ability.goal,
        "learning": [asdict(item) for item in ability.learning],
    }


def corpus_split_digests(corpus: SkillTransferCorpus) -> dict[str, str]:
    return {
        "learning": canonical_digest([learning_projection(ability) for ability in corpus.abilities]),
        "held_out": canonical_digest(
            [
                {"ability_id": ability.ability_id, "instances": [asdict(item) for item in ability.held_out]}
                for ability in corpus.abilities
            ]
        ),
        "hard_negatives": canonical_digest(
            [
                {"ability_id": ability.ability_id, "instances": [asdict(item) for item in ability.hard_negatives]}
                for ability in corpus.abilities
            ]
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan, run, or verify the skill_transfer_v1 campaign")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    prepare_parser = subparsers.add_parser("prepare")
    run_parser = subparsers.add_parser("run")
    for child in (plan_parser, prepare_parser, run_parser):
        child.add_argument("--corpus", type=Path, required=True)
        child.add_argument("--output-root", type=Path, required=True)
        child.add_argument("--pico-wheel", type=Path, required=True)
        child.add_argument("--myna-wheel", type=Path, required=True)
        child.add_argument("--pico-commit", required=True)
        child.add_argument("--myna-commit", required=True)
    for child in (prepare_parser, run_parser):
        child.add_argument("--approval-digest", required=True)
        child.add_argument("--approved-cny", type=float, required=True)
        child.add_argument("--provider-api-base")
        child.add_argument("--execute-paid", action="store_true")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--corpus", type=Path, required=True)
    verify_parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "verify":
        result = verify_evidence(args.output_root, corpus_path=args.corpus)
    else:
        config = CampaignConfig(
            corpus_path=args.corpus,
            output_root=args.output_root,
            pico_wheel=args.pico_wheel,
            myna_wheel=args.myna_wheel,
            pico_commit=args.pico_commit,
            myna_commit=args.myna_commit,
        )
        result = (
            run_campaign(
                config,
                approval_digest=args.approval_digest,
                approved_cny=args.approved_cny,
                execute_paid=args.execute_paid,
                provider_api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                provider_api_base=args.provider_api_base,
                prepare_only=args.command == "prepare",
            )
            if args.command in {"prepare", "run"}
            else plan(config)
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
