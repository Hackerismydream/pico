from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.picobench import (
    PackRegistry,
    rebuild_report,
    run,
)
from benchmarks.picobench.packs.codecairn_task_effect import (
    ScriptedTaskEffectRunner,
    build_codecairn_task_effect_formal_spec,
    create_codecairn_task_effect_pack,
)


@pytest.mark.asyncio
async def test_codecairn_task_effect_formal_run_rebuilds_offline(
    tmp_path: Path,
) -> None:
    runner = ScriptedTaskEffectRunner()
    registry = PackRegistry()
    registry.register(create_codecairn_task_effect_pack(runner))
    spec = build_codecairn_task_effect_formal_spec(
        tmp_path / "evidence",
    )

    ref = await run(spec, registry=registry)

    assert runner.trial_calls == 96
    assert runner.retrieval_calls == 100
    summary = json.loads(
        (ref.root / "summary.json").read_text(
            encoding="utf-8",
        )
    )
    cv_metrics = json.loads(
        (ref.root / "cv-metrics.json").read_text(
            encoding="utf-8",
        )
    )
    assert summary["ship_complete"] is True
    assert summary["measurement_valid"] is True
    assert summary["positive_claim_eligible"] is False
    assert summary["planned_trials"] == 96
    assert summary["terminal_trials"] == 96
    assert summary["planned_retrieval_cases"] == 100
    assert summary["terminal_retrieval_cases"] == 100
    assert len(summary["pair_summaries"]) == 1
    assert summary["pair_summaries"][0]["planned_pairs"] == 48
    assert summary["pair_summaries"][0]["valid_pairs"] == 48
    assert summary["pair_summaries"][0]["coverage_valid"] is True
    assert summary["retrieval_claim_eligible"] is False
    assert summary["task_success_claim_eligible"] is False
    assert summary["efficiency_claim_eligible"] is False
    assert summary["metrics"]["codecairn_task_effect_v2.production_evidence_complete"] is False
    assert summary["metrics"]["codecairn_retrieval_v2.claim_eligible"] is False
    assert summary["metrics"]["codecairn_task_success_v2.claim_eligible"] is False
    assert summary["metrics"]["codecairn_efficiency_v2.claim_eligible"] is False
    assert summary["metrics"]["codecairn_retrieval_v2.memory_off_operation_calls"] == 0
    assert cv_metrics["retrieval_claim_eligible"] is False
    assert cv_metrics["task_success_claim_eligible"] is False
    assert cv_metrics["efficiency_claim_eligible"] is False
    assert cv_metrics["eligible_metrics"] == {}
    assert (
        (ref.root / "REPORT.md")
        .read_text(
            encoding="utf-8",
        )
        .startswith("# PicoBench task-effect v2 Report\n")
    )
    retrieval_case_path = next(
        ref.root.glob(
            "retrieval/**/retrieval-case-record.json",
        )
    )
    retrieval_case = json.loads(retrieval_case_path.read_text(encoding="utf-8"))
    retrieval_attempt_path = ref.root / retrieval_case["attempt_refs"][-1]
    retrieval_attempt = json.loads(retrieval_attempt_path.read_text(encoding="utf-8"))
    assert set(retrieval_case["metadata"]) == {
        "abstained",
        "abstention_reason",
        "anonymous_candidate_ids",
        "anonymous_injected_ids",
        "memory_off_operation_calls",
        "production_evidence_complete",
        "query_class",
        "repository_id",
        "retrieval_latency_ms",
    }
    assert retrieval_case["metadata"] == (retrieval_attempt["metadata"])
    assert retrieval_case["metadata"]["production_evidence_complete"] is False
    assert retrieval_case["metadata"]["memory_off_operation_calls"] == 0

    calls = (
        runner.trial_calls,
        runner.retrieval_calls,
    )
    retrieval_attempt_bytes = retrieval_attempt_path.read_bytes()
    retrieval_case_path.unlink()

    rebuilt = await run(spec, registry=registry)

    assert rebuilt == ref
    assert (
        runner.trial_calls,
        runner.retrieval_calls,
    ) == calls
    assert json.loads(retrieval_case_path.read_text(encoding="utf-8")) == retrieval_case
    assert retrieval_attempt_path.read_bytes() == retrieval_attempt_bytes
    artifacts = {
        name: (ref.root / name).read_bytes()
        for name in (
            "summary.json",
            "cv-metrics.json",
            "REPORT.md",
        )
    }

    first = rebuild_report(ref)
    second = rebuild_report(ref)

    assert first == second
    assert (
        runner.trial_calls,
        runner.retrieval_calls,
    ) == calls
    assert {name: (ref.root / name).read_bytes() for name in artifacts} == artifacts

    resumed = await run(spec, registry=registry)

    assert resumed == ref
    assert (
        runner.trial_calls,
        runner.retrieval_calls,
    ) == calls
    assert {name: (ref.root / name).read_bytes() for name in artifacts} == artifacts
