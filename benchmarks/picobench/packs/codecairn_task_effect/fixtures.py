from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Iterable

from benchmarks.picobench.canonical import canonical_digest, canonical_json

from .models import (
    RepositoryFixture,
    RepositoryFixtureDefinition,
    TaskEffectTask,
)

FIXTURE_MARKER = ".picobench-task-effect-fixture.json"
FIXTURE_MARKER_SCHEMA = "pico.picobench.repository-fixture.v2"


def build_repository_fixture(
    task_or_definition: TaskEffectTask | RepositoryFixtureDefinition,
    destination: Path,
) -> RepositoryFixture:
    definition = _fixture_definition(task_or_definition)
    root = Path(destination)
    if root.is_symlink():
        raise ValueError("repository fixture destination cannot be a symlink")
    if root.exists() and not root.is_dir():
        raise ValueError("repository fixture destination must be a directory")
    if root.exists() and any(root.iterdir()):
        raise ValueError("repository fixture destination must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    for fixture_file in definition.files:
        target = root.joinpath(*Path(fixture_file.path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(fixture_file.content, encoding="utf-8")
        if fixture_file.executable:
            target.chmod(target.stat().st_mode | 0o111)
    marker = {
        "schema": FIXTURE_MARKER_SCHEMA,
        "fixture_id": definition.fixture_id,
        "repository_id": definition.repository_id,
        "revision": definition.revision,
        "fixture_digest": definition.digest,
    }
    (root / FIXTURE_MARKER).write_text(
        canonical_json(marker) + "\n",
        encoding="utf-8",
    )
    return RepositoryFixture(
        root=root.resolve(),
        definition=definition,
        fixture_digest=definition.digest,
        tree_digest=repository_tree_digest(root),
    )


def reset_repository_fixture(
    task_or_definition: TaskEffectTask | RepositoryFixtureDefinition,
    destination: Path,
) -> RepositoryFixture:
    definition = _fixture_definition(task_or_definition)
    root = Path(destination)
    if root.exists():
        _validate_reset_target(root, definition)
        shutil.rmtree(root)
    return build_repository_fixture(definition, root)


def parent_owned_prior_fixture_definition(
    task: TaskEffectTask,
) -> RepositoryFixtureDefinition:
    mutation = task.parent_owned_mutation
    if mutation is None:
        raise ValueError(f"task has no parent-owned mutation: {task.task_id}")
    return mutation.prior_fixture(task.fixture)


def build_parent_owned_prior_fixture(
    task: TaskEffectTask,
    destination: Path,
) -> RepositoryFixture:
    return build_repository_fixture(
        parent_owned_prior_fixture_definition(task),
        destination,
    )


def apply_parent_owned_mutation(
    task: TaskEffectTask,
    destination: Path,
) -> RepositoryFixture:
    prior_definition = parent_owned_prior_fixture_definition(task)
    root = Path(destination)
    drift = fixture_file_drift(prior_definition, root)
    if drift:
        raise ValueError(f"parent-owned prior fixture drifted: {', '.join(drift)}")
    observed_paths = set(observed_repository_paths(root))
    expected_paths = set(expected_repository_paths(prior_definition))
    if observed_paths != expected_paths:
        raise ValueError("parent-owned prior fixture has unexpected paths")
    _validate_reset_target(root, prior_definition)
    shutil.rmtree(root)
    evaluated = build_repository_fixture(task.fixture, root)
    if fixture_file_drift(task.fixture, root):
        raise ValueError("parent-owned mutation did not produce evaluated state")
    return evaluated


def repository_tree_digest(root: Path) -> str:
    root = Path(root).resolve()
    entries: list[dict[str, str | bool]] = []
    if not root.is_dir():
        raise ValueError(f"repository fixture root does not exist: {root}")
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append(
                {
                    "path": relative,
                    "symlink": True,
                    "target": str(path.readlink()),
                }
            )
            continue
        if path.is_dir():
            continue
        entries.append(
            {
                "path": relative,
                "symlink": False,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "executable": bool(path.stat().st_mode & 0o111),
            }
        )
    return canonical_digest(entries)


def expected_repository_paths(
    definition: RepositoryFixtureDefinition,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            (
                *(fixture_file.path for fixture_file in definition.files),
                FIXTURE_MARKER,
            )
        )
    )


def observed_repository_paths(root: Path) -> tuple[str, ...]:
    root = Path(root).resolve()
    if not root.is_dir():
        return ()
    return tuple(
        sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_symlink() or not path.is_dir())
    )


def fixture_file_drift(
    definition: RepositoryFixtureDefinition,
    root: Path,
) -> tuple[str, ...]:
    root = Path(root)
    if root.is_symlink():
        return ("fixture_root_symlink",)
    root = root.resolve()
    findings: list[str] = []
    for fixture_file in definition.files:
        path = root.joinpath(*Path(fixture_file.path).parts)
        if path.is_symlink():
            findings.append(f"fixture_file_symlink:{fixture_file.path}")
        elif not path.is_file():
            findings.append(f"fixture_file_missing:{fixture_file.path}")
        elif path.read_text(encoding="utf-8") != fixture_file.content:
            findings.append(f"fixture_file_changed:{fixture_file.path}")
        elif bool(path.stat().st_mode & 0o111) != fixture_file.executable:
            findings.append(f"fixture_file_mode_changed:{fixture_file.path}")
    marker = root / FIXTURE_MARKER
    if not marker.is_file() or marker.is_symlink():
        findings.append("fixture_marker_missing")
    else:
        try:
            marker_payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            findings.append("fixture_marker_invalid")
        else:
            if marker_payload != {
                "schema": FIXTURE_MARKER_SCHEMA,
                "fixture_id": definition.fixture_id,
                "repository_id": definition.repository_id,
                "revision": definition.revision,
                "fixture_digest": definition.digest,
            }:
                findings.append("fixture_marker_changed")
    return tuple(findings)


def normalized_changed_paths(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(paths)))


def _fixture_definition(
    task_or_definition: TaskEffectTask | RepositoryFixtureDefinition,
) -> RepositoryFixtureDefinition:
    if isinstance(task_or_definition, TaskEffectTask):
        return task_or_definition.fixture
    if isinstance(task_or_definition, RepositoryFixtureDefinition):
        return task_or_definition
    raise TypeError("expected a task or repository fixture definition")


def _validate_reset_target(
    root: Path,
    definition: RepositoryFixtureDefinition,
) -> None:
    if root.is_symlink():
        raise ValueError("repository fixture reset target cannot be a symlink")
    resolved = root.resolve()
    if len(resolved.parts) < 3 or resolved == Path.home().resolve():
        raise ValueError("refusing to reset a broad filesystem path")
    marker_path = resolved / FIXTURE_MARKER
    if not marker_path.is_file() or marker_path.is_symlink():
        raise ValueError("refusing to reset an unmarked directory")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("refusing to reset an invalid fixture marker") from exc
    if (
        marker.get("schema") != FIXTURE_MARKER_SCHEMA
        or marker.get("fixture_id") != definition.fixture_id
        or marker.get("fixture_digest") != definition.digest
    ):
        raise ValueError("refusing to reset a different repository fixture")


__all__ = [
    "FIXTURE_MARKER",
    "FIXTURE_MARKER_SCHEMA",
    "apply_parent_owned_mutation",
    "build_parent_owned_prior_fixture",
    "build_repository_fixture",
    "expected_repository_paths",
    "fixture_file_drift",
    "normalized_changed_paths",
    "observed_repository_paths",
    "parent_owned_prior_fixture_definition",
    "repository_tree_digest",
    "reset_repository_fixture",
]
