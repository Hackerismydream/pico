"""Installed CodeCairn Adapter smoke through Pico's public Plugin Interface."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pico.cli._plugin_stack import build_plugin_registry, maybe_build_memory_backend
from pico.config.pico import PicoConfig


@pytest.mark.external_runtime
async def test_codecairn_workspace_lifecycle_and_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    runtime_root = tmp_path / "runtime"
    other = tmp_path / "other"
    workspace.mkdir()
    other.mkdir()
    subprocess.run(("git", "init", "-q", str(workspace)), check=True)
    executable = Path(sys.executable).parent / "codecairn"
    subprocess.run(
        (
            str(executable),
            "init",
            "--root",
            str(runtime_root),
            "--repo-key",
            "local/pico-runtime-smoke",
            "--retrieval-profile",
            "fastembed",
            "--semantic-profile",
            "none",
            "--prefetch",
        ),
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )

    monkeypatch.chdir(other)
    config = PicoConfig()
    registry = build_plugin_registry(config)
    backend = maybe_build_memory_backend(
        workspace,
        config,
        registry=registry,
    )
    assert backend is not None

    started = asyncio.create_task(backend.start())
    before = time.monotonic()
    await asyncio.sleep(0.01)
    assert time.monotonic() - before < 0.2
    await started
    await backend.store(
        "workspace-smoke",
        [
            {
                "role": "user",
                "content": "Remember that Pico Workspace binding is authoritative.",
            },
            {"role": "assistant", "content": "Recorded."},
        ],
    )
    memories = await backend.recall(
        "Which repository binding is authoritative?",
        user_id="default",
        top_k=5,
    )
    await backend.stop()

    assert len(memories) == 1
    assert memories[0].metadata["repo_key"] == "local/pico-runtime-smoke"
    assert Path.cwd() == other
