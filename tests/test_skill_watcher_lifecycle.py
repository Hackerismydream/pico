"""Lifecycle contracts for the Local Skill filesystem watcher."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pico.cli._runtime_assembly import RuntimeAssembly
from pico.memory_engine.skill_local.watcher import SkillFileWatcher


def test_skill_file_watcher_stops_and_releases_native_thread(tmp_path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    watcher = SkillFileWatcher(
        [root],
        on_change=lambda _source: None,
        resolve_source=lambda _path: "workspace",
    )

    assert watcher.start() is True
    thread = watcher._thread
    assert thread is not None
    assert thread.is_alive()

    watcher.stop()

    assert watcher._thread is None
    assert not thread.is_alive()


def test_skill_file_watcher_keeps_handle_when_join_times_out(tmp_path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    watcher = SkillFileWatcher(
        [root],
        on_change=lambda _source: None,
        resolve_source=lambda _path: "workspace",
    )

    thread = MagicMock()
    thread.is_alive.return_value = True
    watcher._thread = thread

    with pytest.raises(RuntimeError, match="did not stop"):
        watcher.stop(timeout=0.01)

    thread.join.assert_called_once_with(timeout=0.01)
    assert watcher._thread is thread


@pytest.mark.asyncio
async def test_runtime_close_stops_skill_watcher_before_agent_and_backend() -> None:
    order: list[str] = []
    skills = SimpleNamespace(
        stop_file_watcher=MagicMock(
            side_effect=lambda: order.append("skills.stop"),
        ),
    )
    agent_loop = SimpleNamespace(
        context=SimpleNamespace(skills=skills),
        close_mcp=AsyncMock(side_effect=lambda: order.append("agent.close")),
    )
    backend = SimpleNamespace(
        stop=AsyncMock(side_effect=lambda: order.append("backend.stop")),
    )
    runtime = RuntimeAssembly(
        agent_loop=agent_loop,
        session_manager=object(),
        backend=backend,
    )

    await runtime.close()
    await runtime.close()

    assert order == ["skills.stop", "agent.close", "backend.stop"]
    skills.stop_file_watcher.assert_called_once_with()
    agent_loop.close_mcp.assert_awaited_once()
    backend.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_close_retries_failed_watcher_after_other_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pico.cli import _runtime_assembly

    order: list[str] = []
    skills = SimpleNamespace(
        stop_file_watcher=MagicMock(
            side_effect=[RuntimeError("watcher stuck"), None],
        ),
    )
    agent_loop = SimpleNamespace(
        context=SimpleNamespace(skills=skills),
        close_mcp=AsyncMock(side_effect=lambda: order.append("agent.close")),
    )
    backend = SimpleNamespace(
        stop=AsyncMock(side_effect=lambda: order.append("backend.stop")),
    )
    runtime = RuntimeAssembly(
        agent_loop=agent_loop,
        session_manager=object(),
        backend=backend,
    )
    log = MagicMock()
    monkeypatch.setattr(_runtime_assembly, "logger", log)

    await runtime.close()
    await runtime.close()

    assert skills.stop_file_watcher.call_count == 2
    assert agent_loop.close_mcp.await_count == 2
    backend.stop.assert_awaited_once()
    assert order == ["agent.close", "backend.stop", "agent.close"]
    log.exception.assert_called_once_with(
        "local Skill watcher close failed; continuing shutdown",
    )
