from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from benchmarks.picobench.packs.skill_transfer.campaign import load_corpus
from benchmarks.picobench.packs.skill_transfer_v2.stage_a import ARMS, StageATrial, anchor_content, build_report

CORPUS = Path("benchmarks/picobench/tasks/skill_transfer_v1.json")


def _trial(task_id: str, ability_id: str, repetition: int, arm_id: str, *, passed: bool) -> StageATrial:
    injected = () if arm_id == "no_skill" else (f"oracle/{arm_id}/{ability_id}@revision",)
    return StageATrial(
        task_id=task_id,
        ability_id=ability_id,
        repetition=repetition,
        arm_id=arm_id,  # type: ignore[arg-type]
        status="passed" if passed else "task_failed",
        workspace_digest=f"workspace:{task_id}",
        injected_skill_ids=injected,
        gate_status=None if arm_id == "no_skill" else "selected",
        tool_calls=1,
        input_tokens=10,
        output_tokens=2,
        provider_calls=1,
        estimated_cost_cny=0.01,
        verification_receipt={},
        failure_class=None if passed else "task",
    )


def test_anchor_is_derived_only_from_learning_projection() -> None:
    ability = load_corpus(CORPUS).abilities[0]
    body = anchor_content(ability)

    assert ability.goal in body
    assert all(item.result in body and item.verification in body for item in ability.learning)
    assert all(item.prompt not in body for item in ability.held_out)


def test_stage_a_report_applies_frozen_continue_rule() -> None:
    corpus = load_corpus(CORPUS)
    rows = []
    for ability in corpus.abilities:
        for task in ability.held_out:
            for repetition in range(2):
                rows.extend(
                    _trial(
                        task.instance_id,
                        ability.ability_id,
                        repetition,
                        arm,
                        passed=arm == "anchor_skill",
                    )
                    for arm in ARMS
                )

    report = build_report(corpus, tuple(rows), samples=500, seed=7)

    assert report["ship_complete"] is True
    assert report["measurement_valid"] is True
    assert report["primary_contrast"]["estimate_pp"] == 100.0
    assert report["primary_contrast"]["ci95_pp"] == [100.0, 100.0]
    assert report["continue_to_stage_b"] is True

    first = next(row for row in rows if row.arm_id == "anchor_skill")
    invalid = tuple(replace(row, injected_skill_ids=()) if row is first else row for row in rows)
    assert build_report(corpus, invalid, samples=100, seed=7)["measurement_valid"] is False
