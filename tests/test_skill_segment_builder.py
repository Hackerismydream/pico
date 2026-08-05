"""End-to-end tests for SkillsSegmentBuilder.

The builder owns the rewriter, router, gate, local-reference resolution,
and render pipeline. Tests use stub sources to exercise each stage
without network or LLM calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pico.context_engine.base import AssemblyContext, TokenBudget
from pico.context_engine.segments.skills import SkillsSegmentBuilder
from pico.memory_engine.skill_forge import (
    LLMGateFilter,
    QueryRewriter,
    SkillForgeRouter,
)
from pico.memory_engine.skill_forge.types import RouterHit

# ----------------------------------------------------------------------
# Stub doubles
# ----------------------------------------------------------------------


@dataclass
class _Resp:
    content: str
    finish_reason: str = "stop"


class _StubProvider:
    def __init__(self, response: Any) -> None:
        self._response = response

    async def chat_with_retry(self, **_kwargs: Any) -> _Resp:
        if isinstance(self._response, Exception):
            raise self._response
        if isinstance(self._response, _Resp):
            return self._response
        return _Resp(content=str(self._response))


class _StubSource:
    """SkillSource that returns a hard-coded hit list."""

    def __init__(self, name: str, hits: list[RouterHit], weight: float = 1.0) -> None:
        self.name = name
        self.weight = weight
        self._hits = hits

    async def search(
        self,
        query: str,
        history: list[dict[str, Any]],
        k: int,
    ) -> list[RouterHit]:
        return list(self._hits[:k])


def _hit(qid: str, name: str, body: str = "", **meta: Any) -> RouterHit:
    source = qid.split("/", 1)[0]
    meta.setdefault("source", source)
    return RouterHit(
        qualified_id=qid,
        name=name,
        content=body,
        score=0.5,
        meta=meta,
    )


def _ctx(message: str) -> AssemblyContext:
    return AssemblyContext(
        session_key="s",
        current_message=message,
        media=None,
        channel=None,
        chat_id=None,
        session_messages=[],
        budget=TokenBudget(
            context_length=200_000,
            reserved_output=8000,
            reserved_tools=4000,
            reserved_system=4000,
            available_history=184_000,
        ),
    )


# ----------------------------------------------------------------------
# Baseline
# ----------------------------------------------------------------------


async def test_baseline_renders_local_hits() -> None:
    src = _StubSource(
        "local",
        [
            _hit("local/foo", "foo", body="body foo"),
            _hit("local/bar", "bar", body="body bar"),
        ],
    )
    router = SkillForgeRouter([src])
    builder = SkillsSegmentBuilder(router, skill_top_k=2)
    seg = await builder.build(_ctx("anything"))
    assert seg is not None
    assert "# Skills" in seg.text
    assert "foo" in seg.text and "bar" in seg.text
    assert seg.meta["injected_skill_ids"] == ["local/foo", "local/bar"]


async def test_no_router_returns_empty_segment() -> None:
    builder = SkillsSegmentBuilder(None)
    seg = await builder.build(_ctx("q"))
    assert seg.text == ""
    assert seg.meta["injected_skill_ids"] == []


# ----------------------------------------------------------------------
# Rewriter stage
# ----------------------------------------------------------------------


async def test_rewriter_skip_short_circuits_segment() -> None:
    src = _StubSource("local", [_hit("local/foo", "foo", body="b")])
    router = SkillForgeRouter([src])
    rewriter = QueryRewriter(_StubProvider(json.dumps({"need_retrieval": False})))
    builder = SkillsSegmentBuilder(router, rewriter=rewriter)
    seg = await builder.build(_ctx("hello there"))
    assert seg.text == ""
    assert seg.meta.get("rewriter_skipped") is True
    assert seg.meta["injected_skill_ids"] == []


async def test_rewriter_rewrite_passes_through() -> None:
    """When rewriter returns a rewritten_query, the router should be
    invoked with it (not the original)."""
    received: list[str] = []

    class _SpySource:
        name = "local"
        weight = 1.0

        async def search(self, query, history, k):  # noqa: D401
            received.append(query)
            return []

    router = SkillForgeRouter([_SpySource()])
    rewriter = QueryRewriter(
        _StubProvider(
            json.dumps(
                {
                    "need_retrieval": True,
                    "rewritten_query": "pdf gen",
                }
            )
        )
    )
    builder = SkillsSegmentBuilder(router, rewriter=rewriter)
    await builder.build(_ctx("please generate me a pdf report"))
    assert received == ["pdf gen"]


async def test_rewriter_provider_failure_is_visible_in_segment_metadata() -> None:
    src = _StubSource("local", [_hit("local/foo", "foo", body="b")])
    builder = SkillsSegmentBuilder(
        SkillForgeRouter([src]),
        rewriter=QueryRewriter(_StubProvider(TimeoutError("provider timeout"))),
    )

    seg = await builder.build(_ctx("specialized task"))

    assert seg.meta["skill_rewriter_fallback_reason"] == "provider_exception"
    assert seg.meta["skill_rewriter_failure_type"] == "TimeoutError"
    assert seg.meta["injected_skill_ids"] == ["local/foo"]


# ----------------------------------------------------------------------
# Gate stage
# ----------------------------------------------------------------------


async def test_gate_filters_pool_down_to_selected() -> None:
    src = _StubSource(
        "local",
        [
            _hit("local/keep", "keep", body="k"),
            _hit("local/drop", "drop", body="d"),
        ],
    )
    gate = LLMGateFilter(
        _StubProvider(json.dumps({"plan": "p", "skills": ["local/keep"]})),
        max_select=2,
    )
    builder = SkillsSegmentBuilder(
        SkillForgeRouter([src]),
        gate=gate,
        gate_pool_size=5,
    )
    seg = await builder.build(_ctx("task"))
    assert seg.meta["injected_skill_ids"] == ["local/keep"]
    assert "drop" not in seg.text


async def test_gate_empty_selection_yields_empty_segment() -> None:
    src = _StubSource("local", [_hit("local/foo", "foo", body="x")])
    gate = LLMGateFilter(
        _StubProvider(json.dumps({"plan": "none fits", "skills": []})),
    )
    builder = SkillsSegmentBuilder(SkillForgeRouter([src]), gate=gate)
    seg = await builder.build(_ctx("task"))
    assert seg.text == ""
    assert seg.meta["injected_skill_ids"] == []


async def test_gate_provider_failure_is_visible_in_segment_metadata() -> None:
    src = _StubSource("local", [_hit("local/foo", "foo", body="x")])
    gate = LLMGateFilter(
        _StubProvider(ConnectionError("provider unavailable")),
        legacy_top_k=1,
    )
    builder = SkillsSegmentBuilder(SkillForgeRouter([src]), gate=gate)

    seg = await builder.build(_ctx("task"))

    assert seg.meta["skill_gate_fallback_reason"] == "provider_exception"
    assert seg.meta["skill_gate_failure_type"] == "ConnectionError"
    assert seg.meta["injected_skill_ids"] == ["local/foo"]


# ----------------------------------------------------------------------
# Local refs
# ----------------------------------------------------------------------


async def test_post_gate_resolves_local_refs(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skill"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "references" / "x.md").write_text("ref body")

    body = "Read {baseDir}/references/x.md."
    src = _StubSource(
        "local",
        [
            _hit(
                "local/foo",
                "foo",
                body=body,
                skill_dir=str(skill_dir),
            )
        ],
    )
    builder = SkillsSegmentBuilder(SkillForgeRouter([src]), skill_top_k=1)
    seg = await builder.build(_ctx("anything"))
    assert f"{skill_dir}/references/x.md" in seg.text
    assert "{baseDir}" not in seg.text


# ----------------------------------------------------------------------
# Tool-names collection
# ----------------------------------------------------------------------


async def test_get_tool_names_extracts_from_openai_schema() -> None:
    captured: list[list[str] | None] = []

    class _CaptureGate(LLMGateFilter):  # type: ignore[misc]
        async def filter(
            self,
            task,
            candidates,
            available_tools=None,
            *,
            diagnostics=None,
        ):  # type: ignore[override]
            captured.append(available_tools)
            return []

    gate = _CaptureGate(_StubProvider(json.dumps({"plan": "", "skills": []})))
    src = _StubSource("local", [_hit("local/a", "a")])

    def tool_defs() -> list[dict]:
        return [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "exec"}},
            {"name": "flat_form"},
        ]

    builder = SkillsSegmentBuilder(
        SkillForgeRouter([src]),
        gate=gate,
        get_tool_definitions=tool_defs,
    )
    await builder.build(_ctx("task"))
    assert captured == [["read_file", "exec", "flat_form"]]
