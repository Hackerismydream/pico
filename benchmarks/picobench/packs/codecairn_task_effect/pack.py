from __future__ import annotations

import hashlib
import inspect
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from benchmarks.picobench.canonical import canonical_digest, to_primitive
from benchmarks.picobench.protocol import (
    RetrievalContext,
    RetrievalExecution,
    TrialContext,
    TrialExecution,
)
from benchmarks.picobench.schema import (
    JsonValue,
    PackDefinition,
    PairSpec,
    VariantSpec,
)

from .definitions import (
    load_retrieval_definition,
    load_task_effect_tasks,
    retrieval_definition_digest,
    task_effect_task_set_digest,
)
from .models import (
    RETRIEVAL_SCHEMA,
    TASK_SCHEMA,
    TaskDefinitionKind,
)
from .verifier import task_effect_verifier_code_digest

_FORMAL_PACK_ID = "codecairn-task-effect-v2"
_CALIBRATION_PACK_ID = "codecairn-task-effect-calibration-v2"
_REPORT_TITLE = "PicoBench task-effect v2 Report"
_SCRIPTED_RUNNER_KIND = "codecairn_task_effect_scripted_contract"
_PRODUCTION_ATTESTATION_SCHEMA = "pico.picobench.task-effect-production-adapter.v1"
_TRUSTED_PRODUCTION_ADAPTER_DIGESTS: Mapping[str, str] = MappingProxyType(
    {
        "codecairn_task_effect_installed_real_provider": (
            "e032740997d6e916e4fa6e7fc120de892f0c17a1f34fc77dbc78969a15053330"
        ),
    }
)


class CodeCairnTaskEffectRunner(Protocol):
    kind: str
    identity: Mapping[str, JsonValue]

    async def run_trial(
        self,
        context: TrialContext,
    ) -> TrialExecution: ...

    async def run_retrieval_case(
        self,
        context: RetrievalContext,
    ) -> RetrievalExecution: ...


class CodeCairnTaskEffectPack:
    def __init__(
        self,
        runner: CodeCairnTaskEffectRunner,
        *,
        definition_kind: TaskDefinitionKind | str = TaskDefinitionKind.FORMAL,
    ) -> None:
        self._runner = runner
        self._definition_kind = TaskDefinitionKind(definition_kind)
        self._tasks = load_task_effect_tasks(self._definition_kind)
        self._retrieval = load_retrieval_definition(self._definition_kind)
        self._pack_id = _FORMAL_PACK_ID if self._definition_kind is TaskDefinitionKind.FORMAL else _CALIBRATION_PACK_ID

    def definition(self) -> PackDefinition:
        runner_identity = getattr(
            self._runner,
            "identity",
            {"kind": self._runner.kind},
        )
        implementation_digest = _runner_implementation_digest(
            self._runner,
        )
        production_attestation = trusted_production_adapter_attestation(
            self._runner.kind,
            runner_identity,
            implementation_digest=implementation_digest,
        )
        production_evidence_complete = bool(
            self._definition_kind is TaskDefinitionKind.FORMAL
            and isinstance(runner_identity, Mapping)
            and runner_identity.get("production_evidence_complete") is True
            and production_attestation is not None
        )
        mutation_contracts = tuple(
            {
                "task_id": task.task_id,
                "contract": task.mutation_contract,
            }
            for task in self._tasks
            if task.mutation_contract is not None
        )
        return PackDefinition(
            pack_id=self._pack_id,
            tasks=tuple(task.to_task_spec() for task in self._tasks),
            variants=(
                VariantSpec(
                    variant_id="memory_off",
                    settings={"memory_backend": None},
                ),
                VariantSpec(
                    variant_id="codecairn",
                    settings={"memory_backend": "codecairn"},
                ),
            ),
            pairs=(
                PairSpec(
                    treatment_axis="memory_backend",
                    control_variant_id="memory_off",
                    treatment_variant_id="codecairn",
                ),
            ),
            retrieval_suites=(self._retrieval.to_retrieval_suite_spec(),),
            identity={
                "runner_kind": self._runner.kind,
                "runner_identity": to_primitive(runner_identity),
                "claim_reducer": "codecairn_task_effect_v2",
                "report_title": _REPORT_TITLE,
                "minimum_valid_pairs_per_task": 1,
                "definition_kind": self._definition_kind.value,
                "task_schema": TASK_SCHEMA,
                "retrieval_schema": RETRIEVAL_SCHEMA,
                "task_manifest_digest": task_effect_task_set_digest(self._definition_kind),
                "retrieval_definition_digest": retrieval_definition_digest(self._definition_kind),
                "retrieval_corpus_digest": self._retrieval.corpus_digest,
                "anonymous_retrieval_corpus_ids": sorted(
                    self._retrieval.anonymous_memory_id(memory.memory_id) for memory in self._retrieval.corpus
                ),
                "anonymous_retrieval_corpus_metadata": {
                    self._retrieval.anonymous_memory_id(
                        memory.memory_id,
                    ): {
                        "repository_identity": memory.repository_id,
                        "validity_state": memory.validity.value,
                    }
                    for memory in self._retrieval.corpus
                },
                "retrieval_query_labels_digest": (self._retrieval.query_labels_digest),
                "task_effect_verifier_digest": (task_effect_verifier_code_digest()),
                "parent_owned_mutation_digest": canonical_digest(mutation_contracts),
                "production_adapter_attestation": (production_attestation),
                "production_adapter_attestation_digest": (
                    canonical_digest(production_attestation) if production_attestation is not None else None
                ),
                "production_adapter_implementation_digest": (
                    implementation_digest if production_attestation is not None else None
                ),
                "production_evidence_complete": production_evidence_complete,
            },
        )

    async def run_trial(
        self,
        context: TrialContext,
    ) -> TrialExecution:
        return await self._runner.run_trial(context)

    async def run_retrieval_case(
        self,
        context: RetrievalContext,
    ) -> RetrievalExecution:
        return await self._runner.run_retrieval_case(context)


def create_codecairn_task_effect_pack(
    runner: CodeCairnTaskEffectRunner,
) -> CodeCairnTaskEffectPack:
    return CodeCairnTaskEffectPack(runner)


def create_codecairn_task_effect_calibration_pack(
    runner: CodeCairnTaskEffectRunner,
) -> CodeCairnTaskEffectPack:
    return CodeCairnTaskEffectPack(
        runner,
        definition_kind=TaskDefinitionKind.CALIBRATION,
    )


def create_formal_pack(
    runner: CodeCairnTaskEffectRunner,
) -> CodeCairnTaskEffectPack:
    return create_codecairn_task_effect_pack(runner)


def create_calibration_pack(
    runner: CodeCairnTaskEffectRunner,
) -> CodeCairnTaskEffectPack:
    return create_codecairn_task_effect_calibration_pack(runner)


def trusted_production_adapter_attestation(
    runner_kind: str,
    runner_identity: object,
    *,
    implementation_digest: str | None = None,
) -> dict[str, str] | None:
    if runner_kind == _SCRIPTED_RUNNER_KIND or not isinstance(runner_identity, Mapping):
        return None
    expected_digest = _TRUSTED_PRODUCTION_ADAPTER_DIGESTS.get(
        runner_kind,
    )
    attestation = runner_identity.get(
        "production_adapter_attestation",
    )
    if (
        expected_digest is None
        or not isinstance(attestation, Mapping)
        or set(attestation) != {"schema", "adapter_id", "adapter_digest"}
        or attestation.get("schema") != _PRODUCTION_ATTESTATION_SCHEMA
        or attestation.get("adapter_id") != runner_kind
        or attestation.get("adapter_digest") != expected_digest
        or implementation_digest != expected_digest
    ):
        return None
    return {
        "schema": _PRODUCTION_ATTESTATION_SCHEMA,
        "adapter_id": runner_kind,
        "adapter_digest": expected_digest,
    }


def _runner_implementation_digest(
    runner: object,
) -> str | None:
    source_file = inspect.getsourcefile(type(runner))
    if source_file is None:
        return None
    try:
        return hashlib.sha256(Path(source_file).read_bytes()).hexdigest()
    except OSError:
        return None


__all__ = [
    "CodeCairnTaskEffectPack",
    "CodeCairnTaskEffectRunner",
    "create_calibration_pack",
    "create_codecairn_task_effect_calibration_pack",
    "create_codecairn_task_effect_pack",
    "create_formal_pack",
    "trusted_production_adapter_attestation",
]
