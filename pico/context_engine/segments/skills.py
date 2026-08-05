"""Segment 5 — ``# Skills``. Rewriter, router, gate, references, render.

Four-step pipeline:

1. **Rewriter** (optional) — one LLM call that judges ``need_retrieval``
   and rewrites the query for skill routing. ``need_retrieval=False``
   short-circuits the rest of the build to an empty segment.
2. **Router selection** - :class:`SkillForgeRouter` queries Local Skills.
3. **LLM gate** (optional) — one LLM call that picks 0..``max_select``
   hits from the pool. Empty result is a valid "inject nothing".
4. **Local refs resolve** — for selected Local hits, resolve
   ``{baseDir}/x`` and markdown link refs to absolute paths.

When rewriter / gate are not wired (provider missing, config off, etc.)
the pipeline degrades gracefully — both are independent and the segment
still produces a valid result with whatever is wired.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from pico.context_engine.base import AssemblyContext, Segment
from pico.context_engine.segments import render
from pico.memory_engine.skill_forge.refs import resolve_refs
from pico.tracing import semconv, trace

if TYPE_CHECKING:
    from pico.memory_engine.skill_forge import SkillForgeRouter
    from pico.memory_engine.skill_forge.gate import LLMGateFilter
    from pico.memory_engine.skill_forge.rewriter import QueryRewriter
    from pico.memory_engine.skill_forge.types import RouterHit


class SkillsSegmentBuilder:
    name = "skills"
    order = 5
    needs_prefix = False

    def __init__(
        self,
        router: "SkillForgeRouter | None",
        *,
        skill_top_k: int = 5,
        rewriter: "QueryRewriter | None" = None,
        gate: "LLMGateFilter | None" = None,
        gate_pool_size: int = 10,
        get_tool_definitions: "Any | None" = None,
    ) -> None:
        self._router = router
        self._skill_top_k = skill_top_k
        self._rewriter = rewriter
        self._gate = gate
        # When the gate is active, the router selects ``gate_pool_size``
        # candidates (the gate then trims to ``max_select``). Without the
        # gate, ``skill_top_k`` controls direct injection size.
        self._pool_size = gate_pool_size if gate is not None else skill_top_k
        self._get_tool_definitions = get_tool_definitions

    @trace.instrument("skill.inject", kind="skill", detached=True, extract=semconv.skill_inject_skills)
    async def build(self, ctx: AssemblyContext) -> Segment | None:
        if self._router is None:
            return Segment(
                text="",
                meta={"injected_skill_ids": [], "skill_hits_by_source": {}},
            )

        query = ctx.current_message or ""
        rewriter_diagnostics: dict[str, Any] = {}

        # ── ① Rewriter ────────────────────────────────────────────────
        if self._rewriter is not None and query.strip():
            result = await self._rewriter.analyze(
                query,
                diagnostics=rewriter_diagnostics,
            )
            if not result.need_retrieval:
                return Segment(
                    text="",
                    meta={
                        "injected_skill_ids": [],
                        "skill_hits_by_source": {},
                        "rewriter_skipped": True,
                        **_prefixed_diagnostics(
                            "skill_rewriter",
                            rewriter_diagnostics,
                        ),
                    },
                )
            if result.rewritten_query:
                query = result.rewritten_query

        # ── ② Router fan-out ─────────────────────────────────────────
        diagnostics: dict[str, Any] = {}
        candidates = list(
            await self._router.select(
                query=query,
                history=ctx.session_messages,
                k=self._pool_size,
                diagnostics=diagnostics,
            )
        )

        # ── ③ LLM gate ───────────────────────────────────────────────
        if self._gate is not None and candidates:
            tools = self._collect_tool_names()
            gate_diagnostics: dict[str, Any] = {}
            gated = await self._gate.filter(
                query,
                candidates,
                tools,
                diagnostics=gate_diagnostics,
            )
        else:
            gate_diagnostics = {}
            gated = candidates[: self._skill_top_k]

        # ── ④ Local refs resolve ─────────────────────────────────────
        gated = self._resolve_local_refs(gated)

        body = render.render_router_skills(gated)
        meta: dict[str, Any] = {
            "injected_skill_ids": [h.qualified_id for h in gated if getattr(h, "qualified_id", None)],
            "skill_hits_by_source": dict(Counter((h.meta.get("source") or "?") for h in gated)),
            "skill_source_failures": diagnostics.get("failed_sources", []),
            "skill_source_failure_types": diagnostics.get("failure_types", {}),
            **_prefixed_diagnostics(
                "skill_rewriter",
                rewriter_diagnostics,
            ),
            **_prefixed_diagnostics(
                "skill_gate",
                gate_diagnostics,
            ),
        }
        text = f"# Skills\n\n{body}" if body else ""
        return Segment(text=text, meta=meta)

    @staticmethod
    def _resolve_local_refs(gated: list["RouterHit"]) -> list["RouterHit"]:
        out: list["RouterHit"] = []
        for hit in gated:
            if hit.meta.get("source") == "local":
                resolved, _ = resolve_refs(hit.content, hit.meta.get("skill_dir"))
                hit = replace(hit, content=resolved)
            out.append(hit)
        return out

    def _collect_tool_names(self) -> list[str] | None:
        """Return tool names for the gate's hard-constraint block.

        ``get_tool_definitions`` is a callable injected at construction; when
        absent the gate runs without the tool-constraint hint (still
        works, just less aggressive at culling env-mismatched skills).
        """
        if self._get_tool_definitions is None:
            return None
        try:
            defs = self._get_tool_definitions()
        except Exception:
            return None
        names: list[str] = []
        for d in defs or []:
            if isinstance(d, dict):
                # OpenAI function-call schema → name lives under
                # ``function.name``; also accept a flat ``name``.
                fn = d.get("function") if isinstance(d.get("function"), dict) else None
                if fn and isinstance(fn.get("name"), str):
                    names.append(fn["name"])
                elif isinstance(d.get("name"), str):
                    names.append(d["name"])
        return names or None


def _prefixed_diagnostics(
    prefix: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in diagnostics.items()}
