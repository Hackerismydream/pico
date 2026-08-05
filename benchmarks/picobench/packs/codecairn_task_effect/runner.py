from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from benchmarks.picobench.canonical import canonical_json
from benchmarks.picobench.protocol import (
    RetrievalContext,
    RetrievalExecution,
    TrialContext,
    TrialExecution,
)
from benchmarks.picobench.records import (
    DeliveryOutcome,
    RetrievalStatus,
    TrialStatus,
    TurnTerminalState,
    VerificationState,
    VerifierResult,
)

from .definitions import (
    load_retrieval_definition,
    load_task_effect_tasks,
)
from .fixtures import (
    FIXTURE_MARKER,
    FIXTURE_MARKER_SCHEMA,
    apply_parent_owned_mutation,
    build_parent_owned_prior_fixture,
    build_repository_fixture,
    fixture_file_drift,
    parent_owned_prior_fixture_definition,
    reset_repository_fixture,
)
from .models import (
    RetrievalDefinition,
    RetrievalMemory,
    RetrievalQuery,
    RetrievalQueryClass,
    TaskClass,
    TaskDefinitionKind,
    TaskEffectTask,
    TaskEffectTestState,
    TaskEffectVerificationEvidence,
)
from .verifier import SealedTaskEffectVerifier

_VERIFIER_ID = "external_parent_owned_task_effect_v2"
_PACK_IDS = {
    TaskDefinitionKind.FORMAL: "codecairn-task-effect-v2",
    TaskDefinitionKind.CALIBRATION: "codecairn-task-effect-calibration-v2",
}
_ALLOWED_TEST_COMMANDS = {
    "python -B checks/validate_repository.py": (
        sys.executable,
        "-B",
        "checks/validate_repository.py",
    ),
}


class ScriptedTaskEffectRunner:
    kind = "codecairn_task_effect_scripted_contract"

    def __init__(self) -> None:
        tasks = tuple(task for kind in TaskDefinitionKind for task in load_task_effect_tasks(kind))
        retrieval_definitions = tuple(load_retrieval_definition(kind) for kind in TaskDefinitionKind)
        self._task_by_id = {task.task_id: task for task in tasks}
        self._retrieval_by_query_id = {
            query.query_id: (definition, query) for definition in retrieval_definitions for query in definition.queries
        }
        self.trial_calls = 0
        self.retrieval_calls = 0
        self.identity = MappingProxyType(
            {
                "mode": "scripted_contract",
                "production_evidence_complete": False,
                "paid_external_calls": 0,
                "provider_calls": 0,
                "network_calls": 0,
            }
        )

    async def run_trial(
        self,
        context: TrialContext,
    ) -> TrialExecution:
        self.trial_calls += 1
        task = self._task_by_id.get(context.task.task_id)
        if task is None or context.key.task_id != context.task.task_id:
            return _trial_infrastructure_failure(
                context,
                "scripted_task_definition_missing",
            )
        if context.key.pack_id != _PACK_IDS[task.definition_kind]:
            return _trial_infrastructure_failure(
                context,
                "scripted_pack_identity_mismatch",
            )
        backend = context.variant.settings.get("memory_backend")
        expected_backend = (
            None
            if context.variant.variant_id == "memory_off"
            else "codecairn"
            if context.variant.variant_id == "codecairn"
            else object()
        )
        if backend != expected_backend:
            return _trial_infrastructure_failure(
                context,
                "scripted_variant_contract_mismatch",
            )

        verifier = SealedTaskEffectVerifier.capture(task)
        try:
            output_root = Path(context.experiment.output_root).resolve()
            experiment_root, workspace = _attempt_workspace_path(
                output_root=output_root,
                experiment_id=context.experiment_id,
                pack_id=context.key.pack_id,
                task_id=task.task_id,
                repetition=context.key.repetition,
                variant_id=context.key.variant_id,
                block_attempt=context.block_attempt,
            )
            workspace.parent.mkdir(parents=True, exist_ok=True)
            _reset_attempt_workspace(
                task,
                workspace,
                experiment_root=experiment_root,
            )
            parent_owned_setup_complete = _prepare_evaluated_fixture(
                task,
                workspace,
            )
            source_contents = _read_declared_sources(task, workspace)
            artifact_payload = {
                "task_id": task.task_id,
                "result": task.reference_solution.resolve_result(
                    source_contents,
                ),
                "evidence_path": task.reference_solution.evidence_path,
                "verification_command": task.test_command,
            }
            artifact = workspace.joinpath(
                *PurePosixPath(task.artifact_path).parts,
            )
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(
                canonical_json(artifact_payload) + "\n",
                encoding="utf-8",
            )
            receipt_ids = (
                *(f"read:{path}" for path in task.source_paths),
                f"write:{task.artifact_path}",
            )
            test_state = await _run_repository_check(task, workspace)
            receipt_ids = (
                *receipt_ids,
                f"test:{task.test_command}",
            )
            if set(receipt_ids) != set(task.required_receipt_ids):
                raise ValueError("scripted receipt contract mismatch")
            evidence = TaskEffectVerificationEvidence(
                receipt_ids=receipt_ids,
                changed_paths=(task.artifact_path,),
                test_state=test_state,
            )
            verification = await verifier.verify(workspace, evidence)
            if verification.infrastructure_error is not None:
                return TrialExecution(
                    status=TrialStatus.INFRASTRUCTURE_FAILURE,
                    runtime_state=TurnTerminalState.ERROR,
                    delivery_state=DeliveryOutcome.NO_OUTLET,
                    verification=verification.result,
                    observed_variant_settings=dict(context.variant.settings),
                    findings=(verification.infrastructure_error,),
                )
            passed = verification.result.state is VerificationState.PASSED
            return TrialExecution(
                status=(TrialStatus.PASSED if passed else TrialStatus.TASK_FAILED),
                runtime_state=TurnTerminalState.COMPLETED,
                delivery_state=DeliveryOutcome.DELIVERED,
                verification=verification.result,
                observed_variant_settings=dict(context.variant.settings),
                metrics=_trial_metrics(
                    task,
                    backend=backend,
                    parent_owned_setup_complete=(parent_owned_setup_complete),
                ),
                findings=(() if passed else tuple(verification.result.findings)),
                artifact_refs=(artifact.relative_to(output_root).as_posix(),),
            )
        except (
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            return _trial_infrastructure_failure(
                context,
                f"scripted_task_setup_failed:{type(exc).__name__}",
            )

    async def run_retrieval_case(
        self,
        context: RetrievalContext,
    ) -> RetrievalExecution:
        self.retrieval_calls += 1
        located = self._retrieval_by_query_id.get(context.query.query_id)
        if (
            located is None
            or context.key.query_id != context.query.query_id
            or context.configuration.configuration_id != "codecairn"
        ):
            return _retrieval_infrastructure_failure("scripted_retrieval_definition_missing")
        definition, query = located
        expected_ids = tuple(definition.anonymous_memory_id(memory_id) for memory_id in query.expected_memory_ids)
        if expected_ids != context.query.expected_item_ids:
            return _retrieval_infrastructure_failure("scripted_retrieval_labels_changed")

        ranked_results, injected_results = _retrieval_results(
            definition,
            query,
        )
        abstained = not injected_results
        abstention_reason = _abstention_reason(query.query_class)
        return RetrievalExecution(
            status=RetrievalStatus.MEASURABLE,
            ranked_results=ranked_results,
            injected_results=injected_results,
            usage={
                "usage.complete": True,
                "cost.complete": True,
                "embedding_calls": 0,
                "semantic_calls": 0,
                "reranking_calls": 0,
                "cost_cny": 0.0,
            },
            metadata={
                "query_class": query.query_class.value,
                "repository_id": query.repository_id,
                "abstained": abstained,
                "abstention_reason": abstention_reason,
                "retrieval_latency_ms": 1.0,
                "production_evidence_complete": False,
                "memory_off_operation_calls": 0,
                "anonymous_candidate_ids": [result["item_id"] for result in ranked_results],
                "anonymous_injected_ids": [result["item_id"] for result in injected_results],
            },
        )


def _prepare_evaluated_fixture(
    task: TaskEffectTask,
    workspace: Path,
) -> bool:
    mutation = task.parent_owned_mutation
    if mutation is None:
        initial = build_repository_fixture(task, workspace)
        evaluated = reset_repository_fixture(task, workspace)
        if initial.fixture_digest != evaluated.fixture_digest or initial.tree_digest != evaluated.tree_digest:
            raise ValueError("repository fixture reset is not byte-stable")
    else:
        contract = task.mutation_contract
        if contract is None:
            raise ValueError("stale task mutation contract is missing")
        prior = build_parent_owned_prior_fixture(task, workspace)
        prior_path = workspace.joinpath(*PurePosixPath(mutation.path).parts)
        prior_content = prior_path.read_text(encoding="utf-8")
        if mutation.prior_observation not in prior_content:
            raise ValueError("prior observation is absent")
        if prior.fixture_digest != contract["prior_fixture_digest"]:
            raise ValueError("prior fixture digest changed")
        evaluated = apply_parent_owned_mutation(task, workspace)
        if evaluated.fixture_digest != contract["evaluated_fixture_digest"]:
            raise ValueError("evaluated fixture digest changed")
        if prior.fixture_digest == evaluated.fixture_digest:
            raise ValueError("stale transition did not change fixture digest")
    if fixture_file_drift(task.fixture, workspace):
        raise ValueError("evaluated fixture drifted before task execution")
    return True


def _attempt_workspace_path(
    *,
    output_root: Path,
    experiment_id: str,
    pack_id: str,
    task_id: str,
    repetition: int,
    variant_id: str,
    block_attempt: int,
) -> tuple[Path, Path]:
    for label, value in (
        ("experiment_id", experiment_id),
        ("pack_id", pack_id),
        ("task_id", task_id),
        ("variant_id", variant_id),
    ):
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError(f"{label} is not a safe path component")
    if isinstance(repetition, bool) or repetition < 0 or isinstance(block_attempt, bool) or block_attempt < 1:
        raise ValueError("attempt indexes are invalid")
    resolved_output = Path(output_root).resolve()
    experiment_root = (resolved_output / experiment_id).resolve()
    if experiment_root.parent != resolved_output:
        raise ValueError("experiment id escapes the output root")
    workspace_parent = (
        experiment_root
        / "workspaces"
        / pack_id
        / task_id
        / str(repetition)
        / variant_id
        / "attempts"
        / str(block_attempt)
    ).resolve()
    if not workspace_parent.is_relative_to(experiment_root):
        raise ValueError("attempt workspace escapes the experiment root")
    return experiment_root, workspace_parent / "workspace"


def _reset_attempt_workspace(
    task: TaskEffectTask,
    workspace: Path,
    *,
    experiment_root: Path,
) -> None:
    resolved_experiment = experiment_root.resolve()
    resolved_parent = workspace.parent.resolve()
    if workspace.name != "workspace" or not resolved_parent.is_relative_to(resolved_experiment):
        raise ValueError("refusing to use an invalid attempt workspace")
    if workspace.is_symlink():
        raise ValueError("attempt workspace cannot be a symlink")
    if not workspace.exists():
        return
    resolved_workspace = workspace.resolve()
    if (
        not resolved_workspace.is_relative_to(resolved_experiment)
        or resolved_workspace.parent != resolved_parent
        or not resolved_workspace.is_dir()
    ):
        raise ValueError("refusing to reset an invalid attempt workspace")
    marker_path = resolved_workspace / FIXTURE_MARKER
    if not marker_path.is_file() or marker_path.is_symlink():
        raise ValueError("refusing to reset an unmarked attempt workspace")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            "refusing to reset an invalid attempt workspace marker",
        ) from exc
    allowed_definitions = [task.fixture]
    if task.parent_owned_mutation is not None:
        allowed_definitions.append(
            parent_owned_prior_fixture_definition(task),
        )
    if not any(
        marker
        == {
            "schema": FIXTURE_MARKER_SCHEMA,
            "fixture_id": definition.fixture_id,
            "repository_id": definition.repository_id,
            "revision": definition.revision,
            "fixture_digest": definition.digest,
        }
        for definition in allowed_definitions
    ):
        raise ValueError(
            "refusing to reset a different attempt workspace",
        )
    shutil.rmtree(resolved_workspace)


def _read_declared_sources(
    task: TaskEffectTask,
    workspace: Path,
) -> dict[str, str]:
    return {
        path: workspace.joinpath(
            *PurePosixPath(path).parts,
        ).read_text(encoding="utf-8")
        for path in task.source_paths
    }


async def _run_repository_check(
    task: TaskEffectTask,
    workspace: Path,
) -> TaskEffectTestState:
    argv = _ALLOWED_TEST_COMMANDS.get(task.test_command)
    if argv is None:
        raise ValueError("scripted test command is not allowlisted")
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=workspace,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(
            process.wait(),
            timeout=10.0,
        )
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ValueError("scripted test command timed out") from exc
    if process.returncode is None:
        raise ValueError("scripted test command did not terminate")
    return TaskEffectTestState(
        command=task.test_command,
        exit_code=process.returncode,
        fixture_digest=task.fixture.digest,
    )


def _trial_metrics(
    task: TaskEffectTask,
    *,
    backend: object,
    parent_owned_setup_complete: bool,
) -> dict[str, bool | int | float | str]:
    treatment = backend == "codecairn"
    useful_memory = task.task_class in {
        TaskClass.FACT,
        TaskClass.EXPERIENCE,
    }
    memory_hits = int(treatment and useful_memory)
    abstentions = int(treatment and not useful_memory)
    input_tokens = 128
    output_tokens = 32
    repository_reads = len(task.source_paths)
    metrics: dict[str, bool | int | float | str] = {
        "task_effect.production_evidence_complete": False,
        "task_effect.fixture_digest": task.fixture.digest,
        "task_effect.expected_digest": task.expected_digest,
        "task_effect.verifier_id": _VERIFIER_ID,
        "task_effect.parent_owned_setup_complete": (parent_owned_setup_complete),
        "task_effect.fixture_reset_complete": True,
        "usage.complete": True,
        "cost.complete": True,
        "usage.main_agent_input_tokens": input_tokens,
        "usage.main_agent_output_tokens": output_tokens,
        "usage.trial_total_tokens": input_tokens + output_tokens,
        "runtime.repository_read_calls": repository_reads,
        "runtime.repository_search_calls": 0,
        "runtime.test_calls": 1,
        "runtime.write_calls": 1,
        "runtime.tool_calls": repository_reads + 2,
        "runtime.repeated_repository_reads": 0,
        "runtime.end_to_end_latency_ms": 10.0,
        "runtime.retrieval_latency_ms": 1.0 if treatment else 0.0,
        "cost.provider_cny": 0.0,
        "cost.codecairn_cny": 0.0,
        "cost.total_cny": 0.0,
        "codecairn.memory_off_operation_calls": 0,
        "codecairn.memory_hits": memory_hits,
        "codecairn.injected_items": memory_hits,
        "codecairn.abstentions": abstentions,
        "codecairn.memory_failures": 0,
    }
    if task.mutation_contract is not None:
        metrics.update(
            {
                "task_effect.parent_owned_prior_fixture_digest": (task.mutation_contract["prior_fixture_digest"]),
                "task_effect.evaluated_fixture_digest": (task.mutation_contract["evaluated_fixture_digest"]),
                "task_effect.parent_owned_mutation_contract_digest": (task.mutation_contract["contract_digest"]),
            }
        )
    return metrics


def _retrieval_results(
    definition: RetrievalDefinition,
    query: RetrievalQuery,
) -> tuple[
    tuple[dict[str, bool | int | float | str], ...],
    tuple[dict[str, bool | int | float | str], ...],
]:
    if query.query_class.is_positive:
        memories = tuple(definition.corpus_by_id[memory_id] for memory_id in query.expected_memory_ids)
    elif query.query_class in {
        RetrievalQueryClass.STALE,
        RetrievalQueryClass.CROSS_REPOSITORY,
    }:
        memories = tuple(definition.corpus_by_id[memory_id] for memory_id in query.forbidden_memory_ids)
    else:
        memories = ()
    ranked = tuple(
        _ranked_result(
            definition,
            memory,
            rank=index,
        )
        for index, memory in enumerate(memories, start=1)
    )
    if not query.query_class.is_positive:
        return ranked, ()
    injected = tuple(
        {
            **result,
            "injection_position": index,
        }
        for index, result in enumerate(ranked, start=1)
    )
    return ranked, injected


def _ranked_result(
    definition: RetrievalDefinition,
    memory: RetrievalMemory,
    *,
    rank: int,
) -> dict[str, bool | int | float | str]:
    return {
        "item_id": definition.anonymous_memory_id(memory.memory_id),
        "rank": rank,
        "score": round(1.0 - (rank - 1) * 0.01, 4),
        "source": "scripted_parent_owned_corpus",
        "repository_identity": memory.repository_id,
        "validity_state": memory.validity.value,
        "anonymous": True,
    }


def _abstention_reason(
    query_class: RetrievalQueryClass,
) -> str:
    return {
        RetrievalQueryClass.FACT_POSITIVE: "not_abstained",
        RetrievalQueryClass.EXPERIENCE_POSITIVE: "not_abstained",
        RetrievalQueryClass.HARD_NEGATIVE: "no_relevant_memory",
        RetrievalQueryClass.STALE: "stale_or_superseded_filtered",
        RetrievalQueryClass.CROSS_REPOSITORY: ("cross_repository_memory_filtered"),
    }[query_class]


def _trial_infrastructure_failure(
    context: TrialContext,
    finding: str,
) -> TrialExecution:
    return TrialExecution(
        status=TrialStatus.INFRASTRUCTURE_FAILURE,
        runtime_state=TurnTerminalState.ERROR,
        delivery_state=DeliveryOutcome.NO_OUTLET,
        verification=VerifierResult(state=VerificationState.NOT_RUN),
        observed_variant_settings=dict(context.variant.settings),
        findings=(finding,),
    )


def _retrieval_infrastructure_failure(
    finding: str,
) -> RetrievalExecution:
    return RetrievalExecution(
        status=RetrievalStatus.INFRASTRUCTURE_FAILURE,
        findings=(finding,),
    )


__all__ = ["ScriptedTaskEffectRunner"]
