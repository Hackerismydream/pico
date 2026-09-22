"""把 MemoryBackend 的 agent-track Recall 转换为 SkillForge Router Hits。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from pico.memory_engine.skill_forge.types import RouterHit

if TYPE_CHECKING:
    from pico.memory_engine.backend import MemoryBackend


class MemorySkillSource:
    """从已配置 MemoryBackend 检索 active agent Skills。

    Backend 仍拥有 repository scope、生命周期和相关性准入；本适配器只验证返回形状、移除
    `SKILL.md` frontmatter，并形成 SkillForge 可融合的自包含 Hit。缺失身份、正文或有限分数
    的结果会被丢弃，Backend 异常则继续交给 Router 的 source-failure 隔离边界处理。
    """

    name = "memory"
    weight = 1.0

    def __init__(self, backend: "MemoryBackend", *, agent_id: str = "pico") -> None:
        if not agent_id:
            raise ValueError("MemorySkillSource agent_id must not be empty")
        self._backend = backend
        self._agent_id = agent_id

    async def search(self, query: str, history: list[dict[str, Any]], k: int) -> list[RouterHit]:
        del history
        if k < 1:
            return []
        memories = await self._backend.recall(query, agent_id=self._agent_id, top_k=k)
        hits: list[RouterHit] = []
        for memory in memories[:k]:
            metadata = memory.metadata
            qualified_id = metadata.get("qualified_id")
            name = metadata.get("name")
            source = metadata.get("backend")
            content = _skill_body(memory.text)
            try:
                score = float(memory.score)
            except (TypeError, ValueError):
                continue
            if (
                not isinstance(qualified_id, str)
                or "/" not in qualified_id
                or not isinstance(name, str)
                or not name
                or not isinstance(source, str)
                or not source
                or not content
                or isinstance(memory.score, bool)
                or not math.isfinite(score)
                or not 0.0 <= score <= 1.0
            ):
                continue
            hits.append(
                RouterHit(
                    qualified_id=qualified_id,
                    name=name,
                    content=content,
                    score=score,
                    meta={**metadata, "source": source, "gate_required": True},
                )
            )
        return hits


def _skill_body(text: str) -> str:
    """移除规范 SKILL.md frontmatter；正文形状异常时保守返回原文本。"""
    if not text.startswith("---\n"):
        return text.strip()
    _frontmatter, separator, body = text[4:].partition("\n---\n")
    return body.strip() if separator else text.strip()


__all__ = ["MemorySkillSource"]
