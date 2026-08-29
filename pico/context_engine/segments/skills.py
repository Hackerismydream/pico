"""构建 Segment 5：检索 Local 与 Memory-derived Skills，门控后完成引用解析与渲染。

`SkillsSegmentBuilder` 用 `SkillForgeRouter` 和 `LocalSkillResolver` 根据当前消息与 Session
History 选择 activated Skill 和 reference。Memory-derived Activated Candidates 必须通过可选 Gate；Gate
缺失或失败时 Abstain。Activated 正文进入 ``# Skills``，Reference 作为可继续读取的线索；本地命中的
相对引用由 `resolve_refs` 展开，其他 Source 不做本地路径解释。

Router 缺失时返回空 Segment 与完整零值 metadata，而不是让证据字段消失。最终 metadata
分别记录 injected/referenced ids、各 Source 命中数与 Source failure，供 Turn Outcome 核对；
检索失败边界不改变 Segment 4 always-on Skill。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Callable

from pico.context_engine.base import AssemblyContext, Segment
from pico.context_engine.segments import render
from pico.memory_engine.skill_forge.refs import resolve_refs
from pico.tracing import semconv, trace

if TYPE_CHECKING:
    from pico.memory_engine.skill_forge import LLMGateFilter, SkillForgeRouter
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
        activation_max: int | None = None,
        gate: "LLMGateFilter | None" = None,
        get_tool_definitions: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._router = router
        self._gate = gate
        self._get_tool_definitions = get_tool_definitions
        if router is None:
            self._resolver = None
        else:
            from pico.memory_engine.skill_forge import LocalSkillResolver

            self._resolver = LocalSkillResolver(
                router,
                candidate_limit=skill_top_k,
                activation_limit=(skill_top_k if activation_max is None else activation_max),
            )

    @trace.instrument("skill.inject", kind="skill", detached=True, extract=semconv.skill_inject_skills)
    async def build(self, ctx: AssemblyContext) -> Segment | None:
        if self._resolver is None:
            return Segment(
                text="",
                meta={
                    "injected_skill_ids": [],
                    "referenced_skill_ids": [],
                    "skill_hits_by_source": {},
                    "skill_candidate_ids": [],
                    "skill_gate_required_ids": [],
                    "skill_gate_selected_ids": [],
                    "skill_gate_status": "not_required",
                },
            )

        query = ctx.current_message or ""
        resolution = await self._resolver.resolve(query, ctx.session_messages)
        candidate_activated = list(resolution.activated)
        gate_required = [h for h in candidate_activated if h.meta.get("gate_required")]
        gate_diagnostics: dict[str, Any] = {}
        selected_required: list[RouterHit] = []
        if gate_required and self._gate is not None:
            selected_required = await self._gate.filter(
                query,
                gate_required,
                self._available_tool_names(),
                diagnostics=gate_diagnostics,
            )
        selected_required_ids = {h.qualified_id for h in selected_required}
        activated = [
            h
            for h in candidate_activated
            if not h.meta.get("gate_required") or h.qualified_id in selected_required_ids
        ]
        activated = self._resolve_local_refs(activated)
        references = list(resolution.references)
        diagnostics = resolution.diagnostics or {}
        body_parts = [
            part
            for part in (
                render.render_router_skills(activated),
                render.render_skill_references(references),
            )
            if part
        ]
        all_hits = [*activated, *references]
        meta = {
            "injected_skill_ids": [h.qualified_id for h in activated if h.qualified_id],
            "referenced_skill_ids": [h.qualified_id for h in references if h.qualified_id],
            "skill_hits_by_source": dict(Counter((h.meta.get("source") or "?") for h in all_hits)),
            "skill_source_failures": diagnostics.get("failed_sources", []),
            "skill_source_failure_types": diagnostics.get("failure_types", {}),
            "skill_candidate_ids": [h.qualified_id for h in candidate_activated],
            "skill_gate_required_ids": [h.qualified_id for h in gate_required],
            "skill_gate_selected_ids": [h.qualified_id for h in selected_required],
            "skill_gate_status": self._gate_status(
                gate_required=gate_required,
                selected=selected_required,
                diagnostics=gate_diagnostics,
            ),
            "skill_gate_fallback_reason": gate_diagnostics.get("fallback_reason"),
            "skill_gate_abstained_ids": gate_diagnostics.get("abstained_skill_ids", []),
        }
        body = "\n\n".join(body_parts)
        text = f"# Skills\n\n{body}" if body else ""
        return Segment(text=text, meta=meta)

    def _available_tool_names(self) -> list[str] | None:
        if self._get_tool_definitions is None:
            return None
        names: list[str] = []
        for definition in self._get_tool_definitions():
            function = definition.get("function")
            name = function.get("name") if isinstance(function, dict) else definition.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        return names or None

    def _gate_status(
        self,
        *,
        gate_required: list["RouterHit"],
        selected: list["RouterHit"],
        diagnostics: dict[str, Any],
    ) -> str:
        if not gate_required:
            return "not_required"
        if self._gate is None:
            return "disabled_abstain"
        if diagnostics.get("fallback_reason"):
            return "fallback_abstain"
        return "selected" if selected else "rejected"

    @staticmethod
    def _resolve_local_refs(gated: list["RouterHit"]) -> list["RouterHit"]:
        out: list["RouterHit"] = []
        for hit in gated:
            if hit.meta.get("source") == "local":
                resolved, _ = resolve_refs(hit.content, hit.meta.get("skill_dir"))
                hit = replace(hit, content=resolved)
            out.append(hit)
        return out
