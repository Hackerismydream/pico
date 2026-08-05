from __future__ import annotations

from pathlib import Path

from benchmarks.picobench.canonical import canonical_digest
from benchmarks.picobench.schema import (
    ExecutionPolicy,
    ExperimentSpec,
)

from .claims import task_effect_claim_rules
from .models import TaskDefinitionKind

_PACK_IDS = {
    TaskDefinitionKind.FORMAL: "codecairn-task-effect-v2",
    TaskDefinitionKind.CALIBRATION: ("codecairn-task-effect-calibration-v2"),
}
_SUITE_IDS = {
    TaskDefinitionKind.FORMAL: ("codecairn-task-effect-v2-stage-a-formal"),
    TaskDefinitionKind.CALIBRATION: ("codecairn-task-effect-v2-stage-a-calibration"),
}


def build_task_effect_experiment_spec(
    output_root: Path,
    *,
    definition_kind: TaskDefinitionKind | str,
) -> ExperimentSpec:
    kind = TaskDefinitionKind(definition_kind)
    claim_rules = task_effect_claim_rules() if kind is TaskDefinitionKind.FORMAL else ()
    return ExperimentSpec(
        suite=_SUITE_IDS[kind],
        repetitions=(2 if kind is TaskDefinitionKind.FORMAL else 1),
        pack_ids=(_PACK_IDS[kind],),
        output_root=Path(output_root),
        identity={
            "stage": "credential_free_stage_a",
            "definition_kind": kind.value,
            "paid_external_calls": 0,
            "provider_calls_allowed": False,
            "network_calls_allowed": False,
            "generic_shell_allowed": False,
            "production_evidence_complete": False,
            "claim_rules_digest": canonical_digest(claim_rules),
            "rebuild_external_calls_allowed": False,
        },
        execution=ExecutionPolicy(
            timeout_seconds=60.0,
            retry_policy="symmetric",
            provider_call_max_attempts=1,
            max_comparison_block_attempts=1,
            max_comparison_block_retries_total=0,
            max_retrieval_query_block_attempts=1,
        ),
        claim_rules=claim_rules,
    )


def build_codecairn_task_effect_formal_spec(
    output_root: Path,
) -> ExperimentSpec:
    return build_task_effect_experiment_spec(
        output_root,
        definition_kind=TaskDefinitionKind.FORMAL,
    )


def build_codecairn_task_effect_calibration_spec(
    output_root: Path,
) -> ExperimentSpec:
    return build_task_effect_experiment_spec(
        output_root,
        definition_kind=TaskDefinitionKind.CALIBRATION,
    )


__all__ = [
    "build_codecairn_task_effect_calibration_spec",
    "build_codecairn_task_effect_formal_spec",
    "build_task_effect_experiment_spec",
]
