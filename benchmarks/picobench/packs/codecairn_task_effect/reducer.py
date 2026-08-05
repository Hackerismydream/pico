from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from statistics import mean
from typing import Any

from benchmarks.picobench.canonical import canonical_digest
from benchmarks.picobench.schema import JsonValue
from benchmarks.picobench.statistics import (
    BootstrapInterval,
    clustered_bootstrap_interval,
)

from .pack import trusted_production_adapter_attestation

_FORMAL_PACK_ID = "codecairn-task-effect-v2"
_CALIBRATION_PACK_ID = "codecairn-task-effect-calibration-v2"
_CONTROL_VARIANT_ID = "memory_off"
_TREATMENT_VARIANT_ID = "codecairn"
_TREATMENT_AXIS = "memory_backend"
_MEASURABLE_TRIAL_STATUSES = {"passed", "task_failed", "task_timeout"}
_TERMINAL_TRIAL_STATUSES = {
    *_MEASURABLE_TRIAL_STATUSES,
    "provider_failure",
    "infrastructure_failure",
    "cancelled",
    "inconclusive",
}
_TERMINAL_RETRIEVAL_STATUSES = {
    "measurable",
    "provider_failure",
    "infrastructure_failure",
    "cancelled",
    "inconclusive",
}
_POSITIVE_QUERY_CLASSES = {"fact_positive", "experience_positive"}
_QUERY_LABELS = {
    "fact_positive": "positive_repository_fact",
    "experience_positive": "positive_execution_experience",
    "hard_negative": "hard_negative",
    "stale": "stale_or_superseded",
    "cross_repository": "cross_repository",
}
_FORMAL_TASK_CLASS_COUNTS = {
    "fact": 8,
    "experience": 8,
    "stale_conflict": 4,
    "irrelevant": 4,
}
_FORMAL_QUERY_CLASS_COUNTS = {
    "fact_positive": 30,
    "experience_positive": 20,
    "hard_negative": 20,
    "stale": 15,
    "cross_repository": 15,
}
_BOOTSTRAP_SAMPLES = 10_000
_TRIAL_NONNEGATIVE_INT_METRICS = (
    "usage.main_agent_input_tokens",
    "usage.main_agent_output_tokens",
    "usage.trial_total_tokens",
    "runtime.repository_read_calls",
    "runtime.repository_search_calls",
    "runtime.test_calls",
    "runtime.write_calls",
    "runtime.tool_calls",
    "runtime.repeated_repository_reads",
    "codecairn.memory_off_operation_calls",
    "codecairn.memory_hits",
    "codecairn.injected_items",
    "codecairn.abstentions",
    "codecairn.memory_failures",
)
_TRIAL_NONNEGATIVE_NUMBER_METRICS = (
    "runtime.end_to_end_latency_ms",
    "runtime.retrieval_latency_ms",
    "cost.provider_cny",
    "cost.codecairn_cny",
    "cost.total_cny",
)


@dataclass(frozen=True)
class _ManifestContract:
    pack_id: str
    definition_kind: str
    production_evidence_declared: bool
    task_payloads: dict[str, Mapping[str, Any]]
    query_payloads: dict[tuple[str, str], Mapping[str, Any]]
    anonymous_corpus_ids: frozenset[str]
    anonymous_corpus_metadata: dict[str, Mapping[str, str]]
    planned_trial_keys: frozenset[tuple[str, int, str]]
    planned_pair_keys: frozenset[tuple[str, int]]
    planned_retrieval_keys: frozenset[tuple[str, str, str]]
    plan_digest: str


@dataclass(frozen=True)
class _PairObservations:
    valid_pairs: int
    variant_axis_valid: bool
    task_digest_complete: bool
    usage_cost_complete: bool
    memory_off_operation_calls: int
    production_evidence_complete: bool
    control_records: tuple[Mapping[str, Any], ...]
    treatment_records: tuple[Mapping[str, Any], ...]
    pass_deltas: dict[str, tuple[float, ...]]
    control_passes: dict[str, tuple[float, ...]]
    treatment_passes: dict[str, tuple[float, ...]]
    paired_values: dict[str, dict[str, tuple[tuple[float, float], ...]]]


def reduce_task_effect_claims(
    trial_records: Mapping[Any, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    retrieval_records: Mapping[Any, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    pair_results: Mapping[Any, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    *,
    manifest: Mapping[str, Any],
) -> dict[str, JsonValue]:
    contract = _manifest_contract(manifest)
    if contract is None:
        return _invalid_reduction()

    trials = _records_for_pack(trial_records, contract.pack_id)
    pairs = _records_for_pack(pair_results, contract.pack_id)
    retrieval = _records_for_retrieval_suites(
        retrieval_records,
        {suite_id for suite_id, _query_id in contract.query_payloads},
    )
    trial_index, trial_keys_valid = _index_trials(trials)
    pair_index, pair_keys_valid = _index_pairs(pairs)
    retrieval_index, retrieval_keys_valid = _index_retrieval(retrieval)

    exact_trial_denominator = trial_keys_valid and frozenset(trial_index) == contract.planned_trial_keys
    exact_pair_denominator = pair_keys_valid and frozenset(pair_index) == contract.planned_pair_keys
    exact_retrieval_denominator = retrieval_keys_valid and frozenset(retrieval_index) == contract.planned_retrieval_keys
    terminal_records = (
        all(str(record.get("status")) in _TERMINAL_TRIAL_STATUSES for record in trial_index.values())
        and all(str(record.get("status")) in _TERMINAL_RETRIEVAL_STATUSES for record in retrieval_index.values())
        and all(isinstance(record.get("valid"), bool) for record in pair_index.values())
    )
    plan_digests_complete = all(
        record.get("plan_digest") == contract.plan_digest
        for record in (
            *trial_index.values(),
            *pair_index.values(),
            *retrieval_index.values(),
        )
    )
    ship_complete = bool(
        exact_trial_denominator
        and exact_pair_denominator
        and exact_retrieval_denominator
        and terminal_records
        and plan_digests_complete
    )

    pair_observations = _reduce_valid_pairs(
        contract,
        trial_index,
        pair_index,
    )
    (
        trial_digests_complete,
        trial_usage_cost_complete,
        trial_production_evidence,
        memory_off_operation_calls,
    ) = _trial_evidence_state(
        contract,
        trial_index,
    )
    retrieval_metrics, retrieval_valid, retrieval_production = _reduce_retrieval(
        contract,
        retrieval_index,
    )
    retrieval_memory_off_operations = _nonnegative_int(
        retrieval_metrics.get(
            "codecairn_retrieval_v2.retrieval_memory_off_operation_calls",
        )
    )
    if retrieval_memory_off_operations is None:
        retrieval_valid = False
        retrieval_memory_off_operations = 0
    memory_off_operation_calls += retrieval_memory_off_operations
    task_metrics, clustered_complete = _reduce_task_metrics(
        contract,
        pair_observations,
    )
    expected_valid_pairs = math.ceil(
        len(contract.planned_pair_keys) * 0.90,
    )
    covered_tasks = set(pair_observations.pass_deltas)
    task_classes = Counter(str(payload.get("task_class")) for payload in contract.task_payloads.values())
    query_classes = Counter(str(payload.get("query_class")) for payload in contract.query_payloads.values())
    formal_contract_valid = contract.definition_kind != "formal" or (
        contract.pack_id == _FORMAL_PACK_ID
        and len(contract.planned_trial_keys) == 96
        and len(contract.planned_pair_keys) == 48
        and len(contract.planned_retrieval_keys) == 100
        and task_classes == Counter(_FORMAL_TASK_CLASS_COUNTS)
        and query_classes == Counter(_FORMAL_QUERY_CLASS_COUNTS)
    )
    measurement_valid = bool(
        ship_complete
        and formal_contract_valid
        and pair_observations.valid_pairs >= expected_valid_pairs
        and covered_tasks == set(contract.task_payloads)
        and pair_observations.variant_axis_valid
        and trial_digests_complete
        and trial_usage_cost_complete
        and retrieval_valid
        and clustered_complete
    )
    production_evidence_complete = bool(
        contract.production_evidence_declared and trial_production_evidence and retrieval_production
    )

    positive_hit = _number(
        retrieval_metrics.get(
            "codecairn_retrieval_v2.positive_hit_at_5",
        )
    )
    positive_recall = _number(
        retrieval_metrics.get(
            "codecairn_retrieval_v2.positive_recall_at_5",
        )
    )
    injected_precision = _number(
        retrieval_metrics.get(
            "codecairn_retrieval_v2.injected_precision",
        )
    )
    hard_negative_rate = _number(
        retrieval_metrics.get(
            "codecairn_retrieval_v2.hard_negative_any_injection_rate",
        )
    )
    stale_rate = _number(
        retrieval_metrics.get(
            "codecairn_retrieval_v2.stale_any_injection_rate",
        )
    )
    cross_repository_rate = _number(
        retrieval_metrics.get(
            "codecairn_retrieval_v2.cross_repository_any_injection_rate",
        )
    )
    retrieval_claim_eligible = bool(
        contract.definition_kind == "formal"
        and ship_complete
        and measurement_valid
        and production_evidence_complete
        and positive_hit is not None
        and positive_hit >= 0.80
        and positive_recall is not None
        and positive_recall >= 0.80
        and injected_precision is not None
        and injected_precision >= 0.80
        and hard_negative_rate is not None
        and hard_negative_rate <= 0.05
        and stale_rate == 0
        and cross_repository_rate == 0
        and memory_off_operation_calls == 0
    )
    paired_task_delta = _number(
        task_metrics.get(
            "codecairn_task_success_v2.paired_task_pass_delta",
        )
    )
    net_gained_tasks = _number(
        task_metrics.get(
            "codecairn_task_success_v2.net_gained_tasks",
        )
    )
    stale_net_gain = _number(
        task_metrics.get(
            "codecairn_task_success_v2.stale_conflict_net_task_gain",
        )
    )
    irrelevant_net_gain = _number(
        task_metrics.get(
            "codecairn_task_success_v2.irrelevant_net_task_gain",
        )
    )
    task_success_claim_eligible = bool(
        retrieval_claim_eligible
        and paired_task_delta is not None
        and paired_task_delta > 0
        and net_gained_tasks is not None
        and net_gained_tasks >= 3
        and stale_net_gain is not None
        and stale_net_gain >= 0
        and irrelevant_net_gain is not None
        and irrelevant_net_gain >= 0
        and task_metrics.get(
            "codecairn_task_success_v2.clustered_interval_reported",
        )
        == 1
        and task_metrics.get(
            "codecairn_task_success_v2.task_classes_covered",
        )
        == 4
    )
    task_pass_count_delta = _number(
        task_metrics.get(
            "codecairn_efficiency_v2.task_pass_count_delta",
        )
    )
    best_improvement = _number(
        task_metrics.get(
            "codecairn_efficiency_v2.best_rediscovery_improvement_percent",
        )
    )
    efficiency_claim_eligible = bool(
        retrieval_claim_eligible
        and task_pass_count_delta is not None
        and task_pass_count_delta >= -1
        and stale_net_gain is not None
        and stale_net_gain >= 0
        and irrelevant_net_gain is not None
        and irrelevant_net_gain >= 0
        and best_improvement is not None
        and best_improvement >= 15
        and task_metrics.get(
            "codecairn_efficiency_v2.trial_total_token_overhead_reported",
        )
        == 1
        and task_metrics.get(
            "codecairn_efficiency_v2.latency_overhead_reported",
        )
        == 1
        and task_metrics.get(
            "codecairn_efficiency_v2.cost_overhead_reported",
        )
        == 1
        and task_metrics.get(
            "codecairn_efficiency_v2.clustered_interval_reported",
        )
        == 1
    )

    return {
        "codecairn_task_effect_v2.ship_complete": ship_complete,
        "codecairn_task_effect_v2.measurement_valid": measurement_valid,
        "codecairn_task_effect_v2.production_evidence_complete": (production_evidence_complete),
        "codecairn_task_effect_v2.planned_trials": len(
            contract.planned_trial_keys,
        ),
        "codecairn_task_effect_v2.terminal_trials": len(trial_index),
        "codecairn_task_effect_v2.planned_pairs": len(
            contract.planned_pair_keys,
        ),
        "codecairn_task_effect_v2.valid_pairs": (pair_observations.valid_pairs),
        "codecairn_task_effect_v2.planned_retrieval_cases": len(
            contract.planned_retrieval_keys,
        ),
        "codecairn_task_effect_v2.terminal_retrieval_cases": len(
            retrieval_index,
        ),
        "codecairn_task_effect_v2.covered_tasks": len(covered_tasks),
        "codecairn_retrieval_v2.claim_eligible": (retrieval_claim_eligible),
        "codecairn_retrieval_v2.memory_off_operation_calls": (memory_off_operation_calls),
        "codecairn_task_success_v2.claim_eligible": (task_success_claim_eligible),
        "codecairn_efficiency_v2.claim_eligible": (efficiency_claim_eligible),
        **retrieval_metrics,
        **task_metrics,
    }


def _manifest_contract(
    manifest: Mapping[str, Any],
) -> _ManifestContract | None:
    definitions = [
        definition
        for definition in manifest.get("pack_definitions", ())
        if isinstance(definition, Mapping)
        and _mapping(definition.get("identity")).get("claim_reducer") == "codecairn_task_effect_v2"
    ]
    if len(definitions) != 1:
        return None
    definition = definitions[0]
    pack_id = str(definition.get("pack_id", ""))
    if pack_id not in {_FORMAL_PACK_ID, _CALIBRATION_PACK_ID}:
        return None
    identity = _mapping(definition.get("identity"))
    definition_kind = str(identity.get("definition_kind", ""))
    if definition_kind not in {"formal", "calibration"}:
        return None
    anonymous_corpus_ids_raw = identity.get(
        "anonymous_retrieval_corpus_ids",
    )
    if (
        not isinstance(anonymous_corpus_ids_raw, list | tuple)
        or not anonymous_corpus_ids_raw
        or any(not isinstance(item_id, str) or not item_id for item_id in anonymous_corpus_ids_raw)
        or len(set(anonymous_corpus_ids_raw)) != len(anonymous_corpus_ids_raw)
    ):
        return None
    anonymous_corpus_metadata_raw = identity.get(
        "anonymous_retrieval_corpus_metadata",
    )
    if not isinstance(anonymous_corpus_metadata_raw, Mapping):
        return None
    anonymous_corpus_metadata: dict[str, Mapping[str, str]] = {}
    for item_id, raw_metadata in anonymous_corpus_metadata_raw.items():
        if (
            not isinstance(item_id, str)
            or not isinstance(raw_metadata, Mapping)
            or set(raw_metadata) != {"repository_identity", "validity_state"}
            or not isinstance(
                raw_metadata.get("repository_identity"),
                str,
            )
            or not raw_metadata.get("repository_identity")
            or raw_metadata.get("validity_state") not in {"active", "stale", "superseded"}
        ):
            return None
        anonymous_corpus_metadata[item_id] = {
            "repository_identity": str(
                raw_metadata["repository_identity"],
            ),
            "validity_state": str(raw_metadata["validity_state"]),
        }
    if set(anonymous_corpus_metadata) != set(
        anonymous_corpus_ids_raw,
    ):
        return None

    task_payloads: dict[str, Mapping[str, Any]] = {}
    for task in definition.get("tasks", ()):
        if not isinstance(task, Mapping):
            return None
        task_id = task.get("task_id")
        payload = task.get("payload")
        if not isinstance(task_id, str) or task_id in task_payloads or not isinstance(payload, Mapping):
            return None
        task_payloads[task_id] = payload

    query_payloads: dict[tuple[str, str], Mapping[str, Any]] = {}
    for suite in definition.get("retrieval_suites", ()):
        if not isinstance(suite, Mapping):
            return None
        suite_id = suite.get("retrieval_suite_id")
        if not isinstance(suite_id, str):
            return None
        for query in suite.get("queries", ()):
            if not isinstance(query, Mapping):
                return None
            query_id = query.get("query_id")
            payload = query.get("payload")
            if (
                not isinstance(query_id, str)
                or (suite_id, query_id) in query_payloads
                or not isinstance(payload, Mapping)
            ):
                return None
            query_payloads[(suite_id, query_id)] = {
                **payload,
                "label": query.get("label"),
                "expected_item_ids": query.get(
                    "expected_item_ids",
                    (),
                ),
            }

    manifest_spec = _mapping(manifest.get("spec"))
    repetitions = manifest_spec.get("repetitions")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool):
        return None
    planned_trial_keys = frozenset(
        (task_id, repetition, variant_id)
        for task_id in task_payloads
        for repetition in range(repetitions)
        for variant_id in (
            _CONTROL_VARIANT_ID,
            _TREATMENT_VARIANT_ID,
        )
    )
    planned_pair_keys = frozenset(
        (task_id, repetition) for task_id in task_payloads for repetition in range(repetitions)
    )
    planned_retrieval_keys: set[tuple[str, str, str]] = set()
    for suite in definition.get("retrieval_suites", ()):
        if not isinstance(suite, Mapping):
            return None
        suite_id = str(suite.get("retrieval_suite_id"))
        configuration_ids = [
            configuration.get("configuration_id")
            for configuration in suite.get("configurations", ())
            if isinstance(configuration, Mapping)
        ]
        if not configuration_ids or any(
            not isinstance(configuration_id, str) for configuration_id in configuration_ids
        ):
            return None
        for query in suite.get("queries", ()):
            if not isinstance(query, Mapping):
                return None
            query_id = str(query.get("query_id"))
            planned_retrieval_keys.update(
                (suite_id, query_id, str(configuration_id)) for configuration_id in configuration_ids
            )
    plan_digest = manifest.get("plan_digest")
    if not isinstance(plan_digest, str) or not plan_digest:
        return None
    runner_kind = identity.get("runner_kind")
    runner_identity = identity.get("runner_identity")
    attestation = identity.get(
        "production_adapter_attestation",
    )
    implementation_digest = identity.get(
        "production_adapter_implementation_digest",
    )
    trusted_attestation = trusted_production_adapter_attestation(
        str(runner_kind),
        runner_identity,
        implementation_digest=(implementation_digest if isinstance(implementation_digest, str) else None),
    )
    attestation_valid = bool(
        trusted_attestation is not None
        and isinstance(implementation_digest, str)
        and attestation == trusted_attestation
        and identity.get(
            "production_adapter_attestation_digest",
        )
        == canonical_digest(trusted_attestation)
    )
    return _ManifestContract(
        pack_id=pack_id,
        definition_kind=definition_kind,
        production_evidence_declared=bool(
            definition_kind == "formal"
            and identity.get("production_evidence_complete") is True
            and attestation_valid
            and _mapping(manifest_spec.get("identity")).get(
                "production_evidence_complete",
            )
            is True
        ),
        task_payloads=task_payloads,
        query_payloads=query_payloads,
        anonymous_corpus_ids=frozenset(anonymous_corpus_ids_raw),
        anonymous_corpus_metadata=anonymous_corpus_metadata,
        planned_trial_keys=planned_trial_keys,
        planned_pair_keys=planned_pair_keys,
        planned_retrieval_keys=frozenset(planned_retrieval_keys),
        plan_digest=plan_digest,
    )


def _trial_evidence_state(
    contract: _ManifestContract,
    trial_index: Mapping[
        tuple[str, int, str],
        Mapping[str, Any],
    ],
) -> tuple[bool, bool, bool, int]:
    digests_complete = bool(contract.planned_trial_keys)
    usage_cost_complete = bool(contract.planned_trial_keys)
    production_evidence_complete = bool(
        contract.planned_trial_keys,
    )
    memory_off_operation_calls = 0
    for task_id, repetition, variant_id in sorted(
        contract.planned_trial_keys,
    ):
        record = trial_index.get(
            (task_id, repetition, variant_id),
        )
        if record is None:
            digests_complete = False
            usage_cost_complete = False
            production_evidence_complete = False
            continue
        metrics = _mapping(record.get("metrics"))
        payload = contract.task_payloads[task_id]
        mutation = payload.get("parent_owned_mutation")
        mutation_complete = True
        if isinstance(mutation, Mapping):
            mutation_complete = bool(
                metrics.get(
                    "task_effect.parent_owned_setup_complete",
                )
                is True
                and metrics.get(
                    "task_effect.parent_owned_prior_fixture_digest",
                )
                == mutation.get("prior_fixture_digest")
                and metrics.get(
                    "task_effect.evaluated_fixture_digest",
                )
                == mutation.get("evaluated_fixture_digest")
                and metrics.get(
                    "task_effect.parent_owned_mutation_contract_digest",
                )
                == mutation.get("contract_digest")
            )
        digests_complete = bool(
            digests_complete
            and metrics.get("task_effect.fixture_digest") == payload.get("fixture_digest")
            and metrics.get("task_effect.expected_digest") == payload.get("expected_digest")
            and metrics.get("task_effect.verifier_id") == payload.get("verifier")
            and metrics.get("task_effect.fixture_reset_complete") is True
            and mutation_complete
        )
        usage_cost_complete = bool(usage_cost_complete and _trial_usage_cost_metrics_complete(record))
        production_evidence_complete = bool(
            production_evidence_complete
            and metrics.get(
                "task_effect.production_evidence_complete",
            )
            is True
        )
        if variant_id == _CONTROL_VARIANT_ID:
            operations = _metric_int(
                record,
                "codecairn.memory_off_operation_calls",
            )
            if operations != 0:
                usage_cost_complete = False
            else:
                memory_off_operation_calls += operations
    return (
        digests_complete,
        usage_cost_complete,
        production_evidence_complete,
        memory_off_operation_calls,
    )


def _reduce_valid_pairs(
    contract: _ManifestContract,
    trial_index: Mapping[
        tuple[str, int, str],
        Mapping[str, Any],
    ],
    pair_index: Mapping[tuple[str, int], Mapping[str, Any]],
) -> _PairObservations:
    pass_deltas: dict[str, list[float]] = defaultdict(list)
    control_passes: dict[str, list[float]] = defaultdict(list)
    treatment_passes: dict[str, list[float]] = defaultdict(list)
    paired_values: dict[
        str,
        dict[str, list[tuple[float, float]]],
    ] = defaultdict(lambda: defaultdict(list))
    control_records: list[Mapping[str, Any]] = []
    treatment_records: list[Mapping[str, Any]] = []
    variant_axis_valid = True
    task_digest_complete = True
    usage_cost_complete = True
    production_evidence_complete = True
    memory_off_operation_calls = 0
    valid_pairs = 0
    for pair_key in sorted(contract.planned_pair_keys):
        pair = pair_index.get(pair_key)
        if pair is None:
            continue
        task_id, repetition = pair_key
        key = _mapping(pair.get("key"))
        expected_diff = {
            _TREATMENT_AXIS: {
                "control": None,
                "treatment": "codecairn",
            }
        }
        if (
            key.get("treatment_axis") != _TREATMENT_AXIS
            or key.get("control_variant_id") != _CONTROL_VARIANT_ID
            or key.get("treatment_variant_id") != _TREATMENT_VARIANT_ID
            or pair.get("actual_variant_diff") != expected_diff
        ):
            variant_axis_valid = False
            continue
        control = trial_index.get(
            (task_id, repetition, _CONTROL_VARIANT_ID),
        )
        treatment = trial_index.get(
            (task_id, repetition, _TREATMENT_VARIANT_ID),
        )
        selected = pair.get("selected_block_attempt")
        if (
            pair.get("valid") is not True
            or not isinstance(selected, int)
            or isinstance(selected, bool)
            or selected < 1
            or control is None
            or treatment is None
            or control.get("selected_block_attempt") != selected
            or treatment.get("selected_block_attempt") != selected
            or str(control.get("status")) not in _MEASURABLE_TRIAL_STATUSES
            or str(treatment.get("status")) not in _MEASURABLE_TRIAL_STATUSES
            or _mapping(control.get("declared_variant_settings")) != _mapping(control.get("observed_variant_settings"))
            or _mapping(treatment.get("declared_variant_settings"))
            != _mapping(treatment.get("observed_variant_settings"))
        ):
            continue
        valid_pairs += 1
        control_records.append(control)
        treatment_records.append(treatment)
        control_pass = float(control.get("status") == "passed")
        treatment_pass = float(treatment.get("status") == "passed")
        control_passes[task_id].append(control_pass)
        treatment_passes[task_id].append(treatment_pass)
        pass_deltas[task_id].append(treatment_pass - control_pass)

        payload = contract.task_payloads[task_id]
        for record in (control, treatment):
            metrics = _mapping(record.get("metrics"))
            task_digest_complete = bool(
                task_digest_complete
                and metrics.get("task_effect.fixture_digest") == payload.get("fixture_digest")
                and metrics.get("task_effect.expected_digest") == payload.get("expected_digest")
                and metrics.get("task_effect.verifier_id") == payload.get("verifier")
                and (
                    payload.get("parent_owned_mutation") is None
                    or metrics.get(
                        "task_effect.parent_owned_setup_complete",
                    )
                    is True
                )
            )
            usage_cost_complete = bool(usage_cost_complete and _trial_usage_cost_metrics_complete(record))
            production_evidence_complete = bool(
                production_evidence_complete
                and metrics.get(
                    "task_effect.production_evidence_complete",
                )
                is True
            )
        control_operations = _metric_int(
            control,
            "codecairn.memory_off_operation_calls",
        )
        if control_operations != 0:
            usage_cost_complete = False
        else:
            memory_off_operation_calls += control_operations
        _append_paired_values(
            paired_values,
            task_id,
            control,
            treatment,
        )

    return _PairObservations(
        valid_pairs=valid_pairs,
        variant_axis_valid=variant_axis_valid,
        task_digest_complete=task_digest_complete,
        usage_cost_complete=usage_cost_complete,
        memory_off_operation_calls=memory_off_operation_calls,
        production_evidence_complete=bool(control_records and treatment_records and production_evidence_complete),
        control_records=tuple(control_records),
        treatment_records=tuple(treatment_records),
        pass_deltas={task_id: tuple(values) for task_id, values in pass_deltas.items()},
        control_passes={task_id: tuple(values) for task_id, values in control_passes.items()},
        treatment_passes={task_id: tuple(values) for task_id, values in treatment_passes.items()},
        paired_values={
            metric: {task_id: tuple(values) for task_id, values in per_task.items()}
            for metric, per_task in paired_values.items()
        },
    )


def _append_paired_values(
    paired_values: dict[
        str,
        dict[str, list[tuple[float, float]]],
    ],
    task_id: str,
    control: Mapping[str, Any],
    treatment: Mapping[str, Any],
) -> None:
    metrics = {
        "main_agent_input_tokens": ("usage.main_agent_input_tokens",),
        "main_agent_output_tokens": ("usage.main_agent_output_tokens",),
        "trial_total_tokens": ("usage.trial_total_tokens",),
        "repository_read_calls": ("runtime.repository_read_calls",),
        "repository_search_calls": ("runtime.repository_search_calls",),
        "repository_read_search_calls": (
            "runtime.repository_read_calls",
            "runtime.repository_search_calls",
        ),
        "test_calls": ("runtime.test_calls",),
        "write_calls": ("runtime.write_calls",),
        "tool_calls": ("runtime.tool_calls",),
        "repeated_repository_reads": ("runtime.repeated_repository_reads",),
        "end_to_end_latency_ms": ("runtime.end_to_end_latency_ms",),
        "retrieval_latency_ms": ("runtime.retrieval_latency_ms",),
        "total_cost_cny": ("cost.total_cny",),
    }
    for name, keys in metrics.items():
        control_values = [_metric_number(control, key) for key in keys]
        treatment_values = [_metric_number(treatment, key) for key in keys]
        if any(value is None for value in (*control_values, *treatment_values)):
            continue
        paired_values[name][task_id].append(
            (
                sum(value for value in control_values if value is not None),
                sum(value for value in treatment_values if value is not None),
            )
        )


def _reduce_retrieval(
    contract: _ManifestContract,
    records: Mapping[
        tuple[str, str, str],
        Mapping[str, Any],
    ],
) -> tuple[dict[str, JsonValue], bool, bool]:
    positive_hit: list[float] = []
    positive_recall: list[float] = []
    positive_mrr: list[float] = []
    injected_relevant = 0
    injected_total = 0
    hard_negative_queries = 0
    hard_negative_any = 0
    hard_negative_items = 0
    stale_queries = 0
    stale_any = 0
    cross_queries = 0
    cross_any = 0
    retrieval_latencies: list[float] = []
    embedding_calls = 0
    semantic_calls = 0
    reranking_calls = 0
    retrieval_cost_cny = 0.0
    retrieval_memory_off_operation_calls = 0
    class_counts: Counter[str] = Counter()
    structure_valid = True
    usage_cost_complete = True
    production_evidence_complete = True

    for key in sorted(contract.planned_retrieval_keys):
        record = records.get(key)
        if record is None:
            continue
        suite_id, query_id, _configuration_id = key
        payload = contract.query_payloads.get((suite_id, query_id))
        if payload is None:
            structure_valid = False
            continue
        query_class = str(payload.get("query_class", ""))
        query_repository_id = payload.get("repository_id")
        expected_label = _QUERY_LABELS.get(query_class)
        expected = {str(item_id) for item_id in payload.get("expected_item_ids", ())}
        forbidden = {str(item_id) for item_id in payload.get("forbidden_memory_ids", ())}
        ranked_results = record.get("ranked_results")
        injected_results = record.get("injected_results")
        if (
            expected_label is None
            or not isinstance(query_repository_id, str)
            or not query_repository_id
            or record.get("label") != expected_label
            or record.get("expected_item_ids") != list(payload.get("expected_item_ids", ()))
            and record.get("expected_item_ids") != tuple(payload.get("expected_item_ids", ()))
            or not isinstance(ranked_results, list | tuple)
            or not isinstance(injected_results, list | tuple)
            or str(record.get("status")) != "measurable"
        ):
            structure_valid = False
            continue
        ranked_ids, ranked_valid = _result_ids(
            ranked_results,
            require_rank=True,
        )
        injected_ids, injected_valid = _result_ids(
            injected_results,
            require_rank=False,
        )
        structure_valid = bool(structure_valid and ranked_valid and injected_valid)
        structure_valid = bool(
            structure_valid
            and set(ranked_ids).issubset(contract.anonymous_corpus_ids)
            and set(injected_ids).issubset(contract.anonymous_corpus_ids)
            and _result_metadata_matches_corpus(
                ranked_results,
                contract.anonymous_corpus_metadata,
            )
            and _result_metadata_matches_corpus(
                injected_results,
                contract.anonymous_corpus_metadata,
            )
        )
        class_counts[query_class] += 1
        if query_class in _POSITIVE_QUERY_CLASSES:
            top_five = ranked_ids[:5]
            positive_hit.append(float(bool(expected & set(top_five))))
            if expected:
                positive_recall.append(
                    len(expected & set(top_five)) / len(expected),
                )
            else:
                structure_valid = False
            ranks = [index + 1 for index, item_id in enumerate(ranked_ids) if item_id in expected]
            positive_mrr.append(1.0 / min(ranks) if ranks else 0.0)
            injected_relevant += sum(item_id in expected for item_id in injected_ids)
            injected_total += len(injected_ids)
        elif query_class == "hard_negative":
            hard_negative_queries += 1
            hard_negative_any += int(bool(injected_ids))
            hard_negative_items += len(injected_ids)
        elif query_class == "stale":
            stale_queries += 1
            stale_any += int(
                any(
                    _stale_injection_invalid(
                        raw,
                        forbidden_ids=forbidden,
                        repository_id=str(query_repository_id),
                    )
                    for raw in injected_results
                )
            )
        elif query_class == "cross_repository":
            cross_queries += 1
            cross_any += int(
                any(
                    _cross_repository_injection(
                        raw,
                        forbidden_ids=forbidden,
                        repository_id=str(query_repository_id),
                    )
                    for raw in injected_results
                )
            )

        metadata = _mapping(record.get("metadata"))
        abstained = metadata.get("abstained")
        abstention_reason = metadata.get("abstention_reason")
        metadata_memory_off_operations = _nonnegative_int(
            metadata.get("memory_off_operation_calls"),
        )
        metadata_valid = bool(
            metadata.get("query_class") == query_class
            and metadata.get("repository_id") == query_repository_id
            and isinstance(abstained, bool)
            and abstained is (not bool(injected_ids))
            and isinstance(abstention_reason, str)
            and abstention_reason
            == _expected_abstention_reason(
                query_class,
                abstained=bool(abstained),
            )
            and _metadata_ids_equal(
                metadata.get("anonymous_candidate_ids"),
                ranked_ids,
            )
            and _metadata_ids_equal(
                metadata.get("anonymous_injected_ids"),
                injected_ids,
            )
            and metadata_memory_off_operations is not None
        )
        structure_valid = bool(structure_valid and metadata_valid)
        if metadata_memory_off_operations is not None:
            retrieval_memory_off_operation_calls += metadata_memory_off_operations

        usage = _mapping(record.get("usage"))
        latency = _nonnegative_number(
            metadata.get("retrieval_latency_ms"),
        )
        record_embedding_calls = _nonnegative_int(
            usage.get("embedding_calls"),
        )
        record_semantic_calls = _nonnegative_int(
            usage.get("semantic_calls"),
        )
        record_reranking_calls = _nonnegative_int(
            usage.get("reranking_calls"),
        )
        record_cost_cny = _nonnegative_number(usage.get("cost_cny"))
        usage_cost_complete = bool(
            usage_cost_complete
            and usage.get("usage.complete") is True
            and usage.get("cost.complete") is True
            and latency is not None
            and record_embedding_calls is not None
            and record_semantic_calls is not None
            and record_reranking_calls is not None
            and record_cost_cny is not None
        )
        if record_embedding_calls is not None:
            embedding_calls += record_embedding_calls
        if record_semantic_calls is not None:
            semantic_calls += record_semantic_calls
        if record_reranking_calls is not None:
            reranking_calls += record_reranking_calls
        if record_cost_cny is not None:
            retrieval_cost_cny += record_cost_cny
        if latency is not None:
            retrieval_latencies.append(latency)
        production_evidence_complete = bool(
            production_evidence_complete
            and metadata.get(
                "production_evidence_complete",
            )
            is True
        )

    expected_class_counts = Counter(str(payload.get("query_class")) for payload in contract.query_payloads.values())
    coverage_valid = class_counts == expected_class_counts and len(records) == len(contract.planned_retrieval_keys)
    metrics: dict[str, JsonValue] = {
        "codecairn_retrieval_v2.positive_hit_at_5": (mean(positive_hit) if positive_hit else None),
        "codecairn_retrieval_v2.positive_recall_at_5": (mean(positive_recall) if positive_recall else None),
        "codecairn_retrieval_v2.positive_mrr": (mean(positive_mrr) if positive_mrr else None),
        "codecairn_retrieval_v2.injected_precision": (injected_relevant / injected_total if injected_total else 0.0),
        "codecairn_retrieval_v2.hard_negative_any_injection_rate": (
            hard_negative_any / hard_negative_queries if hard_negative_queries else None
        ),
        "codecairn_retrieval_v2.mean_irrelevant_items_per_hard_negative": (
            hard_negative_items / hard_negative_queries if hard_negative_queries else None
        ),
        "codecairn_retrieval_v2.stale_any_injection_rate": (stale_any / stale_queries if stale_queries else None),
        "codecairn_retrieval_v2.cross_repository_any_injection_rate": (
            cross_any / cross_queries if cross_queries else None
        ),
        "codecairn_retrieval_v2.mean_retrieval_latency_ms": (
            mean(retrieval_latencies) if retrieval_latencies else None
        ),
        "codecairn_retrieval_v2.embedding_calls": embedding_calls,
        "codecairn_retrieval_v2.semantic_calls": semantic_calls,
        "codecairn_retrieval_v2.reranking_calls": reranking_calls,
        "codecairn_retrieval_v2.cost_cny": retrieval_cost_cny,
        "codecairn_retrieval_v2.retrieval_memory_off_operation_calls": (retrieval_memory_off_operation_calls),
        "codecairn_retrieval_v2.measurable_cases": sum(
            class_counts.values(),
        ),
    }
    return (
        metrics,
        bool(coverage_valid and structure_valid and usage_cost_complete),
        bool(records and coverage_valid and production_evidence_complete),
    )


def _reduce_task_metrics(
    contract: _ManifestContract,
    observations: _PairObservations,
) -> tuple[dict[str, JsonValue], bool]:
    seed = int(contract.plan_digest[:16], 16)
    pass_interval = _interval(
        observations.pass_deltas,
        seed=seed,
        name="paired_task_pass_delta",
    )
    task_means = {task_id: mean(values) for task_id, values in observations.pass_deltas.items() if values}
    gained_tasks = sum(value > 0 for value in task_means.values())
    regressed_tasks = sum(value < 0 for value in task_means.values())
    class_net_gains: dict[str, int] = {}
    for task_class in {str(payload.get("task_class")) for payload in contract.task_payloads.values()}:
        values = [
            task_means[task_id]
            for task_id, payload in contract.task_payloads.items()
            if payload.get("task_class") == task_class and task_id in task_means
        ]
        class_net_gains[task_class] = sum(value > 0 for value in values) - sum(value < 0 for value in values)

    control_task_passes = sum(
        bool(values) and all(value == 1.0 for value in values) for values in observations.control_passes.values()
    )
    treatment_task_passes = sum(
        bool(values) and all(value == 1.0 for value in values) for values in observations.treatment_passes.values()
    )
    reduction_intervals: dict[str, BootstrapInterval | None] = {}
    for name in (
        "main_agent_input_tokens",
        "repository_read_search_calls",
        "repeated_repository_reads",
    ):
        reduction_intervals[name] = _relative_reduction_interval(
            observations.paired_values.get(name, {}),
            seed=seed
            ^ int(
                canonical_digest(name)[:16],
                16,
            ),
        )
    improvements = {name: interval.estimate for name, interval in reduction_intervals.items() if interval is not None}
    best_name = (
        min(
            (name for name, value in improvements.items() if value == max(improvements.values())),
        )
        if improvements
        else None
    )
    best_interval = reduction_intervals.get(best_name) if best_name is not None else None
    overhead_intervals = {
        name: _delta_interval(
            observations.paired_values.get(name, {}),
            seed=seed
            ^ int(
                canonical_digest(f"overhead:{name}")[:16],
                16,
            ),
        )
        for name in (
            "trial_total_tokens",
            "end_to_end_latency_ms",
            "total_cost_cny",
        )
    }
    effect_intervals = {
        name: _delta_interval(
            observations.paired_values.get(name, {}),
            seed=seed
            ^ int(
                canonical_digest(f"effect:{name}")[:16],
                16,
            ),
        )
        for name in (
            "main_agent_input_tokens",
            "main_agent_output_tokens",
            "repository_read_calls",
            "repository_search_calls",
            "repository_read_search_calls",
            "test_calls",
            "write_calls",
            "tool_calls",
            "repeated_repository_reads",
            "retrieval_latency_ms",
        )
    }
    task_classes_covered = len(
        {contract.task_payloads[task_id].get("task_class") for task_id in observations.pass_deltas}
    )
    required_intervals = (
        pass_interval,
        *effect_intervals.values(),
        *overhead_intervals.values(),
    )
    clustered_complete = bool(
        all(interval is not None for interval in required_intervals)
        and all(
            interval is not None and interval.tasks == len(contract.task_payloads) and interval.unit == "task"
            for interval in required_intervals
        )
    )
    metrics: dict[str, JsonValue] = {
        "codecairn_task_success_v2.paired_task_pass_delta": (
            pass_interval.estimate if pass_interval is not None else None
        ),
        "codecairn_task_success_v2.paired_task_pass_delta_ci95_low": (
            pass_interval.lower if pass_interval is not None else None
        ),
        "codecairn_task_success_v2.paired_task_pass_delta_ci95_high": (
            pass_interval.upper if pass_interval is not None else None
        ),
        "codecairn_task_success_v2.clustered_interval_reported": int(
            pass_interval is not None,
        ),
        "codecairn_task_success_v2.bootstrap_unit": (pass_interval.unit if pass_interval is not None else None),
        "codecairn_task_success_v2.gained_tasks": gained_tasks,
        "codecairn_task_success_v2.regressed_tasks": regressed_tasks,
        "codecairn_task_success_v2.net_gained_tasks": (gained_tasks - regressed_tasks),
        "codecairn_task_success_v2.stale_conflict_net_task_gain": (class_net_gains.get("stale_conflict")),
        "codecairn_task_success_v2.irrelevant_net_task_gain": (class_net_gains.get("irrelevant")),
        "codecairn_task_success_v2.task_classes_covered": (task_classes_covered),
        "codecairn_task_success_v2.control_task_passes": (control_task_passes),
        "codecairn_task_success_v2.treatment_task_passes": (treatment_task_passes),
        "codecairn_efficiency_v2.task_pass_count_delta": (treatment_task_passes - control_task_passes),
        "codecairn_efficiency_v2.stale_conflict_net_task_gain": (class_net_gains.get("stale_conflict")),
        "codecairn_efficiency_v2.irrelevant_net_task_gain": (class_net_gains.get("irrelevant")),
        "codecairn_efficiency_v2.best_rediscovery_metric": best_name,
        "codecairn_efficiency_v2.best_rediscovery_improvement_percent": (
            best_interval.estimate if best_interval is not None else None
        ),
        "codecairn_efficiency_v2.best_rediscovery_ci95_low_percent": (
            best_interval.lower if best_interval is not None else None
        ),
        "codecairn_efficiency_v2.best_rediscovery_ci95_high_percent": (
            best_interval.upper if best_interval is not None else None
        ),
        "codecairn_efficiency_v2.clustered_interval_reported": int(
            best_interval is not None,
        ),
        "codecairn_efficiency_v2.trial_total_token_overhead_reported": int(
            overhead_intervals["trial_total_tokens"] is not None,
        ),
        "codecairn_efficiency_v2.latency_overhead_reported": int(
            overhead_intervals["end_to_end_latency_ms"] is not None,
        ),
        "codecairn_efficiency_v2.cost_overhead_reported": int(
            overhead_intervals["total_cost_cny"] is not None,
        ),
    }
    for name, interval in reduction_intervals.items():
        metrics[f"codecairn_efficiency_v2.{name}_improvement_percent"] = (
            interval.estimate if interval is not None else None
        )
        metrics[f"codecairn_efficiency_v2.{name}_ci95_low_percent"] = interval.lower if interval is not None else None
        metrics[f"codecairn_efficiency_v2.{name}_ci95_high_percent"] = interval.upper if interval is not None else None
        _append_interval_provenance(
            metrics,
            f"codecairn_efficiency_v2.{name}_improvement_percent",
            interval,
        )
    for name, interval in effect_intervals.items():
        metrics[f"codecairn_efficiency_v2.{name}_paired_delta"] = interval.estimate if interval is not None else None
        metrics[f"codecairn_efficiency_v2.{name}_paired_delta_ci95_low"] = (
            interval.lower if interval is not None else None
        )
        metrics[f"codecairn_efficiency_v2.{name}_paired_delta_ci95_high"] = (
            interval.upper if interval is not None else None
        )
        _append_interval_provenance(
            metrics,
            f"codecairn_efficiency_v2.{name}_paired_delta",
            interval,
        )
    for name, interval in overhead_intervals.items():
        metrics[f"codecairn_efficiency_v2.{name}_overhead"] = interval.estimate if interval is not None else None
        metrics[f"codecairn_efficiency_v2.{name}_overhead_ci95_low"] = interval.lower if interval is not None else None
        metrics[f"codecairn_efficiency_v2.{name}_overhead_ci95_high"] = interval.upper if interval is not None else None
        _append_interval_provenance(
            metrics,
            f"codecairn_efficiency_v2.{name}_overhead",
            interval,
        )
    _append_interval_provenance(
        metrics,
        "codecairn_task_success_v2.paired_task_pass_delta",
        pass_interval,
    )
    _append_interval_provenance(
        metrics,
        "codecairn_efficiency_v2.best_rediscovery_improvement_percent",
        best_interval,
    )
    return metrics, clustered_complete


def _append_interval_provenance(
    metrics: dict[str, JsonValue],
    prefix: str,
    interval: BootstrapInterval | None,
) -> None:
    metrics[f"{prefix}_tasks"] = interval.tasks if interval is not None else None
    metrics[f"{prefix}_unit"] = interval.unit if interval is not None else None
    metrics[f"{prefix}_samples"] = interval.samples if interval is not None else None
    metrics[f"{prefix}_seed"] = interval.seed if interval is not None else None


def _relative_reduction_interval(
    per_task_pairs: Mapping[
        str,
        tuple[tuple[float, float], ...],
    ],
    *,
    seed: int,
) -> BootstrapInterval | None:
    reductions = {
        task_id: tuple((1.0 - treatment / control) * 100.0 for control, treatment in pairs if control > 0)
        for task_id, pairs in per_task_pairs.items()
    }
    if not reductions or any(not values for values in reductions.values()):
        return None
    return clustered_bootstrap_interval(
        reductions,
        samples=_BOOTSTRAP_SAMPLES,
        seed=seed,
    )


def _delta_interval(
    per_task_pairs: Mapping[
        str,
        tuple[tuple[float, float], ...],
    ],
    *,
    seed: int,
) -> BootstrapInterval | None:
    deltas = {
        task_id: tuple(treatment - control for control, treatment in pairs) for task_id, pairs in per_task_pairs.items()
    }
    if not deltas or any(not values for values in deltas.values()):
        return None
    return clustered_bootstrap_interval(
        deltas,
        samples=_BOOTSTRAP_SAMPLES,
        seed=seed,
    )


def _interval(
    values: Mapping[str, tuple[float, ...]],
    *,
    seed: int,
    name: str,
) -> BootstrapInterval | None:
    if not values or any(not repetitions for repetitions in values.values()):
        return None
    return clustered_bootstrap_interval(
        dict(values),
        samples=_BOOTSTRAP_SAMPLES,
        seed=seed ^ int(canonical_digest(name)[:16], 16),
    )


def _result_ids(
    results: Iterable[Any],
    *,
    require_rank: bool,
) -> tuple[list[str], bool]:
    item_ids: list[str] = []
    valid = True
    for index, raw in enumerate(results, start=1):
        if not isinstance(raw, Mapping):
            valid = False
            continue
        item_id = raw.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            valid = False
            continue
        if require_rank and raw.get("rank") != index:
            valid = False
        if _number(raw.get("score")) is None:
            valid = False
        if not isinstance(raw.get("source"), str) or not raw.get("source"):
            valid = False
        if not isinstance(raw.get("repository_identity"), str) or not raw.get("repository_identity"):
            valid = False
        if raw.get("validity_state") not in {
            "active",
            "stale",
            "superseded",
        }:
            valid = False
        item_ids.append(item_id)
    if len(item_ids) != len(set(item_ids)):
        valid = False
    return item_ids, valid


def _stale_injection_invalid(
    raw: Any,
    *,
    forbidden_ids: set[str],
    repository_id: str,
) -> bool:
    if not isinstance(raw, Mapping):
        return True
    return bool(
        raw.get("item_id") in forbidden_ids
        or raw.get("validity_state") in {"stale", "superseded"}
        or raw.get("repository_identity") != repository_id
    )


def _result_metadata_matches_corpus(
    results: Iterable[Any],
    corpus_metadata: Mapping[str, Mapping[str, str]],
) -> bool:
    for raw in results:
        if not isinstance(raw, Mapping):
            return False
        canonical = corpus_metadata.get(str(raw.get("item_id", "")))
        if (
            canonical is None
            or raw.get("repository_identity") != canonical["repository_identity"]
            or raw.get("validity_state") != canonical["validity_state"]
        ):
            return False
    return True


def _metadata_ids_equal(
    raw_ids: Any,
    result_ids: list[str],
) -> bool:
    return bool(
        isinstance(raw_ids, list | tuple)
        and all(isinstance(item_id, str) for item_id in raw_ids)
        and tuple(raw_ids) == tuple(result_ids)
    )


def _expected_abstention_reason(
    query_class: str,
    *,
    abstained: bool,
) -> str:
    if not abstained:
        return "not_abstained"
    return {
        "fact_positive": "no_relevant_memory",
        "experience_positive": "no_relevant_memory",
        "hard_negative": "no_relevant_memory",
        "stale": "stale_or_superseded_filtered",
        "cross_repository": "cross_repository_memory_filtered",
    }.get(query_class, "")


def _cross_repository_injection(
    raw: Any,
    *,
    forbidden_ids: set[str],
    repository_id: str,
) -> bool:
    if not isinstance(raw, Mapping):
        return True
    return bool(raw.get("item_id") in forbidden_ids or raw.get("repository_identity") != repository_id)


def _records_for_pack(
    records: Mapping[Any, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    pack_id: str,
) -> list[Mapping[str, Any]]:
    return [record for record in _materialize(records) if _mapping(record.get("key")).get("pack_id") == pack_id]


def _records_for_retrieval_suites(
    records: Mapping[Any, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
    suite_ids: set[str],
) -> list[Mapping[str, Any]]:
    return [
        record for record in _materialize(records) if _mapping(record.get("key")).get("retrieval_suite_id") in suite_ids
    ]


def _index_trials(
    records: Iterable[Mapping[str, Any]],
) -> tuple[
    dict[tuple[str, int, str], Mapping[str, Any]],
    bool,
]:
    indexed: dict[tuple[str, int, str], Mapping[str, Any]] = {}
    valid = True
    for record in records:
        key = _mapping(record.get("key"))
        identity = (
            str(key.get("task_id", "")),
            _int_value(key.get("repetition"), default=-1),
            str(key.get("variant_id", "")),
        )
        if identity in indexed:
            valid = False
        indexed[identity] = record
    return indexed, valid


def _index_pairs(
    records: Iterable[Mapping[str, Any]],
) -> tuple[dict[tuple[str, int], Mapping[str, Any]], bool]:
    indexed: dict[tuple[str, int], Mapping[str, Any]] = {}
    valid = True
    for record in records:
        key = _mapping(record.get("key"))
        identity = (
            str(key.get("task_id", "")),
            _int_value(key.get("repetition"), default=-1),
        )
        if identity in indexed:
            valid = False
        indexed[identity] = record
    return indexed, valid


def _index_retrieval(
    records: Iterable[Mapping[str, Any]],
) -> tuple[
    dict[tuple[str, str, str], Mapping[str, Any]],
    bool,
]:
    indexed: dict[
        tuple[str, str, str],
        Mapping[str, Any],
    ] = {}
    valid = True
    for record in records:
        key = _mapping(record.get("key"))
        identity = (
            str(key.get("retrieval_suite_id", "")),
            str(key.get("query_id", "")),
            str(key.get("configuration_id", "")),
        )
        if identity in indexed:
            valid = False
        indexed[identity] = record
    return indexed, valid


def _invalid_reduction() -> dict[str, JsonValue]:
    return {
        "codecairn_task_effect_v2.ship_complete": False,
        "codecairn_task_effect_v2.measurement_valid": False,
        "codecairn_task_effect_v2.production_evidence_complete": False,
        "codecairn_retrieval_v2.claim_eligible": False,
        "codecairn_task_success_v2.claim_eligible": False,
        "codecairn_efficiency_v2.claim_eligible": False,
        "codecairn_retrieval_v2.positive_hit_at_5": None,
        "codecairn_retrieval_v2.positive_recall_at_5": None,
        "codecairn_retrieval_v2.positive_mrr": None,
        "codecairn_retrieval_v2.injected_precision": None,
        "codecairn_retrieval_v2.hard_negative_any_injection_rate": None,
        "codecairn_retrieval_v2.mean_irrelevant_items_per_hard_negative": None,
        "codecairn_retrieval_v2.stale_any_injection_rate": None,
        "codecairn_retrieval_v2.cross_repository_any_injection_rate": None,
        "codecairn_retrieval_v2.memory_off_operation_calls": 0,
        "codecairn_task_success_v2.paired_task_pass_delta": None,
        "codecairn_task_success_v2.net_gained_tasks": 0,
        "codecairn_efficiency_v2.best_rediscovery_improvement_percent": None,
    }


def _materialize(
    records: Mapping[Any, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return list(records.values()) if isinstance(records, Mapping) else list(records)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _metric_number(
    record: Mapping[str, Any],
    key: str,
) -> float | None:
    return _number(_mapping(record.get("metrics")).get(key))


def _metric_int(
    record: Mapping[str, Any],
    key: str,
) -> int | None:
    value = _mapping(record.get("metrics")).get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _trial_usage_cost_metrics_complete(
    record: Mapping[str, Any],
) -> bool:
    metrics = _mapping(record.get("metrics"))
    return bool(
        metrics.get("usage.complete") is True
        and metrics.get("cost.complete") is True
        and all(_nonnegative_int(metrics.get(key)) is not None for key in _TRIAL_NONNEGATIVE_INT_METRICS)
        and all(_nonnegative_number(metrics.get(key)) is not None for key in _TRIAL_NONNEGATIVE_NUMBER_METRICS)
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _nonnegative_number(value: Any) -> float | None:
    number = _number(value)
    if number is None or number < 0:
        return None
    return number


def _nonnegative_int(value: Any) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _int_value(value: Any, *, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


__all__ = ["reduce_task_effect_claims"]
