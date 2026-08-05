from __future__ import annotations

from typing import Literal, Protocol

from benchmarks.picobench.canonical import canonical_digest, to_primitive
from benchmarks.picobench.protocol import TrialContext, TrialExecution
from benchmarks.picobench.schema import (
    PackDefinition,
    PairSpec,
    TaskSpec,
    VariantSpec,
)

from .tasks import load_codecairn_memory_tasks

_FORMAL_PACK_ID = "codecairn-memory-effect-v1"
_CALIBRATION_PACK_ID = "codecairn-memory-effect-calibration-v1"


class CodeCairnMemoryRunner(Protocol):
    kind: str

    async def run(self, context: TrialContext) -> TrialExecution: ...


class CodeCairnMemoryPack:
    def __init__(
        self,
        runner: CodeCairnMemoryRunner,
        *,
        definition_kind: Literal["formal", "calibration"] = "formal",
    ) -> None:
        self._runner = runner
        self._definition_kind = definition_kind
        self._tasks = load_codecairn_memory_tasks(definition_kind)
        self._pack_id = _FORMAL_PACK_ID if definition_kind == "formal" else _CALIBRATION_PACK_ID

    def definition(self) -> PackDefinition:
        invariant_settings = {
            "context_strategy": "pico",
            "local_skills": "fixed",
            "tool_surface": ["joint_write_result"],
        }
        runner_identity = getattr(
            self._runner,
            "identity",
            {},
        )
        return PackDefinition(
            pack_id=self._pack_id,
            tasks=tuple(TaskSpec(task_id=task.task_id, payload=to_primitive(task)) for task in self._tasks),
            variants=(
                VariantSpec(
                    variant_id="memory_off",
                    settings={
                        "memory_backend": None,
                        **invariant_settings,
                    },
                ),
                VariantSpec(
                    variant_id="codecairn",
                    settings={
                        "memory_backend": "codecairn",
                        **invariant_settings,
                    },
                ),
            ),
            pairs=(
                PairSpec(
                    treatment_axis="memory_backend",
                    control_variant_id="memory_off",
                    treatment_variant_id="codecairn",
                ),
            ),
            identity={
                "runner_kind": self._runner.kind,
                "claim_reducer": "codecairn_memory_v1",
                "task_schema": "pico.picobench.codecairn-memory-tasks.v1",
                "task_manifest_digest": canonical_digest(self._tasks),
                "installed_adapter_required": True,
                "fresh_process_required": True,
                "semantic_pending_accepted": False,
                "installed_pair": to_primitive(
                    runner_identity,
                ),
            },
        )

    async def run_trial(self, context: TrialContext) -> TrialExecution:
        return await self._runner.run(context)


def create_codecairn_memory_pack(
    runner: CodeCairnMemoryRunner,
) -> CodeCairnMemoryPack:
    return CodeCairnMemoryPack(runner)


def create_codecairn_memory_calibration_pack(
    runner: CodeCairnMemoryRunner,
) -> CodeCairnMemoryPack:
    return CodeCairnMemoryPack(runner, definition_kind="calibration")


__all__ = [
    "CodeCairnMemoryPack",
    "CodeCairnMemoryRunner",
    "create_codecairn_memory_calibration_pack",
    "create_codecairn_memory_pack",
]
