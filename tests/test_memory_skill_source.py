from __future__ import annotations

import pytest

from pico.memory_engine.backend import Memory
from pico.memory_engine.skill_forge import MemorySkillSource, SkillSource


class _Backend:
    def __init__(self, memories: list[Memory] | None = None, *, error: Exception | None = None) -> None:
        self.memories = memories or []
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def recall(self, query, *, user_id=None, agent_id=None, top_k=5):
        self.calls.append({"query": query, "user_id": user_id, "agent_id": agent_id, "top_k": top_k})
        if self.error is not None:
            raise self.error
        return self.memories


async def test_agent_track_memory_becomes_self_contained_router_hit() -> None:
    backend = _Backend(
        [
            Memory(
                text='---\nname: "Repository verification"\ndescription: "Run checks"\n---\n\n# Procedure\n\nRun make check.\n',
                score=0.75,
                metadata={
                    "backend": "myna",
                    "name": "Repository verification",
                    "qualified_id": "myna/skill_abc@skill_rev_def",
                    "revision_id": "skill_rev_def",
                    "source_experience_ids": ["mem_1", "mem_2", "mem_3"],
                },
            )
        ]
    )
    source = MemorySkillSource(backend)  # type: ignore[arg-type]

    hits = await source.search("repository verification", history=[], k=3)

    assert isinstance(source, SkillSource)
    assert backend.calls == [{"query": "repository verification", "user_id": None, "agent_id": "pico", "top_k": 3}]
    assert len(hits) == 1
    assert hits[0].qualified_id == "myna/skill_abc@skill_rev_def"
    assert hits[0].content == "# Procedure\n\nRun make check."
    assert hits[0].meta["source"] == "myna"
    assert hits[0].meta["gate_required"] is True
    assert hits[0].meta["source_experience_ids"] == ["mem_1", "mem_2", "mem_3"]


@pytest.mark.parametrize(
    "memory",
    (
        Memory(text="body", score=float("nan"), metadata={"backend": "myna", "name": "x", "qualified_id": "myna/x"}),
        Memory(text="", score=0.5, metadata={"backend": "myna", "name": "x", "qualified_id": "myna/x"}),
        Memory(text="body", score=0.5, metadata={"backend": "myna", "name": "x"}),
    ),
)
async def test_invalid_backend_skill_hit_is_dropped(memory: Memory) -> None:
    source = MemorySkillSource(_Backend([memory]))  # type: ignore[arg-type]
    assert await source.search("query", history=[], k=5) == []


async def test_backend_failure_propagates_to_router_isolation_boundary() -> None:
    source = MemorySkillSource(_Backend(error=RuntimeError("offline")))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="offline"):
        await source.search("query", history=[], k=5)
