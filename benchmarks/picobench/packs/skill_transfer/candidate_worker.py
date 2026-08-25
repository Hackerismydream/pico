from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _run(argv: tuple[str, ...], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=300)
    if completed.returncode != 0:
        raise RuntimeError(f"candidate command failed: {Path(argv[0]).name}")
    return completed


def _cli_json(repository: Path, *arguments: str) -> dict[str, Any]:
    completed = _run((str(Path(sys.executable).parent / "myna"), *arguments), cwd=repository)
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("Myna candidate command returned non-object JSON")
    return value


def _learning_experience_map(repository: Path, ability: dict[str, Any]) -> dict[str, str]:
    completed = _run((str(Path(sys.executable).parent / "myna"), "list"), cwd=repository)
    memories = json.loads(completed.stdout)
    if not isinstance(memories, list):
        raise RuntimeError("Myna memory list returned non-array JSON")
    expected = {
        f"skill-transfer:{ability['ability_id']}:{item['instance_id']}": item["instance_id"]
        for item in ability["learning"]
    }
    mapped: dict[str, str] = {}
    for memory in memories:
        if not isinstance(memory, dict) or memory.get("memory_type") != "task_experience":
            continue
        sessions = {
            reference.get("session_id")
            for reference in memory.get("evidence", [])
            if isinstance(reference, dict) and reference.get("provider") == "pico"
        }
        for session_id in sessions & set(expected):
            mapped[expected[str(session_id)]] = str(memory["memory_id"])
    if set(mapped) != {item["instance_id"] for item in ability["learning"]}:
        raise RuntimeError("learning instances do not map one-to-one to Task Experiences")
    return mapped


def _backend(repository: Path):
    from myna.integrations.pico import make_backend

    context = SimpleNamespace(config={}, services=SimpleNamespace(workspace=repository))
    return make_backend(context)


async def _stop_with_index_recovery(backend: Any, repository: Path) -> None:
    try:
        await backend.stop()
    except Exception as error:
        if getattr(error, "code", None) != "index_not_ready":
            raise
        report = _cli_json(repository, "process", "--no-semantic", "--index", "--max-jobs", "128")
        health = report.get("index", {})
        if any(int(health.get(field, 0)) for field in ("pending", "leased", "failed", "stale")):
            raise RuntimeError(
                "candidate index recovery did not reach ready state: "
                + json.dumps(
                    {field: health.get(field) for field in ("pending", "leased", "indexed", "failed", "stale")},
                    sort_keys=True,
                )
            ) from error


async def _capture(repository: Path, ability: dict[str, Any]) -> None:
    backend = _backend(repository)
    await backend.start()
    try:
        for index, item in enumerate(ability["learning"], 1):
            session_id = f"skill-transfer:{ability['ability_id']}:{item['instance_id']}"
            await backend.store(
                session_id,
                [
                    {"role": "user", "content": ability["goal"]},
                    {"role": "assistant", "content": item["result"]},
                ],
            )
            await backend.feedback(
                {
                    "schema": "pico.turn-feedback.v1",
                    "base_revision": "a" * 40,
                    "session_id": session_id,
                    "turn_id": f"learning-{index}",
                    "trace_id": f"skill-transfer-{ability['ability_id']}-{index}",
                    "terminal_state": "completed",
                    "delivery_state": "delivered",
                    "tool_receipts": [],
                    "command_receipts": [],
                    "file_changes": [],
                    "verifications": [{"check_name": item["verification"], "outcome": "success", "call_id": None}],
                    "injected_skill_ids": [],
                    "referenced_skill_ids": [],
                }
            )
    finally:
        await _stop_with_index_recovery(backend, repository)


async def _retry_pending(repository: Path, ability_id: str) -> None:
    backend = _backend(repository)
    await backend.start()
    try:
        session_id = f"skill-transfer:{ability_id}:retry-tick"
        await backend.store(
            session_id,
            [
                {"role": "user", "content": "Record an extraction retry tick without creating a learning example."},
                {"role": "assistant", "content": "Retry tick recorded."},
            ],
        )
        await backend.feedback(
            {
                "schema": "pico.turn-feedback.v1",
                "base_revision": "a" * 40,
                "session_id": session_id,
                "turn_id": "retry-tick",
                "trace_id": f"skill-transfer-{ability_id}-retry-tick",
                "terminal_state": "completed",
                "delivery_state": "delivered",
                "tool_receipts": [],
                "command_receipts": [],
                "file_changes": [],
                "verifications": [
                    {"check_name": "candidate-extraction-retry-tick", "outcome": "failure", "call_id": None}
                ],
                "injected_skill_ids": [],
                "referenced_skill_ids": [],
            }
        )
    finally:
        await _stop_with_index_recovery(backend, repository)


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if spec.get("mode") == "recall":
        print(json.dumps(asyncio.run(_recall(Path(spec["repository"]), spec["query"])), sort_keys=True))
        return 0
    root = Path(spec["root"]).resolve()
    repository = root / "repository"
    runtime = root / "runtime"
    control = root / "control-runtime"
    treatment = root / "treatment-runtime"
    repository.mkdir(parents=True)
    _run(("git", "init", "-q"), cwd=repository)
    _cli_json(
        repository,
        "init",
        "--root",
        str(runtime),
        "--repo-key",
        f"skill-transfer/{spec['ability']['ability_id']}",
        "--retrieval-profile",
        "fastembed",
        "--semantic-profile",
        "openai-compatible",
    )
    asyncio.run(_capture(repository, spec["ability"]))
    report = _cli_json(repository, "skill", "list")
    revisions = report.get("revisions", [])
    if not revisions:
        asyncio.run(_retry_pending(repository, spec["ability"]["ability_id"]))
        report = _cli_json(repository, "skill", "list")
        revisions = report.get("revisions", [])
    if len(revisions) != 1:
        raise RuntimeError("candidate preparation did not create exactly one Skill revision")
    revision = revisions[0]["revision"]
    learning_experiences = _learning_experience_map(repository, spec["ability"])
    if set(learning_experiences.values()) != set(revision["source_experience_ids"]):
        raise RuntimeError("Skill revision provenance does not match the learning instances")
    shutil.copytree(runtime, control)
    activation = _cli_json(
        repository,
        "skill",
        "activate",
        revision["revision_id"],
        "--authority",
        "evaluation",
        "--receipt-id",
        f"skill-transfer-v1:{spec['ability']['ability_id']}",
    )
    shutil.copytree(runtime, treatment)
    print(
        json.dumps(
            {
                "ability_id": spec["ability"]["ability_id"],
                "active_revision_id": activation["revision_id"],
                "control_runtime": str(control),
                "skill_id": revision["skill_id"],
                "learning_experience_map": learning_experiences,
                "source_experience_ids": revision["source_experience_ids"],
                "source_fact_ids": revision["source_fact_ids"],
                "treatment_runtime": str(treatment),
            },
            sort_keys=True,
        )
    )
    return 0


async def _recall(repository: Path, query: str) -> dict[str, Any]:
    backend = _backend(repository)
    await backend.start()
    try:
        hits = await backend.recall(query, agent_id="pico", top_k=5)
    finally:
        await backend.stop()
    return {
        "recalled_revision_ids": [str(item.metadata.get("revision_id")) for item in hits],
        "source_experience_ids": [item.metadata.get("source_experience_ids", []) for item in hits],
    }


if __name__ == "__main__":
    raise SystemExit(main())
