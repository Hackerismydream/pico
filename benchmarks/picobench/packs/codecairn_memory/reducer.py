from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from benchmarks.picobench.schema import JsonValue

_FORMAL_PACK_ID = "codecairn-memory-effect-v1"
_CALIBRATION_PACK_ID = "codecairn-memory-effect-calibration-v1"
_CONTROL_VARIANT_ID = "memory_off"
_TREATMENT_VARIANT_ID = "codecairn"
_TREATMENT_AXIS = "memory_backend"
_MEASURABLE = {"passed", "task_failed", "task_timeout"}


def reduce_codecairn_memory_claims(
    trial_records: Mapping[Any, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    pair_results: Mapping[Any, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
) -> dict[str, JsonValue]:
    trials = _materialize(trial_records)
    pairs = _materialize(pair_results)
    observed_pack_ids = {
        str(_mapping(record.get("key")).get("pack_id", ""))
        for record in trials
        if str(_mapping(record.get("key")).get("pack_id", "")) in {_FORMAL_PACK_ID, _CALIBRATION_PACK_ID}
    }
    if len(observed_pack_ids) != 1:
        return _invalid_reduction()
    pack_id = next(iter(observed_pack_ids))
    planned_pairs = 16 if pack_id == _FORMAL_PACK_ID else 2
    planned_tasks = 8 if pack_id == _FORMAL_PACK_ID else 2
    minimum_valid_pairs = 15 if pack_id == _FORMAL_PACK_ID else 2
    indexed = {
        (
            str(_mapping(record.get("key")).get("experiment_id", "")),
            str(_mapping(record.get("key")).get("pack_id", "")),
            str(_mapping(record.get("key")).get("task_id", "")),
            int(_mapping(record.get("key")).get("repetition", -1)),
            str(_mapping(record.get("key")).get("variant_id", "")),
        ): record
        for record in trials
        if str(_mapping(record.get("key")).get("pack_id", "")) == pack_id
    }

    valid_pairs = 0
    control_passes = 0
    treatment_passes = 0
    deltas_by_task: dict[str, list[int]] = defaultdict(list)
    losses_by_task: dict[str, int] = defaultdict(int)
    treatment_records: list[Mapping[str, Any]] = []
    control_records: list[Mapping[str, Any]] = []
    control_passes_by_task: dict[str, int] = defaultdict(int)
    treatment_passes_by_task: dict[str, int] = defaultdict(int)
    paired_numeric: dict[str, list[tuple[float, float]]] = defaultdict(
        list,
    )
    variant_axis_valid = True
    pair_identities: set[tuple[str, str, int]] = set()
    for pair in pairs:
        key = _mapping(pair.get("key"))
        if str(key.get("pack_id", "")) != pack_id:
            continue
        if (
            str(key.get("treatment_axis", "")) != _TREATMENT_AXIS
            or str(key.get("control_variant_id", "")) != _CONTROL_VARIANT_ID
            or str(key.get("treatment_variant_id", "")) != _TREATMENT_VARIANT_ID
        ):
            variant_axis_valid = False
            continue
        identity = (
            str(key.get("experiment_id", "")),
            str(key.get("task_id", "")),
            int(key.get("repetition", -1)),
        )
        if identity in pair_identities:
            variant_axis_valid = False
            continue
        pair_identities.add(identity)
        control = indexed.get(
            (
                identity[0],
                pack_id,
                identity[1],
                identity[2],
                _CONTROL_VARIANT_ID,
            )
        )
        treatment = indexed.get(
            (
                identity[0],
                pack_id,
                identity[1],
                identity[2],
                _TREATMENT_VARIANT_ID,
            )
        )
        if control is None or treatment is None:
            continue
        actual_diff = _variant_diff(control, treatment)
        if (
            actual_diff
            != {
                _TREATMENT_AXIS: {
                    "control": None,
                    "treatment": "codecairn",
                }
            }
            or pair.get("actual_variant_diff") != actual_diff
        ):
            variant_axis_valid = False
            continue
        selected = pair.get("selected_block_attempt")
        if (
            pair.get("valid") is not True
            or not isinstance(selected, int)
            or selected < 1
            or control.get("selected_block_attempt") != selected
            or treatment.get("selected_block_attempt") != selected
            or control.get("plan_digest") != pair.get("plan_digest")
            or treatment.get("plan_digest") != pair.get("plan_digest")
            or str(control.get("status")) not in _MEASURABLE
            or str(treatment.get("status")) not in _MEASURABLE
        ):
            continue
        valid_pairs += 1
        control_passed = str(control.get("status")) == "passed"
        treatment_passed = str(treatment.get("status")) == "passed"
        control_passes += int(control_passed)
        treatment_passes += int(treatment_passed)
        delta = int(treatment_passed) - int(control_passed)
        deltas_by_task[identity[1]].append(delta)
        losses_by_task[identity[1]] += int(delta < 0)
        control_passes_by_task[identity[1]] += int(control_passed)
        treatment_passes_by_task[identity[1]] += int(treatment_passed)
        for metric in (
            "runtime.end_to_end_latency_ms",
            "runtime.memory_failures",
            "runtime.repeated_repository_reads",
            "runtime.tool_calls",
            "runtime.tool_failures",
            "usage.main_agent_input_tokens",
            "usage.trial_total_tokens",
        ):
            control_value = _metric_number(
                control,
                metric,
            )
            treatment_value = _metric_number(
                treatment,
                metric,
            )
            if control_value is not None and treatment_value is not None:
                paired_numeric[metric].append(
                    (
                        control_value,
                        treatment_value,
                    )
                )
        control_records.append(control)
        treatment_records.append(treatment)

    every_task_covered = len(deltas_by_task) == planned_tasks and all(
        len(deltas) >= 1 for deltas in deltas_by_task.values()
    )
    measurement_valid = (
        valid_pairs >= minimum_valid_pairs
        and every_task_covered
        and variant_axis_valid
        and all(str(record.get("status")) != "inconclusive" for record in trials)
    )
    ship_complete = (
        len(indexed) == planned_pairs * 2
        and len(pair_identities) == planned_pairs
        and all(str(record.get("status")) for record in indexed.values())
    )
    net_gains = treatment_passes - control_passes
    positive_tasks = sum(sum(deltas) > 0 for deltas in deltas_by_task.values())
    double_regressions = sum(losses >= 2 for losses in losses_by_task.values())

    recall_numerator = sum(_metric_int(record, "codecairn.recall_at_5_numerator") for record in treatment_records)
    recall_denominator = sum(_metric_int(record, "codecairn.recall_at_5_denominator") for record in treatment_records)
    irrelevant = sum(_metric_int(record, "codecairn.irrelevant_injections") for record in treatment_records)
    hard_negatives = sum(_metric_int(record, "codecairn.hard_negative_queries") for record in treatment_records)
    recall_at_5 = recall_numerator / recall_denominator if recall_denominator else None
    irrelevant_rate = irrelevant / hard_negatives if hard_negatives else None
    stale = sum(_metric_int(record, "codecairn.stale_injection_count") for record in treatment_records)
    leakage = sum(_metric_int(record, "codecairn.cross_repository_leakage_count") for record in treatment_records)
    memory_off_calls = sum(_metric_int(record, "codecairn.memory_off_operation_calls") for record in control_records)
    control_evidence = bool(control_records) and all(
        _metric_bool(record, "provider.actual_model_matches")
        and _metric_bool(record, "usage.complete")
        and _metric_bool(record, "cost.complete")
        and _metric_int(
            record,
            "codecairn.memory_off_operation_calls",
        )
        == 0
        and isinstance(
            _mapping(record.get("metrics")).get(
                "codecairn.repository_identity_hash",
            ),
            str,
        )
        for record in control_records
    )
    treatment_evidence = bool(treatment_records) and all(
        _metric_bool(record, "codecairn.production_adapter")
        and _metric_bool(record, "codecairn.fresh_process")
        and _metric_bool(record, "codecairn.profile_evidence_complete")
        and _metric_bool(record, "codecairn.provenance_complete")
        and _metric_bool(record, "codecairn.stale_fixture_complete")
        and _metric_bool(record, "provider.actual_model_matches")
        and _metric_bool(record, "usage.complete")
        and _metric_bool(record, "cost.complete")
        for record in treatment_records
    )
    repository_identity_complete = all(
        _mapping(control.get("metrics")).get(
            "codecairn.repository_identity_hash",
        )
        == _mapping(treatment.get("metrics")).get(
            "codecairn.repository_identity_hash",
        )
        for control, treatment in zip(
            control_records,
            treatment_records,
            strict=True,
        )
    )
    production_evidence = bool(control_evidence and treatment_evidence and repository_identity_complete)
    positive_claim_eligible = bool(
        ship_complete
        and measurement_valid
        and recall_at_5 is not None
        and recall_at_5 >= 0.80
        and irrelevant_rate is not None
        and irrelevant_rate <= 0.05
        and stale == 0
        and leakage == 0
        and memory_off_calls == 0
        and treatment_passes > control_passes
        and net_gains >= 4
        and positive_tasks >= 3
        and double_regressions == 0
        and production_evidence
    )
    control_rate = control_passes / valid_pairs if valid_pairs else None
    treatment_rate = treatment_passes / valid_pairs if valid_pairs else None
    success_delta_pp = (
        (treatment_rate - control_rate) * 100.0 if treatment_rate is not None and control_rate is not None else None
    )
    ci_low, ci_high = _task_clustered_success_ci(
        deltas_by_task,
    )
    control_task_rate = (
        sum(value > 0 for value in control_passes_by_task.values()) / planned_tasks if every_task_covered else None
    )
    treatment_task_rate = (
        sum(value > 0 for value in treatment_passes_by_task.values()) / planned_tasks if every_task_covered else None
    )
    paired_metrics = _paired_metrics(paired_numeric)
    return {
        "codecairn_memory.planned_pairs": planned_pairs,
        "codecairn_memory.valid_pairs": valid_pairs,
        "codecairn_memory.ship_complete": ship_complete,
        "codecairn_memory.measurement_valid": measurement_valid,
        "codecairn_memory.positive_claim_eligible": positive_claim_eligible,
        "codecairn_memory.control_passes": control_passes,
        "codecairn_memory.treatment_passes": treatment_passes,
        "codecairn_memory.control_pass_rate": control_rate,
        "codecairn_memory.treatment_pass_rate": treatment_rate,
        "codecairn_memory.success_delta_pp": success_delta_pp,
        "codecairn_memory.success_delta_ci95_low_pp": ci_low,
        "codecairn_memory.success_delta_ci95_high_pp": ci_high,
        "codecairn_memory.control_task_pass_rate": control_task_rate,
        "codecairn_memory.treatment_task_pass_rate": treatment_task_rate,
        "codecairn_memory.net_verifier_gains": net_gains,
        "codecairn_memory.positive_tasks": positive_tasks,
        "codecairn_memory.tasks_with_two_of_two_regressions": double_regressions,
        "codecairn_memory.recall_at_5": recall_at_5,
        "codecairn_memory.irrelevant_injection_rate": irrelevant_rate,
        "codecairn_memory.stale_injection_count": stale,
        "codecairn_memory.cross_repository_leakage_count": leakage,
        "codecairn_memory.memory_off_operation_calls": memory_off_calls,
        "codecairn_memory.production_evidence_complete": production_evidence,
        **paired_metrics,
    }


def _invalid_reduction() -> dict[str, JsonValue]:
    return {
        "codecairn_memory.planned_pairs": 0,
        "codecairn_memory.valid_pairs": 0,
        "codecairn_memory.ship_complete": False,
        "codecairn_memory.measurement_valid": False,
        "codecairn_memory.positive_claim_eligible": False,
        "codecairn_memory.control_passes": 0,
        "codecairn_memory.treatment_passes": 0,
        "codecairn_memory.control_pass_rate": None,
        "codecairn_memory.treatment_pass_rate": None,
        "codecairn_memory.success_delta_pp": None,
        "codecairn_memory.success_delta_ci95_low_pp": None,
        "codecairn_memory.success_delta_ci95_high_pp": None,
        "codecairn_memory.control_task_pass_rate": None,
        "codecairn_memory.treatment_task_pass_rate": None,
        "codecairn_memory.net_verifier_gains": 0,
        "codecairn_memory.positive_tasks": 0,
        "codecairn_memory.tasks_with_two_of_two_regressions": 0,
        "codecairn_memory.recall_at_5": None,
        "codecairn_memory.irrelevant_injection_rate": None,
        "codecairn_memory.stale_injection_count": 0,
        "codecairn_memory.cross_repository_leakage_count": 0,
        "codecairn_memory.memory_off_operation_calls": 0,
        "codecairn_memory.production_evidence_complete": False,
        "codecairn_memory.main_agent_input_token_delta": None,
        "codecairn_memory.main_agent_input_token_delta_percent": None,
        "codecairn_memory.trial_total_token_delta": None,
        "codecairn_memory.trial_total_token_delta_percent": None,
        "codecairn_memory.latency_delta_ms": None,
        "codecairn_memory.control_p95_latency_ms": None,
        "codecairn_memory.treatment_p95_latency_ms": None,
        "codecairn_memory.tool_call_delta": None,
        "codecairn_memory.tool_failure_delta": None,
        "codecairn_memory.repeated_repository_read_delta": None,
        "codecairn_memory.memory_failure_delta": None,
    }


def _materialize(
    records: Mapping[Any, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return list(records.values()) if isinstance(records, Mapping) else list(records)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _variant_diff(
    control: Mapping[str, Any],
    treatment: Mapping[str, Any],
) -> dict[str, object]:
    control_settings = _mapping(control.get("observed_variant_settings"))
    treatment_settings = _mapping(treatment.get("observed_variant_settings"))
    keys = set(control_settings) | set(treatment_settings)
    return {
        key: {
            "control": control_settings.get(key),
            "treatment": treatment_settings.get(key),
        }
        for key in sorted(keys)
        if control_settings.get(key) != treatment_settings.get(key)
    }


def _metric_int(record: Mapping[str, Any], key: str) -> int:
    value = _mapping(record.get("metrics")).get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _metric_bool(record: Mapping[str, Any], key: str) -> bool:
    return _mapping(record.get("metrics")).get(key) is True


def _metric_number(
    record: Mapping[str, Any],
    key: str,
) -> float | None:
    value = _mapping(record.get("metrics")).get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _task_clustered_success_ci(
    deltas_by_task: Mapping[str, list[int]],
) -> tuple[float | None, float | None]:
    task_ids = sorted(deltas_by_task)
    if not task_ids:
        return None, None
    task_means = [sum(deltas_by_task[task_id]) / len(deltas_by_task[task_id]) for task_id in task_ids]
    generator = random.Random(0)
    estimates = sorted(
        100.0
        * sum(
            task_means[
                generator.randrange(
                    len(task_means),
                )
            ]
            for _ in task_means
        )
        / len(task_means)
        for _ in range(4_096)
    )
    return (
        estimates[int(0.025 * (len(estimates) - 1))],
        estimates[int(0.975 * (len(estimates) - 1))],
    )


def _paired_metrics(
    values: Mapping[str, list[tuple[float, float]]],
) -> dict[str, JsonValue]:
    def mean_delta(metric: str) -> float | None:
        pairs = values.get(metric, [])
        return sum(treatment - control for control, treatment in pairs) / len(pairs) if pairs else None

    def delta_percent(metric: str) -> float | None:
        pairs = values.get(metric, [])
        control = sum(left for left, _ in pairs)
        treatment = sum(right for _, right in pairs)
        return (treatment - control) / control * 100.0 if pairs and control > 0 else None

    def p95(metric: str, index: int) -> float | None:
        observed = sorted(pair[index] for pair in values.get(metric, []))
        if not observed:
            return None
        return observed[
            max(
                0,
                int(0.95 * len(observed) + 0.999999) - 1,
            )
        ]

    return {
        "codecairn_memory.main_agent_input_token_delta": mean_delta(
            "usage.main_agent_input_tokens",
        ),
        "codecairn_memory.main_agent_input_token_delta_percent": delta_percent(
            "usage.main_agent_input_tokens",
        ),
        "codecairn_memory.trial_total_token_delta": mean_delta(
            "usage.trial_total_tokens",
        ),
        "codecairn_memory.trial_total_token_delta_percent": delta_percent(
            "usage.trial_total_tokens",
        ),
        "codecairn_memory.latency_delta_ms": mean_delta(
            "runtime.end_to_end_latency_ms",
        ),
        "codecairn_memory.control_p95_latency_ms": p95(
            "runtime.end_to_end_latency_ms",
            0,
        ),
        "codecairn_memory.treatment_p95_latency_ms": p95(
            "runtime.end_to_end_latency_ms",
            1,
        ),
        "codecairn_memory.tool_call_delta": mean_delta(
            "runtime.tool_calls",
        ),
        "codecairn_memory.tool_failure_delta": mean_delta(
            "runtime.tool_failures",
        ),
        "codecairn_memory.repeated_repository_read_delta": mean_delta(
            "runtime.repeated_repository_reads",
        ),
        "codecairn_memory.memory_failure_delta": mean_delta(
            "runtime.memory_failures",
        ),
    }


__all__ = ["reduce_codecairn_memory_claims"]
