"""Local Skill Retrieval、Fusion、Gate 与 Rendering Machinery。

初级读者可把 Skill 理解为可按当前请求检索并注入 Prompt 的局部操作说明。Active Runtime 先由
`LocalSkillCatalog` 读取文件，再通过 `LocalSkillSource` Search；配置 Memory Backend 时，
`MemorySkillSource` 还读取 agent-track active Skill。`SkillForgeRouter` 融合多路排名，最后由
Resolver 展开引用并形成可注入内容。

:class:`SkillSource` Protocol 是 Host-internal，而不是 Plugin Contribution Point。当前 Runtime 只在
:class:`LocalSkillSource` 和可选 :class:`MemorySkillSource` 上构建 Router。检索 Hit、Skill 注入和
任务成功是不同阶段；Backend 来源失败会降级为空 Source，不影响 Local Skill。
"""

from __future__ import annotations

from pico.memory_engine.skill_forge.catalog import LocalSkillCatalog
from pico.memory_engine.skill_forge.fusion import RRF_K, rrf_merge_weighted
from pico.memory_engine.skill_forge.gate import LLMGateFilter
from pico.memory_engine.skill_forge.local_source import LocalSkillSource
from pico.memory_engine.skill_forge.memory_source import MemorySkillSource
from pico.memory_engine.skill_forge.refs import resolve_refs
from pico.memory_engine.skill_forge.resolver import LocalSkillResolver, SkillResolution
from pico.memory_engine.skill_forge.rewriter import (
    QueryRewriter,
    RewriteResult,
)
from pico.memory_engine.skill_forge.router import SkillForgeRouter
from pico.memory_engine.skill_forge.types import RouterHit, SkillSource

__all__ = [
    "LLMGateFilter",
    "LocalSkillCatalog",
    "LocalSkillSource",
    "MemorySkillSource",
    "LocalSkillResolver",
    "QueryRewriter",
    "RRF_K",
    "RewriteResult",
    "RouterHit",
    "SkillForgeRouter",
    "SkillResolution",
    "SkillSource",
    "resolve_refs",
    "rrf_merge_weighted",
]
