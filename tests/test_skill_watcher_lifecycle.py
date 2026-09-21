"""Skill watcher ownership and shutdown contracts."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pico.agent.context import ContextBuilder
from pico.memory_engine.skill_forge.catalog import LocalSkillCatalog
from pico.memory_engine.skill_local.watcher import SkillFileWatcher


def test_context_builder_has_no_constructor_watcher_side_effect(tmp_path):
    builder = ContextBuilder(tmp_path)
    assert builder.skills._file_watcher is None


def test_watcher_stop_retains_live_thread_for_retry(tmp_path):
    watcher = SkillFileWatcher([tmp_path], lambda _: None, lambda _: None)
    thread = MagicMock()
    thread.is_alive.return_value = True
    watcher._thread = thread

    assert watcher.stop(timeout=0) is False
    assert watcher._thread is thread


def test_catalog_does_not_drop_watcher_that_failed_to_stop(tmp_path):
    catalog = LocalSkillCatalog(tmp_path, start_watcher=False)
    watcher = SimpleNamespace(stop=MagicMock(return_value=False))
    catalog._file_watcher = watcher

    assert catalog.stop_file_watcher() is False
    assert catalog._file_watcher is watcher


def test_real_watcher_thread_stops_before_process_shutdown(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    watcher = SkillFileWatcher([skills], lambda _: None, lambda _: None)

    assert watcher.start() is True
    thread = watcher._thread
    assert thread is not None and thread.is_alive()
    assert watcher.stop() is True
    assert not thread.is_alive()
    assert watcher._thread is None


@pytest.mark.asyncio
async def test_agent_close_stops_watcher_even_when_other_cleanup_fails(tmp_path):
    from tests.test_agent_loop_memory_pipeline import _make_agent

    agent = _make_agent(tmp_path)
    skills = tmp_path / "skills"
    skills.mkdir(exist_ok=True)
    assert agent.context.skills.start_file_watcher() is True
    thread = agent.context.skills._file_watcher._thread
    agent.close_mcp = AsyncMock(side_effect=RuntimeError("cleanup failed"))

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await agent.close()

    assert thread is not None and not thread.is_alive()
    assert agent.context.skills._file_watcher is None


@pytest.mark.asyncio
async def test_one_shot_turn_starts_runtime_owned_watcher(tmp_path):
    from tests.test_agent_loop_memory_pipeline import _make_agent, _msg
    from tests.test_agent_loop_run_emit import _EmitCollector, _drain

    agent = _make_agent(tmp_path)
    start = MagicMock(return_value=True)
    agent.context.skills.start_file_watcher = start

    try:
        await agent.run_turn(_msg(), _EmitCollector(), _drain)
    finally:
        await agent.close()

    start.assert_called_once()


@pytest.mark.asyncio
async def test_agent_close_finishes_watcher_after_caller_cancellation(tmp_path):
    from tests.test_agent_loop_memory_pipeline import _make_agent

    agent = _make_agent(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow_close():
        entered.set()
        await release.wait()

    agent.close_mcp = slow_close
    stop = MagicMock(return_value=True)
    agent.context.skills.stop_file_watcher = stop
    task = asyncio.create_task(agent.close())
    await entered.wait()
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    stop.assert_called_once()
    assert threading.current_thread().is_alive()
