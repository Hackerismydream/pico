"""LocalSkillSource — wraps :class:`LocalPool` to emit :class:`RouterHit`.

Hot-path observation: :class:`LocalPool` already returns the cheap
``ScoredSkill(name, score, source)`` triple. To produce a
:class:`RouterHit` we additionally need ``content`` (the SKILL.md body)
which :class:`SkillRegistry.get` already has cached in memory — so the
per-hit lookup is O(1) dict access, not a fresh disk read.

Hits whose name no longer resolves in the registry (race against a
file-watcher delete between BM25 scoring and meta lookup) are skipped
silently. The router's contract is "at most k hits", not "exactly k",
so dropping is safer than emitting a hit with empty content.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from pico.memory_engine.skill_forge.types import RouterHit

if TYPE_CHECKING:
    from pico.memory_engine.skill_local.local_pool import LocalPool
    from pico.memory_engine.skill_local.registry import SkillRegistry


class LocalSkillSource:
    """SkillSource adapter for the BM25 local pool."""

    name: str = "local"
    weight: float = 1.0

    def __init__(
        self,
        pool: "LocalPool",
        registry: "SkillRegistry",
        *,
        min_score: float = 0.0,
    ) -> None:
        self._pool = pool
        self._registry = registry
        try:
            self._min_score = float(min_score)
        except (TypeError, ValueError):
            raise ValueError(
                "LocalSkillSource: min_score must be nonnegative and finite",
            ) from None
        if isinstance(min_score, bool) or self._min_score < 0 or not math.isfinite(self._min_score):
            raise ValueError(
                "LocalSkillSource: min_score must be nonnegative and finite",
            )

    async def search(
        self,
        query: str,
        history: list[dict[str, Any]],
        k: int,
    ) -> list[RouterHit]:
        # ``history`` is unused — local BM25 doesn't condition on prior
        # conversation. Future "smarter local ranker" could fold it in;
        # signature matches the Protocol so the seam stays.
        del history

        hits = self._pool.search(query, top_k=k)
        out: list[RouterHit] = []
        for h in hits:
            if h.score < self._min_score:
                continue
            meta = self._registry.get(h.name, source=h.source)
            if meta is None:
                # File-watcher race: skill vanished between BM25
                # snapshot and meta lookup. Skip rather than emit a
                # half-populated hit.
                continue
            # ``skill_dir`` lets the post-gate hydrate step in
            # SkillsSegmentBuilder resolve {baseDir} / markdown-link refs
            # without a second registry lookup.
            path_obj = getattr(meta, "path", None)
            path_str = str(path_obj) if path_obj is not None else ""
            skill_dir: str | None = None
            if path_obj is not None and not path_str.startswith("sqlite:"):
                skill_dir = str(path_obj.parent)
            out.append(
                RouterHit(
                    qualified_id=f"local/{h.name}",
                    name=h.name,
                    content=meta.content,
                    score=h.score,
                    meta={
                        "source": "local",
                        # The "physical source" inside Local (one of
                        # ``workspace`` / ``builtin`` / ``external`` /
                        # ``mirror/*``) is occasionally useful for
                        # telemetry — keep it in meta.
                        "physical_source": h.source,
                        "always": meta.always,
                        "skill_dir": skill_dir,
                        "description": meta.description,
                    },
                ),
            )
        return out


__all__ = ["LocalSkillSource"]
