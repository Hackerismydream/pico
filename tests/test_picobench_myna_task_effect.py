from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.picobench.packs.myna_task_effect.campaign import (
    ARM_MEMORY_OFF,
    ARM_MEMORY_ON,
    CampaignConfig,
    TrialRecord,
    arm_order,
    build_report,
    load_task_corpus,
    run_campaign,
)
from benchmarks.picobench.packs.myna_task_effect.worker import run_turn

TASK_ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "picobench" / "tasks" / "myna_task_effect"


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
    assert result["terminal"] == "completed"
    assert result["backend_module"] is None
    assert result["memory_backend_build_calls"] == 0
    assert len(completed_reads) == 1
    assert json.loads((workspace / task.output_path).read_text()) == {
        "task_id": task.task_id,
        "value": task.expected_value,
    }
