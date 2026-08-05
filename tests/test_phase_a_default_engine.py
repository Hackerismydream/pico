"""ContextAssembler factory wiring and Local Skill router assembly."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pico.agent.context import ContextBuilder
from pico.agent.loop import AgentLoop
from pico.config.pico import (
    ContextConfig,
    MemoryConfig,
    SkillForgeRouterConfig,
)
from pico.context_engine import ContextAssembler, TurnContext
from pico.context_engine.factory import build_context_engine
from pico.context_engine.segments import MemorySegmentBuilder, SkillsSegmentBuilder
from pico.memory_engine import TokenBudget
from pico.memory_engine.skill_forge import LocalSkillSource

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeBackend:
    async def start(self):
        pass

    async def stop(self):
        pass

    async def feedback(self, signals):
        pass

    async def store(self, session_id, messages):
        pass

    async def recall(self, query, *, user_id=None, agent_id=None, top_k):
        return []


class _StubProvider:
    api_key = "test"

    def get_default_model(self) -> str:
        return "stub"

    async def chat(self, *args, **kwargs):
        raise NotImplementedError

    async def chat_with_retry(self, *args, **kwargs):
        raise NotImplementedError


def _stub_get_defs() -> list[dict]:
    return []


def _build_engine(
    tmp_path: Path,
    *,
    backend=None,
    memory_config: MemoryConfig | None = None,
    router_config: SkillForgeRouterConfig | None = None,
) -> ContextAssembler:
    builder = ContextBuilder(workspace=tmp_path)
    engine = build_context_engine(
        workspace=tmp_path,
        config=ContextConfig(),
        builder=builder,
        provider=_StubProvider(),
        model="stub",
        context_window_tokens=8192,
        get_tool_definitions=_stub_get_defs,
        backend=backend,
        memory_config=memory_config or MemoryConfig(),
        skill_forge_router_config=router_config or SkillForgeRouterConfig(),
    )
    assert isinstance(engine, ContextAssembler)
    return engine


def _router_sources(engine: ContextAssembler):
    skills = next(b for b in engine._builders if isinstance(b, SkillsSegmentBuilder))
    return [type(s) for s in skills._router._sources], skills._router._sources


def _memory_builder(engine: ContextAssembler) -> MemorySegmentBuilder:
    return next(b for b in engine._builders if isinstance(b, MemorySegmentBuilder))


# ---------------------------------------------------------------------------
# Factory — always builds the assembler
# ---------------------------------------------------------------------------


class TestFactory:
    def test_returns_assembler_with_backend(self, tmp_path: Path) -> None:
        assert isinstance(_build_engine(tmp_path, backend=_FakeBackend()), ContextAssembler)

    def test_returns_assembler_without_backend(self, tmp_path: Path) -> None:
        engine = _build_engine(tmp_path, backend=None)
        assert isinstance(engine, ContextAssembler)
        assert _memory_builder(engine)._backend is None


# ---------------------------------------------------------------------------
# SkillForgeRouter assembly — which sources are present
# ---------------------------------------------------------------------------


class TestSkillForgeRouterAssembly:
    async def test_real_local_skill_injects_body_and_resolves_bundled_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def forbid_network(*_args, **_kwargs) -> None:
            raise AssertionError("Local Skill assembly must not access the network")

        monkeypatch.setattr("socket.socket.connect", forbid_network)
        skill_dir = tmp_path / "skills" / "release-helper"
        (skill_dir / "scripts").mkdir(parents=True)
        (skill_dir / "references").mkdir()
        (skill_dir / "scripts" / "release.sh").write_text("#!/bin/sh\n")
        (skill_dir / "references" / "CHECKLIST.md").write_text("release checklist\n")
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: release-helper\n"
            "description: Prepare and verify a production release\n"
            "---\n"
            "Run {baseDir}/scripts/release.sh and follow "
            "[the checklist](references/CHECKLIST.md).\n"
        )

        engine = _build_engine(tmp_path, backend=None)
        assembled = await engine.assemble(
            "local-skill",
            [],
            TokenBudget(
                context_length=32_000,
                reserved_output=4_000,
                reserved_tools=2_000,
                reserved_system=2_000,
                available_history=24_000,
            ),
            turn=TurnContext(current_message="prepare and verify a production release"),
        )

        system = assembled.messages[0]["content"]
        assert "local/release-helper" in assembled.metadata["injected_skill_ids"]
        assert "Run " + str(skill_dir / "scripts" / "release.sh") in system
        assert f"[the checklist]({skill_dir / 'references' / 'CHECKLIST.md'})" in system
        assert "{baseDir}" not in system

    def test_local_source_always_present(self, tmp_path: Path) -> None:
        types, _ = _router_sources(_build_engine(tmp_path, backend=_FakeBackend()))
        assert LocalSkillSource in types

    def test_backend_does_not_change_local_skill_sources(self, tmp_path: Path) -> None:
        with_backend, _ = _router_sources(_build_engine(tmp_path, backend=_FakeBackend()))
        without_backend, _ = _router_sources(_build_engine(tmp_path, backend=None))
        assert with_backend == without_backend == [LocalSkillSource]

    def test_track_ids_from_memory_config(self, tmp_path: Path) -> None:
        engine = _build_engine(
            tmp_path,
            backend=_FakeBackend(),
            memory_config=MemoryConfig(
                user_id="alice",
            ),
        )
        assert _memory_builder(engine)._user_id == "alice"

    async def test_local_min_score_is_applied_by_factory(
        self,
        tmp_path: Path,
    ) -> None:
        skill_dir = tmp_path / "skills" / "release-helper"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: release-helper\n"
            "description: Prepare and verify a production release\n"
            "---\n"
            "Prepare and verify a production release.\n",
            encoding="utf-8",
        )
        engine = _build_engine(
            tmp_path,
            backend=None,
            router_config=SkillForgeRouterConfig(
                local_min_score=1_000_000.0,
            ),
        )

        assembled = await engine.assemble(
            "local-min-score",
            [],
            TokenBudget(
                context_length=32_000,
                reserved_output=4_000,
                reserved_tools=2_000,
                reserved_system=2_000,
                available_history=24_000,
            ),
            turn=TurnContext(
                current_message="prepare and verify a production release",
            ),
        )

        assert "local/release-helper" not in assembled.metadata["injected_skill_ids"]


# ---------------------------------------------------------------------------
# AgentLoop helpers
# ---------------------------------------------------------------------------


def _make_loop(tmp_path: Path, *, backend=None) -> AgentLoop:
    return AgentLoop(
        provider=_StubProvider(),
        workspace=tmp_path,
        model="stub",
        max_iterations=2,
        restrict_to_workspace=True,
        backend=backend,
        context_config=ContextConfig(),
        memory_config=MemoryConfig(),
        skill_forge_router_config=SkillForgeRouterConfig(),
    )


class TestAgentLoopEngineDetection:
    def test_uses_default_engine_always_true(self, tmp_path: Path) -> None:
        assert _make_loop(tmp_path, backend=_FakeBackend())._uses_default_engine() is True

    def test_uses_default_engine_true_without_backend(self, tmp_path: Path) -> None:
        assert _make_loop(tmp_path, backend=None)._uses_default_engine() is True


class TestSelectSkillsGating:
    async def test_skill_selection_short_circuits_to_none(self, tmp_path: Path) -> None:
        agent = _make_loop(tmp_path, backend=_FakeBackend())
        assert await agent._select_skills_for_turn("hi", []) is None


# ---------------------------------------------------------------------------
# Selector metadata path for _collect_injected_skill_ids
# ---------------------------------------------------------------------------


class TestInjectedIdsFromMetadata:
    def test_uses_selector_metadata(self, tmp_path: Path) -> None:
        agent = _make_loop(tmp_path, backend=None)
        fake_meta = MagicMock(spec_set=["source", "id"])
        fake_meta.source = "local"
        fake_meta.id = "git-resolver"
        ids = agent._collect_injected_skill_ids([fake_meta])
        assert "local/git-resolver" in ids
