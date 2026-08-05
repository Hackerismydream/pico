from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from benchmarks.picobench.canonical import canonical_digest, to_primitive
from benchmarks.picobench.schema import (
    RetrievalConfigurationSpec,
    RetrievalQuerySpec,
    RetrievalSuiteSpec,
    TaskSpec,
)

TASK_SCHEMA = "pico.picobench.codecairn-task-effect.v2"
RETRIEVAL_SCHEMA = "pico.picobench.codecairn-retrieval-quality.v2"


class TaskDefinitionKind(StrEnum):
    FORMAL = "formal"
    CALIBRATION = "calibration"


class TaskClass(StrEnum):
    FACT = "fact"
    EXPERIENCE = "experience"
    STALE_CONFLICT = "stale_conflict"
    IRRELEVANT = "irrelevant"


class RetrievalQueryClass(StrEnum):
    FACT_POSITIVE = "fact_positive"
    EXPERIENCE_POSITIVE = "experience_positive"
    HARD_NEGATIVE = "hard_negative"
    STALE = "stale"
    CROSS_REPOSITORY = "cross_repository"

    @property
    def label(self) -> str:
        return {
            RetrievalQueryClass.FACT_POSITIVE: "positive_repository_fact",
            RetrievalQueryClass.EXPERIENCE_POSITIVE: ("positive_execution_experience"),
            RetrievalQueryClass.HARD_NEGATIVE: "hard_negative",
            RetrievalQueryClass.STALE: "stale_or_superseded",
            RetrievalQueryClass.CROSS_REPOSITORY: "cross_repository",
        }[self]

    @property
    def is_positive(self) -> bool:
        return self in {
            RetrievalQueryClass.FACT_POSITIVE,
            RetrievalQueryClass.EXPERIENCE_POSITIVE,
        }


class MemoryValidity(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class FixtureFile:
    path: str
    content: str
    executable: bool = False

    @property
    def content_digest(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RepositoryFixtureDefinition:
    fixture_id: str
    repository_id: str
    revision: str
    files: tuple[FixtureFile, ...]

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "fixture_id": self.fixture_id,
                "repository_id": self.repository_id,
                "revision": self.revision,
                "files": self.files,
            }
        )

    @property
    def file_map(self) -> Mapping[str, FixtureFile]:
        return MappingProxyType({file.path: file for file in self.files})


@dataclass(frozen=True)
class ParentOwnedMutation:
    mutation_id: str
    path: str
    prior_revision: str
    prior_content: str
    prior_observation: str

    def prior_fixture(
        self,
        evaluated_fixture: RepositoryFixtureDefinition,
    ) -> RepositoryFixtureDefinition:
        if self.path not in evaluated_fixture.file_map:
            raise ValueError(f"mutation path is absent from evaluated fixture: {self.path}")
        files = tuple(
            FixtureFile(
                path=fixture_file.path,
                content=self.prior_content,
                executable=fixture_file.executable,
            )
            if fixture_file.path == self.path
            else fixture_file
            for fixture_file in evaluated_fixture.files
        )
        return RepositoryFixtureDefinition(
            fixture_id=evaluated_fixture.fixture_id,
            repository_id=evaluated_fixture.repository_id,
            revision=self.prior_revision,
            files=files,
        )

    def contract_payload(
        self,
        evaluated_fixture: RepositoryFixtureDefinition,
    ) -> Mapping[str, str]:
        prior_fixture = self.prior_fixture(evaluated_fixture)
        payload = {
            "mutation_id": self.mutation_id,
            "path": self.path,
            "prior_fixture_digest": prior_fixture.digest,
            "evaluated_fixture_digest": evaluated_fixture.digest,
        }
        return MappingProxyType(
            {
                **payload,
                "contract_digest": canonical_digest(payload),
            }
        )


@dataclass(frozen=True)
class ExpectedArtifact:
    expected_id: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            _freeze_json_value(dict(self.payload)),
        )

    @property
    def digest(self) -> str:
        return canonical_digest(self.payload)


@dataclass(frozen=True)
class ReferenceCapture:
    name: str
    path: str
    line_prefix: str
    line_suffix: str

    def resolve(self, source_contents: Mapping[str, str]) -> str:
        try:
            content = source_contents[self.path]
        except KeyError as exc:
            raise ValueError(f"reference capture source is missing: {self.path}") from exc
        matches = [
            line
            for line in content.splitlines()
            if line.startswith(self.line_prefix)
            and line.endswith(self.line_suffix)
            and len(line) >= len(self.line_prefix) + len(self.line_suffix)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"reference capture must match exactly one line: {self.name}",
            )
        value = matches[0][len(self.line_prefix) :]
        if self.line_suffix:
            value = value[: -len(self.line_suffix)]
        return value


@dataclass(frozen=True)
class ReferenceSolution:
    captures: tuple[ReferenceCapture, ...]
    result_template: Any
    evidence_path: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "result_template",
            _freeze_json_value(self.result_template),
        )

    @property
    def digest(self) -> str:
        return canonical_digest(self)

    def resolve_result(
        self,
        source_contents: Mapping[str, str],
    ) -> Any:
        values = {capture.name: capture.resolve(source_contents) for capture in self.captures}
        return _resolve_reference_template(self.result_template, values)


@dataclass(frozen=True)
class TaskEffectTask:
    task_id: str
    definition_kind: TaskDefinitionKind
    task_class: TaskClass
    title: str
    fixture: RepositoryFixtureDefinition
    prior_work_prompt: str
    memory_query: str
    evaluation_prompt: str
    source_paths: tuple[str, ...]
    artifact_path: str
    expected_artifact: ExpectedArtifact
    reference_solution: ReferenceSolution
    allowed_mutation_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    required_receipt_ids: tuple[str, ...]
    test_command: str
    parent_owned_mutation: ParentOwnedMutation | None = None

    @property
    def fixture_id(self) -> str:
        return self.fixture.fixture_id

    @property
    def expected_id(self) -> str:
        return self.expected_artifact.expected_id

    @property
    def expected_digest(self) -> str:
        return self.expected_artifact.digest

    @property
    def mutation_contract(self) -> Mapping[str, str] | None:
        if self.parent_owned_mutation is None:
            return None
        return self.parent_owned_mutation.contract_payload(self.fixture)

    def to_task_spec(self) -> TaskSpec:
        return TaskSpec(
            task_id=self.task_id,
            payload={
                "schema": TASK_SCHEMA,
                "definition_kind": self.definition_kind.value,
                "task_class": self.task_class.value,
                "fixture_id": self.fixture_id,
                "fixture_revision": self.fixture.revision,
                "fixture_digest": self.fixture.digest,
                "expected_id": self.expected_id,
                "expected_digest": self.expected_digest,
                "prior_work_prompt": self.prior_work_prompt,
                "prior_work_prompt_digest": canonical_digest(
                    self.prior_work_prompt,
                ),
                "memory_query": self.memory_query,
                "memory_query_digest": canonical_digest(self.memory_query),
                "reference_solution_digest": self.reference_solution.digest,
                "evaluation_prompt": self.evaluation_prompt,
                "source_paths": list(self.source_paths),
                "artifact_path": self.artifact_path,
                "allowed_mutation_paths": list(self.allowed_mutation_paths),
                "forbidden_paths": list(self.forbidden_paths),
                "required_receipt_ids": list(self.required_receipt_ids),
                "test_command": self.test_command,
                "parent_owned_mutation": self.mutation_contract,
                "verifier": "external_parent_owned_task_effect_v2",
            },
        )


@dataclass(frozen=True)
class RetrievalMemory:
    memory_id: str
    repository_id: str
    memory_class: str
    validity: MemoryValidity
    content: str
    source_uri: str
    fixture_revision: str | None = None
    evidence_path: str | None = None
    evidence_digest: str | None = None


@dataclass(frozen=True)
class RetrievalQuery:
    query_id: str
    query_class: RetrievalQueryClass
    repository_id: str
    query_text: str
    expected_memory_ids: tuple[str, ...] = ()
    forbidden_memory_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalDefinition:
    definition_kind: TaskDefinitionKind
    suite_id: str
    corpus: tuple[RetrievalMemory, ...]
    queries: tuple[RetrievalQuery, ...]

    @property
    def corpus_by_id(self) -> Mapping[str, RetrievalMemory]:
        return MappingProxyType({memory.memory_id: memory for memory in self.corpus})

    @property
    def expected_id_map(self) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType({query.query_id: query.expected_memory_ids for query in self.queries})

    @property
    def corpus_digest(self) -> str:
        return canonical_digest(self.corpus)

    @property
    def query_labels_digest(self) -> str:
        return canonical_digest(self.queries)

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "schema": RETRIEVAL_SCHEMA,
                "definition_kind": self.definition_kind.value,
                "suite_id": self.suite_id,
                "corpus": self.corpus,
                "queries": self.queries,
            }
        )

    def anonymous_memory_id(self, memory_id: str) -> str:
        return hashlib.sha256(f"{self.suite_id}:{memory_id}".encode("utf-8")).hexdigest()[:20]

    def to_retrieval_suite_spec(self) -> RetrievalSuiteSpec:
        query_specs = tuple(
            RetrievalQuerySpec(
                query_id=query.query_id,
                label=query.query_class.label,
                expected_item_ids=tuple(self.anonymous_memory_id(memory_id) for memory_id in query.expected_memory_ids),
                payload={
                    "query_text": query.query_text,
                    "repository_id": query.repository_id,
                    "query_class": query.query_class.value,
                    "forbidden_memory_ids": [
                        self.anonymous_memory_id(memory_id) for memory_id in query.forbidden_memory_ids
                    ],
                },
            )
            for query in self.queries
        )
        return RetrievalSuiteSpec(
            retrieval_suite_id=self.suite_id,
            queries=query_specs,
            configurations=(
                RetrievalConfigurationSpec(
                    configuration_id="codecairn",
                    settings={
                        "memory_backend": "codecairn",
                        "retrieval_contract": "task_effect_v2",
                    },
                ),
            ),
            corpus_digest=self.corpus_digest,
            query_labels_digest=canonical_digest(query_specs),
        )

    def canonical_payload(self) -> dict[str, Any]:
        return to_primitive(
            {
                "schema": RETRIEVAL_SCHEMA,
                "definition_kind": self.definition_kind,
                "suite_id": self.suite_id,
                "corpus": self.corpus,
                "queries": self.queries,
            }
        )


@dataclass(frozen=True)
class TaskEffectTestState:
    command: str
    exit_code: int
    fixture_digest: str


@dataclass(frozen=True)
class TaskEffectVerificationEvidence:
    receipt_ids: tuple[str, ...]
    changed_paths: tuple[str, ...]
    test_state: TaskEffectTestState | None


@dataclass(frozen=True)
class RepositoryFixture:
    root: Path
    definition: RepositoryFixtureDefinition
    fixture_digest: str
    tree_digest: str


def _resolve_reference_template(
    value: Any,
    captures: Mapping[str, str],
) -> Any:
    if isinstance(value, str):
        if value.startswith("{") and value.endswith("}"):
            name = value[1:-1]
            if name in captures:
                return captures[name]
        return value
    if isinstance(value, list | tuple):
        return [_resolve_reference_template(item, captures) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _resolve_reference_template(item, captures) for key, item in value.items()}
    if value is None or isinstance(value, bool | int | float):
        return value
    raise TypeError(
        f"unsupported reference result template value: {type(value).__name__}",
    )


def _freeze_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json_value(item) for item in value)
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise TypeError(
        f"unsupported JSON value: {type(value).__name__}",
    )


__all__ = [
    "ExpectedArtifact",
    "FixtureFile",
    "MemoryValidity",
    "ParentOwnedMutation",
    "ReferenceCapture",
    "ReferenceSolution",
    "RETRIEVAL_SCHEMA",
    "RepositoryFixture",
    "RepositoryFixtureDefinition",
    "RetrievalDefinition",
    "RetrievalMemory",
    "RetrievalQuery",
    "RetrievalQueryClass",
    "TASK_SCHEMA",
    "TaskClass",
    "TaskDefinitionKind",
    "TaskEffectTask",
    "TaskEffectTestState",
    "TaskEffectVerificationEvidence",
]
