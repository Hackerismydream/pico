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


def _backend(repository: Path):
    from myna.integrations.pico import make_backend

    context = SimpleNamespace(config={}, services=SimpleNamespace(workspace=repository))
    return make_backend(context)


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
        await backend.stop()


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
    if len(revisions) != 1:
        raise RuntimeError("candidate preparation did not create exactly one Skill revision")
    revision = revisions[0]["revision"]
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
