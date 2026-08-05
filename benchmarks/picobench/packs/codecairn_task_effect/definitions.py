from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from benchmarks.picobench.canonical import canonical_digest, to_primitive
from benchmarks.picobench.verifier import require_normalized_relative_path

from .models import (
    RETRIEVAL_SCHEMA,
    TASK_SCHEMA,
    ExpectedArtifact,
    FixtureFile,
    MemoryValidity,
    ParentOwnedMutation,
    ReferenceCapture,
    ReferenceSolution,
    RepositoryFixtureDefinition,
    RetrievalDefinition,
    RetrievalMemory,
    RetrievalQuery,
    RetrievalQueryClass,
    TaskClass,
    TaskDefinitionKind,
    TaskEffectTask,
)

FORMAL_TASK_COUNT = 24
CALIBRATION_TASK_COUNT = 6
FORMAL_RETRIEVAL_QUERY_COUNT = 100
CALIBRATION_RETRIEVAL_QUERY_COUNT = 10

_TASK_CLASS_COUNTS = {
    TaskDefinitionKind.FORMAL: {
        TaskClass.FACT: 8,
        TaskClass.EXPERIENCE: 8,
        TaskClass.STALE_CONFLICT: 4,
        TaskClass.IRRELEVANT: 4,
    },
    TaskDefinitionKind.CALIBRATION: {
        TaskClass.FACT: 2,
        TaskClass.EXPERIENCE: 2,
        TaskClass.STALE_CONFLICT: 1,
        TaskClass.IRRELEVANT: 1,
    },
}
_RETRIEVAL_CLASS_COUNTS = {
    TaskDefinitionKind.FORMAL: {
        RetrievalQueryClass.FACT_POSITIVE: 30,
        RetrievalQueryClass.EXPERIENCE_POSITIVE: 20,
        RetrievalQueryClass.HARD_NEGATIVE: 20,
        RetrievalQueryClass.STALE: 15,
        RetrievalQueryClass.CROSS_REPOSITORY: 15,
    },
    TaskDefinitionKind.CALIBRATION: {
        RetrievalQueryClass.FACT_POSITIVE: 2,
        RetrievalQueryClass.EXPERIENCE_POSITIVE: 2,
        RetrievalQueryClass.HARD_NEGATIVE: 2,
        RetrievalQueryClass.STALE: 2,
        RetrievalQueryClass.CROSS_REPOSITORY: 2,
    },
}
_TASK_ROOT = Path(__file__).resolve().parents[2] / "tasks" / "codecairn_task_effect"


@lru_cache(maxsize=2)
def load_task_effect_tasks(
    definition_kind: TaskDefinitionKind | str,
) -> tuple[TaskEffectTask, ...]:
    definition_kind = TaskDefinitionKind(definition_kind)
    payload = _load_json(_TASK_ROOT / f"{definition_kind.value}.json")
    if payload.get("schema") != TASK_SCHEMA:
        raise ValueError(f"unsupported CodeCairn task-effect schema: {payload.get('schema')!r}")
    if payload.get("definition_kind") != definition_kind.value:
        raise ValueError("task definition_kind does not match its filename")

    fixture_rows = payload.get("repositories")
    if not isinstance(fixture_rows, list) or not fixture_rows:
        raise ValueError("task definitions require repository fixtures")
    fixtures = tuple(_parse_fixture(row) for row in fixture_rows)
    _ensure_unique(
        (fixture.fixture_id for fixture in fixtures),
        "repository fixture id",
    )
    fixture_by_id = {fixture.fixture_id: fixture for fixture in fixtures}

    task_rows = payload.get("tasks")
    if not isinstance(task_rows, list):
        raise ValueError("task definitions require a task list")
    tasks = tuple(_parse_task(definition_kind, row, fixture_by_id) for row in task_rows)
    expected_count = FORMAL_TASK_COUNT if definition_kind is TaskDefinitionKind.FORMAL else CALIBRATION_TASK_COUNT
    if len(tasks) != expected_count:
        raise ValueError(f"{definition_kind.value} requires exactly {expected_count} tasks")
    _ensure_unique((task.task_id for task in tasks), "task id")
    _ensure_unique((task.expected_id for task in tasks), "expected artifact id")
    _ensure_unique(
        (task.parent_owned_mutation.mutation_id for task in tasks if task.parent_owned_mutation is not None),
        "parent-owned mutation id",
    )
    observed_classes = Counter(task.task_class for task in tasks)
    if observed_classes != Counter(_TASK_CLASS_COUNTS[definition_kind]):
        raise ValueError(f"unexpected {definition_kind.value} task class distribution: {dict(observed_classes)}")
    formal_fixture_count = len({task.fixture_id for task in tasks})
    if definition_kind is TaskDefinitionKind.FORMAL and formal_fixture_count < 4:
        raise ValueError("formal task definitions require at least four fixtures")
    _validate_cross_track_task_ids(definition_kind, tasks)
    return tasks


def task_effect_task_set_digest(
    definition_kind: TaskDefinitionKind | str,
) -> str:
    tasks = load_task_effect_tasks(definition_kind)
    return canonical_digest(
        [
            {
                "task_spec": task.to_task_spec(),
                "fixture": task.fixture,
                "expected_id": task.expected_id,
                "expected_digest": task.expected_digest,
            }
            for task in tasks
        ]
    )


@lru_cache(maxsize=2)
def load_retrieval_definition(
    definition_kind: TaskDefinitionKind | str,
) -> RetrievalDefinition:
    definition_kind = TaskDefinitionKind(definition_kind)
    payload = _load_json(_TASK_ROOT / f"retrieval_{definition_kind.value}.json")
    if payload.get("schema") != RETRIEVAL_SCHEMA:
        raise ValueError(f"unsupported CodeCairn retrieval schema: {payload.get('schema')!r}")
    if payload.get("definition_kind") != definition_kind.value:
        raise ValueError("retrieval definition_kind does not match its filename")
    suite_id = _required_str(payload, "suite_id")

    corpus_rows = payload.get("corpus")
    if not isinstance(corpus_rows, list) or not corpus_rows:
        raise ValueError("retrieval definitions require a corpus")
    corpus = tuple(_parse_memory(row) for row in corpus_rows)
    _ensure_unique((memory.memory_id for memory in corpus), "Memory id")
    corpus_by_id = {memory.memory_id: memory for memory in corpus}

    query_rows = payload.get("queries")
    if not isinstance(query_rows, list):
        raise ValueError("retrieval definitions require a query list")
    queries = tuple(_parse_retrieval_query(row, corpus_by_id) for row in query_rows)
    expected_count = (
        FORMAL_RETRIEVAL_QUERY_COUNT
        if definition_kind is TaskDefinitionKind.FORMAL
        else CALIBRATION_RETRIEVAL_QUERY_COUNT
    )
    if len(queries) != expected_count:
        raise ValueError(f"{definition_kind.value} requires exactly {expected_count} retrieval queries")
    _ensure_unique((query.query_id for query in queries), "retrieval query id")
    if len({query.query_text.casefold() for query in queries}) != len(queries):
        raise ValueError("retrieval query wording must be unique")
    observed_classes = Counter(query.query_class for query in queries)
    if observed_classes != Counter(_RETRIEVAL_CLASS_COUNTS[definition_kind]):
        raise ValueError(f"unexpected {definition_kind.value} retrieval class distribution: {dict(observed_classes)}")
    if definition_kind is TaskDefinitionKind.FORMAL:
        multi_relevant = sum(len(query.expected_memory_ids) > 1 for query in queries if query.query_class.is_positive)
        if multi_relevant < 10:
            raise ValueError("formal retrieval requires at least ten multi-relevant positives")
    definition = RetrievalDefinition(
        definition_kind=definition_kind,
        suite_id=suite_id,
        corpus=corpus,
        queries=queries,
    )
    if definition_kind is TaskDefinitionKind.FORMAL:
        _validate_formal_fact_provenance(definition)
    _validate_cross_track_retrieval_ids(definition)
    return definition


def retrieval_definition_digest(
    definition_kind: TaskDefinitionKind | str,
) -> str:
    return load_retrieval_definition(definition_kind).digest


def _parse_fixture(raw: Any) -> RepositoryFixtureDefinition:
    if not isinstance(raw, dict):
        raise ValueError("repository fixture entries must be objects")
    file_rows = raw.get("files")
    if not isinstance(file_rows, list) or not file_rows:
        raise ValueError("repository fixtures require files")
    files = tuple(_parse_fixture_file(row) for row in file_rows)
    _ensure_unique((file.path for file in files), "fixture file path")
    return RepositoryFixtureDefinition(
        fixture_id=_required_str(raw, "fixture_id"),
        repository_id=_required_str(raw, "repository_id"),
        revision=_required_str(raw, "revision"),
        files=files,
    )


def _parse_fixture_file(raw: Any) -> FixtureFile:
    if not isinstance(raw, dict):
        raise ValueError("fixture file entries must be objects")
    executable = raw.get("executable", False)
    if not isinstance(executable, bool):
        raise ValueError("fixture file executable must be a boolean")
    return FixtureFile(
        path=require_normalized_relative_path(
            _required_str(raw, "path"),
            field_name="fixture file path",
        ),
        content=_required_str(raw, "content"),
        executable=executable,
    )


def _parse_task(
    definition_kind: TaskDefinitionKind,
    raw: Any,
    fixture_by_id: dict[str, RepositoryFixtureDefinition],
) -> TaskEffectTask:
    if not isinstance(raw, dict):
        raise ValueError("task entries must be objects")
    fixture_id = _required_str(raw, "fixture_id")
    try:
        fixture = fixture_by_id[fixture_id]
    except KeyError as exc:
        raise ValueError(f"unknown task fixture: {fixture_id}") from exc

    source_paths = _path_tuple(raw, "source_paths", allow_empty=False)
    artifact_path = require_normalized_relative_path(
        _required_str(raw, "artifact_path"),
        field_name="artifact_path",
    )
    allowed_paths = _path_tuple(
        raw,
        "allowed_mutation_paths",
        allow_empty=False,
    )
    forbidden_paths = _path_tuple(raw, "forbidden_paths", allow_empty=False)
    if artifact_path not in allowed_paths:
        raise ValueError("artifact_path must be an allowed mutation path")
    if set(allowed_paths) & set(forbidden_paths):
        raise ValueError("allowed and forbidden paths must be disjoint")
    if any(path not in fixture.file_map for path in source_paths):
        raise ValueError(f"{raw.get('task_id')} references a missing source path")

    expected_raw = raw.get("expected_artifact")
    if not isinstance(expected_raw, dict):
        raise ValueError("task expected_artifact must be an object")
    expected_id = _required_str(expected_raw, "expected_id")
    expected_payload = expected_raw.get("payload")
    if not isinstance(expected_payload, dict):
        raise ValueError("expected artifact payload must be an object")
    required_expected_fields = {
        "task_id",
        "result",
        "evidence_path",
        "verification_command",
    }
    if set(expected_payload) != required_expected_fields:
        raise ValueError("expected artifact must contain task_id, result, evidence_path, and verification_command")

    test_command = _required_str(raw, "test_command")
    task = TaskEffectTask(
        task_id=_required_str(raw, "task_id"),
        definition_kind=definition_kind,
        task_class=TaskClass(_required_str(raw, "task_class")),
        title=_required_str(raw, "title"),
        fixture=fixture,
        prior_work_prompt=_required_str(raw, "prior_work_prompt"),
        memory_query=_required_str(raw, "memory_query"),
        evaluation_prompt=_required_str(raw, "evaluation_prompt"),
        source_paths=source_paths,
        artifact_path=artifact_path,
        expected_artifact=ExpectedArtifact(
            expected_id=expected_id,
            payload=expected_payload,
        ),
        reference_solution=_parse_reference_solution(
            raw.get("reference_solution"),
            fixture,
        ),
        allowed_mutation_paths=allowed_paths,
        forbidden_paths=forbidden_paths,
        required_receipt_ids=_str_tuple(
            raw,
            "required_receipt_ids",
            allow_empty=False,
        ),
        test_command=test_command,
        parent_owned_mutation=_parse_parent_owned_mutation(
            raw.get("parent_owned_mutation"),
        ),
    )
    _validate_task_contract(task)
    return task


def _validate_task_contract(task: TaskEffectTask) -> None:
    expected = task.expected_artifact.payload
    if expected["task_id"] != task.task_id:
        raise ValueError(f"{task.task_id} expected payload has the wrong task id")
    if expected["evidence_path"] not in task.source_paths:
        raise ValueError(f"{task.task_id} expected evidence_path is not a declared source")
    if expected["verification_command"] != task.test_command:
        raise ValueError(f"{task.task_id} expected verification command does not match")
    reference_solution = task.reference_solution
    if reference_solution.evidence_path != expected["evidence_path"]:
        raise ValueError(
            f"{task.task_id} reference evidence path does not match",
        )
    if reference_solution.evidence_path not in task.source_paths:
        raise ValueError(
            f"{task.task_id} reference evidence path is not a declared source",
        )
    if any(capture.path not in task.source_paths for capture in reference_solution.captures):
        raise ValueError(
            f"{task.task_id} reference capture is not a declared source",
        )
    if task.definition_kind is TaskDefinitionKind.FORMAL:
        if len(set(task.source_paths)) < 2:
            raise ValueError(
                f"{task.task_id} formal task requires at least two source paths",
            )
        if len(reference_solution.captures) < 2 or len({capture.path for capture in reference_solution.captures}) < 2:
            raise ValueError(
                f"{task.task_id} formal task requires captures from at least two source paths",
            )
    source_contents = {path: task.fixture.file_map[path].content for path in task.source_paths}
    if to_primitive(reference_solution.resolve_result(source_contents)) != to_primitive(expected["result"]):
        raise ValueError(
            f"{task.task_id} reference solution does not reproduce the expected result",
        )
    if task.definition_kind is TaskDefinitionKind.FORMAL and task.task_class in {TaskClass.FACT, TaskClass.EXPERIENCE}:
        prior_work = task.prior_work_prompt.casefold()
        answer_values = {
            *(capture.resolve(source_contents) for capture in reference_solution.captures),
            *_string_leaves(expected["result"]),
        }
        leaked = sorted(
            value
            for value in answer_values
            if _is_nontrivial_answer_text(value) and value.strip().casefold() in prior_work
        )
        if leaked:
            raise ValueError(
                f"{task.task_id} prior_work_prompt contains a formal answer value",
            )
    required_receipts = {
        *(f"read:{path}" for path in task.source_paths),
        f"test:{task.test_command}",
        f"write:{task.artifact_path}",
    }
    if not required_receipts.issubset(task.required_receipt_ids):
        raise ValueError(f"{task.task_id} is missing required receipt ids")
    mutation = task.parent_owned_mutation
    if task.task_class is TaskClass.STALE_CONFLICT:
        if mutation is None:
            raise ValueError(f"{task.task_id} requires a parent-owned mutation")
    elif mutation is not None:
        raise ValueError(f"{task.task_id} cannot declare a parent-owned mutation")
    if mutation is None:
        return
    if mutation.path not in task.source_paths:
        raise ValueError(f"{task.task_id} mutation path is not a declared source")
    if mutation.prior_revision == task.fixture.revision:
        raise ValueError(f"{task.task_id} mutation revisions must differ")
    evaluated_content = task.fixture.file_map[mutation.path].content
    if mutation.prior_content == evaluated_content:
        raise ValueError(f"{task.task_id} mutation does not change repository state")
    if mutation.prior_observation not in mutation.prior_content:
        raise ValueError(f"{task.task_id} prior observation is absent from prior state")
    mutated_capture_values = [
        capture.resolve(source_contents) for capture in reference_solution.captures if capture.path == mutation.path
    ]
    if not mutated_capture_values:
        raise ValueError(
            f"{task.task_id} mutation path has no reference capture",
        )
    if all(value in mutation.prior_content for value in mutated_capture_values):
        raise ValueError(
            f"{task.task_id} evaluated mutation values already exist in prior state",
        )
    contract = mutation.contract_payload(task.fixture)
    if contract["prior_fixture_digest"] == contract["evaluated_fixture_digest"]:
        raise ValueError(f"{task.task_id} mutation fixture digests must differ")


def _parse_parent_owned_mutation(raw: Any) -> ParentOwnedMutation | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("parent_owned_mutation must be an object")
    return ParentOwnedMutation(
        mutation_id=_required_str(raw, "mutation_id"),
        path=require_normalized_relative_path(
            _required_str(raw, "path"),
            field_name="parent_owned_mutation.path",
        ),
        prior_revision=_required_str(raw, "prior_revision"),
        prior_content=_required_str(raw, "prior_content"),
        prior_observation=_required_str(raw, "prior_observation"),
    )


def _parse_reference_solution(
    raw: Any,
    fixture: RepositoryFixtureDefinition,
) -> ReferenceSolution:
    if not isinstance(raw, dict):
        raise ValueError("reference_solution must be an object")
    capture_rows = raw.get("captures")
    if not isinstance(capture_rows, list) or not capture_rows:
        raise ValueError("reference_solution captures must be a non-empty list")
    captures = tuple(_parse_reference_capture(row, fixture) for row in capture_rows)
    _ensure_unique(
        (capture.name for capture in captures),
        "reference capture name",
    )
    result_template = raw.get("result_template")
    _validate_result_template(
        result_template,
        {capture.name for capture in captures},
    )
    referenced_captures = _result_template_capture_names(result_template)
    if referenced_captures != {capture.name for capture in captures}:
        raise ValueError(
            "reference result template must use every declared capture",
        )
    evidence_path = require_normalized_relative_path(
        _required_str(raw, "evidence_path"),
        field_name="reference_solution.evidence_path",
    )
    if evidence_path not in fixture.file_map:
        raise ValueError("reference solution evidence path is absent from fixture")
    return ReferenceSolution(
        captures=captures,
        result_template=result_template,
        evidence_path=evidence_path,
    )


def _parse_reference_capture(
    raw: Any,
    fixture: RepositoryFixtureDefinition,
) -> ReferenceCapture:
    if not isinstance(raw, dict):
        raise ValueError("reference solution captures must be objects")
    name = _required_str(raw, "name")
    if not name.isidentifier() or not name.isascii():
        raise ValueError("reference capture name must be an ASCII identifier")
    path = require_normalized_relative_path(
        _required_str(raw, "path"),
        field_name="reference_solution.capture.path",
    )
    if path not in fixture.file_map:
        raise ValueError("reference capture path is absent from fixture")
    line_suffix = raw.get("line_suffix")
    if not isinstance(line_suffix, str):
        raise ValueError("reference capture line_suffix must be a string")
    return ReferenceCapture(
        name=name,
        path=path,
        line_prefix=_required_str(raw, "line_prefix"),
        line_suffix=line_suffix,
    )


def _validate_result_template(
    value: Any,
    capture_names: set[str],
) -> None:
    if isinstance(value, str):
        if not (
            value.startswith("{")
            and value.endswith("}")
            and value.count("{") == 1
            and value.count("}") == 1
            and value[1:-1] in capture_names
        ):
            raise ValueError(
                "reference result template string leaves must be capture placeholders",
            )
        return
    if isinstance(value, list):
        for item in value:
            _validate_result_template(item, capture_names)
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("reference result template keys must be strings")
        for item in value.values():
            _validate_result_template(item, capture_names)
        return
    if value is None or isinstance(value, bool | int | float):
        raise ValueError(
            "reference result template leaves must be capture placeholders",
        )
    raise ValueError("reference result template must contain JSON containers and capture placeholders")


def _result_template_capture_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value[1:-1]}
    if isinstance(value, list):
        return {capture_name for item in value for capture_name in _result_template_capture_names(item)}
    if isinstance(value, dict):
        return {capture_name for item in value.values() for capture_name in _result_template_capture_names(item)}
    return set()


def _string_leaves(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {leaf for item in value for leaf in _string_leaves(item)}
    if isinstance(value, dict):
        return {leaf for item in value.values() for leaf in _string_leaves(item)}
    return set()


def _is_nontrivial_answer_text(value: str) -> bool:
    return len(value.strip()) >= 4


def _parse_memory(raw: Any) -> RetrievalMemory:
    if not isinstance(raw, dict):
        raise ValueError("retrieval corpus entries must be objects")
    return RetrievalMemory(
        memory_id=_required_str(raw, "memory_id"),
        repository_id=_required_str(raw, "repository_id"),
        memory_class=_required_str(raw, "memory_class"),
        validity=MemoryValidity(_required_str(raw, "validity")),
        content=_required_str(raw, "content"),
        source_uri=_required_str(raw, "source_uri"),
        fixture_revision=_optional_str(raw, "fixture_revision"),
        evidence_path=_optional_normalized_path(raw, "evidence_path"),
        evidence_digest=_optional_str(raw, "evidence_digest"),
    )


def _validate_formal_fact_provenance(
    definition: RetrievalDefinition,
) -> None:
    fixtures = {task.fixture.repository_id: task.fixture for task in load_task_effect_tasks(TaskDefinitionKind.FORMAL)}
    positive_fact_ids = {
        memory_id
        for query in definition.queries
        if query.query_class is RetrievalQueryClass.FACT_POSITIVE
        for memory_id in query.expected_memory_ids
    }
    for memory_id in sorted(positive_fact_ids):
        memory = definition.corpus_by_id[memory_id]
        if memory.memory_class != "repository_fact" or memory.validity is not MemoryValidity.ACTIVE:
            raise ValueError(
                f"positive repository fact has invalid class or state: {memory_id}",
            )
        try:
            fixture = fixtures[memory.repository_id]
        except KeyError as exc:
            raise ValueError(
                f"positive repository fact has no pinned fixture: {memory_id}",
            ) from exc
        if memory.fixture_revision != fixture.revision:
            raise ValueError(
                f"positive repository fact revision mismatch: {memory_id}",
            )
        evidence_path = memory.evidence_path
        if evidence_path is None or evidence_path not in fixture.file_map:
            raise ValueError(
                f"positive repository fact evidence is missing: {memory_id}",
            )
        evidence = fixture.file_map[evidence_path]
        if memory.evidence_digest != evidence.content_digest:
            raise ValueError(
                f"positive repository fact evidence digest mismatch: {memory_id}",
            )
        if memory.content not in evidence.content:
            raise ValueError(
                f"positive repository fact is absent from evidence: {memory_id}",
            )


def _parse_retrieval_query(
    raw: Any,
    corpus_by_id: dict[str, RetrievalMemory],
) -> RetrievalQuery:
    if not isinstance(raw, dict):
        raise ValueError("retrieval query entries must be objects")
    query = RetrievalQuery(
        query_id=_required_str(raw, "query_id"),
        query_class=RetrievalQueryClass(_required_str(raw, "query_class")),
        repository_id=_required_str(raw, "repository_id"),
        query_text=_required_str(raw, "query_text"),
        expected_memory_ids=_str_tuple(
            raw,
            "expected_memory_ids",
            allow_empty=True,
        ),
        forbidden_memory_ids=_str_tuple(
            raw,
            "forbidden_memory_ids",
            allow_empty=True,
        ),
    )
    referenced_ids = {
        *query.expected_memory_ids,
        *query.forbidden_memory_ids,
    }
    missing = referenced_ids - corpus_by_id.keys()
    if missing:
        raise ValueError(f"{query.query_id} references unknown Memory ids: {sorted(missing)}")
    if set(query.expected_memory_ids) & set(query.forbidden_memory_ids):
        raise ValueError(f"{query.query_id} marks the same Memory expected and forbidden")

    if query.query_class.is_positive:
        if not query.expected_memory_ids:
            raise ValueError(f"{query.query_id} positive query has no labels")
        for memory_id in query.expected_memory_ids:
            memory = corpus_by_id[memory_id]
            if memory.validity is not MemoryValidity.ACTIVE:
                raise ValueError(f"{query.query_id} expects a non-active Memory")
            if memory.repository_id != query.repository_id:
                raise ValueError(f"{query.query_id} expects cross-repository Memory")
    elif query.expected_memory_ids:
        raise ValueError(f"{query.query_id} negative query cannot have expected Memory ids")

    if query.query_class is RetrievalQueryClass.HARD_NEGATIVE:
        if query.forbidden_memory_ids:
            raise ValueError("hard-negative queries use an empty relevant set")
    elif query.query_class is RetrievalQueryClass.STALE:
        if not query.forbidden_memory_ids:
            raise ValueError("stale queries require forbidden Memory ids")
        if any(corpus_by_id[memory_id].validity is MemoryValidity.ACTIVE for memory_id in query.forbidden_memory_ids):
            raise ValueError("stale query forbids an active Memory")
    elif query.query_class is RetrievalQueryClass.CROSS_REPOSITORY:
        if not query.forbidden_memory_ids:
            raise ValueError("cross-repository queries require forbidden ids")
        if any(
            corpus_by_id[memory_id].repository_id == query.repository_id for memory_id in query.forbidden_memory_ids
        ):
            raise ValueError("cross-repository query forbids same-repository Memory")
    return query


def _validate_cross_track_task_ids(
    definition_kind: TaskDefinitionKind,
    tasks: tuple[TaskEffectTask, ...],
) -> None:
    other_kind = (
        TaskDefinitionKind.CALIBRATION if definition_kind is TaskDefinitionKind.FORMAL else TaskDefinitionKind.FORMAL
    )
    other_payload = _load_json(_TASK_ROOT / f"{other_kind.value}.json")
    other_rows = other_payload.get("tasks", [])
    other_ids = {row.get("task_id") for row in other_rows if isinstance(row, dict)}
    overlap = {task.task_id for task in tasks} & other_ids
    if overlap:
        raise ValueError(f"formal and calibration task ids overlap: {sorted(overlap)}")
    other_fixture_rows = other_payload.get("repositories", [])
    other_fixture_ids = {row.get("fixture_id") for row in other_fixture_rows if isinstance(row, dict)}
    fixture_overlap = {task.fixture_id for task in tasks} & other_fixture_ids
    if fixture_overlap:
        raise ValueError(f"formal and calibration fixture ids overlap: {sorted(fixture_overlap)}")
    other_expected_ids = {
        row.get("expected_artifact", {}).get("expected_id")
        for row in other_rows
        if isinstance(row, dict) and isinstance(row.get("expected_artifact"), dict)
    }
    expected_overlap = {task.expected_id for task in tasks} & other_expected_ids
    if expected_overlap:
        raise ValueError(f"formal and calibration expected ids overlap: {sorted(expected_overlap)}")


def _validate_cross_track_retrieval_ids(
    definition: RetrievalDefinition,
) -> None:
    other_kind = (
        TaskDefinitionKind.CALIBRATION
        if definition.definition_kind is TaskDefinitionKind.FORMAL
        else TaskDefinitionKind.FORMAL
    )
    other_payload = _load_json(_TASK_ROOT / f"retrieval_{other_kind.value}.json")
    other_corpus_rows = other_payload.get("corpus", [])
    other_memory_ids = {row.get("memory_id") for row in other_corpus_rows if isinstance(row, dict)}
    memory_overlap = {memory.memory_id for memory in definition.corpus} & other_memory_ids
    if memory_overlap:
        raise ValueError(f"formal and calibration Memory ids overlap: {sorted(memory_overlap)}")
    other_rows = other_payload.get("queries", [])
    other_ids = {row.get("query_id") for row in other_rows if isinstance(row, dict)}
    overlap = {query.query_id for query in definition.queries} & other_ids
    if overlap:
        raise ValueError(f"formal and calibration query ids overlap: {sorted(overlap)}")
    other_texts = {str(row.get("query_text", "")).casefold() for row in other_rows if isinstance(row, dict)}
    wording_overlap = {query.query_text for query in definition.queries if query.query_text.casefold() in other_texts}
    if wording_overlap:
        raise ValueError("formal and calibration query wording overlaps")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid task definition: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"task definition root must be an object: {path}")
    return payload


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_str(
    raw: dict[str, Any],
    key: str,
) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string when present")
    return value


def _optional_normalized_path(
    raw: dict[str, Any],
    key: str,
) -> str | None:
    value = _optional_str(raw, key)
    if value is None:
        return None
    return require_normalized_relative_path(
        value,
        field_name=key,
    )


def _str_tuple(
    raw: dict[str, Any],
    key: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"{key} must be a list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{key} must contain non-empty strings")
    result = tuple(value)
    _ensure_unique(result, key)
    return result


def _path_tuple(
    raw: dict[str, Any],
    key: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    return tuple(
        require_normalized_relative_path(item, field_name=key) for item in _str_tuple(raw, key, allow_empty=allow_empty)
    )


def _ensure_unique(values: Any, label: str) -> None:
    materialized = tuple(values)
    if len(set(materialized)) != len(materialized):
        raise ValueError(f"duplicate {label}")


__all__ = [
    "CALIBRATION_RETRIEVAL_QUERY_COUNT",
    "CALIBRATION_TASK_COUNT",
    "FORMAL_RETRIEVAL_QUERY_COUNT",
    "FORMAL_TASK_COUNT",
    "load_retrieval_definition",
    "load_task_effect_tasks",
    "retrieval_definition_digest",
    "task_effect_task_set_digest",
]
