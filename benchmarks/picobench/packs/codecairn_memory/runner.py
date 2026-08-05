from __future__ import annotations

from benchmarks.picobench.protocol import TrialContext, TrialExecution
from benchmarks.picobench.records import (
    DeliveryOutcome,
    TrialStatus,
    TurnTerminalState,
    VerificationState,
    VerifierResult,
)


class ScriptedCodeCairnMemoryRunner:
    kind = "codecairn_memory_scripted_contract"

    async def run(self, context: TrialContext) -> TrialExecution:
        treatment = context.variant.settings["memory_backend"] == "codecairn"
        return TrialExecution(
            status=TrialStatus.PASSED if treatment else TrialStatus.TASK_FAILED,
            runtime_state=TurnTerminalState.COMPLETED,
            delivery_state=DeliveryOutcome.DELIVERED,
            verification=VerifierResult(
                state=(VerificationState.PASSED if treatment else VerificationState.FAILED),
            ),
            observed_variant_settings=dict(context.variant.settings),
            metrics={
                "codecairn.memory_off_operation_calls": 0,
                "codecairn.recall_at_5_numerator": int(treatment),
                "codecairn.recall_at_5_denominator": int(treatment),
                "codecairn.irrelevant_injections": 0,
                "codecairn.hard_negative_queries": int(treatment),
                "codecairn.stale_injection_count": 0,
                "codecairn.cross_repository_leakage_count": 0,
                "codecairn.production_adapter": False,
                "codecairn.fresh_process": treatment,
                "codecairn.profile_evidence_complete": True,
                "provider.actual_model_matches": False,
                "usage.complete": True,
                "cost.complete": True,
            },
        )


__all__ = ["ScriptedCodeCairnMemoryRunner"]
