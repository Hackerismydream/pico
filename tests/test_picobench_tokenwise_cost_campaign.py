from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.picobench.packs.tokenwise_cost import (
    CACHE_POLICY_PREFIX_DISRUPTED,
    CACHE_POLICY_PREFIX_STABLE,
)
from benchmarks.picobench.packs.tokenwise_cost.live import (
    CampaignBudget,
    CampaignConfig,
    CampaignError,
    LiveTrialResult,
    build_arm,
    build_campaign_report,
    load_task_corpus,
    rotated_cache_policies,
)
from benchmarks.picobench.packs.tokenwise_cost.runner import (
    TrialArtifact,
    load_deepseek_key,
    run_formal_campaign,
)

CORPUS = Path(__file__).resolve().parents[1] / "benchmarks" / "picobench" / "tasks" / "tokenwise_cost" / "formal.json"


def test_formal_corpus_is_sealed_and_matches_the_frozen_matrix() -> None:
    corpus = load_task_corpus(CORPUS)

    assert corpus.schema == "pico.picobench.tokenwise-cost.tasks.v1"
    assert len(corpus.tasks) == 12
    assert {task.workload_class for task in corpus.tasks} == {
        "stable_dialogue",
        "long_history",
        "tool_accumulation",
        "intra_turn_tool_chain",
    }
    assert all(len(task.expected_outputs) == task.turn_count for task in corpus.tasks)
    assert len(corpus.digest) == 64


@pytest.mark.parametrize(
    ("policy", "strategy_name"),
    [
        (CACHE_POLICY_PREFIX_DISRUPTED, "prefix_disruptor"),
        (CACHE_POLICY_PREFIX_STABLE, None),
    ],
)
def test_build_arm_exposes_only_the_declared_cache_treatment(
    policy: str,
    strategy_name: str | None,
) -> None:
    arm = build_arm(policy)

    assert arm.cache_policy == policy
    assert getattr(arm.strategy, "name", None) == strategy_name


def test_arm_order_rotates_deterministically_without_dropping_policies() -> None:
    orders = [rotated_cache_policies("0" * 64, index) for index in range(2)]

    assert [order[0] for order in orders] == [
        CACHE_POLICY_PREFIX_DISRUPTED,
        CACHE_POLICY_PREFIX_STABLE,
    ]
    assert all(set(order) == set(orders[0]) for order in orders)


def test_campaign_budget_fails_before_the_next_provider_call() -> None:
    budget = CampaignBudget(hard_cap_usd=0.10, max_provider_calls=2)
    budget.record_call(cost_usd=0.04)
    budget.record_call(cost_usd=0.04)

    with pytest.raises(CampaignError, match="provider call ceiling"):
        budget.reserve_call()

    budget = CampaignBudget(hard_cap_usd=0.10, max_provider_calls=5)
    budget.record_call(cost_usd=0.10)

    with pytest.raises(CampaignError, match="cost ceiling"):
        budget.reserve_call()


def test_campaign_report_rebuilds_cv_metrics_from_terminal_trial_records(tmp_path: Path) -> None:
    corpus = load_task_corpus(CORPUS)
    config = CampaignConfig(
        model="deepseek/deepseek-v4-flash",
        repetitions=3,
        hard_cap_usd=2.0,
        output_root=tmp_path,
    )
    costs = {
        CACHE_POLICY_PREFIX_DISRUPTED: 1.0,
        CACHE_POLICY_PREFIX_STABLE: 0.5,
    }
    records: list[LiveTrialResult] = []
    for task in corpus.tasks:
        for repetition in range(3):
            for policy, cost in costs.items():
                records.append(
                    LiveTrialResult(
                        task_id=task.task_id,
                        workload_class=task.workload_class,
                        repetition=repetition,
                        cache_policy=policy,
                        task_passed=True,
                        usage_complete=True,
                        cost_complete=True,
                        requested_model=config.model,
                        actual_model=config.model,
                        fallback_used=False,
                        fresh_input_tokens=1000,
                        cache_write_tokens=0,
                        cache_read_tokens=600 if policy == CACHE_POLICY_PREFIX_STABLE else 0,
                        output_tokens=20,
                        cost_usd=cost,
                        provider_calls=2,
                        latency_ms=10,
                        findings=(),
                    )
                )

    report = build_campaign_report(config=config, corpus=corpus, trials=tuple(records))
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"))

    assert report["claim"]["claim_eligible"] is True
    assert report["claim"]["cv_metrics"]["trial_count"] == 72
    assert report["claim"]["cv_metrics"]["valid_comparison_blocks"] == 36
    assert report["campaign"]["task_corpus_digest"] == corpus.digest
    assert report["campaign"]["price_snapshot"]["cache_miss_usd_per_token"] == 0.14e-6
    assert "generated_at" not in encoded


def test_deepseek_key_preflight_fails_closed_without_a_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(CampaignError, match="DeepSeek credential"):
        load_deepseek_key(config_path=tmp_path / "missing.json")


@pytest.mark.asyncio
async def test_formal_campaign_persists_each_trial_and_rebuilds_on_resume(tmp_path: Path) -> None:
    corpus = load_task_corpus(CORPUS)
    config = CampaignConfig(output_root=tmp_path)
    calls: list[tuple[str, int, str]] = []

    async def fake_trial(task, repetition, arm, **_kwargs):
        calls.append((task.task_id, repetition, arm.cache_policy))
        cost = {
            CACHE_POLICY_PREFIX_DISRUPTED: 1.0,
            CACHE_POLICY_PREFIX_STABLE: 0.5,
        }[arm.cache_policy]
        return TrialArtifact(
            result=LiveTrialResult(
                task_id=task.task_id,
                workload_class=task.workload_class,
                repetition=repetition,
                cache_policy=arm.cache_policy,
                task_passed=True,
                usage_complete=True,
                cost_complete=True,
                requested_model=config.model,
                actual_model=config.model,
                fallback_used=False,
                fresh_input_tokens=1000,
                cache_write_tokens=0,
                cache_read_tokens=600 if arm.cache_policy == CACHE_POLICY_PREFIX_STABLE else 0,
                output_tokens=10,
                cost_usd=cost,
                provider_calls=1,
                latency_ms=1,
                findings=(),
            ),
            provider_calls=(),
            outputs=task.expected_outputs,
        )

    first = await run_formal_campaign(
        config=config,
        corpus=corpus,
        api_key="deepseek-test-key",
        pico_commit="f" * 40,
        trial_executor=fake_trial,
    )
    second = await run_formal_campaign(
        config=config,
        corpus=corpus,
        api_key="deepseek-test-key",
        pico_commit="f" * 40,
        trial_executor=fake_trial,
    )

    assert len(calls) == 72
    assert first == second
    assert first["claim"]["claim_eligible"] is True
    assert len(tuple((tmp_path / "trials").glob("*.json"))) == 72
