"""Tests for the LLM gate that filters router candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pico.memory_engine.skill_forge.gate import LLMGateFilter
from pico.memory_engine.skill_forge.types import RouterHit


@dataclass
class _Resp:
    content: str
    finish_reason: str = "stop"


class _StubProvider:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def chat_with_retry(self, **kwargs: Any) -> _Resp:
        self.calls.append(kwargs)
        if isinstance(self._response, BaseException):
            raise self._response
        if isinstance(self._response, _Resp):
            return self._response
        return _Resp(content=str(self._response))


def _hit(
    qid: str,
    name: str,
    body: str = "",
    desc: str = "",
    *,
    gate_required: bool = False,
) -> RouterHit:
    return RouterHit(
        qualified_id=qid,
        name=name,
        content=body,
        score=0.5,
        meta={
            "description": desc,
            "source": qid.split("/", 1)[0],
            "gate_required": gate_required,
        },
    )


# ----------------------------------------------------------------------


async def test_empty_candidates_returns_empty() -> None:
    gate = LLMGateFilter(_StubProvider("{}"))
    assert await gate.filter("any task", []) == []


async def test_selects_by_qualified_id() -> None:
    provider = _StubProvider(
        json.dumps(
            {
                "plan": "use pdf gen",
                "skills": ["local/pdf-gen"],
            }
        )
    )
    gate = LLMGateFilter(provider, max_select=2)
    hits = [
        _hit("local/pdf-gen", "pdf-gen", body="generate pdf"),
        _hit("local/weather", "weather", body="get weather"),
    ]
    out = await gate.filter("make a pdf report", hits)
    assert [h.qualified_id for h in out] == ["local/pdf-gen"]


async def test_empty_skills_list_is_valid_inject_nothing() -> None:
    provider = _StubProvider(json.dumps({"plan": "nothing fits", "skills": []}))
    out = await LLMGateFilter(provider).filter("task", [_hit("local/foo", "foo")])
    assert out == []


async def test_respects_max_select_truncation() -> None:
    provider = _StubProvider(
        json.dumps(
            {
                "plan": "p",
                "skills": ["local/a", "local/b", "local/c"],
            }
        )
    )
    gate = LLMGateFilter(provider, max_select=2)
    hits = [_hit(f"local/{n}", n) for n in ("a", "b", "c")]
    out = await gate.filter("task", hits)
    assert [h.qualified_id for h in out] == ["local/a", "local/b"]


async def test_unknown_id_in_response_silently_dropped() -> None:
    provider = _StubProvider(
        json.dumps(
            {
                "plan": "p",
                "skills": ["local/known", "ghost/missing"],
            }
        )
    )
    hits = [_hit("local/known", "known")]
    out = await LLMGateFilter(provider).filter("task", hits)
    assert [h.qualified_id for h in out] == ["local/known"]


async def test_provider_error_falls_back_to_top_n() -> None:
    """Infra failure ≠ deliberate empty. Falling back to legacy top-N
    keeps the prompt populated; returning [] would silently kill skill
    injection when the provider has a transient blip."""
    provider = _StubProvider(RuntimeError("network blip"))
    gate = LLMGateFilter(provider, legacy_top_k=2)
    hits = [_hit(f"local/{n}", n) for n in ("a", "b", "c", "d")]
    out = await gate.filter("task", hits)
    assert [h.qualified_id for h in out] == ["local/a", "local/b"]


async def test_provider_error_abstains_from_gate_required_candidates() -> None:
    provider = _StubProvider(RuntimeError("network blip"))
    diagnostics: dict[str, Any] = {}
    hits = [
        _hit("myna/a", "a", gate_required=True),
        _hit("local/b", "b"),
    ]

    out = await LLMGateFilter(provider, legacy_top_k=2).filter(
        "task",
        hits,
        diagnostics=diagnostics,
    )

    assert [h.qualified_id for h in out] == ["local/b"]
    assert diagnostics["fallback_reason"] == "provider_exception"
    assert diagnostics["abstained_skill_ids"] == ["myna/a"]


async def test_unparseable_response_falls_back_to_top_n() -> None:
    provider = _StubProvider("garbage no json here")
    gate = LLMGateFilter(provider, legacy_top_k=1)
    hits = [_hit("local/a", "a"), _hit("local/b", "b")]
    out = await gate.filter("task", hits)
    assert [h.qualified_id for h in out] == ["local/a"]


async def test_unknown_id_invalidates_gate_required_selection() -> None:
    provider = _StubProvider(
        json.dumps(
            {
                "plan": "p",
                "skills": ["myna/known", "ghost/missing"],
            }
        )
    )
    diagnostics: dict[str, Any] = {}

    out = await LLMGateFilter(provider).filter(
        "task",
        [_hit("myna/known", "known", gate_required=True)],
        diagnostics=diagnostics,
    )

    assert out == []
    assert diagnostics["fallback_reason"] == "unknown_skill_id"
    assert diagnostics["unknown_skill_ids"] == ["ghost/missing"]
    assert diagnostics["abstained_skill_ids"] == ["myna/known"]


async def test_think_block_stripped_before_parse() -> None:
    """Qwen3-style reasoning models emit <think>...</think> before JSON.
    The gate must tolerate it without falling back."""
    provider = _StubProvider('<think>let me think...</think>\n{"plan": "p", "skills": ["local/a"]}')
    out = await LLMGateFilter(provider).filter("task", [_hit("local/a", "a")])
    assert [h.qualified_id for h in out] == ["local/a"]


async def test_tools_block_present_when_tools_given() -> None:
    provider = _StubProvider(json.dumps({"plan": "p", "skills": []}))
    gate = LLMGateFilter(provider)
    await gate.filter("task", [_hit("local/a", "a")], available_tools=["read_file", "exec"])
    prompt = provider.calls[0]["messages"][0]["content"]
    assert "# Agent Tools" in prompt
    assert "read_file" in prompt
    assert "exec" in prompt
    assert "decision rule, parser or classifier contract" in prompt


async def test_tools_block_absent_when_tools_none() -> None:
    provider = _StubProvider(json.dumps({"plan": "p", "skills": []}))
    await LLMGateFilter(provider).filter("task", [_hit("local/a", "a")])
    prompt = provider.calls[0]["messages"][0]["content"]
    assert "# Agent Tools" not in prompt


async def test_candidate_excerpt_preserves_bounded_ability_procedure() -> None:
    provider = _StubProvider(json.dumps({"plan": "p", "skills": []}))
    body = "A" * 350 + " Accept pytest and uv run pytest. " + "B" * 900

    await LLMGateFilter(provider).filter("implement pytest classifier", [_hit("myna/checks", "checks", body=body)])

    prompt = provider.calls[0]["messages"][0]["content"]
    assert "Accept pytest and uv run pytest" in prompt
    assert "B" * 700 not in prompt
