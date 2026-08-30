from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from benchmarks.picobench.budget import ProviderBudgetConfig, ProviderBudgetLedger
from benchmarks.picobench.canonical import canonical_digest
from benchmarks.picobench.packs.myna_task_effect.runner import _tool_metrics
from benchmarks.picobench.packs.skill_transfer.campaign import (
    AbilityDefinition,
    HeldOutInstance,
    SkillTransferCorpus,
    load_corpus,
)
from benchmarks.picobench.packs.skill_transfer.fixtures import materialize
from benchmarks.picobench.packs.skill_transfer.fixtures import verify as verify_fixture
from benchmarks.picobench.packs.skill_transfer.runner import InstalledSkillTransferExecutor
from benchmarks.picobench.statistics import clustered_bootstrap_interval

ARMS = ("no_skill", "long_skill", "anchor_skill")
SCHEMA = "pico.picobench.skill-transfer-v2.stage-a.v1"


@dataclass(frozen=True)
class StageAConfig:
    corpus_path: Path
    long_skill_receipt: Path
    output_root: Path
    pico_wheel: Path
    myna_wheel: Path
    pico_commit: str
    myna_commit: str
    repetitions: int = 2
    seed: int = 20260829
    bootstrap_samples: int = 5_000
    provider: str = "deepseek"
    model: str = "deepseek/deepseek-v4-flash"
    max_tool_iterations: int = 5
    max_attempts_per_call: int = 1
    max_input_tokens_per_call: int = 32_768
    max_output_tokens_per_call: int = 1_024
    input_cache_miss_usd_per_million: float = 0.14
    output_usd_per_million: float = 0.28
    conservative_usd_to_cny_multiplier: float = 7.5
    hard_cap_cny: float = 3.5
    anchor_profile: Literal["generic", "pico_policy"] = "generic"

    def __post_init__(self) -> None:
        if self.repetitions != 2:
            raise ValueError("Stage A requires exactly two repetitions")
        if self.anchor_profile not in {"generic", "pico_policy"}:
            raise ValueError("unsupported Stage A Anchor profile")
        for path in (self.corpus_path, self.long_skill_receipt, self.pico_wheel, self.myna_wheel):
            if not path.is_file():
                raise ValueError(f"missing Stage A input: {path}")

    @property
    def planned_trials(self) -> int:
        return 24 * self.repetitions * len(ARMS)

    @property
    def maximum_provider_attempts(self) -> int:
        return self.planned_trials * (self.max_tool_iterations + 1) * self.max_attempts_per_call

    @property
    def manifest_schema(self) -> str:
        return (
            "pico.picobench.pico-ability-transfer.stage-a.manifest.v1"
            if self.anchor_profile == "pico_policy"
            else SCHEMA
        )

    @property
    def report_schema(self) -> str:
        return (
            "pico.picobench.pico-ability-transfer.stage-a.report.v1"
            if self.anchor_profile == "pico_policy"
            else "pico.picobench.skill-transfer-v2.stage-a.report.v1"
        )

    def manifest(self, corpus: SkillTransferCorpus) -> dict[str, Any]:
        execution = {
            "provider": self.provider,
            "model": self.model,
            "repetitions": self.repetitions,
            "planned_trials": self.planned_trials,
            "seed": self.seed,
            "max_tool_iterations": self.max_tool_iterations,
            "oracle_gate_is_credential_free": True,
            "pico_commit": self.pico_commit,
            "myna_commit": self.myna_commit,
            "pico_wheel_sha256": _sha256(self.pico_wheel),
            "myna_wheel_sha256": _sha256(self.myna_wheel),
        }
        if self.anchor_profile != "generic":
            execution["anchor_profile"] = self.anchor_profile
        arms = {
            "no_skill": "no Skill candidate or Gate call",
            "long_skill": "v1 automatic long Skill with deterministic oracle routing",
            "anchor_skill": "learning-only compact anchor with deterministic oracle routing",
        }
        if self.anchor_profile == "pico_policy":
            arms = {
                "no_skill": "no Skill candidate or Gate call",
                "long_skill": "Myna-derived Pico policy Skill with deterministic Ability routing",
                "anchor_skill": "learning-only Pico Ability card with deterministic Ability routing",
            }
        return {
            "schema": self.manifest_schema,
            "stage": (
                "repository_private_knowledge_upper_bound"
                if self.anchor_profile == "pico_policy"
                else "knowledge_upper_bound"
            ),
            "corpus_digest": corpus.digest,
            "long_skill_receipt_digest": _sha256(self.long_skill_receipt),
            "anchor_projection_digest": canonical_digest(
                {
                    ability.ability_id: anchor_content(ability, profile=self.anchor_profile)
                    for ability in corpus.abilities
                }
            ),
            "arms": arms,
            "execution": execution,
            "analysis": {
                "primary_contrast": "anchor_skill - no_skill",
                "bootstrap_unit": "held_out_instance",
                "bootstrap_samples": self.bootstrap_samples,
                "confidence_level": 0.95,
                "continue_rule": "measurement valid and clustered CI lower bound above zero",
            },
            "budget": {
                "hard_cap_cny": self.hard_cap_cny,
                "maximum_provider_attempts": self.maximum_provider_attempts,
            },
        }


@dataclass(frozen=True)
class StageATrial:
    task_id: str
    ability_id: str
    repetition: int
    arm_id: Literal["no_skill", "long_skill", "anchor_skill"]
    status: str
    workspace_digest: str
    injected_skill_ids: tuple[str, ...]
    gate_status: str | None
    tool_calls: int
    input_tokens: int
    output_tokens: int
    provider_calls: int
    estimated_cost_cny: float
    verification_receipt: dict[str, Any]
    failure_class: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def anchor_content(
    ability: AbilityDefinition,
    *,
    profile: Literal["generic", "pico_policy"] = "generic",
) -> str:
    evidence = "\n".join(f"- {item.result}" for item in ability.learning)
    checks = "\n".join(f"- {item.verification}" for item in ability.learning)
    if profile == "pico_policy":
        return (
            f"## Trigger\n\n{ability.goal}\n\n"
            "## Procedure and boundaries\n\n"
            f"{evidence}\n\n"
            "Apply these repository rules exactly when the current task implements the same Pico contract. "
            "Do not generalize them to a merely similar topic. Preserve the supplied function interface, inspect "
            "the local fixture, edit only solution.py, and treat the task statement and executable verifier as authority.\n\n"
            "## Verification evidence\n\n"
            f"{checks}\n\n"
            "Run smoke.py before finishing. Do not modify smoke.py or create unrelated files."
        )
    if profile != "generic":
        raise ValueError("unsupported Stage A Anchor profile")
    return (
        f"## Use this strategy when\n\n{ability.goal}\n\n"
        "Treat repository code and tests as the authority. Inspect the target implementation before editing, "
        "preserve explicit falsy and failure cases, and make the smallest change that satisfies the requested contract.\n\n"
        f"## Learning evidence\n\n{evidence}\n\n"
        "## Procedure\n\n"
        "1. Read the target function and its callers, then state the exact input, output, and boundary cases.\n"
        "2. Translate the learning evidence above into code without copying names or assumptions that the current repository does not support.\n"
        "3. Add or update focused checks for the happy path and every boundary named in the learning evidence.\n"
        "4. Run the public smoke check and a focused executable check. If evidence conflicts with this strategy, follow the repository evidence.\n\n"
        "## Verification examples from learning\n\n"
        f"{checks}\n\n"
        "Do not modify smoke.py, create unrelated files, or claim success from explanation alone."
    )


def long_content(skill: dict[str, Any]) -> str:
    content = skill["content"]
    sections = [f"## {content['name']}", content["description"]]
    for title, key in (
        ("Applicability", "applicability"),
        ("Procedure", "procedure"),
        ("Verification", "verification"),
        ("Failure avoidance", "failure_avoidance"),
    ):
        sections.append(f"### {title}\n" + "\n".join(f"- {item}" for item in content[key]))
    return "\n\n".join(sections)


def build_report(
    corpus: SkillTransferCorpus,
    trials: tuple[StageATrial, ...],
    *,
    samples: int,
    seed: int,
    schema: str = "pico.picobench.skill-transfer-v2.stage-a.report.v1",
) -> dict[str, Any]:
    expected = {
        (task.instance_id, repetition, arm)
        for ability in corpus.abilities
        for task in ability.held_out
        for repetition in range(2)
        for arm in ARMS
    }
    observed = {(row.task_id, row.repetition, row.arm_id) for row in trials}
    valid = len(observed) == len(trials) and observed == expected
    grouped = {(row.task_id, row.repetition, row.arm_id): row for row in trials}
    anchor_per_task: dict[str, tuple[float, ...]] = {}
    long_per_task: dict[str, tuple[float, ...]] = {}
    for ability in corpus.abilities:
        for task in ability.held_out:
            anchor_deltas = []
            long_deltas = []
            for repetition in range(2):
                no_skill = grouped.get((task.instance_id, repetition, "no_skill"))
                long_skill = grouped.get((task.instance_id, repetition, "long_skill"))
                anchor = grouped.get((task.instance_id, repetition, "anchor_skill"))
                if no_skill is None or long_skill is None or anchor is None:
                    continue
                anchor_deltas.append(float(anchor.passed) - float(no_skill.passed))
                long_deltas.append(float(long_skill.passed) - float(no_skill.passed))
                valid &= (
                    no_skill.ability_id == ability.ability_id
                    and long_skill.ability_id == ability.ability_id
                    and anchor.ability_id == ability.ability_id
                    and no_skill.workspace_digest == long_skill.workspace_digest == anchor.workspace_digest
                    and no_skill.injected_skill_ids == ()
                    and len(long_skill.injected_skill_ids) == 1
                    and len(anchor.injected_skill_ids) == 1
                    and long_skill.gate_status == "selected"
                    and anchor.gate_status == "selected"
                    and no_skill.failure_class not in {"provider", "transport", "budget", "infrastructure"}
                    and long_skill.failure_class not in {"provider", "transport", "budget", "infrastructure"}
                    and anchor.failure_class not in {"provider", "transport", "budget", "infrastructure"}
                )
                for row in (no_skill, long_skill, anchor):
                    receipt = row.verification_receipt
                    valid &= (
                        row.status in {"passed", "task_failed"}
                        and all(
                            value >= 0
                            for value in (
                                row.tool_calls,
                                row.input_tokens,
                                row.output_tokens,
                                row.provider_calls,
                                row.estimated_cost_cny,
                            )
                        )
                        and (
                            not row.passed
                            or (
                                receipt.get("passed") is True
                                and receipt.get("smoke_fixture_unchanged") is True
                                and receipt.get("unexpected_workspace_paths") == []
                            )
                        )
                    )
            if anchor_deltas:
                anchor_per_task[task.instance_id] = tuple(anchor_deltas)
                long_per_task[task.instance_id] = tuple(long_deltas)
    anchor_interval = clustered_bootstrap_interval(anchor_per_task, samples=samples, seed=seed)
    long_interval = clustered_bootstrap_interval(long_per_task, samples=samples, seed=seed)
    passes = {arm: sum(row.passed for row in trials if row.arm_id == arm) for arm in ARMS}
    capability_floor = {}
    for ability in corpus.abilities:
        task_ids = {item.instance_id for item in ability.held_out}
        if not any(
            row.passed for row in trials if row.task_id in task_ids and row.arm_id in {"no_skill", "anchor_skill"}
        ):
            capability_floor[ability.ability_id] = True
    return {
        "schema": schema,
        "ship_complete": observed == expected,
        "measurement_valid": valid and len(anchor_per_task) == 24,
        "trials": len(trials),
        "passes": passes,
        "primary_contrast": {
            "estimate_pp": 100 * anchor_interval.estimate,
            "ci95_pp": [100 * anchor_interval.lower, 100 * anchor_interval.upper],
            "tasks": anchor_interval.tasks,
        },
        "long_skill_contrast": {
            "estimate_pp": 100 * long_interval.estimate,
            "ci95_pp": [100 * long_interval.lower, 100 * long_interval.upper],
            "tasks": long_interval.tasks,
        },
        "capability_floor": capability_floor,
        "continue_to_stage_b": bool(valid and len(anchor_per_task) == 24 and anchor_interval.lower > 0),
    }


class StageAExecutor(InstalledSkillTransferExecutor):
    def __init__(self, config: StageAConfig, *, provider_api_key: str, provider_api_base: str | None) -> None:
        super().__init__(config, provider_api_key=provider_api_key, provider_api_base=provider_api_base)  # type: ignore[arg-type]
        receipt = json.loads(config.long_skill_receipt.read_text(encoding="utf-8"))
        self._long = {row["ability_id"]: row for row in receipt["skills"]}

    def _turn_spec(
        self,
        ability: AbilityDefinition,
        task: HeldOutInstance,
        *,
        repetition: int,
        arm_id: str,
        workspace: Path,
        state: Path,
    ) -> dict[str, Any]:
        spec = super()._turn_spec(
            ability,
            task,
            repetition=repetition,
            arm_id=arm_id,
            workspace=workspace,
            state=state,
        )
        if self._config.anchor_profile == "pico_policy":
            _apply_pico_policy_execution_contract(spec)
        return spec

    def run_stage_a_trial(
        self,
        ability: AbilityDefinition,
        task: HeldOutInstance,
        repetition: int,
        arm_id: str,
    ) -> StageATrial:
        if self._budget_path is None or self._budget_config is None:
            raise ValueError("Stage A budget is not configured")
        root = self._root / "stage-a" / task.instance_id / str(repetition) / arm_id
        workspace = root / "repository"
        workspace.mkdir(parents=True)
        paths = materialize(workspace, task.fixture)
        self._run(("git", "init", "-q"), cwd=workspace)
        fixture_digest = canonical_digest(
            {path: hashlib.sha256((workspace / path).read_bytes()).hexdigest() for path in sorted(paths)}
        )
        smoke_digest = hashlib.sha256((workspace / "smoke.py").read_bytes()).hexdigest()
        spec = self._turn_spec(
            ability,
            task,
            repetition=repetition,
            arm_id=arm_id,
            workspace=workspace,
            state=root / "state",
        )
        expected_id = None
        if arm_id != "no_skill":
            body = (
                long_content(self._long[ability.ability_id])
                if arm_id == "long_skill"
                else anchor_content(ability, profile=self._config.anchor_profile)
            )
            revision = hashlib.sha256(body.encode()).hexdigest()
            expected_id = f"oracle/{arm_id}/{ability.ability_id}@{revision}"
            spec.update(
                {
                    "memory_enabled": True,
                    "skill_forge_enabled": True,
                    "llm_gate_enabled": True,
                    "oracle_gate": True,
                    "oracle_skill": {
                        "qualified_id": expected_id,
                        "name": f"{arm_id}-{ability.ability_id}",
                        "description": ability.goal,
                        "content": body,
                        "revision_id": revision,
                        "source_experience_ids": [item.instance_id for item in ability.learning],
                    },
                }
            )
        else:
            spec.update({"memory_enabled": False, "skill_forge_enabled": False, "llm_gate_enabled": False})
        worker = self._worker_call(
            spec,
            root / "worker",
            environment_overrides={"MYNA_SEMANTIC_API_KEY": "", "PICO_BENCH_PROVIDER_API_KEY": self._provider_api_key},
        )
        receipt = verify_fixture(workspace, task.fixture)
        receipt["smoke_fixture_unchanged"] = (
            hashlib.sha256((workspace / "smoke.py").read_bytes()).hexdigest() == smoke_digest
        )
        observed_paths = {
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
            if path.is_file()
            and not path.is_relative_to(workspace / ".git")
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        }
        receipt["unexpected_workspace_paths"] = sorted(observed_paths - set(paths))
        injected = tuple(str(item) for item in worker.get("injected_skill_ids", ()))
        passed = bool(
            receipt["passed"]
            and receipt["smoke_fixture_unchanged"]
            and not receipt["unexpected_workspace_paths"]
            and worker.get("terminal") == "completed"
            and ((expected_id is None and not injected) or injected == (expected_id,))
        )
        failure = worker.get("failure_class") or (None if passed else "task")
        input_tokens = int(worker.get("input_tokens", 0) or 0)
        output_tokens = int(worker.get("output_tokens", 0) or 0)
        metrics = _tool_metrics(worker.get("tool_events"))
        return StageATrial(
            task_id=task.instance_id,
            ability_id=ability.ability_id,
            repetition=repetition,
            arm_id=arm_id,  # type: ignore[arg-type]
            status="passed" if passed else "task_failed" if failure == "task" else "infrastructure_failure",
            workspace_digest=fixture_digest,
            injected_skill_ids=injected,
            gate_status=worker.get("skill_gate_status"),
            tool_calls=metrics["tool_calls"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            provider_calls=int(worker.get("provider_calls", 0) or 0),
            estimated_cost_cny=self._budget_config.cost_cny(input_tokens, output_tokens),
            verification_receipt=receipt,
            failure_class=failure,
        )


def run(config: StageAConfig, *, approval_digest: str, api_key: str, api_base: str | None) -> dict[str, Any]:
    corpus = load_corpus(config.corpus_path)
    manifest = config.manifest(corpus)
    if canonical_digest(manifest) != approval_digest:
        raise ValueError("Stage A approval digest mismatch")
    output = config.output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    _freeze(output / "manifest.json", manifest)
    base_budget_config = ProviderBudgetConfig(
        hard_cap_cny=config.hard_cap_cny,
        external_service_reserve_cny=0.0,
        max_total_request_attempts=config.maximum_provider_attempts,
        max_input_tokens_per_call=config.max_input_tokens_per_call,
        max_output_tokens_per_call=config.max_output_tokens_per_call,
        input_cache_miss_usd_per_million=config.input_cache_miss_usd_per_million,
        output_usd_per_million=config.output_usd_per_million,
        conservative_usd_to_cny_multiplier=config.conservative_usd_to_cny_multiplier,
    )
    ledger_path = output / "provider-budget.jsonl"
    approval_path = output / "provider-budget-approval.json"
    if approval_path.exists():
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        if approval.get("approval_digest") != approval_digest:
            raise ValueError("Stage A budget approval digest mismatch")
        prefix = approval["ledger_prefix"]
    else:
        if ledger_path.exists() or ledger_path.with_suffix(".high-water.json").exists():
            raise ValueError("Stage A budget evidence exists without approval")
        initial = ProviderBudgetLedger(ledger_path, base_budget_config).snapshot()
        prefix = {
            "event_count": initial.ledger_event_count,
            "digest": initial.ledger_digest,
            "charged_cny": initial.provider_charged_cny,
        }
        _freeze(
            approval_path,
            {
                "schema": "pico.picobench.skill-transfer-v2.stage-a.budget-approval.v1",
                "approval_digest": approval_digest,
                "ledger_prefix": prefix,
            },
        )
    budget_config = ProviderBudgetConfig(
        **{
            **asdict(base_budget_config),
            "approval_digest": approval_digest,
            "ledger_prefix_event_count": int(prefix["event_count"]),
            "ledger_prefix_digest": str(prefix["digest"]),
            "ledger_prefix_charged_cny": float(prefix["charged_cny"]),
        }
    )
    ledger = ProviderBudgetLedger(ledger_path, budget_config)
    records = _journal(output / "raw-outcomes.jsonl")
    with StageAExecutor(config, provider_api_key=api_key, provider_api_base=api_base) as executor:
        executor.configure_budget(ledger.path, budget_config)
        for ability in corpus.abilities:
            for task in ability.held_out:
                for repetition in range(config.repetitions):
                    for arm_id in ARMS:
                        key = (task.instance_id, repetition, arm_id)
                        if key in records:
                            continue
                        row = executor.run_stage_a_trial(ability, task, repetition, arm_id)
                        with (output / "raw-outcomes.jsonl").open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(asdict(row), sort_keys=True) + "\n")
                        records[key] = row
    report = build_report(
        corpus,
        tuple(records[key] for key in sorted(records)),
        samples=config.bootstrap_samples,
        seed=config.seed,
        schema=config.report_schema,
    )
    _write(output / "aggregate.json", report)
    _write(output / "provider-budget-report.json", asdict(ledger.snapshot()))
    verify_artifacts(config)
    return report


def verify_artifacts(config: StageAConfig) -> dict[str, Any]:
    corpus = load_corpus(config.corpus_path)
    output = config.output_root.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    records = _journal(output / "raw-outcomes.jsonl")
    recomputed = build_report(
        corpus,
        tuple(records[key] for key in sorted(records)),
        samples=config.bootstrap_samples,
        seed=config.seed,
        schema=config.report_schema,
    )
    aggregate = json.loads((output / "aggregate.json").read_text(encoding="utf-8"))
    approval = json.loads((output / "provider-budget-approval.json").read_text(encoding="utf-8"))
    prefix = approval["ledger_prefix"]
    budget_config = ProviderBudgetConfig(
        hard_cap_cny=config.hard_cap_cny,
        external_service_reserve_cny=0.0,
        max_total_request_attempts=config.maximum_provider_attempts,
        max_input_tokens_per_call=config.max_input_tokens_per_call,
        max_output_tokens_per_call=config.max_output_tokens_per_call,
        input_cache_miss_usd_per_million=config.input_cache_miss_usd_per_million,
        output_usd_per_million=config.output_usd_per_million,
        conservative_usd_to_cny_multiplier=config.conservative_usd_to_cny_multiplier,
        approval_digest=approval["approval_digest"],
        ledger_prefix_event_count=int(prefix["event_count"]),
        ledger_prefix_digest=str(prefix["digest"]),
        ledger_prefix_charged_cny=float(prefix["charged_cny"]),
    )
    budget = ProviderBudgetLedger(output / "provider-budget.jsonl", budget_config).snapshot()
    recorded_budget = json.loads((output / "provider-budget-report.json").read_text(encoding="utf-8"))
    checks = {
        "manifest_matches_inputs": manifest == config.manifest(corpus),
        "aggregate_recomputed": aggregate == recomputed,
        "all_trials_present": recomputed["ship_complete"] is True,
        "measurement_valid": recomputed["measurement_valid"] is True,
        "budget_recomputed": recorded_budget == asdict(budget),
        "budget_accounting_complete": budget.accounting_complete and budget.open_reservations == 0,
        "budget_within_cap": budget.total_committed_cny <= config.hard_cap_cny,
    }
    report = {
        "schema": "pico.picobench.skill-transfer-v2.stage-a.verifier.v1",
        "passed": all(checks.values()),
        "checks": checks,
        "recomputed_report": recomputed,
    }
    _write(output / "verifier-report.json", report)
    inventory_paths = (
        "manifest.json",
        "provider-budget-approval.json",
        "provider-budget.jsonl",
        "provider-budget.high-water.json",
        "provider-budget-report.json",
        "raw-outcomes.jsonl",
        "aggregate.json",
        "verifier-report.json",
    )
    _write(
        output / "inventory.json",
        {
            "schema": "pico.picobench.skill-transfer-v2.stage-a.inventory.v1",
            "files": [{"path": path, "sha256": _sha256(output / path)} for path in inventory_paths],
        },
    )
    return report


def _journal(path: Path) -> dict[tuple[str, int, str], StageATrial]:
    if not path.exists():
        return {}
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        value["injected_skill_ids"] = tuple(value["injected_skill_ids"])
        row = StageATrial(**value)
        key = (row.task_id, row.repetition, row.arm_id)
        if key in rows:
            raise ValueError(f"duplicate Stage A Trial: {key}")
        rows[key] = row
    return rows


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _freeze(path: Path, value: Any) -> None:
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != value:
        raise ValueError(f"frozen artifact changed: {path.name}")
    if not path.exists():
        _write(path, value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _apply_pico_policy_execution_contract(spec: dict[str, Any]) -> dict[str, Any]:
    spec["prompt"] = (
        f"{spec['prompt']}\n\n"
        "Any selected memory Skill body is already inline under # Skills. Do not search for a Skill file. "
        "Read solution.py and smoke.py, replace the stub in solution.py, run smoke.py, and finish."
    )
    disabled = list(spec.get("disabled_tools", ()))
    if "skill_read" not in disabled:
        disabled.append("skill_read")
    spec["disabled_tools"] = disabled
    return spec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--long-skill-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pico-wheel", type=Path, required=True)
    parser.add_argument("--myna-wheel", type=Path, required=True)
    parser.add_argument("--pico-commit", required=True)
    parser.add_argument("--myna-commit", required=True)
    parser.add_argument("--approval-digest")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--anchor-profile", choices=("generic", "pico_policy"), default="generic")
    parser.add_argument("--hard-cap-cny", type=float, default=3.5)
    parser.add_argument("--max-tool-iterations", type=int, default=5)
    args = parser.parse_args()
    config = StageAConfig(
        corpus_path=args.corpus,
        long_skill_receipt=args.long_skill_receipt,
        output_root=args.output,
        pico_wheel=args.pico_wheel,
        myna_wheel=args.myna_wheel,
        pico_commit=args.pico_commit,
        myna_commit=args.myna_commit,
        anchor_profile=args.anchor_profile,
        hard_cap_cny=args.hard_cap_cny,
        max_tool_iterations=args.max_tool_iterations,
    )
    corpus = load_corpus(config.corpus_path)
    digest = canonical_digest(config.manifest(corpus))
    if args.verify:
        report = verify_artifacts(config)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if not args.run:
        print(json.dumps({"approval_digest": digest, "manifest": config.manifest(corpus)}, indent=2, sort_keys=True))
        return 0
    if not args.approval_digest:
        raise ValueError("--approval-digest is required with --run")
    report = run(
        config,
        approval_digest=args.approval_digest,
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        api_base=os.environ.get("DEEPSEEK_API_BASE"),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
