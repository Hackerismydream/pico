from __future__ import annotations

from benchmarks.picobench.protocol import TrialContext, TrialExecution
from benchmarks.picobench.records import TrialStatus, VerificationState, VerifierResult
from benchmarks.picobench.schema import PackDefinition, PairSpec, TaskSpec, VariantSpec

from .reducer import (
    CACHE_POLICY_ADAPTIVE_4,
    CACHE_POLICY_NO_EXPLICIT,
    CACHE_POLICY_PROVIDER_AUTO,
    CACHE_POLICY_SYSTEM_AND_3,
)

_WORKLOAD_SHAPES = (
    ("stable_dialogue", 6, 0, 0),
    ("long_history", 6, 16, 0),
    ("tool_accumulation", 6, 0, 1),
    ("intra_turn_tool_chain", 1, 0, 3),
)


class TokenWiseCostPack:
    def definition(self) -> PackDefinition:
        tasks = tuple(
            TaskSpec(
                task_id=f"tw-{workload_class.replace('_', '-')}-{case_index}",
                payload={
                    "workload_class": workload_class,
                    "case_index": case_index,
                    "turn_count": turn_count,
                    "seed_history_turns": seed_history_turns,
                    "expected_tool_calls_per_turn": tool_calls_per_turn,
                    "verifier": "sealed_exact_outcome_v1",
                },
            )
            for workload_class, turn_count, seed_history_turns, tool_calls_per_turn in _WORKLOAD_SHAPES
            for case_index in range(1, 4)
        )
        return PackDefinition(
            pack_id="tokenwise-cost",
            tasks=tasks,
            variants=tuple(
                VariantSpec(variant_id=variant_id, settings={"cache_policy": policy})
                for variant_id, policy in (
                    ("tokenwise-no-explicit-cache", CACHE_POLICY_NO_EXPLICIT),
                    ("tokenwise-provider-auto", CACHE_POLICY_PROVIDER_AUTO),
                    ("tokenwise-system-and-3", CACHE_POLICY_SYSTEM_AND_3),
                    ("tokenwise-adaptive-4", CACHE_POLICY_ADAPTIVE_4),
                )
            ),
            pairs=(
                PairSpec(
                    treatment_axis="cache_policy",
                    control_variant_id="tokenwise-no-explicit-cache",
                    treatment_variant_id="tokenwise-provider-auto",
                ),
                PairSpec(
                    treatment_axis="cache_policy",
                    control_variant_id="tokenwise-no-explicit-cache",
                    treatment_variant_id="tokenwise-system-and-3",
                ),
                PairSpec(
                    treatment_axis="cache_policy",
                    control_variant_id="tokenwise-no-explicit-cache",
                    treatment_variant_id="tokenwise-adaptive-4",
                ),
                PairSpec(
                    treatment_axis="cache_policy",
                    control_variant_id="tokenwise-provider-auto",
                    treatment_variant_id="tokenwise-adaptive-4",
                ),
            ),
            identity={
                "claim_reducer": "tokenwise_cost_v1",
                "workload_classes": [shape[0] for shape in _WORKLOAD_SHAPES],
                "cache_hit_denominator": "fresh_plus_cache_write_plus_cache_read",
                "primary_metric": "cost_per_verified_success_usd",
                "result_scope": "contract_only_until_live_runner_and_frozen_tasks",
            },
        )

    async def run_trial(self, context: TrialContext) -> TrialExecution:
        finding = "tokenwise_cost_live_runner_not_configured"
        return TrialExecution(
            status=TrialStatus.INFRASTRUCTURE_FAILURE,
            runtime_state=None,
            delivery_state=None,
            verification=VerifierResult(
                state=VerificationState.NOT_RUN,
                findings=(finding,),
            ),
            observed_variant_settings=dict(context.variant.settings),
            findings=(finding,),
        )


__all__ = ["TokenWiseCostPack"]
