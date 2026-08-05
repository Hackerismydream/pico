from __future__ import annotations

import asyncio
import hashlib
import http.client
import io
import json
import ssl
import subprocess
import threading
import time
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import certifi
import httpx
import pytest

import benchmarks.picobench.packs.codecairn_task_effect.pack as task_effect_pack_module
import benchmarks.picobench.packs.codecairn_task_effect.production as task_effect_production_module
from benchmarks.picobench import (
    PackRegistry,
)
from benchmarks.picobench import (
    run as run_picobench,
)
from benchmarks.picobench.artifacts import ArtifactStore
from benchmarks.picobench.budget import (
    ProviderBudgetConfig,
    ProviderBudgetLedger,
)
from benchmarks.picobench.campaign import (
    CampaignError,
    CampaignMode,
    CampaignOutcome,
    DeterministicGateResult,
    estimate_worst_case_cost,
    load_campaign_suite,
)
from benchmarks.picobench.canonical import canonical_digest, to_primitive
from benchmarks.picobench.claims import ClaimRuleResult
from benchmarks.picobench.codecairn_campaign import (
    _campaign_paths,
    _write_completion_handoff,
    run_codecairn_campaign,
)
from benchmarks.picobench.codecairn_continuity import PairIntegrityError
from benchmarks.picobench.codecairn_installed_worker import (
    _RecordingProvider,
    _register_result_tool,
    _runtime_dependencies,
)
from benchmarks.picobench.codecairn_task_effect_campaign import (
    DEFAULT_TASK_EFFECT_SUITE_PATH,
)
from benchmarks.picobench.codecairn_task_effect_campaign import (
    _campaign_paths as _task_effect_campaign_paths,
)
from benchmarks.picobench.harness import _retrieval_artifact_dict
from benchmarks.picobench.isolation import TrialIsolation
from benchmarks.picobench.packs.codecairn_memory import (
    ScriptedCodeCairnMemoryRunner,
    create_codecairn_memory_calibration_pack,
    create_codecairn_memory_pack,
    load_codecairn_memory_tasks,
    reduce_codecairn_memory_claims,
)
from benchmarks.picobench.packs.codecairn_memory.production import (
    ProductionCodeCairnMemoryRunner,
    _aggregate_usage,
    _MeteredSemanticProxy,
    _minimal_environment,
    _prefetch_codecairn_models,
    _process_semantic_with_retry,
    _profile_complete,
    _provider_call_envelope,
    _recall_provenance,
    _rendered_memory_ids,
    _runtime_state,
    _seed_local_skill,
    _write_combined_ca_bundle,
)
from benchmarks.picobench.packs.codecairn_task_effect import (
    ProductionTaskEffectRunner,
    ScriptedTaskEffectRunner,
    build_codecairn_task_effect_calibration_spec,
    create_codecairn_task_effect_calibration_pack,
    create_codecairn_task_effect_pack,
)
from benchmarks.picobench.packs.codecairn_task_effect.claims import (
    task_effect_claim_rules,
)
from benchmarks.picobench.packs.codecairn_task_effect.definitions import (
    _parse_reference_solution,
    _validate_task_contract,
    load_retrieval_definition,
    load_task_effect_tasks,
)
from benchmarks.picobench.packs.codecairn_task_effect.fixtures import (
    apply_parent_owned_mutation,
    build_parent_owned_prior_fixture,
    build_repository_fixture,
    repository_tree_digest,
    reset_repository_fixture,
)
from benchmarks.picobench.packs.codecairn_task_effect.models import (
    RetrievalQueryClass,
    TaskClass,
)
from benchmarks.picobench.packs.codecairn_task_effect.production import (
    _file_digests,
    _remove_runtime_paths,
    _RetrievalStore,
    _tool_receipts,
)
from benchmarks.picobench.packs.codecairn_task_effect.reducer import (
    _manifest_contract,
    _PairObservations,
    _reduce_retrieval,
    _reduce_task_metrics,
    _trial_evidence_state,
)
from benchmarks.picobench.packs.codecairn_task_effect.runner import (
    _attempt_workspace_path,
    _reset_attempt_workspace,
    _run_repository_check,
)
from benchmarks.picobench.packs.codecairn_task_effect.verifier import (
    SealedTaskEffectVerifier,
    valid_verification_evidence,
)
from benchmarks.picobench.records import (
    RetrievalAttemptKey,
    RetrievalAttemptRecord,
    RetrievalQueryBlockKey,
    RetrievalStatus,
    TurnTerminalState,
    VerificationState,
)
from benchmarks.picobench.reducer import (
    Reduction,
    _reduce_declared_pack_claims,
    _reduce_pairs,
)
from benchmarks.picobench.report import (
    FullReport,
    _claim_metric_exportable,
    _write_cv_metrics,
    rebuild_full_report,
)
from benchmarks.picobench.schema import (
    EVIDENCE_SCHEMA,
    EXPERIMENT_SCHEMA,
    ClaimRule,
    ExperimentRef,
    ExperimentSpec,
    RetrievalQuerySpec,
)
from pico.config.schema import Config
from pico.providers.base import LLMProvider, LLMResponse


class _AttestedTaskEffectRunner:
    kind = "codecairn_task_effect_production_test_adapter"

    def __init__(self) -> None:
        self.identity: dict[str, object] = {}


def test_codecairn_task_effect_definitions_are_frozen_and_disjoint() -> None:
    formal = load_task_effect_tasks("formal")
    calibration = load_task_effect_tasks("calibration")

    assert len(formal) == 24
    assert Counter(task.task_class for task in formal) == {
        TaskClass.FACT: 8,
        TaskClass.EXPERIENCE: 8,
        TaskClass.STALE_CONFLICT: 4,
        TaskClass.IRRELEVANT: 4,
    }
    assert len({task.fixture_id for task in formal}) >= 4
    assert len(calibration) == 6
    assert Counter(task.task_class for task in calibration) == {
        TaskClass.FACT: 2,
        TaskClass.EXPERIENCE: 2,
        TaskClass.STALE_CONFLICT: 1,
        TaskClass.IRRELEVANT: 1,
    }
    assert {task.task_id for task in formal}.isdisjoint(task.task_id for task in calibration)
    assert {task.fixture_id for task in formal}.isdisjoint(task.fixture_id for task in calibration)
    assert {task.expected_id for task in formal}.isdisjoint(task.expected_id for task in calibration)
    assert {task.expected_digest for task in formal}.isdisjoint(task.expected_digest for task in calibration)
    for task in (*formal, *calibration):
        source_contents = {path: task.fixture.file_map[path].content for path in task.source_paths}
        assert to_primitive(
            task.reference_solution.resolve_result(
                source_contents,
            )
        ) == to_primitive(task.expected_artifact.payload["result"])
        task_payload = task.to_task_spec().payload
        assert task_payload["prior_work_prompt"] == task.prior_work_prompt
        assert task_payload["memory_query"] == task.memory_query

        task_spec_digest = canonical_digest(task.to_task_spec())
        assert (
            canonical_digest(
                replace(
                    task,
                    prior_work_prompt=f"{task.prior_work_prompt} changed",
                ).to_task_spec()
            )
            != task_spec_digest
        )
        assert (
            canonical_digest(
                replace(
                    task,
                    memory_query=f"{task.memory_query} changed",
                ).to_task_spec()
            )
            != task_spec_digest
        )
        assert (
            canonical_digest(
                replace(
                    task,
                    reference_solution=replace(
                        task.reference_solution,
                        evidence_path=(f"{task.reference_solution.evidence_path}.changed"),
                    ),
                ).to_task_spec()
            )
            != task_spec_digest
        )
        if task.definition_kind.value == "formal":
            assert len(set(task.source_paths)) >= 2
            assert len(task.reference_solution.captures) >= 2
            assert len({capture.path for capture in task.reference_solution.captures}) >= 2


def test_codecairn_task_effect_reference_parser_rejects_literal_results() -> None:
    task = load_task_effect_tasks("formal")[0]
    captures = [
        {
            "name": capture.name,
            "path": capture.path,
            "line_prefix": capture.line_prefix,
            "line_suffix": capture.line_suffix,
        }
        for capture in task.reference_solution.captures
    ]

    with pytest.raises(
        ValueError,
        match="string leaves must be capture placeholders",
    ):
        _parse_reference_solution(
            {
                "captures": captures,
                "result_template": {
                    "leaked_answer": "literal answer",
                },
                "evidence_path": task.reference_solution.evidence_path,
            },
            task.fixture,
        )
    with pytest.raises(
        ValueError,
        match="leaves must be capture placeholders",
    ):
        _parse_reference_solution(
            {
                "captures": captures,
                "result_template": {
                    "leaked_answer": 7,
                },
                "evidence_path": task.reference_solution.evidence_path,
            },
            task.fixture,
        )


def test_codecairn_task_effect_nested_identity_values_are_immutable() -> None:
    task = load_task_effect_tasks("formal")[0]
    expected_result = task.expected_artifact.payload["result"]
    result_template = task.reference_solution.result_template

    with pytest.raises(TypeError):
        expected_result["leaked"] = "changed"
    with pytest.raises(TypeError):
        result_template["leaked"] = "{capture}"


def test_codecairn_task_effect_formal_prompt_rejects_answer_leakage() -> None:
    task = next(
        task for task in load_task_effect_tasks("formal") if task.task_class in {TaskClass.FACT, TaskClass.EXPERIENCE}
    )
    source_contents = {path: task.fixture.file_map[path].content for path in task.source_paths}
    leaked_value = next(
        value
        for value in (capture.resolve(source_contents) for capture in task.reference_solution.captures)
        if len(value.strip()) >= 4
    )

    with pytest.raises(
        ValueError,
        match="prior_work_prompt contains a formal answer value",
    ):
        _validate_task_contract(
            replace(
                task,
                prior_work_prompt=(f"{task.prior_work_prompt}\nKnown answer: {leaked_value}"),
            )
        )


def test_codecairn_task_effect_retrieval_definitions_are_frozen() -> None:
    formal = load_retrieval_definition("formal")
    calibration = load_retrieval_definition("calibration")

    assert len(formal.queries) == 100
    assert Counter(query.query_class for query in formal.queries) == {
        RetrievalQueryClass.FACT_POSITIVE: 30,
        RetrievalQueryClass.EXPERIENCE_POSITIVE: 20,
        RetrievalQueryClass.HARD_NEGATIVE: 20,
        RetrievalQueryClass.STALE: 15,
        RetrievalQueryClass.CROSS_REPOSITORY: 15,
    }
    assert sum(len(query.expected_memory_ids) > 1 for query in formal.queries if query.query_class.is_positive) >= 10
    assert len(calibration.queries) == 10
    assert Counter(query.query_class for query in calibration.queries) == {
        RetrievalQueryClass.FACT_POSITIVE: 2,
        RetrievalQueryClass.EXPERIENCE_POSITIVE: 2,
        RetrievalQueryClass.HARD_NEGATIVE: 2,
        RetrievalQueryClass.STALE: 2,
        RetrievalQueryClass.CROSS_REPOSITORY: 2,
    }
    assert {query.query_id for query in formal.queries}.isdisjoint(query.query_id for query in calibration.queries)
    assert {query.query_text for query in formal.queries}.isdisjoint(query.query_text for query in calibration.queries)
    assert {memory.memory_id for memory in formal.corpus}.isdisjoint(memory.memory_id for memory in calibration.corpus)
    positive_fact_ids = {
        memory_id
        for query in formal.queries
        if query.query_class is RetrievalQueryClass.FACT_POSITIVE
        for memory_id in query.expected_memory_ids
    }
    for memory_id in positive_fact_ids:
        memory = formal.corpus_by_id[memory_id]
        assert memory.fixture_revision is not None
        assert memory.evidence_path is not None
        assert memory.evidence_digest is not None


def test_codecairn_task_effect_fixture_reset_is_digest_stable(
    tmp_path: Path,
) -> None:
    task = load_task_effect_tasks("formal")[0]
    root = tmp_path / "fixture"

    initial = build_repository_fixture(task, root)
    source_path = root / task.source_paths[0]
    source_path.write_text("drifted", encoding="utf-8")
    reset = reset_repository_fixture(task, root)

    assert initial.fixture_digest == task.fixture.digest
    assert reset.fixture_digest == initial.fixture_digest
    assert reset.tree_digest == initial.tree_digest
    assert repository_tree_digest(root) == initial.tree_digest
    assert source_path.read_text(encoding="utf-8") == (task.fixture.file_map[task.source_paths[0]].content)


@pytest.mark.asyncio
async def test_codecairn_task_effect_repository_check_is_real_and_allowlisted(
    tmp_path: Path,
) -> None:
    task = load_task_effect_tasks("formal")[0]
    failed_fixture = replace(
        task.fixture,
        files=tuple(
            replace(
                fixture_file,
                content="raise SystemExit(7)\n",
            )
            if fixture_file.path == "checks/validate_repository.py"
            else fixture_file
            for fixture_file in task.fixture.files
        ),
    )
    failed_task = replace(task, fixture=failed_fixture)
    root = tmp_path / "failed-check"
    build_repository_fixture(failed_task, root)

    state = await _run_repository_check(failed_task, root)

    assert state.exit_code == 7
    with pytest.raises(
        ValueError,
        match="not allowlisted",
    ):
        await _run_repository_check(
            replace(
                failed_task,
                test_command="python checks/validate_repository.py",
            ),
            root,
        )


def test_codecairn_task_effect_attempt_workspace_reset_is_scoped(
    tmp_path: Path,
) -> None:
    task = load_task_effect_tasks("formal")[0]
    experiment_root = tmp_path / "experiment"
    workspace = (
        experiment_root / "workspaces" / "pack" / task.task_id / "0" / "memory_off" / "attempts" / "1" / "workspace"
    )
    build_repository_fixture(task, workspace)
    extra = workspace / task.artifact_path
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("retained output", encoding="utf-8")

    _reset_attempt_workspace(
        task,
        workspace,
        experiment_root=experiment_root,
    )

    assert not workspace.exists()
    unmarked = workspace
    unmarked.mkdir(parents=True)
    sentinel = unmarked / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="unmarked"):
        _reset_attempt_workspace(
            task,
            unmarked,
            experiment_root=experiment_root,
        )
    assert sentinel.read_text(encoding="utf-8") == "preserve"

    with pytest.raises(ValueError, match="safe path component"):
        _attempt_workspace_path(
            output_root=tmp_path / "evidence",
            experiment_id="experiment",
            pack_id="../escape",
            task_id=task.task_id,
            repetition=0,
            variant_id="memory_off",
            block_attempt=1,
        )
    assert not (tmp_path / "evidence" / "escape").exists()


def test_codecairn_task_effect_parent_materializes_stale_transition(
    tmp_path: Path,
) -> None:
    stale_tasks = tuple(
        task for task in load_task_effect_tasks("formal") if task.task_class is TaskClass.STALE_CONFLICT
    )

    assert len(stale_tasks) == 4
    assert len({task.mutation_contract["contract_digest"] for task in stale_tasks}) == 4
    for task in stale_tasks:
        contract = task.mutation_contract
        mutation = task.parent_owned_mutation
        assert contract is not None
        assert mutation is not None
        assert contract["prior_fixture_digest"] != contract["evaluated_fixture_digest"]
        root = tmp_path / task.task_id
        prior = build_parent_owned_prior_fixture(task, root)
        prior_content = (root / mutation.path).read_text(encoding="utf-8")

        evaluated = apply_parent_owned_mutation(task, root)

        assert prior.fixture_digest == contract["prior_fixture_digest"]
        assert evaluated.fixture_digest == (contract["evaluated_fixture_digest"])
        assert evaluated.tree_digest == repository_tree_digest(root)
        assert (root / mutation.path).read_text(encoding="utf-8") == task.fixture.file_map[mutation.path].content
        assert prior_content == mutation.prior_content
        assert prior_content != (root / mutation.path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_codecairn_task_effect_sealed_verifier_owns_outcomes(
    tmp_path: Path,
) -> None:
    task = load_task_effect_tasks("formal")[0]
    root = tmp_path / "fixture"
    build_repository_fixture(task, root)
    artifact = root / task.artifact_path
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(to_primitive(task.expected_artifact.payload)),
        encoding="utf-8",
    )
    verifier = SealedTaskEffectVerifier.capture(task)
    valid = valid_verification_evidence(task)

    passed = await verifier.verify(root, valid)
    wrong_path = await verifier.verify(
        root,
        replace(
            valid,
            changed_paths=(
                task.artifact_path,
                "unexpected.txt",
            ),
        ),
    )
    missing_receipt = await verifier.verify(
        root,
        replace(valid, receipt_ids=()),
    )
    failed_test = await verifier.verify(
        root,
        replace(
            valid,
            test_state=replace(valid.test_state, exit_code=1),
        ),
    )
    artifact.write_text("{}", encoding="utf-8")
    wrong_artifact = await verifier.verify(root, valid)

    assert passed.result.state is VerificationState.PASSED
    assert wrong_artifact.result.state is VerificationState.FAILED
    assert "artifact_mismatch" in wrong_artifact.result.findings
    assert wrong_path.result.state is VerificationState.FAILED
    assert "path_policy_changed:unexpected.txt" in wrong_path.result.findings
    assert missing_receipt.result.state is VerificationState.FAILED
    assert any(finding.startswith("required_receipt_missing:") for finding in missing_receipt.result.findings)
    assert failed_test.result.state is VerificationState.FAILED
    assert "test_state_failed:1" in failed_test.result.findings


def test_codecairn_task_effect_preserves_v1_fingerprints_and_labels() -> None:
    v1_runner = ScriptedCodeCairnMemoryRunner()
    v1_pack = create_codecairn_memory_pack(v1_runner).definition()
    v1_tasks = load_codecairn_memory_tasks("formal")
    v1_labels = (
        RetrievalQuerySpec(
            query_id="legacy-positive",
            label="positive",
            expected_item_ids=("item",),
        ),
        RetrievalQuerySpec(
            query_id="legacy-negative",
            label="hard_negative",
        ),
    )
    v2_labels = {query.label for query in load_retrieval_definition("formal").to_retrieval_suite_spec().queries}

    assert canonical_digest(v1_pack) == ("f6a4598b512585baf3156da031339a556d96cee848cba8dfa7112608794c21fe")
    assert canonical_digest(v1_tasks) == ("7c020685731098f4487e25e982565309f18f2ba8dc3d46af9b36e54b2b1b8524")
    assert v1_pack.identity["task_schema"] == ("pico.picobench.codecairn-memory-tasks.v1")
    assert EXPERIMENT_SCHEMA == "pico.picobench.experiment.v1"
    assert EVIDENCE_SCHEMA == "pico.picobench.evidence.v1"
    assert canonical_digest(v1_labels) == ("3c6653993a6ece281690b9fe5a831260c5c2b27e14b0bacc564537f583710854")
    assert v2_labels == {
        "positive_repository_fact",
        "positive_execution_experience",
        "hard_negative",
        "stale_or_superseded",
        "cross_repository",
    }


@pytest.mark.asyncio
async def test_codecairn_task_effect_preserves_v1_report_bytes(
    tmp_path: Path,
) -> None:
    registry = PackRegistry()
    registry.register(
        create_codecairn_memory_pack(
            ScriptedCodeCairnMemoryRunner(),
        )
    )
    spec = ExperimentSpec(
        suite="codecairn-memory-v1-regression",
        repetitions=2,
        pack_ids=("codecairn-memory-effect-v1",),
        output_root=tmp_path / "evidence",
        identity={"regression": "v1-report-byte-contract"},
    )

    ref = await run_picobench(spec, registry=registry)
    rebuild_full_report(ref)

    assert ref.experiment_id == ("2af2093dff4f3fcaf39767a7f3423868923d7a35f600eb3dfce2b4dfb7bd2ae0")
    assert {
        name: hashlib.sha256((ref.root / name).read_bytes()).hexdigest()
        for name in (
            "manifest.json",
            "summary.json",
            "cv-metrics.json",
            "REPORT.md",
        )
    } == {
        "manifest.json": ("2f2bd793d5c5cb04b1d3fccc396b0dc2907fb0f2ea57b119d280a83330acfb3c"),
        "summary.json": ("dc0ae745d0feb79902c9a21aba275e6f544a88e9cb24147d4ca2476ca6e3c0f0"),
        "cv-metrics.json": ("dd1022edc672bf1f90a619f866e4cac6b30a67730c8901284ea0ba47f0665af0"),
        "REPORT.md": ("c8433754bd26b13b8031f2429bae24005cf2965fc33e0ad4229a50b6cdbb61a4"),
    }


def test_codecairn_task_effect_retrieval_metadata_preserves_legacy_shape() -> None:
    key = RetrievalAttemptKey(
        block=RetrievalQueryBlockKey(
            experiment_id="experiment",
            retrieval_suite_id="legacy-retrieval",
            query_id="legacy-query",
        ),
        configuration_id="legacy-config",
        query_block_attempt=1,
    )
    legacy = RetrievalAttemptRecord(
        key=key,
        plan_digest="plan",
        status=RetrievalStatus.MEASURABLE,
        label="positive",
        expected_item_ids=("item",),
    )
    metadata = {
        "repository_id": "repository-a",
        "abstained": False,
    }

    legacy_payload = _retrieval_artifact_dict(legacy)
    v2_payload = _retrieval_artifact_dict(replace(legacy, metadata=metadata))

    assert "metadata" not in legacy_payload
    assert v2_payload["metadata"] == metadata


def test_codecairn_task_effect_pack_freezes_single_axis_and_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = create_codecairn_task_effect_pack(
        SimpleNamespace(kind="scripted/task-effect-v2"),
    ).definition()

    assert definition.pack_id == "codecairn-task-effect-v2"
    assert len(definition.tasks) == 24
    assert [variant.variant_id for variant in definition.variants] == [
        "memory_off",
        "codecairn",
    ]
    assert [
        (
            pair.treatment_axis,
            pair.control_variant_id,
            pair.treatment_variant_id,
        )
        for pair in definition.pairs
    ] == [("memory_backend", "memory_off", "codecairn")]
    assert dict(definition.variants[0].settings) == {
        "memory_backend": None,
    }
    assert dict(definition.variants[1].settings) == {
        "memory_backend": "codecairn",
    }
    assert definition.identity["claim_reducer"] == ("codecairn_task_effect_v2")
    assert definition.identity["report_title"] == ("PicoBench task-effect v2 Report")
    assert definition.identity["minimum_valid_pairs_per_task"] == 1
    assert definition.identity["production_evidence_complete"] is False
    assert len(definition.identity["anonymous_retrieval_corpus_ids"]) == len(
        load_retrieval_definition("formal").corpus,
    )
    assert set(definition.identity["anonymous_retrieval_corpus_metadata"]) == set(
        definition.identity["anonymous_retrieval_corpus_ids"]
    )

    forged = create_codecairn_task_effect_pack(
        SimpleNamespace(
            kind="production/task-effect-v2",
            identity={
                "production_evidence_complete": True,
                "production_adapter_attestation": {
                    "schema": ("pico.picobench.task-effect-production-adapter.v1"),
                    "adapter_id": "production/task-effect-v2",
                    "adapter_digest": "f" * 64,
                },
            },
        )
    ).definition()

    assert forged.identity["production_evidence_complete"] is False
    assert forged.identity["production_adapter_attestation"] is None

    scripted_forgery = create_codecairn_task_effect_pack(
        SimpleNamespace(
            kind="codecairn_task_effect_scripted_contract",
            identity={
                "production_evidence_complete": True,
                "production_adapter_attestation": {
                    "schema": ("pico.picobench.task-effect-production-adapter.v1"),
                    "adapter_id": ("codecairn_task_effect_scripted_contract"),
                    "adapter_digest": "e" * 64,
                },
            },
        )
    ).definition()
    assert scripted_forgery.identity["production_evidence_complete"] is False

    adapter = _AttestedTaskEffectRunner()
    adapter_digest = task_effect_pack_module._runner_implementation_digest(
        adapter,
    )
    assert adapter_digest is not None
    adapter.identity = {
        "production_evidence_complete": True,
        "production_adapter_attestation": {
            "schema": ("pico.picobench.task-effect-production-adapter.v1"),
            "adapter_id": adapter.kind,
            "adapter_digest": adapter_digest,
        },
    }
    monkeypatch.setattr(
        task_effect_pack_module,
        "_TRUSTED_PRODUCTION_ADAPTER_DIGESTS",
        {adapter.kind: adapter_digest},
    )
    trusted = create_codecairn_task_effect_pack(
        adapter,
    ).definition()
    assert trusted.identity["production_evidence_complete"] is True
    assert trusted.identity["production_adapter_implementation_digest"] == adapter_digest

    base_manifest = {
        "pack_definitions": [to_primitive(trusted)],
        "spec": {
            "repetitions": 2,
            "identity": {
                "production_evidence_complete": False,
            },
        },
        "plan_digest": "a" * 64,
    }
    stage_a_contract = _manifest_contract(base_manifest)
    assert stage_a_contract is not None
    assert stage_a_contract.production_evidence_declared is False

    authorized_contract = _manifest_contract(
        {
            **base_manifest,
            "spec": {
                "repetitions": 2,
                "identity": {
                    "production_evidence_complete": True,
                },
            },
        }
    )
    assert authorized_contract is not None
    assert authorized_contract.production_evidence_declared is True

    forged_definition = to_primitive(scripted_forgery)
    forged_identity = forged_definition["identity"]
    forged_attestation = {
        "schema": ("pico.picobench.task-effect-production-adapter.v1"),
        "adapter_id": ("codecairn_task_effect_scripted_contract"),
        "adapter_digest": "e" * 64,
    }
    forged_identity.update(
        {
            "production_evidence_complete": True,
            "production_adapter_attestation": forged_attestation,
            "production_adapter_attestation_digest": (canonical_digest(forged_attestation)),
            "production_adapter_implementation_digest": "e" * 64,
        }
    )
    forged_contract = _manifest_contract(
        {
            "pack_definitions": [forged_definition],
            "spec": {
                "repetitions": 2,
                "identity": {
                    "production_evidence_complete": True,
                },
            },
            "plan_digest": "b" * 64,
        }
    )
    assert forged_contract is not None
    assert forged_contract.production_evidence_declared is False

    calibration = create_codecairn_task_effect_calibration_pack(
        adapter,
    ).definition()
    assert calibration.identity["production_evidence_complete"] is False


def test_codecairn_task_effect_production_adapter_is_digest_attested() -> None:
    runner = object.__new__(ProductionTaskEffectRunner)
    adapter_digest = hashlib.sha256(
        Path(
            "benchmarks/picobench/packs/codecairn_task_effect/production.py",
        ).read_bytes()
    ).hexdigest()
    runner.identity = {
        "production_adapter_attestation": {
            "schema": ("pico.picobench.task-effect-production-adapter.v1"),
            "adapter_id": runner.kind,
            "adapter_digest": adapter_digest,
        },
        "production_evidence_complete": True,
    }

    definition = create_codecairn_task_effect_pack(
        runner,
    ).definition()

    assert definition.identity["production_adapter_implementation_digest"] == adapter_digest
    assert definition.identity["production_adapter_attestation"] == runner.identity["production_adapter_attestation"]
    assert definition.identity["production_evidence_complete"] is True


def test_codecairn_task_effect_campaign_suite_matches_frozen_contract() -> None:
    suite = load_campaign_suite(
        DEFAULT_TASK_EFFECT_SUITE_PATH,
    )
    estimate = estimate_worst_case_cost(
        suite,
        modes=(
            CampaignMode.CALIBRATION,
            CampaignMode.FORMAL,
        ),
    )

    assert suite.provider.name == "deepseek"
    assert suite.provider.model == "deepseek-v4-flash"
    assert suite.provider.allow_fallback is False
    assert suite.calibration.expected_trials == 12
    assert suite.calibration.expected_retrieval_cases == 10
    assert suite.formal.expected_trials == 96
    assert suite.formal.expected_retrieval_cases == 100
    assert suite.budget.hard_cap_cny == 30
    assert estimate.trial_count == 108
    assert estimate.estimated_cny < suite.budget.hard_cap_cny
    assert canonical_digest(
        suite.claim_rules,
    ) == canonical_digest(task_effect_claim_rules())


def test_codecairn_task_effect_campaign_requires_explicit_paid_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    suite = load_campaign_suite(
        DEFAULT_TASK_EFFECT_SUITE_PATH,
    )
    pico_wheel = tmp_path / "pico.whl"
    codecairn_wheel = tmp_path / "codecairn.whl"
    stage_c = tmp_path / "stage-c.json"
    pico_wheel.write_bytes(b"pico")
    codecairn_wheel.write_bytes(b"codecairn")
    stage_c.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv(
        "PICO_TASK_EFFECT_PICO_WHEEL",
        str(pico_wheel),
    )
    monkeypatch.setenv(
        "PICO_TASK_EFFECT_CODECAIRN_WHEEL",
        str(codecairn_wheel),
    )
    monkeypatch.setenv(
        "PICO_TASK_EFFECT_STAGE_C_SUMMARY",
        str(stage_c),
    )
    monkeypatch.delenv(
        "PICO_TASK_EFFECT_AUTHORIZATION",
        raising=False,
    )

    with pytest.raises(
        CampaignError,
        match="PICO_TASK_EFFECT_AUTHORIZATION is required",
    ):
        _task_effect_campaign_paths(suite)


def test_codecairn_task_effect_worker_exposes_only_repository_tools(
    tmp_path: Path,
) -> None:
    _provider, config, pico_config, _scope = _runtime_dependencies(
        {
            "context_window_tokens": 18_048,
            "mode": "task_effect",
        },
        tmp_path,
    )

    assert {
        "read_file",
        "write_file",
        "exec",
    }.isdisjoint(config.tools.disabled_tools)
    assert "web_search" in config.tools.disabled_tools
    assert "spawn" in config.tools.disabled_tools
    assert config.agents.defaults.context_window_tokens == 18_048
    assert config.agents.defaults.max_tool_iterations == 8
    assert pico_config.skill_forge.router.top_k == 0


@pytest.mark.asyncio
async def test_codecairn_task_effect_worker_does_not_reinject_reasoning() -> None:
    class ReasoningProvider(LLMProvider):
        async def chat(self, *args, **kwargs) -> LLMResponse:
            del args, kwargs
            return LLMResponse(
                content="use repository tools",
                reasoning_content="private reasoning",
                thinking_blocks=[
                    {
                        "type": "thinking",
                        "thinking": "private block",
                    }
                ],
                usage={
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                },
            )

        def get_default_model(self) -> str:
            return "deepseek-v4-flash"

    provider = _RecordingProvider(
        ReasoningProvider(),
        preserve_reasoning_content=False,
    )

    response = await provider.chat(
        messages=[
            {
                "content": "task",
                "role": "user",
            }
        ],
    )

    assert response.reasoning_content is None
    assert response.thinking_blocks is None
    assert provider.calls[0]["usage"] == {
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
    }


def test_codecairn_task_effect_runtime_paths_are_isolated(
    tmp_path: Path,
) -> None:
    git_file = tmp_path / ".git" / "config"
    curator_file = tmp_path / "memory" / ".curator" / "manifest.json"
    user_memory = tmp_path / "memory" / "project.md"
    artifact = tmp_path / "deliverables" / "result.json"
    for path, content in (
        (git_file, "git"),
        (curator_file, "curator"),
        (user_memory, "user"),
        (artifact, "artifact"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    digests = _file_digests(tmp_path)

    assert set(digests) == {
        "deliverables/result.json",
        "memory/project.md",
    }

    _remove_runtime_paths(tmp_path)

    assert not git_file.exists()
    assert not curator_file.exists()
    assert user_memory.read_text(encoding="utf-8") == "user"
    assert artifact.read_text(encoding="utf-8") == "artifact"


def test_codecairn_task_effect_stale_memory_uses_one_subject(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    subjects: list[str] = []

    def remember(
        _self: object,
        _repository: Path,
        _runtime_root: Path,
        *,
        subject_key: str,
        **_kwargs: object,
    ) -> str:
        subjects.append(subject_key)
        return f"memory-{len(subjects)}"

    monkeypatch.setattr(
        ProductionTaskEffectRunner,
        "_remember",
        remember,
    )
    monkeypatch.setattr(
        ProductionTaskEffectRunner,
        "_supersede",
        lambda *_args, **_kwargs: None,
    )
    task = next(task for task in load_task_effect_tasks("calibration") if task.parent_owned_mutation is not None)
    runner = object.__new__(ProductionTaskEffectRunner)

    receipt = runner._seed_task_memory(
        task,
        tmp_path,
        tmp_path / "runtime",
        {},
    )

    assert subjects == [
        f"{task.task_id}_state",
        f"{task.task_id}_state",
    ]
    assert receipt["superseded_memory_ids"] == ["memory-1"]
    assert receipt["active_memory_ids"] == ["memory-2"]


def test_codecairn_task_effect_hidden_lifecycle_memory_is_not_scored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    definition = load_retrieval_definition("calibration")
    query = definition.queries[0]
    memory = next(memory for memory in definition.corpus if memory.repository_id == query.repository_id)
    monkeypatch.setattr(
        task_effect_production_module,
        "_command_json",
        lambda *_args, **_kwargs: {
            "sidecar": {
                "repo_key": query.repository_id,
                "retrieval_profile": "fastembed",
                "semantic_state": "complete",
                "ranked": [
                    {
                        "memory_id": "hidden",
                        "final_score": 1.0,
                    },
                    {
                        "memory_id": "visible",
                        "final_score": 0.5,
                    },
                ],
                "context_trace": {
                    "rendered_memory_ids": [
                        "hidden",
                        "visible",
                    ],
                },
                "admission_trace": {
                    "outcome": "admitted",
                },
            },
        },
    )
    store = _RetrievalStore(
        codecairn=tmp_path / "codecairn",
        definition=definition,
        runtime_root=tmp_path / "runtime",
        environment={},
        repositories={
            query.repository_id: tmp_path,
        },
        actual_to_memory={
            "visible": memory,
        },
        hidden_memory_ids={"hidden"},
    )

    execution = store.recall(query)

    assert len(execution.ranked_results) == 1
    assert execution.ranked_results[0]["rank"] == 1
    assert len(execution.injected_results) == 1
    assert execution.injected_results[0]["injection_position"] == 1


def test_codecairn_task_effect_tool_receipts_are_success_only() -> None:
    observed = _tool_receipts(
        [
            {
                "phase": "complete",
                "failed": False,
                "name": "read_file",
                "arguments": {"path": "README.md"},
            },
            {
                "phase": "complete",
                "failed": False,
                "name": "write_file",
                "arguments": {
                    "path": "deliverables/result.json",
                },
            },
            {
                "phase": "complete",
                "failed": False,
                "name": "exec",
                "arguments": {
                    "command": ("python -B checks/validate_repository.py"),
                },
            },
            {
                "phase": "complete",
                "failed": True,
                "name": "read_file",
                "arguments": {"path": "missing.txt"},
            },
        ]
    )

    assert observed["receipt_ids"] == (
        "read:README.md",
        "write:deliverables/result.json",
        "test:python -B checks/validate_repository.py",
    )
    assert observed["tool_calls"] == 4
    assert observed["tool_failures"] == 1


def test_codecairn_task_effect_pair_coverage_boundaries() -> None:
    pack_id = "codecairn-task-effect-v2"
    axis = "memory_backend"
    planned = tuple((f"task-{index:02d}", repetition) for index in range(24) for repetition in range(2))
    manifest = {
        "pack_definitions": [
            {
                "pack_id": pack_id,
                "identity": {
                    "minimum_valid_pairs_per_task": 1,
                },
            }
        ],
        "pairs": [
            {
                "pack_id": pack_id,
                "treatment_axis": axis,
                "task_id": task_id,
                "repetition": repetition,
                "control_variant_id": "memory_off",
                "treatment_variant_id": "codecairn",
            }
            for task_id, repetition in planned
        ],
    }

    def coverage_for(
        valid_keys: set[tuple[str, int]],
        *,
        minimum_valid_pairs_per_task: int | None = 1,
    ) -> bool:
        coverage_manifest = {
            **manifest,
            "pack_definitions": [
                {
                    "pack_id": pack_id,
                    "identity": (
                        {}
                        if minimum_valid_pairs_per_task is None
                        else {
                            "minimum_valid_pairs_per_task": (minimum_valid_pairs_per_task),
                        }
                    ),
                }
            ],
        }
        pair_records = {
            (
                pack_id,
                axis,
                task_id,
                repetition,
            ): {
                "key": {
                    "pack_id": pack_id,
                    "treatment_axis": axis,
                    "task_id": task_id,
                    "repetition": repetition,
                },
                "valid": True,
            }
            for task_id, repetition in valid_keys
        }
        summaries, _metrics = _reduce_pairs(
            manifest=coverage_manifest,
            trial_records={},
            pair_records=pair_records,
            seed=1,
        )
        return summaries[0].coverage_valid

    valid_44 = set(planned) - {(f"task-{index:02d}", 1) for index in range(4)}
    valid_43 = set(planned) - {(f"task-{index:02d}", 1) for index in range(5)}
    uncovered_task = set(planned) - {
        ("task-00", 0),
        ("task-00", 1),
    }
    one_per_task = {(task_id, 0) for task_id, _repetition in planned}

    assert len(valid_44) == 44
    assert coverage_for(valid_44) is True
    assert len(valid_43) == 43
    assert coverage_for(valid_43) is False
    assert len(uncovered_task) == 46
    assert coverage_for(uncovered_task) is False
    assert len(one_per_task) == 24
    assert (
        coverage_for(
            one_per_task,
            minimum_valid_pairs_per_task=None,
        )
        is False
    )


def test_codecairn_task_effect_retrieval_metrics_use_true_denominators() -> None:
    retrieval_definition = load_retrieval_definition("formal")
    anonymous_corpus = {
        retrieval_definition.anonymous_memory_id(memory.memory_id): memory for memory in retrieval_definition.corpus
    }
    definition = create_codecairn_task_effect_pack(
        SimpleNamespace(kind="scripted/task-effect-v2"),
    ).definition()
    contract = _manifest_contract(
        {
            "pack_definitions": [
                to_primitive(definition),
            ],
            "spec": {"repetitions": 2},
            "plan_digest": "a" * 64,
        }
    )
    assert contract is not None
    positive_keys = [
        key
        for key in sorted(contract.planned_retrieval_keys)
        if contract.query_payloads[key[:2]]["query_class"] in {"fact_positive", "experience_positive"}
    ]
    partial_recall_key = next(
        key for key in positive_keys if len(contract.query_payloads[key[:2]]["expected_item_ids"]) > 1
    )
    delayed_mrr_key = next(key for key in positive_keys if key != partial_recall_key)
    first_hard_negative = next(
        key
        for key in sorted(contract.planned_retrieval_keys)
        if contract.query_payloads[key[:2]]["query_class"] == "hard_negative"
    )
    first_stale = next(
        key
        for key in sorted(contract.planned_retrieval_keys)
        if contract.query_payloads[key[:2]]["query_class"] == "stale"
    )
    first_cross_repository = next(
        key
        for key in sorted(contract.planned_retrieval_keys)
        if contract.query_payloads[key[:2]]["query_class"] == "cross_repository"
    )

    def result(
        item_id: str,
        *,
        rank: int | None = None,
        repository_identity: str | None = None,
        validity_state: str | None = None,
    ) -> dict[str, object]:
        memory = anonymous_corpus[item_id]
        payload: dict[str, object] = {
            "item_id": item_id,
            "score": 1.0,
            "source": "fixture",
            "repository_identity": (repository_identity if repository_identity is not None else memory.repository_id),
            "validity_state": (validity_state if validity_state is not None else memory.validity.value),
        }
        if rank is not None:
            payload["rank"] = rank
        return payload

    records = {}
    expected_injected_relevant = 0
    expected_injected_total = 0
    expected_positive_recall: list[float] = []
    expected_positive_mrr: list[float] = []
    for key in sorted(contract.planned_retrieval_keys):
        suite_id, query_id, configuration_id = key
        query = contract.query_payloads[(suite_id, query_id)]
        query_class = query["query_class"]
        expected = list(query["expected_item_ids"])
        forbidden = list(query["forbidden_memory_ids"])
        ranked_ids: list[str] = []
        injected_ids: list[str] = []
        if query_class in {
            "fact_positive",
            "experience_positive",
        }:
            if key == partial_recall_key:
                irrelevant_id = next(
                    item_id
                    for item_id, memory in anonymous_corpus.items()
                    if item_id not in expected and memory.validity.value == "active"
                )
                ranked_ids = expected[:1]
                injected_ids = [
                    expected[0],
                    irrelevant_id,
                ]
            elif key == delayed_mrr_key:
                irrelevant_id = next(
                    item_id
                    for item_id, memory in anonymous_corpus.items()
                    if item_id not in expected and memory.validity.value == "active"
                )
                ranked_ids = [
                    irrelevant_id,
                    *expected,
                ]
                injected_ids = expected
            else:
                ranked_ids = expected
                injected_ids = expected
            expected_injected_relevant += sum(item_id in expected for item_id in injected_ids)
            expected_injected_total += len(injected_ids)
            expected_positive_recall.append(
                len(set(ranked_ids[:5]) & set(expected)) / len(expected),
            )
            expected_positive_mrr.append(
                1
                / min(
                    index
                    for index, item_id in enumerate(
                        ranked_ids,
                        start=1,
                    )
                    if item_id in expected
                )
            )
        elif key == first_hard_negative:
            injected_ids = [
                item_id for item_id, memory in anonymous_corpus.items() if memory.validity.value == "active"
            ][:2]
        elif key == first_stale:
            injected_ids = [
                next(
                    item_id
                    for item_id, memory in anonymous_corpus.items()
                    if item_id not in forbidden
                    and memory.repository_id == query["repository_id"]
                    and memory.validity.value
                    in {
                        "stale",
                        "superseded",
                    }
                )
            ]
        elif key == first_cross_repository:
            injected_ids = [
                next(
                    item_id
                    for item_id, memory in anonymous_corpus.items()
                    if item_id not in forbidden
                    and memory.repository_id != query["repository_id"]
                    and memory.validity.value == "active"
                )
            ]
        abstained = not injected_ids
        abstention_reason = (
            {
                "fact_positive": "no_relevant_memory",
                "experience_positive": "no_relevant_memory",
                "hard_negative": "no_relevant_memory",
                "stale": "stale_or_superseded_filtered",
                "cross_repository": ("cross_repository_memory_filtered"),
            }[query_class]
            if abstained
            else "not_abstained"
        )
        records[key] = {
            "key": {
                "retrieval_suite_id": suite_id,
                "query_id": query_id,
                "configuration_id": configuration_id,
            },
            "status": "measurable",
            "label": query["label"],
            "expected_item_ids": expected,
            "ranked_results": [
                result(item_id, rank=index)
                for index, item_id in enumerate(
                    ranked_ids,
                    start=1,
                )
            ],
            "injected_results": [result(item_id) for item_id in injected_ids],
            "usage": {
                "usage.complete": True,
                "cost.complete": True,
                "embedding_calls": 1,
                "semantic_calls": 2,
                "reranking_calls": 3,
                "cost_cny": 0.25,
            },
            "metadata": {
                "query_class": query_class,
                "repository_id": query["repository_id"],
                "abstained": abstained,
                "abstention_reason": abstention_reason,
                "anonymous_candidate_ids": ranked_ids,
                "anonymous_injected_ids": injected_ids,
                "memory_off_operation_calls": 0,
                "retrieval_latency_ms": 10.0,
                "production_evidence_complete": False,
            },
        }

    metrics, valid, production = _reduce_retrieval(
        contract,
        records,
    )

    assert valid is True
    assert production is False
    assert metrics["codecairn_retrieval_v2.positive_hit_at_5"] == 1.0
    assert metrics["codecairn_retrieval_v2.positive_recall_at_5"] == pytest.approx(
        sum(expected_positive_recall) / len(expected_positive_recall)
    )
    assert metrics["codecairn_retrieval_v2.positive_recall_at_5"] < metrics["codecairn_retrieval_v2.positive_hit_at_5"]
    assert metrics["codecairn_retrieval_v2.positive_mrr"] == pytest.approx(
        sum(expected_positive_mrr) / len(expected_positive_mrr)
    )
    assert metrics["codecairn_retrieval_v2.injected_precision"] == pytest.approx(
        expected_injected_relevant / expected_injected_total
    )
    assert metrics["codecairn_retrieval_v2.hard_negative_any_injection_rate"] == pytest.approx(1 / 20)
    assert metrics["codecairn_retrieval_v2.mean_irrelevant_items_per_hard_negative"] == pytest.approx(2 / 20)
    assert metrics["codecairn_retrieval_v2.stale_any_injection_rate"] == pytest.approx(1 / 15)
    assert metrics["codecairn_retrieval_v2.cross_repository_any_injection_rate"] == pytest.approx(1 / 15)
    assert metrics["codecairn_retrieval_v2.embedding_calls"] == 100
    assert metrics["codecairn_retrieval_v2.semantic_calls"] == 200
    assert metrics["codecairn_retrieval_v2.reranking_calls"] == 300
    assert metrics["codecairn_retrieval_v2.cost_cny"] == pytest.approx(
        25.0,
    )

    malformed = deepcopy(records)
    malformed[partial_recall_key]["ranked_results"][0]["score"] = "invalid"
    _, malformed_valid, _ = _reduce_retrieval(
        contract,
        malformed,
    )
    assert malformed_valid is False
    non_finite = deepcopy(records)
    non_finite[partial_recall_key]["ranked_results"][0]["score"] = float(
        "nan",
    )
    _, non_finite_valid, _ = _reduce_retrieval(
        contract,
        non_finite,
    )
    assert non_finite_valid is False
    spoofed_metadata = deepcopy(records)
    spoofed_metadata[first_stale]["injected_results"][0]["validity_state"] = "active"
    _, spoofed_metadata_valid, _ = _reduce_retrieval(
        contract,
        spoofed_metadata,
    )
    assert spoofed_metadata_valid is False
    metadata_mutations = (
        ("query_class", "wrong"),
        ("repository_id", "wrong/repository"),
        ("anonymous_candidate_ids", []),
        ("anonymous_injected_ids", []),
        (
            "abstained",
            not records[partial_recall_key]["metadata"]["abstained"],
        ),
        ("abstention_reason", ""),
        ("memory_off_operation_calls", -1),
    )
    for field, value in metadata_mutations:
        mismatched_metadata = deepcopy(records)
        mismatched_metadata[partial_recall_key]["metadata"][field] = value
        _, metadata_valid, _ = _reduce_retrieval(
            contract,
            mismatched_metadata,
        )
        assert metadata_valid is False, field

    unknown = deepcopy(records)
    unknown[first_hard_negative]["injected_results"][0]["item_id"] = "unknown-corpus-item"
    _, unknown_valid, _ = _reduce_retrieval(contract, unknown)
    assert unknown_valid is False


def test_codecairn_task_effect_interval_metrics_export_task_provenance() -> None:
    definition = create_codecairn_task_effect_pack(
        SimpleNamespace(kind="scripted/task-effect-v2"),
    ).definition()
    contract = _manifest_contract(
        {
            "pack_definitions": [to_primitive(definition)],
            "spec": {
                "repetitions": 2,
                "identity": {
                    "production_evidence_complete": False,
                },
            },
            "plan_digest": "a" * 64,
        }
    )
    assert contract is not None
    task_ids = tuple(sorted(contract.task_payloads))
    paired_metric_names = (
        "main_agent_input_tokens",
        "main_agent_output_tokens",
        "trial_total_tokens",
        "repository_read_calls",
        "repository_search_calls",
        "repository_read_search_calls",
        "test_calls",
        "write_calls",
        "tool_calls",
        "repeated_repository_reads",
        "end_to_end_latency_ms",
        "retrieval_latency_ms",
        "total_cost_cny",
    )
    paired_values = {
        metric: {
            task_id: (
                (10.0, 9.0),
                (10.0, 9.0),
            )
            for task_id in task_ids
        }
        for metric in paired_metric_names
    }
    observations = _PairObservations(
        valid_pairs=48,
        variant_axis_valid=True,
        task_digest_complete=True,
        usage_cost_complete=True,
        memory_off_operation_calls=0,
        production_evidence_complete=False,
        control_records=(),
        treatment_records=(),
        pass_deltas={task_id: (0.0, 0.0) for task_id in task_ids},
        control_passes={task_id: (1.0, 1.0) for task_id in task_ids},
        treatment_passes={task_id: (1.0, 1.0) for task_id in task_ids},
        paired_values=paired_values,
    )

    metrics, clustered_complete = _reduce_task_metrics(
        contract,
        observations,
    )

    assert clustered_complete is True
    representative_intervals = (
        "codecairn_task_success_v2.paired_task_pass_delta",
        ("codecairn_efficiency_v2.main_agent_input_tokens_paired_delta"),
        "codecairn_efficiency_v2.tool_calls_paired_delta",
        "codecairn_efficiency_v2.end_to_end_latency_ms_overhead",
        "codecairn_efficiency_v2.total_cost_cny_overhead",
    )
    for prefix in representative_intervals:
        assert metrics[f"{prefix}_tasks"] == 24
        assert metrics[f"{prefix}_unit"] == "task"
        assert metrics[f"{prefix}_samples"] == 10_000
        assert isinstance(metrics[f"{prefix}_seed"], int)


def test_codecairn_task_effect_trial_usage_rejects_negative_values() -> None:
    definition = create_codecairn_task_effect_pack(
        SimpleNamespace(kind="scripted/task-effect-v2"),
    ).definition()
    contract = _manifest_contract(
        {
            "pack_definitions": [to_primitive(definition)],
            "spec": {
                "repetitions": 2,
                "identity": {
                    "production_evidence_complete": False,
                },
            },
            "plan_digest": "c" * 64,
        }
    )
    assert contract is not None
    records: dict[tuple[str, int, str], dict[str, object]] = {}
    for key in contract.planned_trial_keys:
        task_id, _repetition, _variant_id = key
        payload = contract.task_payloads[task_id]
        metrics: dict[str, object] = {
            "task_effect.fixture_digest": payload["fixture_digest"],
            "task_effect.expected_digest": payload["expected_digest"],
            "task_effect.verifier_id": payload["verifier"],
            "task_effect.fixture_reset_complete": True,
            "task_effect.production_evidence_complete": False,
            "usage.complete": True,
            "cost.complete": True,
            "usage.main_agent_input_tokens": 0,
            "usage.main_agent_output_tokens": 0,
            "usage.trial_total_tokens": 0,
            "runtime.repository_read_calls": 0,
            "runtime.repository_search_calls": 0,
            "runtime.test_calls": 0,
            "runtime.write_calls": 0,
            "runtime.tool_calls": 0,
            "runtime.repeated_repository_reads": 0,
            "runtime.end_to_end_latency_ms": 0.0,
            "runtime.retrieval_latency_ms": 0.0,
            "cost.provider_cny": 0.0,
            "cost.codecairn_cny": 0.0,
            "cost.total_cny": 0.0,
            "codecairn.memory_off_operation_calls": 0,
            "codecairn.memory_hits": 0,
            "codecairn.injected_items": 0,
            "codecairn.abstentions": 0,
            "codecairn.memory_failures": 0,
        }
        mutation = payload.get("parent_owned_mutation")
        if isinstance(mutation, Mapping):
            metrics.update(
                {
                    "task_effect.parent_owned_setup_complete": True,
                    ("task_effect.parent_owned_prior_fixture_digest"): mutation["prior_fixture_digest"],
                    "task_effect.evaluated_fixture_digest": (mutation["evaluated_fixture_digest"]),
                    ("task_effect.parent_owned_mutation_contract_digest"): mutation["contract_digest"],
                }
            )
        records[key] = {"metrics": metrics}

    digests, usage, production, operations = _trial_evidence_state(contract, records)
    assert digests is True
    assert usage is True
    assert production is False
    assert operations == 0

    negative_usage = deepcopy(records)
    first_key = min(contract.planned_trial_keys)
    negative_usage[first_key]["metrics"]["usage.main_agent_input_tokens"] = -1
    _, negative_valid, _, _ = _trial_evidence_state(
        contract,
        negative_usage,
    )
    assert negative_valid is False

    offset_operations = deepcopy(records)
    control_keys = sorted(key for key in contract.planned_trial_keys if key[2] == "memory_off")
    offset_operations[control_keys[0]]["metrics"]["codecairn.memory_off_operation_calls"] = -1
    offset_operations[control_keys[1]]["metrics"]["codecairn.memory_off_operation_calls"] = 1
    _, offset_valid, _, _ = _trial_evidence_state(
        contract,
        offset_operations,
    )
    assert offset_valid is False


@pytest.mark.asyncio
async def test_codecairn_task_effect_scripted_claim_states_are_independent(
    tmp_path: Path,
) -> None:
    runner = ScriptedTaskEffectRunner()
    registry = PackRegistry()
    registry.register(
        create_codecairn_task_effect_calibration_pack(
            runner,
        )
    )
    spec = build_codecairn_task_effect_calibration_spec(
        tmp_path / "evidence",
    )

    ref = await run_picobench(spec, registry=registry)
    summary = json.loads(
        (ref.root / "summary.json").read_text(
            encoding="utf-8",
        )
    )

    assert runner.trial_calls == 12
    assert runner.retrieval_calls == 10
    assert summary["ship_complete"] is True
    assert summary["measurement_valid"] is True
    assert summary["retrieval_claim_eligible"] is False
    assert summary["task_success_claim_eligible"] is False
    assert summary["efficiency_claim_eligible"] is False
    assert summary["metrics"]["codecairn_task_effect_v2.production_evidence_complete"] is False
    assert summary["metrics"]["codecairn_retrieval_v2.claim_eligible"] is False
    assert summary["metrics"]["codecairn_task_success_v2.claim_eligible"] is False
    assert summary["metrics"]["codecairn_efficiency_v2.claim_eligible"] is False
    assert summary["metrics"]["codecairn_retrieval_v2.memory_off_operation_calls"] == 0
    trial_records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in ref.root.glob(
            "trials/**/trial-record.json",
        )
    ]
    assert len(trial_records) == 12
    for record in trial_records:
        assert len(record["artifact_refs"]) == 1
        artifact_ref = record["artifact_refs"][0]
        artifact = (spec.output_root / artifact_ref).resolve()
        assert artifact.is_relative_to(ref.root.resolve())
        assert artifact.is_file()
        assert "/workspace/" in artifact_ref
        assert "workspace-" not in artifact_ref


@pytest.mark.parametrize(
    (
        "retrieval_eligible",
        "task_eligible",
        "efficiency_eligible",
        "eligible_metrics",
    ),
    (
        (
            True,
            True,
            False,
            {
                "codecairn_retrieval_v2.positive_hit_at_5": 0.9,
                "codecairn_task_success_v2.net_gained_tasks": 3,
            },
        ),
        (
            True,
            False,
            True,
            {
                "codecairn_retrieval_v2.positive_hit_at_5": 0.9,
                ("codecairn_efficiency_v2.best_rediscovery_improvement_percent"): 20.0,
            },
        ),
    ),
    ids=(
        "task-without-efficiency",
        "efficiency-without-task",
    ),
)
def test_codecairn_task_effect_report_preserves_independent_claim_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retrieval_eligible: bool,
    task_eligible: bool,
    efficiency_eligible: bool,
    eligible_metrics: dict[str, float | int],
) -> None:
    experiment_id = "b" * 64
    ref = ExperimentRef(
        experiment_id=experiment_id,
        root=tmp_path / experiment_id,
    )
    rules = (
        ClaimRule(
            rule_id="v2-retrieval-hit",
            metric=("codecairn_retrieval_v2.positive_hit_at_5"),
            operator="ge",
            threshold=0.8,
        ),
        ClaimRule(
            rule_id="v2-task-gain",
            metric=("codecairn_task_success_v2.net_gained_tasks"),
            operator="ge",
            threshold=3,
        ),
        ClaimRule(
            rule_id="v2-efficiency-improvement",
            metric=("codecairn_efficiency_v2.best_rediscovery_improvement_percent"),
            operator="ge",
            threshold=15,
        ),
    )
    ArtifactStore(ref).freeze_manifest(
        {
            "experiment_id": experiment_id,
            "plan_digest": experiment_id,
            "spec": {
                "claim_rules": to_primitive(rules),
            },
            "pack_definitions": [
                {
                    "pack_id": "codecairn-task-effect-v2",
                    "identity": {
                        "report_title": ("PicoBench task-effect v2 Report"),
                    },
                }
            ],
        }
    )
    metrics = {
        "codecairn_retrieval_v2.claim_eligible": (retrieval_eligible),
        "codecairn_retrieval_v2.positive_hit_at_5": 0.9,
        "codecairn_task_success_v2.claim_eligible": (task_eligible),
        "codecairn_task_success_v2.net_gained_tasks": 3,
        "codecairn_efficiency_v2.claim_eligible": (efficiency_eligible),
        ("codecairn_efficiency_v2.best_rediscovery_improvement_percent"): 20.0,
    }
    reduction = Reduction(
        experiment_id=experiment_id,
        ship_complete=True,
        measurement_valid=True,
        planned_trials=0,
        terminal_trials=0,
        planned_retrieval_cases=0,
        terminal_retrieval_cases=0,
        selected_status_counts={},
        first_attempt_status_counts={},
        all_attempt_status_counts={},
        retrieval_status_counts={},
        retrieval_first_attempt_status_counts={},
        retrieval_all_attempt_status_counts={},
        pair_summaries=(),
        metrics=metrics,
        findings=(),
    )
    monkeypatch.setattr(
        "benchmarks.picobench.report.reduce_experiment",
        lambda _ref: reduction,
    )

    report = rebuild_full_report(ref)
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
    expected_states = {
        "retrieval_claim_eligible": retrieval_eligible,
        "task_success_claim_eligible": task_eligible,
        "efficiency_claim_eligible": efficiency_eligible,
    }
    expected_reducer_states = {
        "codecairn_retrieval_v2.claim_eligible": (retrieval_eligible),
        "codecairn_task_success_v2.claim_eligible": (task_eligible),
        "codecairn_efficiency_v2.claim_eligible": (efficiency_eligible),
    }

    assert report.retrieval_claim_eligible is retrieval_eligible
    assert report.task_success_claim_eligible is task_eligible
    assert report.efficiency_claim_eligible is efficiency_eligible
    assert {name: summary["metrics"][name] for name in expected_reducer_states} == expected_reducer_states
    assert {name: summary[name] for name in expected_states} == expected_states
    assert {name: cv_metrics[name] for name in expected_states} == expected_states
    assert cv_metrics["eligible_metrics"] == eligible_metrics


def test_codecairn_memory_pack_freezes_single_axis_and_disjoint_tasks() -> None:
    runner = ScriptedCodeCairnMemoryRunner()
    formal = create_codecairn_memory_pack(runner).definition()
    calibration = create_codecairn_memory_calibration_pack(runner).definition()

    assert formal.pack_id == "codecairn-memory-effect-v1"
    assert calibration.pack_id == "codecairn-memory-effect-calibration-v1"
    assert len(formal.tasks) == 8
    assert len(calibration.tasks) == 2
    assert {task.task_id for task in formal.tasks}.isdisjoint(task.task_id for task in calibration.tasks)
    assert [variant.variant_id for variant in formal.variants] == [
        "memory_off",
        "codecairn",
    ]
    assert [
        (
            pair.treatment_axis,
            pair.control_variant_id,
            pair.treatment_variant_id,
        )
        for pair in formal.pairs
    ] == [("memory_backend", "memory_off", "codecairn")]
    assert dict(formal.variants[0].settings) == {
        **dict(formal.variants[1].settings),
        "memory_backend": None,
    } | {"memory_backend": None}
    assert dict(formal.variants[1].settings)["memory_backend"] == "codecairn"
    assert dict(formal.variants[1].settings)["tool_surface"] == ["joint_write_result"]
    assert formal.identity["claim_reducer"] == "codecairn_memory_v1"
    assert formal.identity["installed_adapter_required"] is True
    assert formal.identity["fresh_process_required"] is True


def test_codecairn_memory_tasks_have_external_verifier_contract() -> None:
    tasks = load_codecairn_memory_tasks("formal")

    assert len(tasks) == 8
    for task in tasks:
        assert task.prior_session_id != task.evaluation_session_id
        assert task.output_file.endswith(".json")
        assert task.expected_key
        assert task.expected_value
        assert task.memory_query
        assert task.learning_prompt
        assert task.evaluation_prompt


def test_codecairn_memory_reducer_allows_valid_negative_ship() -> None:
    trials, pairs = _records(
        control_passes=set(),
        treatment_passes=set(),
    )

    metrics = reduce_codecairn_memory_claims(trials, pairs)

    assert metrics["codecairn_memory.ship_complete"] is True
    assert metrics["codecairn_memory.measurement_valid"] is True
    assert metrics["codecairn_memory.positive_claim_eligible"] is False
    assert metrics["codecairn_memory.valid_pairs"] == 16
    assert metrics["codecairn_memory.success_delta_pp"] == 0.0


def test_codecairn_memory_reducer_exports_only_preregistered_uplift() -> None:
    control_passes = {
        ("cc-memory-formal-01", 0),
        ("cc-memory-formal-02", 0),
        ("cc-memory-formal-03", 0),
        ("cc-memory-formal-04", 0),
    }
    treatment_passes = {
        *control_passes,
        ("cc-memory-formal-01", 1),
        ("cc-memory-formal-02", 1),
        ("cc-memory-formal-03", 1),
        ("cc-memory-formal-04", 1),
    }
    trials, pairs = _records(
        control_passes=control_passes,
        treatment_passes=treatment_passes,
    )

    metrics = reduce_codecairn_memory_claims(trials, pairs)

    assert metrics["codecairn_memory.ship_complete"] is True
    assert metrics["codecairn_memory.measurement_valid"] is True
    assert metrics["codecairn_memory.positive_claim_eligible"] is True
    assert metrics["codecairn_memory.net_verifier_gains"] == 4
    assert metrics["codecairn_memory.positive_tasks"] == 4
    assert metrics["codecairn_memory.recall_at_5"] == 1.0
    assert metrics["codecairn_memory.irrelevant_injection_rate"] == 0.0
    assert metrics["codecairn_memory.cross_repository_leakage_count"] == 0
    assert metrics["codecairn_memory.main_agent_input_token_delta"] == 0.0
    assert metrics["codecairn_memory.control_p95_latency_ms"] == 100.0
    assert metrics["codecairn_memory.treatment_p95_latency_ms"] == 100.0


def test_codecairn_metrics_are_not_exportable_without_pack_positive_gate() -> None:
    metric = "codecairn_memory.success_delta_pp"

    assert (
        _claim_metric_exportable(
            metric,
            {
                "codecairn_memory.positive_claim_eligible": False,
                metric: 25.0,
            },
        )
        is False
    )
    assert (
        _claim_metric_exportable(
            metric,
            {
                "codecairn_memory.positive_claim_eligible": True,
                metric: 25.0,
            },
        )
        is True
    )


def test_generic_reducer_dispatches_codecairn_claim_reducer() -> None:
    trials, pairs = _records(
        control_passes=set(),
        treatment_passes=set(),
    )
    trial_map = {
        (
            str(record["key"]["pack_id"]),
            str(record["key"]["task_id"]),
            int(record["key"]["repetition"]),
            str(record["key"]["variant_id"]),
        ): record
        for record in trials
    }
    pair_map = {
        (
            str(record["key"]["pack_id"]),
            str(record["key"]["treatment_axis"]),
            str(record["key"]["task_id"]),
            int(record["key"]["repetition"]),
        ): record
        for record in pairs
    }

    metrics, valid, findings = _reduce_declared_pack_claims(
        manifest={"pack_definitions": [{"identity": {"claim_reducer": "codecairn_memory_v1"}}]},
        trial_records=trial_map,
        retrieval_records={},
        pair_records=pair_map,
    )

    assert valid is True
    assert findings == ()
    assert metrics["codecairn_memory.measurement_valid"] is True


def test_codecairn_campaign_freezes_budget_and_denominators() -> None:
    suite = load_campaign_suite(
        Path("benchmarks/picobench/suites/codecairn_memory_effect.yaml"),
    )

    assert suite.provider.name == "deepseek"
    assert suite.provider.model == "deepseek-v4-flash"
    assert suite.calibration.expected_trials == 4
    assert suite.formal.expected_trials == 32
    assert suite.budget.hard_cap_cny == 99.9
    assert suite.budget.max_provider_calls_per_trial == 7
    assert suite.budget.max_input_tokens_per_call == 16_000
    assert suite.budget.max_output_tokens_per_call == 2_048
    assert _provider_call_envelope("agent") == (16_000, 1_024)
    assert _provider_call_envelope("semantic") == (8_000, 2_048)
    estimate = estimate_worst_case_cost(
        suite,
        modes=(CampaignMode.CALIBRATION, CampaignMode.FORMAL),
    )
    assert estimate.estimated_cny < suite.budget.hard_cap_cny


def test_codecairn_profile_evidence_reads_installed_git_binding(
    tmp_path: Path,
) -> None:
    binding = tmp_path / "git-common-dir" / "codecairn.toml"
    binding.parent.mkdir()
    binding.write_text(
        '[retrieval]\nprofile = "fastembed"\n\n[semantic]\nprofile = "deepseek"\n',
        encoding="utf-8",
    )
    initialization = {
        "config": str(binding),
        "repo_key": "picobench/task-01",
        "retrieval": {
            "profile": "fastembed",
        },
        "semantic": "deepseek",
    }
    semantic_report = {
        "semantic": {
            "completed": 1,
            "failed": 0,
            "pending": 0,
        }
    }

    assert _profile_complete(
        initialization,
        semantic_report,
        expected_repo_key="picobench/task-01",
    )
    assert not _profile_complete(
        {
            **initialization,
            "repo_key": "picobench/other-task",
        },
        semantic_report,
        expected_repo_key="picobench/task-01",
    )
    assert not _profile_complete(
        {
            **initialization,
            "config": str(tmp_path / "missing.toml"),
        },
        semantic_report,
        expected_repo_key="picobench/task-01",
    )
    assert not _profile_complete(
        initialization,
        {
            "semantic": {
                "completed": 0,
                "failed": 1,
                "pending": 0,
            }
        },
        expected_repo_key="picobench/task-01",
    )


def test_codecairn_cli_recall_observer_reads_context_trace() -> None:
    assert _rendered_memory_ids(
        {
            "sidecar": {
                "context_trace": {
                    "rendered_memory_ids": [
                        "memory-active",
                        "memory-successor",
                    ]
                }
            }
        }
    ) == {
        "memory-active",
        "memory-successor",
    }
    assert (
        _rendered_memory_ids(
            {
                "sidecar": {
                    "rendered_memory_ids": [
                        "obsolete-root-shape",
                    ]
                }
            }
        )
        == set()
    )
    assert _rendered_memory_ids(
        {
            "sidecar": {
                "context_trace": {
                    "rendered_memory_ids": [
                        "memory-active",
                        42,
                    ]
                }
            }
        }
    ) == {"memory-active"}


def test_codecairn_model_prefetch_uses_local_retrieval_without_semantic_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def init_git(repository: Path) -> None:
        repository.mkdir(parents=True)
        (repository / ".git").mkdir()

    def initialize(
        executable: Path,
        repository: Path,
        runtime_root: Path,
        *,
        repo_key: str,
        environment: dict[str, str],
    ) -> dict[str, object]:
        calls.append(
            {
                "executable": executable,
                "repository": repository,
                "repo_key": repo_key,
                "runtime_root": runtime_root,
                "model_cache": environment["CODECAIRN_MODEL_CACHE"],
                "semantic_endpoint": environment["CODECAIRN_SEMANTIC_ENDPOINT"],
                "semantic_model": environment["CODECAIRN_SEMANTIC_MODEL"],
                "semantic_api_key": environment.get("CODECAIRN_SEMANTIC_API_KEY"),
            }
        )
        return {
            "provider_state": {
                "retrieval": "fastembed",
                "retrieval_state": "live_verified",
            }
        }

    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._init_git_repository",
        init_git,
    )
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._initialize_codecairn",
        initialize,
    )
    model_cache = tmp_path / "model-cache"
    model_cache.mkdir()

    evidence = _prefetch_codecairn_models(
        Path("/venv/bin/codecairn"),
        tmp_path / "prefetch",
        model_cache,
    )

    assert evidence == {
        "retrieval": "fastembed",
        "retrieval_state": "live_verified",
    }
    assert calls == [
        {
            "executable": Path("/venv/bin/codecairn"),
            "repository": tmp_path / "prefetch" / "repository",
            "repo_key": "picobench/model-prefetch",
            "runtime_root": tmp_path / "prefetch" / "runtime",
            "model_cache": str(model_cache),
            "semantic_endpoint": "https://api.deepseek.com",
            "semantic_model": "deepseek-v4-flash",
            "semantic_api_key": None,
        }
    ]


def test_codecairn_model_prefetch_timeout_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._init_git_repository",
        lambda repository: repository.mkdir(parents=True),
    )

    def timeout(*args, **kwargs):
        del args, kwargs
        raise subprocess.TimeoutExpired(
            cmd=("codecairn", "init"),
            timeout=300,
        )

    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._initialize_codecairn",
        timeout,
    )
    model_cache = tmp_path / "model-cache"
    model_cache.mkdir()

    with pytest.raises(
        PairIntegrityError,
        match="retrieval model prefetch timed out",
    ):
        _prefetch_codecairn_models(
            Path("/venv/bin/codecairn"),
            tmp_path / "prefetch",
            model_cache,
        )


def test_codecairn_runner_prefetches_before_installed_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class GuardedProvider:
        ledger = object()

    def install(root: Path, **kwargs) -> Path:
        del kwargs
        events.append("install")
        environment = root / "environment"
        (environment / "bin").mkdir(parents=True)
        return environment

    def copy_worker(source: Path, target: Path) -> None:
        del source
        events.append("copy_worker")
        target.write_text("worker", encoding="utf-8")

    def prefetch(
        executable: Path,
        root: Path,
        model_cache: Path,
    ) -> dict[str, str]:
        del executable, root, model_cache
        events.append("prefetch")
        return {
            "retrieval": "fastembed",
            "retrieval_state": "live_verified",
        }

    def identity(*args, **kwargs) -> dict[str, str]:
        del args, kwargs
        events.append("identity")
        return {"distribution": "installed"}

    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production.BudgetGuardedProvider",
        GuardedProvider,
    )
    monkeypatch.setattr(
        ProductionCodeCairnMemoryRunner,
        "_validate_inputs",
        lambda self: events.append("validate"),
    )
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._install_pair",
        install,
    )
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production.shutil.copy2",
        copy_worker,
    )
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._provider_api_key",
        lambda config, provider_name: events.append("credential") or "provider-secret",
    )
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._prefetch_codecairn_models",
        prefetch,
    )
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._worker",
        identity,
    )
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._read_json",
        lambda path: {
            "audit": {
                "codecairn": {
                    "commit": "c" * 40,
                }
            }
        },
    )
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._sha256",
        lambda path: "d" * 64,
    )

    runner = ProductionCodeCairnMemoryRunner(
        config=object(),
        pico_config=object(),
        provider=GuardedProvider(),
        pico_wheel=tmp_path / "pico.whl",
        codecairn_wheel=tmp_path / "codecairn.whl",
        pair_manifest=tmp_path / "pair.json",
        continuity_summary=tmp_path / "continuity.json",
        benchmark_source_root=tmp_path,
    )

    assert events == [
        "validate",
        "install",
        "copy_worker",
        "credential",
        "prefetch",
        "identity",
    ]
    runner._temporary.cleanup()

    events.clear()

    def failed_prefetch(*args, **kwargs):
        del args, kwargs
        events.append("prefetch")
        raise PairIntegrityError("prefetch failed")

    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._prefetch_codecairn_models",
        failed_prefetch,
    )

    with pytest.raises(
        PairIntegrityError,
        match="prefetch failed",
    ):
        ProductionCodeCairnMemoryRunner(
            config=object(),
            pico_config=object(),
            provider=GuardedProvider(),
            pico_wheel=tmp_path / "pico.whl",
            codecairn_wheel=tmp_path / "codecairn.whl",
            pair_manifest=tmp_path / "pair.json",
            continuity_summary=tmp_path / "continuity.json",
            benchmark_source_root=tmp_path,
        )

    assert events == [
        "validate",
        "install",
        "copy_worker",
        "credential",
        "prefetch",
    ]


def test_codecairn_runner_wires_role_specific_provider_envelopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy_calls: list[dict[str, object]] = []

    class Ledger:
        def snapshot(self) -> object:
            return object()

    class Proxy:
        def __init__(self, root: Path, **kwargs) -> None:
            proxy_calls.append(
                {
                    "root": root.name,
                    "role": kwargs["role"],
                    "maximum_input_tokens": kwargs["maximum_input_tokens"],
                    "maximum_output_tokens": kwargs["maximum_output_tokens"],
                }
            )

        def __enter__(self):
            raise PairIntegrityError("stop after proxy construction")

        def __exit__(self, *args: object) -> None:
            del args

    definition = create_codecairn_memory_pack(
        ScriptedCodeCairnMemoryRunner(),
    ).definition()
    task = definition.tasks[0]
    variant = next(item for item in definition.variants if item.variant_id == "codecairn")
    budget = SimpleNamespace(
        max_provider_calls_per_trial=7,
        max_input_tokens_per_call=16_000,
        max_output_tokens_per_call=2_048,
    )
    execution = SimpleNamespace(
        provider_call_max_attempts=2,
        provider_trial_budget_for=lambda pack_id: budget,
    )
    experiment = SimpleNamespace(
        execution=execution,
        output_root=tmp_path,
    )
    context = SimpleNamespace(
        block_attempt=1,
        experiment=experiment,
        experiment_id="provider-envelope",
        key=SimpleNamespace(
            pack_id=definition.pack_id,
            repetition=0,
            task_id=task.task_id,
            variant_id=variant.variant_id,
        ),
        task=task,
        variant=variant,
    )
    runner = ProductionCodeCairnMemoryRunner.__new__(
        ProductionCodeCairnMemoryRunner,
    )
    runner._codecairn = Path("/venv/bin/codecairn")
    runner._ledger = Ledger()
    runner._upstream_api_key = "provider-secret"
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._MeteredSemanticProxy",
        Proxy,
    )
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._init_git_repository",
        lambda path: None,
    )
    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._seed_local_skill",
        lambda path: None,
    )

    result = runner._run_sync(context)

    assert proxy_calls == [
        {
            "root": "agent-proxy",
            "role": "agent",
            "maximum_input_tokens": 16_000,
            "maximum_output_tokens": 1_024,
        },
        {
            "root": "semantic-proxy",
            "role": "semantic",
            "maximum_input_tokens": 8_000,
            "maximum_output_tokens": 2_048,
        },
    ]
    assert result.findings == ("codecairn_trial_infrastructure:stop after proxy construction",)

    mismatched_values = vars(context).copy()
    mismatched_values["experiment"] = SimpleNamespace(
        execution=SimpleNamespace(
            provider_call_max_attempts=2,
            provider_trial_budget_for=lambda pack_id: SimpleNamespace(
                max_provider_calls_per_trial=7,
                max_input_tokens_per_call=16_000,
                max_output_tokens_per_call=1_024,
            ),
        ),
        output_root=tmp_path,
    )
    mismatched = SimpleNamespace(**mismatched_values)

    rejected = runner._run_sync(mismatched)

    assert rejected.findings == ("codecairn_provider_budget_not_frozen",)
    assert len(proxy_calls) == 2


def test_codecairn_semantic_processing_retries_failed_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reports = [
        {
            "semantic": {
                "completed": 0,
                "failed": 1,
                "pending": 0,
            }
        },
        {
            "semantic": {
                "completed": 1,
                "failed": 0,
                "pending": 0,
            }
        },
    ]
    commands: list[tuple[str, ...]] = []

    def command_json(
        command: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> dict[str, object]:
        assert cwd == tmp_path
        assert env == {"PATH": "/bin"}
        commands.append(command)
        return reports.pop(0)

    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._command_json",
        command_json,
    )

    final, attempts = _process_semantic_with_retry(
        Path("/venv/bin/codecairn"),
        tmp_path,
        {"PATH": "/bin"},
        worker_id="memory-worker",
    )

    assert final["semantic"]["completed"] == 1
    assert len(attempts) == 2
    assert "--retry-failed" not in commands[0]
    assert "--retry-failed" in commands[1]


def test_codecairn_semantic_processing_stops_after_three_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def command_json(
        command: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> dict[str, object]:
        del cwd, env
        commands.append(command)
        return {
            "semantic": {
                "completed": 0,
                "failed": 1,
                "pending": 0,
            }
        }

    monkeypatch.setattr(
        "benchmarks.picobench.packs.codecairn_memory.production._command_json",
        command_json,
    )

    final, attempts = _process_semantic_with_retry(
        Path("/venv/bin/codecairn"),
        tmp_path,
        {"PATH": "/bin"},
        worker_id="memory-worker",
    )

    assert final["semantic"]["failed"] == 1
    assert len(attempts) == 3
    assert len(commands) == 3


def test_codecairn_calibration_reduction_is_measurement_valid() -> None:
    trials, pairs = _records(
        definition_kind="calibration",
        control_passes=set(),
        treatment_passes=set(),
    )

    metrics = reduce_codecairn_memory_claims(trials, pairs)

    assert metrics["codecairn_memory.planned_pairs"] == 2
    assert metrics["codecairn_memory.valid_pairs"] == 2
    assert metrics["codecairn_memory.ship_complete"] is True
    assert metrics["codecairn_memory.measurement_valid"] is True
    assert metrics["codecairn_memory.positive_claim_eligible"] is False


@pytest.mark.asyncio
async def test_codecairn_campaign_smoke_reuses_stage_a_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pico_wheel = tmp_path / "pico.whl"
    codecairn_wheel = tmp_path / "codecairn.whl"
    pair_manifest = tmp_path / "pair-manifest.json"
    continuity_summary = tmp_path / "continuity-summary.json"
    pico_wheel.write_bytes(b"pico")
    codecairn_wheel.write_bytes(b"codecairn")
    frozen_commit = "a" * 40
    monkeypatch.setattr(
        "benchmarks.picobench.codecairn_campaign._current_pico_commit",
        lambda: frozen_commit,
    )
    pair_manifest.write_text(
        json.dumps(
            {
                "audit": {
                    "codecairn": {
                        "wheel_sha256": hashlib.sha256(
                            codecairn_wheel.read_bytes(),
                        ).hexdigest(),
                    },
                    "current_pico": {
                        "commit": frozen_commit,
                        "wheel_sha256": hashlib.sha256(
                            pico_wheel.read_bytes(),
                        ).hexdigest(),
                    },
                },
                "schema": "pico.codecairn.pair-manifest.v1",
            }
        ),
        encoding="utf-8",
    )
    continuity_summary.write_text(
        json.dumps(
            {
                "paid_external_calls": 0,
                "pair_manifest_sha256": hashlib.sha256(
                    pair_manifest.read_bytes(),
                ).hexdigest(),
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "PICO_CODECAIRN_PICO_WHEEL",
        str(pico_wheel),
    )
    monkeypatch.setenv(
        "PICO_CODECAIRN_WHEEL",
        str(codecairn_wheel),
    )
    monkeypatch.setenv(
        "PICO_CODECAIRN_PAIR_MANIFEST",
        str(pair_manifest),
    )
    monkeypatch.setenv(
        "PICO_CODECAIRN_CONTINUITY_SUMMARY",
        str(continuity_summary),
    )

    outcome = await run_codecairn_campaign(
        CampaignMode.SMOKE,
        output_root=tmp_path / "output",
    )

    assert outcome.mode is CampaignMode.SMOKE
    assert outcome.preflight is None
    assert outcome.deterministic.passed is True
    assert outcome.deterministic.details["stage"] == "installed-codecairn-continuity"


def test_codecairn_campaign_rejects_wheel_substitution_after_stage_a(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pico_wheel = tmp_path / "pico.whl"
    codecairn_wheel = tmp_path / "codecairn.whl"
    pair_manifest = tmp_path / "pair-manifest.json"
    continuity_summary = tmp_path / "continuity-summary.json"
    pico_wheel.write_bytes(b"pico")
    codecairn_wheel.write_bytes(b"codecairn")
    frozen_commit = "a" * 40
    monkeypatch.setattr(
        "benchmarks.picobench.codecairn_campaign._current_pico_commit",
        lambda: frozen_commit,
    )
    pair_manifest.write_text(
        json.dumps(
            {
                "audit": {
                    "codecairn": {
                        "wheel_sha256": hashlib.sha256(
                            codecairn_wheel.read_bytes(),
                        ).hexdigest(),
                    },
                    "current_pico": {
                        "commit": frozen_commit,
                        "wheel_sha256": hashlib.sha256(
                            pico_wheel.read_bytes(),
                        ).hexdigest(),
                    },
                },
                "schema": "pico.codecairn.pair-manifest.v1",
            }
        ),
        encoding="utf-8",
    )
    continuity_summary.write_text(
        json.dumps(
            {
                "paid_external_calls": 0,
                "pair_manifest_sha256": hashlib.sha256(
                    pair_manifest.read_bytes(),
                ).hexdigest(),
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    for name, path in {
        "PICO_CODECAIRN_PICO_WHEEL": pico_wheel,
        "PICO_CODECAIRN_WHEEL": codecairn_wheel,
        "PICO_CODECAIRN_PAIR_MANIFEST": pair_manifest,
        "PICO_CODECAIRN_CONTINUITY_SUMMARY": continuity_summary,
    }.items():
        monkeypatch.setenv(name, str(path))
    pico_wheel.write_bytes(b"substituted")

    with pytest.raises(
        CampaignError,
        match="do not match the frozen Stage A pair",
    ):
        _campaign_paths()


def test_codecairn_campaign_rejects_stage_a_commit_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pico_wheel = tmp_path / "pico.whl"
    codecairn_wheel = tmp_path / "codecairn.whl"
    pair_manifest = tmp_path / "pair-manifest.json"
    continuity_summary = tmp_path / "continuity-summary.json"
    pico_wheel.write_bytes(b"pico")
    codecairn_wheel.write_bytes(b"codecairn")
    monkeypatch.setattr(
        "benchmarks.picobench.codecairn_campaign._current_pico_commit",
        lambda: "b" * 40,
    )
    pair_manifest.write_text(
        json.dumps(
            {
                "audit": {
                    "codecairn": {
                        "wheel_sha256": hashlib.sha256(
                            codecairn_wheel.read_bytes(),
                        ).hexdigest(),
                    },
                    "current_pico": {
                        "commit": "a" * 40,
                        "wheel_sha256": hashlib.sha256(
                            pico_wheel.read_bytes(),
                        ).hexdigest(),
                    },
                },
                "schema": "pico.codecairn.pair-manifest.v1",
            }
        ),
        encoding="utf-8",
    )
    continuity_summary.write_text(
        json.dumps(
            {
                "paid_external_calls": 0,
                "pair_manifest_sha256": hashlib.sha256(
                    pair_manifest.read_bytes(),
                ).hexdigest(),
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    for name, path in {
        "PICO_CODECAIRN_PICO_WHEEL": pico_wheel,
        "PICO_CODECAIRN_WHEEL": codecairn_wheel,
        "PICO_CODECAIRN_PAIR_MANIFEST": pair_manifest,
        "PICO_CODECAIRN_CONTINUITY_SUMMARY": continuity_summary,
    }.items():
        monkeypatch.setenv(name, str(path))

    with pytest.raises(
        CampaignError,
        match="do not match the frozen Stage A pair",
    ):
        _campaign_paths()


def test_codecairn_cv_metrics_exports_preregistered_derived_metrics(
    tmp_path: Path,
) -> None:
    suite = load_campaign_suite(
        Path(
            "benchmarks/picobench/suites/codecairn_memory_effect.yaml",
        )
    )
    metrics = {rule.metric: rule.threshold for rule in suite.claim_rules}
    metrics.update(
        {
            "codecairn_memory.positive_claim_eligible": True,
            "codecairn_memory.success_delta_pp": 25.0,
            "codecairn_memory.trial_total_token_delta_percent": -12.5,
            "codecairn_memory.treatment_p95_latency_ms": 1_250.0,
            "codecairn_memory.tool_call_delta": -0.5,
            "codecairn_memory.repeated_repository_read_delta": -1.0,
        }
    )
    report = FullReport(
        experiment_id="codecairn-cv",
        report_digest="digest",
        ship_complete=True,
        measurement_valid=True,
        positive_claim_eligible=True,
        planned_trials=32,
        terminal_trials=32,
        planned_retrieval_cases=0,
        terminal_retrieval_cases=0,
        metrics=metrics,
        pair_summaries=(),
        claim_results=tuple(
            ClaimRuleResult(
                rule_id=rule.rule_id,
                metric=rule.metric,
                passed=True,
                observed=metrics[rule.metric],
                threshold=rule.threshold,
                reason="passed",
            )
            for rule in suite.claim_rules
        ),
        selected_status_counts={"passed": 32},
        first_attempt_status_counts={"passed": 32},
        all_attempt_status_counts={"passed": 32},
        retrieval_status_counts={},
        retrieval_first_attempt_status_counts={},
        retrieval_all_attempt_status_counts={},
        findings=(),
    )
    ref = ExperimentRef(
        experiment_id=report.experiment_id,
        root=tmp_path,
    )

    _write_cv_metrics(ArtifactStore(ref), report)

    exported = json.loads(
        (tmp_path / "cv-metrics.json").read_text(
            encoding="utf-8",
        )
    )["eligible_metrics"]
    assert exported["codecairn_memory.success_delta_pp"] == 25.0
    assert exported["codecairn_memory.trial_total_token_delta_percent"] == -12.5
    assert exported["codecairn_memory.treatment_p95_latency_ms"] == 1_250.0
    assert exported["codecairn_memory.tool_call_delta"] == -0.5
    assert exported["codecairn_memory.repeated_repository_read_delta"] == -1.0


def test_codecairn_completion_handoff_is_immutable_and_portable(
    tmp_path: Path,
) -> None:
    pair_manifest = tmp_path / "pair-manifest.json"
    continuity_summary = tmp_path / "continuity-summary.json"
    campaign_artifact = tmp_path / "campaign.json"
    experiment_root = tmp_path / "formal"
    experiment_root.mkdir()
    pair_manifest.write_text(
        json.dumps(
            {
                "audit": {
                    "codecairn": {
                        "commit": "c" * 40,
                        "wheel_sha256": "codecairn-wheel",
                    },
                    "current_pico": {
                        "commit": "p" * 40,
                        "wheel_sha256": "pico-wheel",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    continuity_summary.write_text(
        json.dumps(
            {
                "j1": {"passed": True},
                "j2": {"passed": True},
                "paid_external_calls": 0,
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    campaign_artifact.write_text(
        json.dumps({"mode": "ship"}),
        encoding="utf-8",
    )
    (experiment_root / "summary.json").write_text(
        json.dumps({"ship_complete": True}),
        encoding="utf-8",
    )
    (experiment_root / "cv-metrics.json").write_text(
        json.dumps({"positive_claim_eligible": True}),
        encoding="utf-8",
    )
    report = FullReport(
        experiment_id="formal-experiment",
        report_digest="formal-report",
        ship_complete=True,
        measurement_valid=True,
        positive_claim_eligible=True,
        planned_trials=32,
        terminal_trials=32,
        planned_retrieval_cases=0,
        terminal_retrieval_cases=0,
        metrics={},
        pair_summaries=(),
        claim_results=(),
        selected_status_counts={"passed": 32},
        first_attempt_status_counts={"passed": 32},
        all_attempt_status_counts={"passed": 32},
        retrieval_status_counts={},
        retrieval_first_attempt_status_counts={},
        retrieval_all_attempt_status_counts={},
        findings=(),
    )
    outcome = CampaignOutcome(
        mode=CampaignMode.SHIP,
        deterministic=DeterministicGateResult(
            passed=True,
            details={"stage": "installed-codecairn-continuity"},
        ),
        preflight=None,
        experiments=(
            ExperimentRef(
                experiment_id=report.experiment_id,
                root=experiment_root,
            ),
        ),
        reports=(report,),
        campaign_artifact_path=str(campaign_artifact),
    )

    handoff = _write_completion_handoff(
        outcome,
        paths={
            "continuity_summary": continuity_summary,
            "pair_manifest": pair_manifest,
        },
    )

    payload = json.loads(handoff.read_text(encoding="utf-8"))
    assert handoff.name == "codecairn-v02-003-handoff.json"
    assert payload["kind"] == "codecairn.pico.joint-evidence.handoff"
    assert payload["deterministic"]["j1_passed"] is True
    assert payload["deterministic"]["j2_passed"] is True
    assert payload["result"] == {
        "measurement_valid": True,
        "positive_claim_eligible": True,
        "ship_complete": True,
    }
    assert payload["aggregate_digest"]
    assert str(tmp_path) not in handoff.read_text(encoding="utf-8")


def test_codecairn_usage_aggregation_fails_closed() -> None:
    valid = {
        "model_calls": [
            {
                "usage": {
                    "completion_tokens": 5,
                    "prompt_tokens": 20,
                    "total_tokens": 25,
                }
            }
        ]
    }

    assert (
        _aggregate_usage(
            valid,
            valid,
            [
                {
                    "accounting_valid": True,
                    "input_tokens": 11,
                    "output_tokens": 3,
                }
            ],
        )["complete"]
        is True
    )
    assert (
        _aggregate_usage(
            valid,
            {
                "model_calls": [
                    {
                        "usage": {
                            "completion_tokens": 5,
                            "prompt_tokens": 20,
                        }
                    }
                ]
            },
            [],
        )["complete"]
        is False
    )
    assert (
        _aggregate_usage(
            valid,
            valid,
            [
                {
                    "accounting_valid": False,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            ],
        )["complete"]
        is False
    )


def test_codecairn_trial_environment_does_not_inherit_unrelated_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")

    environment = _minimal_environment(
        tmp_path / "home",
        {"PICO_HOME": str(tmp_path / "pico-home")},
    )

    assert environment["HOME"] == str(tmp_path / "home")
    assert environment["PYTHONPATH"] == ""
    assert environment["PICO_HOME"] == str(tmp_path / "pico-home")
    assert "DEEPSEEK_API_KEY" not in environment
    assert "AWS_SECRET_ACCESS_KEY" not in environment


def test_codecairn_trial_config_contains_only_loopback_credential(
    tmp_path: Path,
) -> None:
    runner = ProductionCodeCairnMemoryRunner.__new__(
        ProductionCodeCairnMemoryRunner,
    )
    config = Config()
    config.agents.defaults.model = "deepseek/deepseek-v4-flash"
    config.providers.deepseek.api_key = "private-upstream-key"
    runner._config = config
    isolation = TrialIsolation.create(tmp_path, "trial")
    isolation.prepare()

    path = runner._write_trial_config(
        isolation,
        SimpleNamespace(
            endpoint="https://localhost:12345/v1",
            local_api_key="local-loopback-key",
        ),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    provider = payload["config"]["providers"]["deepseek"]

    assert provider["api_key"] == "local-loopback-key"
    assert provider["api_base"] == "https://localhost:12345/v1"
    assert "private-upstream-key" not in path.read_text(
        encoding="utf-8",
    )
    assert path.stat().st_mode & 0o777 == 0o600


def test_installed_worker_has_no_picobench_source_import() -> None:
    source = Path(
        "benchmarks/picobench/codecairn_installed_worker.py",
    ).read_text(encoding="utf-8")

    assert "benchmarks.picobench" not in source
    assert "benchmark_source_root" not in source


def test_installed_worker_exposes_result_tool_only_during_evaluation(
    tmp_path: Path,
) -> None:
    registered: list[object] = []
    runtime = SimpleNamespace(
        agent_loop=SimpleNamespace(
            tools=SimpleNamespace(
                register=registered.append,
            )
        )
    )

    assert (
        _register_result_tool(
            runtime,
            workspace=tmp_path,
            output_file="result.json",
            mode="learn",
        )
        is False
    )
    assert registered == []
    assert (
        _register_result_tool(
            runtime,
            workspace=tmp_path,
            output_file="result.json",
            mode="evaluate",
        )
        is True
    )
    assert [tool.name for tool in registered] == [
        "joint_write_result",
    ]


def test_codecairn_task_workspace_overrides_generic_file_guidance(
    tmp_path: Path,
) -> None:
    _seed_local_skill(tmp_path)

    policy = (tmp_path / "TOOLS.md").read_text(
        encoding="utf-8",
    )
    skill = (tmp_path / "skills" / "memory-evaluation" / "SKILL.md").read_text(encoding="utf-8")

    assert "Do not call read_file" in policy
    assert "learning request" in policy
    assert "evaluation request" in policy
    assert "do not guess" in skill


def test_codecairn_runtime_state_uses_spine_provider_failure() -> None:
    assert (
        _runtime_state(
            {
                "outcome": {"status": "failed"},
                "terminal_error": "provider_error:unknown",
            }
        )
        is TurnTerminalState.PROVIDER_FAILED
    )


def test_recall_provenance_binds_expected_hit_to_repository(
    tmp_path: Path,
) -> None:
    observation = tmp_path / "recall.json"
    observation.write_text(
        json.dumps(
            {
                "hits": [
                    {
                        "metadata": {
                            "index_cursor": "foreign-index",
                            "rendered_memory_ids": ["foreign"],
                            "repo_key": "other/repository",
                            "source_cursor": "foreign-source",
                            "source_uris": ["codecairn://foreign"],
                        }
                    },
                    {
                        "metadata": {
                            "index_cursor": "index-7",
                            "rendered_memory_ids": ["expected-memory"],
                            "repo_key": "picobench/task-001",
                            "source_cursor": "source-7",
                            "source_uris": ["codecairn://expected"],
                        }
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    provenance = _recall_provenance(
        observation,
        expected_memory_ids={"expected-memory"},
        expected_repo_key="picobench/task-001",
    )

    assert provenance["complete"] is True
    assert provenance["repo_key"] == "picobench/task-001"
    assert provenance["observed_expected_memory_ids"] == ["expected-memory"]
    assert provenance["source_uris"] == ["codecairn://expected"]


def test_semantic_proxy_trust_bundle_keeps_public_and_local_roots(
    tmp_path: Path,
) -> None:
    ledger = ProviderBudgetLedger(
        tmp_path / "budget.jsonl",
        ProviderBudgetConfig(
            hard_cap_cny=100,
            external_service_reserve_cny=0,
            max_total_request_attempts=1,
            max_input_tokens_per_call=8_000,
            max_output_tokens_per_call=1_024,
            input_cache_miss_usd_per_million=0.14,
            output_usd_per_million=0.28,
            conservative_usd_to_cny_multiplier=8,
        ),
    )
    proxy = _MeteredSemanticProxy(
        tmp_path / "proxy",
        api_key="private-upstream-key",
        upstream_endpoint="https://example.invalid",
        ledger=ledger,
        trial_id="semantic-trust",
        model="deepseek-v4-flash",
        maximum_input_tokens=8_000,
        maximum_output_tokens=1_024,
    )

    with proxy:
        public_context = ssl.create_default_context(
            cafile=certifi.where(),
        )
        combined_context = ssl.create_default_context(
            cafile=str(proxy.trust_bundle),
        )

    public_roots = set(
        public_context.get_ca_certs(binary_form=True),
    )
    combined_roots = set(
        combined_context.get_ca_certs(binary_form=True),
    )
    local_root = ssl.PEM_cert_to_DER_cert(
        proxy.certificate.read_text(),
    )
    assert public_roots <= combined_roots
    assert local_root in combined_roots
    assert proxy.trust_bundle.stat().st_mode & 0o777 == 0o600


def test_semantic_proxy_envelope_allows_codecairn_task_experience(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded: dict[str, object] = {}
    ledger = ProviderBudgetLedger(
        tmp_path / "budget.jsonl",
        ProviderBudgetConfig(
            hard_cap_cny=100,
            external_service_reserve_cny=0,
            max_total_request_attempts=1,
            max_input_tokens_per_call=8_000,
            max_output_tokens_per_call=2_048,
            input_cache_miss_usd_per_million=0.14,
            output_usd_per_million=0.28,
            conservative_usd_to_cny_multiplier=8,
        ),
    )
    proxy = _MeteredSemanticProxy(
        tmp_path / "proxy",
        api_key="private-upstream-key",
        upstream_endpoint="https://example.invalid",
        ledger=ledger,
        trial_id="semantic-envelope",
        model="deepseek-v4-flash",
        maximum_input_tokens=8_000,
        maximum_output_tokens=2_048,
    )

    def fake_post(*args, **kwargs):
        del args
        forwarded.update(kwargs["json"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": ('{"candidates":[],"evolution":[]}'),
                            "role": "assistant",
                        }
                    }
                ],
                "model": "deepseek-v4-flash",
                "usage": {
                    "completion_tokens": 8,
                    "prompt_tokens": 16,
                    "total_tokens": 24,
                },
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    payload = json.dumps(
        {
            "messages": [
                {
                    "content": "extract memory",
                    "role": "user",
                }
            ],
            "padding": "x" * (70 * 1024),
            "stream": False,
        }
    )
    with proxy:
        context = ssl.create_default_context(
            cafile=str(proxy.trust_bundle),
        )
        connection = http.client.HTTPSConnection(
            "localhost",
            proxy._server.server_port,
            context=context,
        )
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=payload,
            headers={
                "Authorization": (f"Bearer {proxy.local_api_key}"),
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        response.read()
        connection.close()

    assert response.status == 200
    assert forwarded["max_tokens"] == 2_048
    assert ledger.snapshot().provider_charged_cny > 0


def test_semantic_proxy_returns_classifiable_context_overflow(
    tmp_path: Path,
) -> None:
    ledger = ProviderBudgetLedger(
        tmp_path / "budget.jsonl",
        ProviderBudgetConfig(
            hard_cap_cny=100,
            external_service_reserve_cny=0,
            max_total_request_attempts=1,
            max_input_tokens_per_call=256,
            max_output_tokens_per_call=128,
            input_cache_miss_usd_per_million=0.14,
            output_usd_per_million=0.28,
            conservative_usd_to_cny_multiplier=8,
        ),
    )
    proxy = _MeteredSemanticProxy(
        tmp_path / "proxy",
        api_key="private-upstream-key",
        upstream_endpoint="https://example.invalid",
        ledger=ledger,
        trial_id="semantic-context-overflow",
        model="deepseek-v4-flash",
        maximum_input_tokens=256,
        maximum_output_tokens=128,
    )
    handler = _ProxyHandler()

    proxy._forward(
        handler,
        json.dumps(
            {
                "messages": [
                    {
                        "content": "x" * 1_000,
                        "role": "user",
                    }
                ],
                "stream": False,
            }
        ).encode(),
    )

    body = json.loads(handler.wfile.getvalue())
    assert handler.status_code == 413
    assert handler.error_code is None
    assert body["error"]["code"] == "context_length_exceeded"
    assert "maximum context length" in body["error"]["message"]
    assert LLMProvider.classify_error(
        content=json.dumps(body),
    ).should_compress
    assert ledger.snapshot().ledger_event_count == 0


def test_combined_proxy_trust_bundle_contains_both_local_roots(
    tmp_path: Path,
) -> None:
    ledger = ProviderBudgetLedger(
        tmp_path / "budget.jsonl",
        ProviderBudgetConfig(
            hard_cap_cny=100,
            external_service_reserve_cny=0,
            max_total_request_attempts=2,
            max_input_tokens_per_call=8_000,
            max_output_tokens_per_call=1_024,
            input_cache_miss_usd_per_million=0.14,
            output_usd_per_million=0.28,
            conservative_usd_to_cny_multiplier=8,
        ),
    )
    first = _MeteredSemanticProxy(
        tmp_path / "first",
        api_key="private-upstream-key",
        upstream_endpoint="https://example.invalid",
        ledger=ledger,
        trial_id="first",
        model="deepseek-v4-flash",
        maximum_input_tokens=8_000,
        maximum_output_tokens=1_024,
    )
    second = _MeteredSemanticProxy(
        tmp_path / "second",
        api_key="private-upstream-key",
        upstream_endpoint="https://example.invalid",
        ledger=ledger,
        trial_id="second",
        model="deepseek-v4-flash",
        maximum_input_tokens=8_000,
        maximum_output_tokens=1_024,
    )
    output = tmp_path / "combined.pem"

    with first, second:
        _write_combined_ca_bundle(
            (first.certificate, second.certificate),
            output,
        )
        context = ssl.create_default_context(cafile=str(output))

    roots = set(context.get_ca_certs(binary_form=True))
    assert (
        ssl.PEM_cert_to_DER_cert(
            first.certificate.read_text(),
        )
        in roots
    )
    assert (
        ssl.PEM_cert_to_DER_cert(
            second.certificate.read_text(),
        )
        in roots
    )
    assert output.stat().st_mode & 0o777 == 0o600


def test_semantic_proxy_rejects_unaccounted_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = ProviderBudgetLedger(
        tmp_path / "budget.jsonl",
        ProviderBudgetConfig(
            hard_cap_cny=100,
            external_service_reserve_cny=0,
            max_total_request_attempts=2,
            max_input_tokens_per_call=8_000,
            max_output_tokens_per_call=1_024,
            input_cache_miss_usd_per_million=0.14,
            output_usd_per_million=0.28,
            conservative_usd_to_cny_multiplier=8,
        ),
    )
    proxy = _MeteredSemanticProxy(
        tmp_path / "proxy",
        api_key="private-upstream-key",
        upstream_endpoint="https://example.invalid",
        ledger=ledger,
        trial_id="semantic-accounting",
        model="deepseek-v4-flash",
        maximum_input_tokens=8_000,
        maximum_output_tokens=1_024,
    )
    forwarded: dict[str, object] = {}

    def fake_post(*args, **kwargs):
        del args
        forwarded.update(kwargs["json"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "{}",
                            "role": "assistant",
                        }
                    }
                ],
                "model": "deepseek-v4-flash",
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    handler = _ProxyHandler()
    proxy._forward(
        handler,
        json.dumps(
            {
                "messages": [
                    {
                        "content": "extract memory",
                        "role": "user",
                    }
                ],
                "model": "untrusted-model",
                "stream": False,
            }
        ).encode(),
    )

    assert handler.error_code == 502
    assert forwarded["model"] == "deepseek-v4-flash"
    assert forwarded["max_tokens"] == 1_024
    assert forwarded["stream"] is False
    assert proxy.calls[0]["accounting_valid"] is False
    assert ledger.snapshot().open_reservations == 0


@pytest.mark.asyncio
async def test_codecairn_runner_waits_for_paid_worker_on_cancellation() -> None:
    started = threading.Event()
    finished = threading.Event()
    runner = ProductionCodeCairnMemoryRunner.__new__(
        ProductionCodeCairnMemoryRunner,
    )

    def run_sync(_context):
        started.set()
        time.sleep(0.05)
        finished.set()
        return object()

    runner._run_sync = run_sync
    task = asyncio.create_task(runner.run(object()))
    while not started.is_set():
        await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()


class _ProxyHandler:
    def __init__(self) -> None:
        self.error_code: int | None = None
        self.status_code: int | None = None
        self.headers: dict[str, str] = {}
        self.wfile = io.BytesIO()

    def send_error(self, code: int) -> None:
        self.error_code = code

    def send_response(self, code: int) -> None:
        self.status_code = code

    def send_header(self, name: str, value: str) -> None:
        self.headers[name] = value

    def end_headers(self) -> None:
        pass


def _records(
    *,
    control_passes: set[tuple[str, int]],
    treatment_passes: set[tuple[str, int]],
    definition_kind: Literal["formal", "calibration"] = "formal",
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    trials: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    pack_id = "codecairn-memory-effect-v1" if definition_kind == "formal" else "codecairn-memory-effect-calibration-v1"
    repetitions = 2 if definition_kind == "formal" else 1
    for task in load_codecairn_memory_tasks(definition_kind):
        for repetition in range(repetitions):
            pair_key = {
                "experiment_id": "experiment",
                "pack_id": pack_id,
                "treatment_axis": "memory_backend",
                "task_id": task.task_id,
                "repetition": repetition,
                "control_variant_id": "memory_off",
                "treatment_variant_id": "codecairn",
            }
            pairs.append(
                {
                    "key": pair_key,
                    "plan_digest": "plan",
                    "selected_block_attempt": 1,
                    "valid": True,
                    "actual_variant_diff": {
                        "memory_backend": {
                            "control": None,
                            "treatment": "codecairn",
                        }
                    },
                    "findings": [],
                }
            )
            trials.extend(
                (
                    _trial(
                        task_id=task.task_id,
                        repetition=repetition,
                        variant_id="memory_off",
                        passed=(task.task_id, repetition) in control_passes,
                        pair_key=pair_key,
                        pack_id=pack_id,
                    ),
                    _trial(
                        task_id=task.task_id,
                        repetition=repetition,
                        variant_id="codecairn",
                        passed=(task.task_id, repetition) in treatment_passes,
                        pair_key=pair_key,
                        pack_id=pack_id,
                    ),
                )
            )
    return trials, pairs


def _trial(
    *,
    task_id: str,
    repetition: int,
    variant_id: str,
    passed: bool,
    pair_key: Mapping[str, object],
    pack_id: str = "codecairn-memory-effect-v1",
) -> dict[str, object]:
    backend = None if variant_id == "memory_off" else "codecairn"
    return {
        "key": {
            "experiment_id": "experiment",
            "pack_id": pack_id,
            "task_id": task_id,
            "variant_id": variant_id,
            "repetition": repetition,
        },
        "plan_digest": "plan",
        "pair_memberships": [dict(pair_key)],
        "status": "passed" if passed else "task_failed",
        "selected_block_attempt": 1,
        "declared_variant_settings": {
            "memory_backend": backend,
            "context_strategy": "pico",
            "local_skills": "fixed",
            "tool_surface": ["joint_write_result"],
        },
        "observed_variant_settings": {
            "memory_backend": backend,
            "context_strategy": "pico",
            "local_skills": "fixed",
            "tool_surface": ["joint_write_result"],
        },
        "metrics": {
            "codecairn.memory_off_operation_calls": 0 if backend is None else None,
            "codecairn.recall_at_5_numerator": 0 if backend is None else 1,
            "codecairn.recall_at_5_denominator": 0 if backend is None else 1,
            "codecairn.irrelevant_injections": 0,
            "codecairn.hard_negative_queries": 1,
            "codecairn.stale_injection_count": 0,
            "codecairn.stale_fixture_complete": True,
            "codecairn.cross_repository_leakage_count": 0,
            "codecairn.production_adapter": backend == "codecairn",
            "codecairn.fresh_process": backend == "codecairn",
            "codecairn.profile_evidence_complete": True,
            "codecairn.provenance_complete": True,
            "codecairn.repository_identity_hash": "repo-identity",
            "provider.actual_model_matches": True,
            "usage.complete": True,
            "usage.main_agent_input_tokens": 100,
            "usage.trial_total_tokens": 120,
            "cost.complete": True,
            "runtime.end_to_end_latency_ms": 100,
            "runtime.memory_failures": 0,
            "runtime.repeated_repository_reads": 0,
            "runtime.tool_calls": 1,
            "runtime.tool_failures": 0,
        },
    }
