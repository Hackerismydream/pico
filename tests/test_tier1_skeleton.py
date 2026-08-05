"""Tier 1 smoke tests — verify the skeleton imports,
and the surviving interface ABCs behave correctly.

These tests should pass on a fresh checkout with only Python stdlib and
pydantic + loguru installed. They do NOT require an LLM provider, a
configured workspace, or any external service.

Relocation map (kept as a header note so future readers can trace where
the symbols came from):

    pico.core.interfaces.TokenStrategy / UsageSnapshot
        →  pico.token_wise.base
    pico.core.interfaces.AssembledContext / TokenBudget
        →  pico.memory_engine.base

The three dead ABCs ``ContextEngine`` / ``Monitor`` / ``SkillHandler`` plus
their helper dataclasses
were removed (no implementations, alternate routes chosen by the
design owners). The tests that exercised them are gone with them.

``pico.core`` is fully removed now that AssembledContext + TokenBudget
have moved to their permanent home under ``memory_engine``.
"""

from __future__ import annotations

import pytest

from pico import __version__
from pico.memory_engine.base import AssembledContext, TokenBudget
from pico.token_wise.base import TokenStrategy, UsageSnapshot

# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------


def test_package_imports():
    assert isinstance(__version__, str)
    assert __version__  # non-empty


def test_memory_engine_base_exports_assembled_dataclasses():
    # AssembledContext + TokenBudget have their permanent home
    # under memory_engine; pico.core is fully removed.
    from pico.memory_engine.base import AssembledContext as ReAssembled
    from pico.memory_engine.base import TokenBudget as ReBudget

    assert ReAssembled is AssembledContext
    assert ReBudget is TokenBudget


def test_pico_core_module_is_gone():
    # The transitional pico.core package was deleted. Any
    # holdout import should fail loudly so callers update the path.
    with pytest.raises(ModuleNotFoundError):
        import pico.core  # noqa: F401


# ---------------------------------------------------------------------------
# Surviving ABC: TokenStrategy
#
# ContextEngine / Monitor / SkillHandler were removed — they had zero
# implementations and the design owners chose alternate routes
# (SkillService and Curator). The TokenStrategy
# contract remains load-bearing (CacheOptimizer, UsageTracker,
# SystemAndTailCacheStrategy all implement it), so its abstractness is still
# part of the tier-1 contract.
# ---------------------------------------------------------------------------


def test_token_strategy_is_abstract():
    with pytest.raises(TypeError):
        TokenStrategy()  # type: ignore[abstract]


def test_minimal_token_strategy_subclass():
    class Noop(TokenStrategy):
        @property
        def name(self) -> str:
            return "noop"

    strat = Noop()
    assert strat.name == "noop"


# ---------------------------------------------------------------------------
# Surviving dataclass behavior
# ---------------------------------------------------------------------------


def test_token_budget_threshold():
    b = TokenBudget(
        context_length=100_000,
        reserved_output=8_000,
        reserved_tools=4_000,
        reserved_system=2_000,
        available_history=86_000,
    )
    assert b.total_reserved == 14_000
    assert b.threshold == int(86_000 * 0.75)


def test_assembled_context_defaults():
    ac = AssembledContext(messages=[{"role": "user", "content": "hi"}])
    assert ac.system_prompt_addition is None
    assert ac.include_indices is None
    assert ac.metadata == {}


def test_usage_snapshot():
    u = UsageSnapshot(
        model="claude-opus-4-6",
        input_tokens=10_000,
        output_tokens=500,
    )
    assert u.estimated_cost_usd == 0.0
    assert u.session_key is None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_config_module_imports():
    # Lazy import — config depends on pydantic-settings which may not load
    # if the env is misconfigured. We still want the test to be informative.
    from pico.config import (
        ContextConfig,
        PicoConfig,
        SkillForgeConfig,
        TokenWiseConfig,
    )

    cfg = PicoConfig()
    assert isinstance(cfg.context, ContextConfig)
    assert isinstance(cfg.token_wise, TokenWiseConfig)
    assert isinstance(cfg.skill_forge, SkillForgeConfig)


def test_config_safe_defaults():
    from pico.config import PicoConfig

    cfg = PicoConfig()
    # Risky/novel auto-* features must default to OFF so a fresh install
    # behaves like vanilla Pico; the baseline retrieval pipeline
    # (context engine, skill_forge retrieval/injection) defaults ON as of R8.
    assert cfg.context.engine == "unified"
    assert cfg.skill_forge.enabled is True  # R8: retrieval/injection pipeline on by default
    assert not hasattr(cfg.skill_forge, "auto_detect")
    assert not hasattr(cfg.skill_forge, "auto_evolve")
    assert cfg.token_wise.smart_routing.enabled is False
    # Baseline memory/skill feature layer defaults ON: a fresh install runs the
    # CodeCairn memory backend, the SkillForgeRouter, and
    # empty-response recovery. Pinned so a future silent flip gets caught.
    assert cfg.memory.backend == "codecairn"
    assert cfg.skill_forge.router.enabled is True
    assert cfg.base.agents.defaults.empty_recovery_enabled is True
    # Safe/cheap defaults can be ON.
    assert cfg.token_wise.usage_tracking is True
    assert cfg.token_wise.cache_optimization is True


if __name__ == "__main__":
    # Allow `python tests/test_tier1_skeleton.py` as a quick smoke run.
    pytest.main([__file__, "-v"])
