from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from benchmarks.picobench.budget import ProviderBudgetError
from benchmarks.picobench.canonical import canonical_digest
from benchmarks.picobench.packs.myna_task_effect.agent_campaign import (
    AgentCampaignConfig,
    AgentTrialRecord,
    build_agent_report,
    load_agent_task_corpus,
    run_agent_campaign,
    verify_agent_evidence,
)
from benchmarks.picobench.packs.myna_task_effect.campaign import (
    ARM_MEMORY_OFF,
    ARM_MEMORY_ON,
    CampaignConfig,
    TaskCorpus,
    TrialRecord,
    arm_order,
    build_report,
    load_task_corpus,
    run_campaign,
)
from benchmarks.picobench.packs.myna_task_effect.worker import run_turn
from pico.providers.base import LLMProvider, LLMResponse, ToolCallRequest

TASK_ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "picobench" / "tasks" / "myna_task_effect"
MEMORY_OPERATION_SCHEMA = "pico.picobench.myna-agent-task-effect.memory-operation.v2"
AGENT_LIFECYCLE = ("start", "recall", "store", "stop", "start", "recall", "store", "stop")


def test_agent_corpus_is_lightweight_balanced_and_disjoint() -> None:
    agent = load_agent_task_corpus(TASK_ROOT / "agent.json")
    formal = load_task_corpus(TASK_ROOT / "formal.json")

    assert agent.schema == "pico.picobench.myna-agent-task-effect.tasks.v1"
    assert agent.definition_kind == "agent"
    assert len(agent.tasks) == 12
    assert {task.task_class for task in agent.tasks} == {
        "fact",
        "experience",
        "stale_conflict",
        "irrelevant",
    }
    assert all(
        sum(task.task_class == task_class for task in agent.tasks) == 3
        for task_class in {task.task_class for task in agent.tasks}
    )
    assert {task.task_id for task in agent.tasks}.isdisjoint(task.task_id for task in formal.tasks)


def test_agent_corpus_rejects_path_escaping_task_id(tmp_path: Path) -> None:
    raw = json.loads((TASK_ROOT / "agent.json").read_text(encoding="utf-8"))
    raw["tasks"][0]["task_id"] = "../escaped"
    corpus = tmp_path / "agent.json"
    corpus.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="task_id"):
        load_agent_task_corpus(corpus)


def test_agent_plan_freezes_48_trials_and_a_hard_spend_ceiling(tmp_path: Path) -> None:
    pico_wheel = tmp_path / "pico.whl"
    myna_wheel = tmp_path / "myna.whl"
    pico_wheel.write_bytes(b"pico-wheel")
    myna_wheel.write_bytes(b"myna-wheel")
    config = AgentCampaignConfig(
        corpus_path=TASK_ROOT / "agent.json",
        output_root=tmp_path / "evidence",
        pico_wheel=pico_wheel,
        myna_wheel=myna_wheel,
        pico_commit="a" * 40,
        myna_commit="b" * 40,
        provider_name="deepseek",
        model="deepseek/deepseek-v4-flash",
    )

    manifest = config.manifest(load_agent_task_corpus(config.corpus_path))

    assert manifest["schema"] == "pico.picobench.myna-agent-task-effect.manifest.v2"
    assert manifest["execution"]["planned_evaluation_trials"] == 48
    assert manifest["execution"]["repetitions"] == 2
    assert manifest["execution"]["provider_calls_paid"] == "approval_required"
    assert manifest["budget"]["maximum_cost_cny"] <= manifest["budget"]["hard_cap_cny"]
    assert manifest["treatment_axis"] == {
        "control": {"memory_backend": None},
        "treatment": {"memory_backend": "myna"},
    }


def test_agent_campaign_rejects_legacy_unversioned_raw_outcomes(tmp_path: Path) -> None:
    pico_wheel = tmp_path / "pico.whl"
    myna_wheel = tmp_path / "myna.whl"
    pico_wheel.write_bytes(b"pico-wheel")
    myna_wheel.write_bytes(b"myna-wheel")
    config = AgentCampaignConfig(
        corpus_path=TASK_ROOT / "agent.json",
        output_root=tmp_path / "evidence",
        pico_wheel=pico_wheel,
        myna_wheel=myna_wheel,
        pico_commit="a" * 40,
        myna_commit="b" * 40,
        provider_name="deepseek",
        model="deepseek/deepseek-v4-flash",
    )
    config.output_root.mkdir()
    legacy = {
        "task_id": "agent-fact-01",
        "task_class": "fact",
        "repetition": 0,
        "arm_id": "memory_off",
        "status": "passed",
        "workspace_digest": "legacy",
        "tool_calls": 1,
        "input_tokens": 1,
        "output_tokens": 1,
        "provider_calls": 1,
        "memory_hits": 0,
        "myna_operations": [],
    }
    (config.output_root / "raw-outcomes.jsonl").write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    class Executor:
        identity = {"pico": "0.1.7", "myna": "0.1.1"}

        def __call__(self, *args, **kwargs):
            raise AssertionError("legacy evidence must fail before execution")

    approval_digest = canonical_digest(config.manifest(load_agent_task_corpus(config.corpus_path)))
    with pytest.raises(ValueError, match="legacy agent raw outcomes cannot be resumed"):
        run_agent_campaign(
            config,
            approval_digest=approval_digest,
            approved_cny=config.maximum_cost_cny,
            execute_paid=True,
            trial_executor=Executor(),
        )


def test_agent_report_uses_success_tool_calls_and_input_tokens() -> None:
    corpus = load_agent_task_corpus(TASK_ROOT / "agent.json")
    lifecycle = AGENT_LIFECYCLE
    trials: list[AgentTrialRecord] = []
    for task in corpus.tasks:
        for repetition in range(2):
            trials.extend(
                [
                    AgentTrialRecord(
                        task_id=task.task_id,
                        task_class=task.task_class,
                        repetition=repetition,
                        arm_id="memory_off",
                        status="passed",
                        workspace_digest=f"workspace-{task.task_id}-{repetition}",
                        tool_calls=4,
                        input_tokens=2_000,
                        output_tokens=100,
                        provider_calls=3,
                        memory_hits=0,
                        myna_operations=(),
                    ),
                    AgentTrialRecord(
                        task_id=task.task_id,
                        task_class=task.task_class,
                        repetition=repetition,
                        arm_id="memory_on",
                        status="passed",
                        workspace_digest=f"workspace-{task.task_id}-{repetition}",
                        tool_calls=3,
                        input_tokens=1_500,
                        output_tokens=100,
                        provider_calls=2,
                        memory_hits=1,
                        myna_operations=lifecycle,
                    ),
                ]
            )

    report = build_agent_report(
        corpus=corpus,
        trials=tuple(trials),
        repetitions=2,
        require_verification_receipts=False,
    )

    assert report["measurement"]["valid_pairs"] == 24
    assert report["capability"]["verified_pass_delta_pp"] == 0.0
    assert report["efficiency"]["successful_task_tool_call_reduction_percent"] == 25.0
    assert report["efficiency"]["successful_task_input_token_reduction_percent"] == 25.0
    assert report["claim"]["measurement_valid"] is True
    assert report["claim"]["positive_claim_eligible"] is True
    assert report["claim"]["general_agent_claim_eligible"] is False


def test_agent_report_fails_closed_on_stale_or_cross_repository_memory() -> None:
    corpus = load_agent_task_corpus(TASK_ROOT / "agent.json")
    lifecycle = AGENT_LIFECYCLE
    trials: list[AgentTrialRecord] = []
    for task in corpus.tasks:
        trials.extend(
            [
                AgentTrialRecord(
                    task_id=task.task_id,
                    task_class=task.task_class,
                    repetition=0,
                    arm_id="memory_off",
                    status="passed",
                    workspace_digest=f"workspace-{task.task_id}",
                    tool_calls=4,
                    input_tokens=2_000,
                    output_tokens=100,
                    provider_calls=3,
                    memory_hits=0,
                    myna_operations=(),
                ),
                AgentTrialRecord(
                    task_id=task.task_id,
                    task_class=task.task_class,
                    repetition=0,
                    arm_id="memory_on",
                    status="task_failed" if task.task_class == "stale_conflict" else "passed",
                    workspace_digest=f"workspace-{task.task_id}",
                    tool_calls=3,
                    input_tokens=1_500,
                    output_tokens=100,
                    provider_calls=2,
                    memory_hits=1,
                    myna_operations=lifecycle,
                    stale_memory_used=task.task_class == "stale_conflict",
                    cross_repository_memory=task.task_class == "irrelevant",
                ),
            ]
        )

    report = build_agent_report(
        corpus=corpus,
        trials=tuple(trials),
        repetitions=1,
        require_verification_receipts=False,
    )

    assert report["safety"]["stale_memory_caused_regressions"] == 3
    assert report["safety"]["cross_repository_memory_events"] == 3
    assert report["claim"]["positive_claim_eligible"] is False


def test_agent_report_rejects_24_pair_provider_failure_fake_uplift() -> None:
    corpus = load_agent_task_corpus(TASK_ROOT / "agent.json")
    lifecycle = AGENT_LIFECYCLE
    trials: list[AgentTrialRecord] = []
    for task in corpus.tasks:
        for repetition in range(2):
            workspace_digest = f"workspace-{task.task_id}-{repetition}"
            trials.extend(
                [
                    AgentTrialRecord(
                        task_id=task.task_id,
                        task_class=task.task_class,
                        repetition=repetition,
                        arm_id="memory_off",
                        status="provider_failure",
                        failure_class="provider",
                        workspace_digest=workspace_digest,
                        tool_calls=0,
                        input_tokens=0,
                        output_tokens=0,
                        provider_calls=1,
                        memory_hits=0,
                        myna_operations=(),
                    ),
                    AgentTrialRecord(
                        task_id=task.task_id,
                        task_class=task.task_class,
                        repetition=repetition,
                        arm_id="memory_on",
                        status="passed",
                        workspace_digest=workspace_digest,
                        tool_calls=1,
                        input_tokens=100,
                        output_tokens=10,
                        provider_calls=1,
                        memory_hits=1,
                        myna_operations=lifecycle,
                    ),
                ]
            )

    report = build_agent_report(
        corpus=corpus,
        trials=tuple(trials),
        repetitions=2,
        require_verification_receipts=False,
    )

    assert report["claim"]["ship_complete"] is True
    assert report["measurement"]["contaminated_pairs"] == 24
    assert report["measurement"]["valid_pairs"] == 0
    assert report["claim"]["measurement_valid"] is False
    assert report["claim"]["positive_claim_eligible"] is False


def test_agent_report_retains_myna_backend_failure_in_capability_pair() -> None:
    corpus = load_agent_task_corpus(TASK_ROOT / "agent.json")
    task = corpus.tasks[0]
    trials = (
        AgentTrialRecord(
            task_id=task.task_id,
            task_class=task.task_class,
            repetition=0,
            arm_id="memory_off",
            status="passed",
            workspace_digest="workspace",
            tool_calls=2,
            input_tokens=100,
            output_tokens=10,
            provider_calls=1,
            memory_hits=0,
            myna_operations=(),
        ),
        AgentTrialRecord(
            task_id=task.task_id,
            task_class=task.task_class,
            repetition=0,
            arm_id="memory_on",
            status="task_failed",
            failure_class="memory_backend",
            workspace_digest="workspace",
            tool_calls=0,
            input_tokens=0,
            output_tokens=0,
            provider_calls=0,
            memory_hits=0,
            myna_operations=("start", "stop"),
            memory_operation_receipt=(
                {
                    "schema": MEMORY_OPERATION_SCHEMA,
                    "operation": "start",
                    "outcome": "succeeded",
                    "phase": "evaluate",
                },
                {
                    "operation": "recall",
                    "outcome": "failed",
                    "phase": "evaluate",
                    "schema": MEMORY_OPERATION_SCHEMA,
                    "error": {"type": "RuntimeError", "code": "RuntimeError", "message": "failed"},
                },
                {
                    "schema": MEMORY_OPERATION_SCHEMA,
                    "operation": "stop",
                    "outcome": "succeeded",
                    "phase": "evaluate",
                },
            ),
        ),
    )

    report = build_agent_report(
        corpus=TaskCorpus(schema=corpus.schema, definition_kind="agent", tasks=(task,)),
        trials=trials,
        repetitions=1,
        require_verification_receipts=False,
    )

    assert report["measurement"]["contaminated_pairs"] == 0
    assert report["measurement"]["valid_pairs"] == 1
    assert report["capability"]["verified_pass_delta_pp"] == -100.0
    assert report["claim"]["measurement_valid"] is True
    assert report["claim"]["positive_claim_eligible"] is False


def test_agent_report_requires_rebuildable_receipts_for_formal_evidence() -> None:
    corpus = load_agent_task_corpus(TASK_ROOT / "agent.json")
    task = corpus.tasks[0]
    lifecycle = AGENT_LIFECYCLE
    trials = tuple(
        AgentTrialRecord(
            task_id=task.task_id,
            task_class=task.task_class,
            repetition=0,
            arm_id=arm_id,
            status="passed",
            workspace_digest="workspace",
            tool_calls=2,
            input_tokens=100,
            output_tokens=10,
            provider_calls=1,
            memory_hits=int(arm_id == "memory_on"),
            myna_operations=lifecycle if arm_id == "memory_on" else (),
        )
        for arm_id in ("memory_off", "memory_on")
    )

    report = build_agent_report(
        corpus=TaskCorpus(schema=corpus.schema, definition_kind="agent", tasks=(task,)),
        trials=trials,
        repetitions=1,
        require_verification_receipts=True,
    )

    assert report["measurement"]["verification_receipts_valid"] is False
    assert report["measurement"]["memory_operation_receipts_valid"] is False
    assert report["claim"]["measurement_valid"] is False


def test_agent_campaign_requires_approval_persists_and_resumes(tmp_path: Path) -> None:
    pico_wheel = tmp_path / "pico.whl"
    myna_wheel = tmp_path / "myna.whl"
    pico_wheel.write_bytes(b"pico-wheel")
    myna_wheel.write_bytes(b"myna-wheel")
    config = AgentCampaignConfig(
        corpus_path=TASK_ROOT / "agent.json",
        output_root=tmp_path / "evidence",
        pico_wheel=pico_wheel,
        myna_wheel=myna_wheel,
        pico_commit="a" * 40,
        myna_commit="b" * 40,
        provider_name="deepseek",
        model="deepseek/deepseek-v4-flash",
    )
    corpus = load_agent_task_corpus(config.corpus_path)
    approval_digest = canonical_digest(config.manifest(corpus))
    calls: list[tuple[str, int, str]] = []

    class Executor:
        identity = {"pico": "0.1.7", "myna": "0.1.1"}

        def __call__(self, task, repetition, arm, _config):
            calls.append((task.task_id, repetition, arm.arm_id))
            treatment = arm.arm_id == "memory_on"
            operation_receipt = (
                (
                    {"schema": MEMORY_OPERATION_SCHEMA, "operation": "start", "outcome": "succeeded", "phase": "prime"},
                    {
                        "schema": MEMORY_OPERATION_SCHEMA,
                        "operation": "recall",
                        "outcome": "succeeded",
                        "phase": "prime",
                    },
                    {"schema": MEMORY_OPERATION_SCHEMA, "operation": "store", "outcome": "succeeded", "phase": "prime"},
                    {"schema": MEMORY_OPERATION_SCHEMA, "operation": "stop", "outcome": "succeeded", "phase": "prime"},
                    {
                        "schema": MEMORY_OPERATION_SCHEMA,
                        "operation": "start",
                        "outcome": "succeeded",
                        "phase": "evaluate",
                    },
                    {
                        "schema": MEMORY_OPERATION_SCHEMA,
                        "operation": "recall",
                        "outcome": "succeeded",
                        "phase": "evaluate",
                    },
                    {
                        "schema": MEMORY_OPERATION_SCHEMA,
                        "operation": "store",
                        "outcome": "succeeded",
                        "phase": "evaluate",
                    },
                    {
                        "schema": MEMORY_OPERATION_SCHEMA,
                        "operation": "stop",
                        "outcome": "succeeded",
                        "phase": "evaluate",
                    },
                )
                if treatment
                else ()
            )
            return AgentTrialRecord(
                task_id=task.task_id,
                task_class=task.task_class,
                repetition=repetition,
                arm_id=arm.arm_id,
                status="passed",
                workspace_digest=f"workspace-{task.task_id}-{repetition}",
                tool_calls=3 if treatment else 4,
                input_tokens=1_500 if treatment else 2_000,
                output_tokens=100,
                provider_calls=0,
                memory_hits=int(treatment),
                myna_operations=(AGENT_LIFECYCLE if treatment else ()),
                memory_operation_receipt=operation_receipt,
                verification_receipt={
                    "schema": "pico.picobench.myna-agent-task-effect.verification-receipt.v2",
                    "terminal": "completed",
                    "artifact_sha256": "0" * 64,
                    "observed": {"task_id": task.task_id, "value": task.expected_value},
                    "unexpected_workspace_paths": [],
                },
            )

    with pytest.raises(ValueError, match="paid execution approval"):
        run_agent_campaign(
            config,
            approval_digest=approval_digest,
            approved_cny=config.maximum_cost_cny,
            execute_paid=False,
            trial_executor=Executor(),
        )

    first = run_agent_campaign(
        config,
        approval_digest=approval_digest,
        approved_cny=config.maximum_cost_cny,
        execute_paid=True,
        trial_executor=Executor(),
    )
    second = run_agent_campaign(
        config,
        approval_digest=approval_digest,
        approved_cny=config.maximum_cost_cny,
        execute_paid=True,
        trial_executor=Executor(),
    )

    assert first == second
    assert len(calls) == 48
    assert first["claim"]["positive_claim_eligible"] is True
    verification = verify_agent_evidence(config.output_root, corpus_path=config.corpus_path)
    assert verification["passed"] is True
    assert all(verification["gates"].values())

    (config.output_root / "aggregate.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence digest changed"):
        verify_agent_evidence(config.output_root, corpus_path=config.corpus_path)


def test_agent_campaign_rebuild_preserves_provider_failure_contamination(tmp_path: Path) -> None:
    pico_wheel = tmp_path / "pico.whl"
    myna_wheel = tmp_path / "myna.whl"
    pico_wheel.write_bytes(b"pico-wheel")
    myna_wheel.write_bytes(b"myna-wheel")
    config = AgentCampaignConfig(
        corpus_path=TASK_ROOT / "agent.json",
        output_root=tmp_path / "evidence",
        pico_wheel=pico_wheel,
        myna_wheel=myna_wheel,
        pico_commit="a" * 40,
        myna_commit="b" * 40,
        provider_name="deepseek",
        model="deepseek/deepseek-v4-flash",
    )
    calls = 0

    class Executor:
        identity = {"pico": "0.1.7", "myna": "0.1.1"}

        def __call__(self, task, repetition, arm, _config):
            nonlocal calls
            calls += 1
            treatment = arm.arm_id == "memory_on"
            lifecycle = AGENT_LIFECYCLE
            operation_receipt = tuple(
                {
                    "schema": MEMORY_OPERATION_SCHEMA,
                    "operation": operation,
                    "outcome": "succeeded",
                    "phase": phase,
                }
                for phase, operations in (
                    ("prime", ("start", "recall", "store", "stop")),
                    ("evaluate", ("start", "recall", "store", "stop")),
                )
                for operation in operations
            )
            if treatment:
                return AgentTrialRecord(
                    task_id=task.task_id,
                    task_class=task.task_class,
                    repetition=repetition,
                    arm_id=arm.arm_id,
                    status="passed",
                    workspace_digest=f"workspace-{task.task_id}-{repetition}",
                    tool_calls=1,
                    input_tokens=100,
                    output_tokens=10,
                    provider_calls=0,
                    memory_hits=1,
                    myna_operations=lifecycle,
                    memory_operation_receipt=operation_receipt,
                    verification_receipt={
                        "schema": "pico.picobench.myna-agent-task-effect.verification-receipt.v2",
                        "terminal": "completed",
                        "artifact_sha256": "0" * 64,
                        "observed": {"task_id": task.task_id, "value": task.expected_value},
                        "unexpected_workspace_paths": [],
                    },
                )
            failure_receipt = {
                "schema": "pico.picobench.myna-agent-task-effect.failure-receipt.v2",
                "failure_class": "provider",
                "phase": "provider_call",
                "error": {
                    "code": "ProviderError",
                    "message": "provider unavailable",
                    "type": "ProviderError",
                },
            }
            return AgentTrialRecord(
                task_id=task.task_id,
                task_class=task.task_class,
                repetition=repetition,
                arm_id=arm.arm_id,
                status="provider_failure",
                failure_class="provider",
                failure_receipt=failure_receipt,
                workspace_digest=f"workspace-{task.task_id}-{repetition}",
                tool_calls=0,
                input_tokens=0,
                output_tokens=0,
                provider_calls=0,
                memory_hits=0,
                myna_operations=(),
            )

    approval_digest = canonical_digest(config.manifest(load_agent_task_corpus(config.corpus_path)))
    first = run_agent_campaign(
        config,
        approval_digest=approval_digest,
        approved_cny=config.maximum_cost_cny,
        execute_paid=True,
        trial_executor=Executor(),
    )
    second = run_agent_campaign(
        config,
        approval_digest=approval_digest,
        approved_cny=config.maximum_cost_cny,
        execute_paid=True,
        trial_executor=Executor(),
    )

    assert first == second
    assert calls == 48
    assert first["measurement"]["contaminated_pairs"] == 24
    assert first["claim"]["measurement_valid"] is False
    rows = [json.loads(line) for line in (config.output_root / "raw-outcomes.jsonl").read_text().splitlines()]
    assert all(row["schema"] == "pico.picobench.myna-agent-task-effect.trial-record.v2" for row in rows)
    assert sum(row["failure_class"] == "provider" for row in rows) == 24
    verification = verify_agent_evidence(config.output_root, corpus_path=config.corpus_path)
    assert verification["passed"] is False
    assert verification["gates"]["aggregate_reproduces"] is True
    assert verification["recomputed_report"]["measurement"]["contaminated_pairs"] == 24


def test_task_corpora_are_frozen_disjoint_and_cover_memory_risks() -> None:
    calibration = load_task_corpus(TASK_ROOT / "calibration.json")
    formal = load_task_corpus(TASK_ROOT / "formal.json")

    assert calibration.schema == "pico.picobench.myna-task-effect.tasks.v1"
    assert formal.schema == calibration.schema
    assert len(calibration.tasks) == 6
    assert len(formal.tasks) == 24
    assert {task.task_id for task in calibration.tasks}.isdisjoint(task.task_id for task in formal.tasks)
    assert {task.task_class for task in formal.tasks} == {
        "fact",
        "experience",
        "stale_conflict",
        "irrelevant",
    }
    assert len({task.repository_id for task in formal.tasks}) >= 4
    assert all(task.expected_value not in task.evaluation_prompt for task in formal.tasks)
    assert len(formal.digest) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", "../escaped"),
        ("repository_id", "../other-repository"),
    ],
)
def test_task_corpus_rejects_path_escaping_identifiers(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    raw = json.loads((TASK_ROOT / "calibration.json").read_text(encoding="utf-8"))
    raw["tasks"][0][field] = value
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError):
        load_task_corpus(corpus)


def test_arm_order_is_deterministic_balanced_and_changes_only_memory_backend() -> None:
    orders = [arm_order("formal-fact-01", repetition, seed=20260811) for repetition in range(6)]

    assert orders == [arm_order("formal-fact-01", repetition, seed=20260811) for repetition in range(6)]
    assert all(set(order) == {ARM_MEMORY_OFF, ARM_MEMORY_ON} for order in orders)
    assert sum(order[0] == ARM_MEMORY_ON for order in orders) == 3
    assert ARM_MEMORY_OFF.settings == {"memory_backend": None}
    assert ARM_MEMORY_ON.settings == {"memory_backend": "myna"}


def test_report_qualifies_efficiency_uplift_without_inventing_success_uplift() -> None:
    corpus = load_task_corpus(TASK_ROOT / "formal.json")
    trials: list[TrialRecord] = []
    lifecycle = ("start", "store", "stop", "start", "recall", "store", "stop")
    for task in corpus.tasks:
        trials.extend(
            [
                TrialRecord(
                    task_id=task.task_id,
                    task_class=task.task_class,
                    repetition=0,
                    arm_id=ARM_MEMORY_OFF.arm_id,
                    status="passed",
                    workspace_digest=f"workspace-{task.task_id}",
                    repository_reads=1,
                    tool_calls=2,
                    memory_hits=0,
                    myna_operations=(),
                ),
                TrialRecord(
                    task_id=task.task_id,
                    task_class=task.task_class,
                    repetition=0,
                    arm_id=ARM_MEMORY_ON.arm_id,
                    status="passed",
                    workspace_digest=f"workspace-{task.task_id}",
                    repository_reads=(0 if task.task_class in {"fact", "experience"} else 1),
                    tool_calls=(1 if task.task_class in {"fact", "experience"} else 2),
                    memory_hits=(1 if task.task_class in {"fact", "experience"} else 0),
                    myna_operations=lifecycle,
                ),
            ]
        )

    report = build_report(corpus=corpus, trials=tuple(trials), repetitions=1)

    assert report["measurement"]["valid_pairs"] == 24
    assert report["capability"]["verified_pass_delta_pp"] == 0.0
    assert report["efficiency"]["repository_read_reduction_percent"] == 50.0
    assert report["claim"]["capability_claim_eligible"] is False
    assert report["claim"]["efficiency_claim_eligible"] is True
    assert report["claim"]["positive_claim_eligible"] is True


def test_report_fails_closed_when_control_touches_myna() -> None:
    corpus = load_task_corpus(TASK_ROOT / "calibration.json")
    trials: list[TrialRecord] = []
    for task in corpus.tasks:
        for arm in (ARM_MEMORY_OFF, ARM_MEMORY_ON):
            trials.append(
                TrialRecord(
                    task_id=task.task_id,
                    task_class=task.task_class,
                    repetition=0,
                    arm_id=arm.arm_id,
                    status="passed",
                    workspace_digest=f"workspace-{task.task_id}",
                    repository_reads=1,
                    tool_calls=2,
                    memory_hits=0,
                    myna_operations=("start",),
                )
            )

    report = build_report(corpus=corpus, trials=tuple(trials), repetitions=1)

    assert report["measurement"]["axis_valid"] is False
    assert report["claim"]["measurement_valid"] is False
    assert report["claim"]["positive_claim_eligible"] is False


def test_campaign_persists_candidate_bound_evidence_and_resumes(tmp_path: Path) -> None:
    pico_wheel = tmp_path / "pico.whl"
    myna_wheel = tmp_path / "myna.whl"
    pico_wheel.write_bytes(b"pico-wheel")
    myna_wheel.write_bytes(b"myna-wheel")
    output = tmp_path / "evidence"
    calls: list[tuple[str, str]] = []

    def execute(task, repetition, arm, _config):
        calls.append((task.task_id, arm.arm_id))
        treatment = arm is ARM_MEMORY_ON
        return TrialRecord(
            task_id=task.task_id,
            task_class=task.task_class,
            repetition=repetition,
            arm_id=arm.arm_id,
            status="passed",
            workspace_digest=f"workspace-{task.task_id}",
            repository_reads=(0 if treatment and task.task_class in {"fact", "experience"} else 1),
            tool_calls=(1 if treatment and task.task_class in {"fact", "experience"} else 2),
            memory_hits=int(treatment and task.task_class in {"fact", "experience"}),
            myna_operations=(("start", "store", "stop", "start", "recall", "store", "stop") if treatment else ()),
        )

    config = CampaignConfig(
        corpus_path=TASK_ROOT / "formal.json",
        output_root=output,
        pico_wheel=pico_wheel,
        myna_wheel=myna_wheel,
        pico_commit="a" * 40,
        myna_commit="b" * 40,
        repetitions=1,
    )

    first = run_campaign(config, trial_executor=execute)
    second = run_campaign(config, trial_executor=execute)

    assert first == second
    assert len(calls) == 48
    assert first["claim"]["positive_claim_eligible"] is True
    assert (output / "manifest.json").is_file()
    assert len((output / "raw-outcomes.jsonl").read_text().splitlines()) == 48
    assert (output / "aggregate.json").is_file()
    assert (output / "verifier-report.json").is_file()
    assert (output / "inventory.json").is_file()
    assert (output / "claim-eligibility.json").is_file()

    (output / "aggregate.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="existing evidence digest changed"):
        run_campaign(config, trial_executor=execute)


@pytest.mark.asyncio
async def test_installed_worker_control_uses_runtime_and_repository_evidence(
    tmp_path: Path,
) -> None:
    task = load_task_corpus(TASK_ROOT / "calibration.json").tasks[0]
    workspace = tmp_path / "workspace"
    source = workspace / task.source_path
    source.parent.mkdir(parents=True)
    source.write_text(task.source_text, encoding="utf-8")

    result = await run_turn(
        {
            "worker_mode": "turn",
            "arm_id": "memory_off",
            "stage": "evaluate",
            "task_id": task.task_id,
            "task_class": task.task_class,
            "source_path": task.source_path,
            "output_path": task.output_path,
            "workspace": str(workspace),
            "state_root": str(tmp_path / "state"),
            "prompt": f"{task.recall_query}\n\n{task.evaluation_prompt}",
            "session_id": "control-session",
            "message_id": "control-message",
            "timeout_seconds": 30,
        }
    )

    completed_reads = [
        event for event in result["tool_events"] if event["phase"] == "complete" and event["name"] == "read_file"
    ]
    assert result["terminal"] == "completed", result
    assert result["backend_module"] is None
    assert result["memory_backend_build_calls"] == 0
    assert len(completed_reads) == 1
    assert json.loads((workspace / task.output_path).read_text()) == {
        "task_id": task.task_id,
        "value": task.expected_value,
    }


@pytest.mark.asyncio
async def test_worker_records_live_provider_usage_and_tools(tmp_path: Path) -> None:
    task = load_agent_task_corpus(TASK_ROOT / "agent.json").tasks[0]
    workspace = tmp_path / "workspace"
    source = workspace / task.source_path
    source.parent.mkdir(parents=True)
    source.write_text(task.source_text, encoding="utf-8")

    class LiveProvider(LLMProvider):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="write-result",
                            name="write_file",
                            arguments={
                                "path": task.output_path,
                                "content": json.dumps({"task_id": task.task_id, "value": task.expected_value}),
                            },
                        )
                    ],
                    usage={"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140},
                )
            return LLMResponse(
                content="done",
                usage={"prompt_tokens": 80, "completion_tokens": 10, "total_tokens": 90},
            )

        def get_default_model(self) -> str:
            return "deepseek/deepseek-v4-flash"

    result = await run_turn(
        {
            "worker_mode": "turn",
            "provider_mode": "live",
            "arm_id": "memory_off",
            "stage": "evaluate",
            "task_id": task.task_id,
            "task_class": task.task_class,
            "source_path": task.source_path,
            "output_path": task.output_path,
            "workspace": str(workspace),
            "state_root": str(tmp_path / "state"),
            "prompt": task.evaluation_prompt,
            "session_id": "live-session",
            "message_id": "live-message",
            "timeout_seconds": 30,
        },
        provider_override=LiveProvider(),
    )

    assert result["terminal"] == "completed", result
    assert result["provider_calls"] == 2
    assert result["input_tokens"] == 200
    assert result["output_tokens"] == 30
    assert sum(event["phase"] == "complete" for event in result["tool_events"]) == 1


@pytest.mark.asyncio
async def test_worker_classifies_control_provider_exception(tmp_path: Path) -> None:
    task = load_agent_task_corpus(TASK_ROOT / "agent.json").tasks[0]

    class FailingProvider(LLMProvider):
        async def chat(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

        def get_default_model(self) -> str:
            return "deepseek/deepseek-v4-flash"

    result = await run_turn(
        {
            "worker_mode": "turn",
            "provider_mode": "live",
            "arm_id": "memory_off",
            "stage": "evaluate",
            "task_id": task.task_id,
            "task_class": task.task_class,
            "source_path": task.source_path,
            "output_path": task.output_path,
            "workspace": str(tmp_path / "workspace"),
            "state_root": str(tmp_path / "state"),
            "prompt": task.evaluation_prompt,
            "session_id": "provider-failure-session",
            "message_id": "provider-failure-message",
            "timeout_seconds": 30,
        },
        provider_override=FailingProvider(),
    )

    assert result["terminal"] == "failed"
    assert result["failure_class"] == "provider"
    assert result["failure_receipt"]["error"]["type"] == "RuntimeError"
    assert result["memory_operation_receipt"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_class"),
    [
        (ConnectionError("connection reset"), "transport"),
        (ProviderBudgetError("budget exhausted"), "budget"),
    ],
)
async def test_worker_classifies_transport_and_budget_failures(
    tmp_path: Path,
    error: Exception,
    expected_class: str,
) -> None:
    task = load_agent_task_corpus(TASK_ROOT / "agent.json").tasks[0]

    class FailingProvider(LLMProvider):
        async def chat(self, *args, **kwargs):
            raise error

        def get_default_model(self) -> str:
            return "deepseek/deepseek-v4-flash"

    result = await run_turn(
        {
            "worker_mode": "turn",
            "provider_mode": "live",
            "arm_id": "memory_off",
            "stage": "evaluate",
            "task_id": task.task_id,
            "task_class": task.task_class,
            "source_path": task.source_path,
            "output_path": task.output_path,
            "workspace": str(tmp_path / expected_class / "workspace"),
            "state_root": str(tmp_path / expected_class / "state"),
            "prompt": task.evaluation_prompt,
            "session_id": f"{expected_class}-failure-session",
            "message_id": f"{expected_class}-failure-message",
            "timeout_seconds": 30,
        },
        provider_override=FailingProvider(),
    )

    assert result["terminal"] == "failed"
    assert result["failure_class"] == expected_class
    assert result["failure_receipt"]["failure_class"] == expected_class


@pytest.mark.asyncio
async def test_worker_classifies_turn_timeout_as_infrastructure_failure(tmp_path: Path) -> None:
    task = load_agent_task_corpus(TASK_ROOT / "agent.json").tasks[0]

    class HangingProvider(LLMProvider):
        async def chat(self, *args, **kwargs):
            await asyncio.sleep(60)
            raise AssertionError("unreachable")

        def get_default_model(self) -> str:
            return "deepseek/deepseek-v4-flash"

    result = await run_turn(
        {
            "worker_mode": "turn",
            "provider_mode": "live",
            "arm_id": "memory_off",
            "stage": "evaluate",
            "task_id": task.task_id,
            "task_class": task.task_class,
            "source_path": task.source_path,
            "output_path": task.output_path,
            "workspace": str(tmp_path / "workspace"),
            "state_root": str(tmp_path / "state"),
            "prompt": task.evaluation_prompt,
            "session_id": "timeout-session",
            "message_id": "timeout-message",
            "timeout_seconds": 0.01,
        },
        provider_override=HangingProvider(),
    )

    assert result["failure_class"] == "infrastructure"
    assert result["failure_receipt"]["error"]["type"] == "TimeoutError"


@pytest.mark.asyncio
async def test_worker_treatment_provider_failure_has_no_fake_store(tmp_path: Path) -> None:
    task = load_agent_task_corpus(TASK_ROOT / "agent.json").tasks[0]

    class MemoryBackend:
        async def start(self) -> None:
            return None

        async def recall(self, query, *, user_id=None, agent_id=None, top_k=5):
            return []

        async def store(self, session_id, messages) -> None:
            return None

        async def feedback(self, signals) -> None:
            return None

        async def stop(self) -> None:
            return None

    class FailingProvider(LLMProvider):
        async def chat(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

        def get_default_model(self) -> str:
            return "deepseek/deepseek-v4-flash"

    result = await run_turn(
        {
            "worker_mode": "turn",
            "provider_mode": "live",
            "arm_id": "memory_on",
            "stage": "evaluate",
            "task_id": task.task_id,
            "task_class": task.task_class,
            "source_path": task.source_path,
            "output_path": task.output_path,
            "workspace": str(tmp_path / "workspace"),
            "state_root": str(tmp_path / "state"),
            "prompt": task.evaluation_prompt,
            "session_id": "treatment-provider-failure-session",
            "message_id": "treatment-provider-failure-message",
            "timeout_seconds": 30,
        },
        provider_override=FailingProvider(),
        backend_override=MemoryBackend(),
    )

    assert result["terminal"] == "failed"
    assert result["failure_class"] == "provider"
    assert [row["operation"] for row in result["memory_operation_receipt"]] == [
        "start",
        "recall",
        "stop",
    ]
    assert all(row["outcome"] == "succeeded" for row in result["memory_operation_receipt"])
    assert result["myna_operations"] == ["start", "recall", "stop"]


@pytest.mark.asyncio
async def test_worker_classifies_myna_backend_failure_as_product_failure(tmp_path: Path) -> None:
    task = load_agent_task_corpus(TASK_ROOT / "agent.json").tasks[0]

    class FailingMemoryBackend:
        async def start(self) -> None:
            return None

        async def recall(self, query, *, user_id=None, agent_id=None, top_k=5):
            raise RuntimeError("myna recall failed")

        async def store(self, session_id, messages) -> None:
            return None

        async def feedback(self, signals) -> None:
            return None

        async def stop(self) -> None:
            return None

    result = await run_turn(
        {
            "worker_mode": "turn",
            "arm_id": "memory_on",
            "stage": "evaluate",
            "task_id": task.task_id,
            "task_class": task.task_class,
            "source_path": task.source_path,
            "output_path": task.output_path,
            "workspace": str(tmp_path / "workspace"),
            "state_root": str(tmp_path / "state"),
            "prompt": task.evaluation_prompt,
            "session_id": "memory-failure-session",
            "message_id": "memory-failure-message",
            "timeout_seconds": 30,
        },
        backend_override=FailingMemoryBackend(),
    )

    assert result["terminal"] == "failed"
    assert result["failure_class"] == "memory_backend"
    assert result["failure_receipt"]["operation"] == "recall"
    assert [(row["operation"], row["outcome"]) for row in result["memory_operation_receipt"]] == [
        ("start", "succeeded"),
        ("recall", "failed"),
        ("stop", "succeeded"),
    ]
    assert result["myna_operations"] == ["start", "stop"]


@pytest.mark.asyncio
async def test_worker_records_actual_prime_memory_lifecycle(tmp_path: Path) -> None:
    task = load_agent_task_corpus(TASK_ROOT / "agent.json").tasks[0]

    class MemoryBackend:
        async def start(self) -> None:
            return None

        async def recall(self, query, *, user_id=None, agent_id=None, top_k=5):
            return []

        async def store(self, session_id, messages) -> None:
            return None

        async def feedback(self, signals) -> None:
            return None

        async def stop(self) -> None:
            return None

    result = await run_turn(
        {
            "worker_mode": "turn",
            "arm_id": "memory_on",
            "stage": "prime",
            "task_id": task.task_id,
            "task_class": task.task_class,
            "source_path": task.source_path,
            "output_path": task.output_path,
            "workspace": str(tmp_path / "workspace"),
            "state_root": str(tmp_path / "state"),
            "prompt": task.memory_text,
            "session_id": "prime-lifecycle-session",
            "message_id": "prime-lifecycle-message",
            "timeout_seconds": 30,
        },
        backend_override=MemoryBackend(),
    )

    assert result["terminal"] == "completed"
    assert result["failure_class"] is None
    assert result["myna_operations"] == ["start", "recall", "store", "stop"]
    assert [row["operation"] for row in result["memory_operation_receipt"]] == [
        "start",
        "recall",
        "store",
        "stop",
    ]
