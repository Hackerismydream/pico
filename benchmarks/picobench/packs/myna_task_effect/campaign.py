from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from types import MappingProxyType
from typing import Any

from benchmarks.picobench.canonical import canonical_bytes, canonical_digest
from benchmarks.picobench.statistics import clustered_bootstrap_interval
from benchmarks.picobench.verifier import require_normalized_relative_path
from pico.utils.portable_lock import file_lock

TASK_SCHEMA = "pico.picobench.myna-task-effect.tasks.v1"
TASK_CLASSES = frozenset({"fact", "experience", "stale_conflict", "irrelevant"})
_TASK_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_INVENTORY_PATHS = (
    "manifest.json",
    "raw-outcomes.jsonl",
    "aggregate.json",
    "verifier-report.json",
    "claim-eligibility.json",
)


@dataclass(frozen=True)
class ExperimentArm:
    arm_id: str
    settings: Mapping[str, str | None]

    def __hash__(self) -> int:
        return hash(self.arm_id)


ARM_MEMORY_OFF = ExperimentArm(
    arm_id="memory_off",
    settings=MappingProxyType({"memory_backend": None}),
)
ARM_MEMORY_ON = ExperimentArm(
    arm_id="memory_on",
    settings=MappingProxyType({"memory_backend": "myna"}),
)


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    task_class: str
    repository_id: str
    source_path: str
    source_text: str
    memory_text: str
    recall_query: str
    evaluation_prompt: str
    output_path: str
    expected_value: str


@dataclass(frozen=True)
class TaskCorpus:
    schema: str
    definition_kind: str
    tasks: tuple[TaskDefinition, ...]

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True)
class TrialRecord:
    task_id: str
    task_class: str
    repetition: int
    arm_id: str
    status: str
    workspace_digest: str
    repository_reads: int
    tool_calls: int
    memory_hits: int
    myna_operations: tuple[str, ...]
    stale_memory_used: bool = False
    cross_repository_memory: bool = False
    findings: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status == "passed"


@dataclass(frozen=True)
class CampaignConfig:
    corpus_path: Path
    output_root: Path
    pico_wheel: Path
    myna_wheel: Path
    pico_commit: str
    myna_commit: str
    repetitions: int = 3
    seed: int = 20260811

    def __post_init__(self) -> None:
        if self.repetitions < 1:
            raise ValueError("repetitions must be positive")
        for name in ("pico_commit", "myna_commit"):
            value = getattr(self, name)
            if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{name} must be a lowercase full commit SHA")
        for path in (self.corpus_path, self.pico_wheel, self.myna_wheel):
            if not Path(path).is_file():
                raise ValueError(f"campaign input is missing: {Path(path).name}")

    def manifest(self, corpus: TaskCorpus) -> dict[str, Any]:
        return {
            "schema": "pico.picobench.myna-task-effect.manifest.v1",
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
                "repetitions": self.repetitions,
                "seed": self.seed,
                "provider": "deterministic-task-policy-v1",
                "provider_calls_paid": 0,
                "network_provider_calls_allowed": False,
            },
        }


def load_task_corpus(path: Path) -> TaskCorpus:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid Myna task-effect corpus: {path}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != TASK_SCHEMA:
        raise ValueError("unsupported Myna task-effect task schema")
    definition_kind = raw.get("definition_kind")
    if definition_kind not in {"calibration", "formal"}:
        raise ValueError("definition_kind must be calibration or formal")
    rows = raw.get("tasks")
    if not isinstance(rows, list):
        raise ValueError("task corpus requires a task list")
    tasks = tuple(_parse_task(row) for row in rows)
    expected_count = 6 if definition_kind == "calibration" else 24
    if len(tasks) != expected_count:
        raise ValueError(f"{definition_kind} requires exactly {expected_count} tasks")
    ids = tuple(task.task_id for task in tasks)
    if len(set(ids)) != len(ids):
        raise ValueError("task ids must be unique")
    if definition_kind == "formal":
        counts = {task_class: 0 for task_class in TASK_CLASSES}
        for task in tasks:
            counts[task.task_class] += 1
        if set(counts.values()) != {6}:
            raise ValueError("formal corpus requires six tasks per task class")
        if len({task.repository_id for task in tasks}) < 4:
            raise ValueError("formal corpus requires at least four repositories")
    return TaskCorpus(
        schema=TASK_SCHEMA,
        definition_kind=definition_kind,
        tasks=tasks,
    )


def arm_order(
    task_id: str,
    repetition: int,
    *,
    seed: int,
) -> tuple[ExperimentArm, ExperimentArm]:
    if repetition < 0:
        raise ValueError("repetition must not be negative")
    block = hashlib.sha256(f"{seed}:{task_id}".encode()).digest()[0] + repetition
    if block % 2:
        return ARM_MEMORY_ON, ARM_MEMORY_OFF
    return ARM_MEMORY_OFF, ARM_MEMORY_ON


def build_report(
    *,
    corpus: TaskCorpus,
    trials: tuple[TrialRecord, ...],
    repetitions: int,
    bootstrap_samples: int = 2_000,
    bootstrap_seed: int = 20260811,
) -> dict[str, Any]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    task_by_id = {task.task_id: task for task in corpus.tasks}
    grouped: dict[tuple[str, int], dict[str, TrialRecord]] = {}
    duplicate_trials = False
    unknown_trials = False
    for trial in trials:
        if trial.task_id not in task_by_id or trial.task_class != task_by_id[trial.task_id].task_class:
            unknown_trials = True
            continue
        if trial.repetition < 0 or trial.repetition >= repetitions:
            unknown_trials = True
            continue
        by_arm = grouped.setdefault((trial.task_id, trial.repetition), {})
        if trial.arm_id in by_arm:
            duplicate_trials = True
        by_arm[trial.arm_id] = trial

    expected_pairs = len(corpus.tasks) * repetitions
    complete_pairs = 0
    valid_pairs: list[tuple[TrialRecord, TrialRecord]] = []
    lifecycle_complete = True
    axis_valid = not duplicate_trials and not unknown_trials
    expected_lifecycle = (
        "start",
        "recall",
        "recall",
        "store",
        "feedback",
        "stop",
        "start",
        "recall",
        "recall",
        "store",
        "feedback",
        "stop",
    )
    for task in corpus.tasks:
        for repetition in range(repetitions):
            by_arm = grouped.get((task.task_id, repetition), {})
            if set(by_arm) != {ARM_MEMORY_OFF.arm_id, ARM_MEMORY_ON.arm_id}:
                axis_valid = False
                continue
            complete_pairs += 1
            control = by_arm[ARM_MEMORY_OFF.arm_id]
            treatment = by_arm[ARM_MEMORY_ON.arm_id]
            pair_axis_valid = not control.myna_operations and bool(treatment.myna_operations)
            same_workspace = control.workspace_digest == treatment.workspace_digest
            terminal = control.status != "infrastructure_failure" and treatment.status != "infrastructure_failure"
            lifecycle_complete &= treatment.myna_operations == expected_lifecycle
            axis_valid &= pair_axis_valid
            if pair_axis_valid and same_workspace and terminal:
                valid_pairs.append((control, treatment))

    ship_complete = complete_pairs == expected_pairs and len(trials) == expected_pairs * 2
    measurement_valid = bool(ship_complete and axis_valid and len(valid_pairs) == expected_pairs)
    control_passes = sum(control.passed for control, _ in valid_pairs)
    treatment_passes = sum(treatment.passed for _, treatment in valid_pairs)
    denominator = len(valid_pairs)
    pass_delta_pp = 100.0 * (treatment_passes - control_passes) / denominator if denominator else 0.0
    improvements = sum(not control.passed and treatment.passed for control, treatment in valid_pairs)
    regressions = sum(control.passed and not treatment.passed for control, treatment in valid_pairs)

    pass_deltas = _per_task_values(
        valid_pairs,
        lambda control, treatment: float(treatment.passed) - float(control.passed),
    )
    pass_interval = _interval(
        pass_deltas,
        samples=bootstrap_samples,
        seed=bootstrap_seed,
    )
    concordant_passes = tuple(
        (control, treatment)
        for control, treatment in valid_pairs
        if control.passed and treatment.passed and control.repository_reads > 0
    )
    read_reductions = _per_task_values(
        concordant_passes,
        lambda control, treatment: (
            100.0 * (control.repository_reads - treatment.repository_reads) / control.repository_reads
        ),
    )
    read_interval = _interval(
        read_reductions,
        samples=bootstrap_samples,
        seed=bootstrap_seed + 1,
    )
    read_reduction = mean(value for values in read_reductions.values() for value in values) if read_reductions else 0.0
    concordant_coverage = len(concordant_passes) / denominator if denominator else 0.0
    stale_regressions = sum(
        treatment.stale_memory_used and control.passed and not treatment.passed for control, treatment in valid_pairs
    )
    cross_repository_events = sum(treatment.cross_repository_memory for _, treatment in valid_pairs)
    capability_eligible = bool(
        corpus.definition_kind == "formal"
        and measurement_valid
        and lifecycle_complete
        and pass_delta_pp >= 10.0
        and pass_interval is not None
        and pass_interval["lower"] > 0.0
        and stale_regressions == 0
        and cross_repository_events == 0
    )
    efficiency_eligible = bool(
        corpus.definition_kind == "formal"
        and measurement_valid
        and lifecycle_complete
        and pass_interval is not None
        and pass_interval["lower"] >= -0.05
        and concordant_coverage >= 0.80
        and read_reduction >= 20.0
        and read_interval is not None
        and read_interval["lower"] > 0.0
        and stale_regressions == 0
        and cross_repository_events == 0
    )
    return {
        "schema": "pico.picobench.myna-task-effect.report.v1",
        "task_corpus_digest": corpus.digest,
        "definition_kind": corpus.definition_kind,
        "measurement": {
            "planned_pairs": expected_pairs,
            "complete_pairs": complete_pairs,
            "valid_pairs": denominator,
            "axis_valid": axis_valid,
            "lifecycle_complete": lifecycle_complete,
        },
        "capability": {
            "control_passes": control_passes,
            "treatment_passes": treatment_passes,
            "verified_pass_delta_pp": round(pass_delta_pp, 6),
            "memory_induced_improvements": improvements,
            "memory_induced_regressions": regressions,
            "paired_bootstrap_95_ci": pass_interval,
        },
        "efficiency": {
            "concordant_pass_pairs": len(concordant_passes),
            "concordant_pair_coverage": round(concordant_coverage, 6),
            "repository_read_reduction_percent": round(read_reduction, 6),
            "paired_bootstrap_95_ci": read_interval,
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
        },
    }


TrialExecutor = Callable[
    [TaskDefinition, int, ExperimentArm, CampaignConfig],
    TrialRecord,
]


def run_campaign(
    config: CampaignConfig,
    *,
    trial_executor: TrialExecutor,
) -> dict[str, Any]:
    corpus = load_task_corpus(config.corpus_path)
    output = Path(config.output_root)
    output.mkdir(parents=True, exist_ok=True)
    manifest = config.manifest(corpus)
    installed_identity = getattr(trial_executor, "identity", None)
    if isinstance(installed_identity, Mapping):
        manifest = {
            **manifest,
            "installed_identity": dict(installed_identity),
            "installed_identity_digest": canonical_digest(installed_identity),
        }
    with file_lock(output / ".run.lock", blocking=False):
        _freeze_json(output / "manifest.json", manifest)
        _verify_existing_inventory(output)
        records = _read_trial_journal(output / "raw-outcomes.jsonl")
        expected = {
            (task.task_id, repetition, arm.arm_id)
            for task in corpus.tasks
            for repetition in range(config.repetitions)
            for arm in (ARM_MEMORY_OFF, ARM_MEMORY_ON)
        }
        if set(records) - expected:
            raise ValueError("raw outcomes contain trials outside the frozen plan")
        for task in corpus.tasks:
            for repetition in range(config.repetitions):
                for arm in arm_order(task.task_id, repetition, seed=config.seed):
                    key = (task.task_id, repetition, arm.arm_id)
                    if key in records:
                        continue
                    record = trial_executor(task, repetition, arm, config)
                    _validate_trial_record(record, task=task, repetition=repetition, arm=arm)
                    _append_jsonl(output / "raw-outcomes.jsonl", asdict(record))
                    records[key] = record
        ordered = tuple(records[key] for key in sorted(records))
        report = build_report(
            corpus=corpus,
            trials=ordered,
            repetitions=config.repetitions,
        )
        _write_json(output / "aggregate.json", report)
        _write_json(
            output / "verifier-report.json",
            {
                "schema": "pico.picobench.myna-task-effect.verifier.v1",
                "measurement": report["measurement"],
                "safety": report["safety"],
                "passed": report["claim"]["measurement_valid"],
            },
        )
        _write_json(output / "claim-eligibility.json", report["claim"])
        _write_json(
            output / "inventory.json",
            {
                "schema": "pico.picobench.myna-task-effect.inventory.v1",
                "files": [
                    {
                        "path": relative,
                        "sha256": _sha256(output / relative),
                    }
                    for relative in _INVENTORY_PATHS
                ],
            },
        )
        return report


def _validate_trial_record(
    record: TrialRecord,
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
        raise ValueError("trial executor returned a record outside the planned trial")
    if record.status not in {"passed", "task_failed", "infrastructure_failure"}:
        raise ValueError("trial executor returned an unknown status")
    for name in ("repository_reads", "tool_calls", "memory_hits"):
        value = getattr(record, name)
        if isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} must not be negative")


def _read_trial_journal(path: Path) -> dict[tuple[str, int, str], TrialRecord]:
    if not path.exists():
        return {}
    records: dict[tuple[str, int, str], TrialRecord] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            raw = json.loads(line)
            raw["myna_operations"] = tuple(raw.get("myna_operations", ()))
            raw["findings"] = tuple(raw.get("findings", ()))
            record = TrialRecord(**raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid raw outcome at line {line_number}") from exc
        key = (record.task_id, record.repetition, record.arm_id)
        if key in records:
            raise ValueError("raw outcomes contain a duplicate trial")
        records[key] = record
    return records


def _verify_existing_inventory(output: Path) -> None:
    path = output / "inventory.json"
    if not path.exists():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw["files"]
        observed = {row["path"]: row["sha256"] for row in rows}
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("existing evidence inventory is invalid") from exc
    if raw.get("schema") != "pico.picobench.myna-task-effect.inventory.v1":
        raise ValueError("existing evidence inventory schema is invalid")
    if set(observed) != set(_INVENTORY_PATHS) or len(rows) != len(_INVENTORY_PATHS):
        raise ValueError("existing evidence inventory file set is invalid")
    for relative in _INVENTORY_PATHS:
        artifact = output / relative
        if not artifact.is_file() or observed[relative] != _sha256(artifact):
            raise ValueError(f"existing evidence digest changed: {relative}")


def _append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_bytes(value).decode("utf-8") + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _freeze_json(path: Path, value: Any) -> None:
    payload = canonical_bytes(value)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"frozen artifact changed: {path.name}")
        return
    _write_bytes(path, payload)


def _write_json(path: Path, value: Any) -> None:
    _write_bytes(path, canonical_bytes(value))


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Pico x Myna task-effect A/B")
    parser.add_argument("command", choices=("plan", "run", "verify"))
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--pico-wheel", type=Path, required=True)
    parser.add_argument("--myna-wheel", type=Path, required=True)
    parser.add_argument("--pico-commit", required=True)
    parser.add_argument("--myna-commit", required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260811)
    args = parser.parse_args(argv)
    config = CampaignConfig(
        corpus_path=args.corpus,
        output_root=args.output_root,
        pico_wheel=args.pico_wheel,
        myna_wheel=args.myna_wheel,
        pico_commit=args.pico_commit,
        myna_commit=args.myna_commit,
        repetitions=args.repetitions,
        seed=args.seed,
    )
    corpus = load_task_corpus(config.corpus_path)
    if args.command == "plan":
        print(
            json.dumps(
                {
                    "manifest": config.manifest(corpus),
                    "pair_count": len(corpus.tasks) * config.repetitions,
                    "trial_count": len(corpus.tasks) * config.repetitions * 2,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    from .runner import InstalledTrialExecutor

    with InstalledTrialExecutor(config) as executor:
        report = run_campaign(config, trial_executor=executor)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _per_task_values(
    pairs: tuple[tuple[TrialRecord, TrialRecord], ...] | list[tuple[TrialRecord, TrialRecord]],
    metric: Any,
) -> dict[str, tuple[float, ...]]:
    collected: dict[str, list[float]] = {}
    for control, treatment in pairs:
        collected.setdefault(control.task_id, []).append(metric(control, treatment))
    return {task_id: tuple(values) for task_id, values in collected.items()}


def _interval(
    values: dict[str, tuple[float, ...]],
    *,
    samples: int,
    seed: int,
) -> dict[str, float | int] | None:
    if not values:
        return None
    interval = clustered_bootstrap_interval(values, samples=samples, seed=seed)
    return {
        "estimate": round(interval.estimate, 6),
        "lower": round(interval.lower, 6),
        "upper": round(interval.upper, 6),
        "tasks": interval.tasks,
        "samples": interval.samples,
        "seed": interval.seed,
    }


def _parse_task(raw: Any) -> TaskDefinition:
    if not isinstance(raw, dict):
        raise ValueError("task entries must be objects")
    fields = {
        key: _required_str(raw, key)
        for key in (
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
    }
    if fields["task_class"] not in TASK_CLASSES:
        raise ValueError(f"unknown task class: {fields['task_class']}")
    if _TASK_ID.fullmatch(fields["task_id"]) is None:
        raise ValueError("task_id must be a lowercase path-safe identifier")
    fields["repository_id"] = require_normalized_relative_path(
        fields["repository_id"],
        field_name="repository_id",
    )
    fields["source_path"] = require_normalized_relative_path(fields["source_path"], field_name="source_path")
    fields["output_path"] = require_normalized_relative_path(fields["output_path"], field_name="output_path")
    if fields["source_path"] == fields["output_path"]:
        raise ValueError("source and output paths must differ")
    expected = fields["expected_value"]
    if expected in fields["evaluation_prompt"]:
        raise ValueError("evaluation prompt leaks the expected value")
    if expected not in fields["source_text"]:
        raise ValueError("expected value must remain independently discoverable")
    if fields["task_class"] in {"fact", "experience"} and expected not in fields["memory_text"]:
        raise ValueError("positive tasks require useful prior Memory")
    return TaskDefinition(**fields)


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


__all__ = [
    "ARM_MEMORY_OFF",
    "ARM_MEMORY_ON",
    "CampaignConfig",
    "TASK_SCHEMA",
    "ExperimentArm",
    "TaskCorpus",
    "TaskDefinition",
    "TrialRecord",
    "arm_order",
    "build_report",
    "load_task_corpus",
    "run_campaign",
]


if __name__ == "__main__":
    raise SystemExit(main())
