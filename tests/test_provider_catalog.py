"""Catalog-shape tests for the LLM provider registry and backend classes.

These pin the *current* shape so that adding / removing a provider spec or a
concrete backend class trips a test instead of silently drifting.
"""

from __future__ import annotations

import pytest

from pico.providers.base import LLMProvider
from pico.providers.common_models import common_models_for
from pico.providers.registry import PROVIDERS, find_by_name

# The Confluence "Providers" page claims 19 providers. This pins the current
# registry so any drift (add/remove a ProviderSpec) is caught here.
EXPECTED_PROVIDER_NAMES = {
    "custom",
    "azure_openai",
    "openrouter",
    "aihubmix",
    "siliconflow",
    "volcengine",
    "anthropic",
    "openai",
    "openai_codex",
    "github_copilot",
    "deepseek",
    "gemini",
    "zhipu",
    "dashscope",
    "moonshot",
    "minimax",
    "vllm",
    "ollama",
    "groq",
}


def test_registry_has_exactly_19_providers() -> None:
    assert len(PROVIDERS) == 19
    assert len(EXPECTED_PROVIDER_NAMES) == 19


def test_registry_provider_name_set_is_pinned() -> None:
    assert {spec.name for spec in PROVIDERS} == EXPECTED_PROVIDER_NAMES


def test_provider_names_are_unique() -> None:
    names = [spec.name for spec in PROVIDERS]
    assert len(names) == len(set(names))


# Direct providers seeded in the model picker (issue #100). Each must expose a
# non-empty default_model drawn from its curated shortlist, so the onboarding
# fallback and the picker stay in sync and no provider defaults to empty.
_SEEDED_DIRECT_PROVIDERS = [
    "deepseek",
    "openai",
    "anthropic",
    "gemini",
    "zhipu",
    "dashscope",
    "groq",
]


@pytest.mark.parametrize("slug", _SEEDED_DIRECT_PROVIDERS)
def test_seeded_provider_default_model_in_shortlist(slug: str) -> None:
    default = find_by_name(slug).default_model
    assert default, f"{slug} has no default_model"
    assert default in common_models_for(slug)


def _concrete_provider_subclasses() -> set[type]:
    """All non-abstract LLMProvider subclasses defined in pico.providers."""
    # Import each backend module so its subclass is registered on LLMProvider.
    import pico.providers.azure_openai_provider  # noqa: F401
    import pico.providers.custom_provider  # noqa: F401
    import pico.providers.lazy  # noqa: F401
    import pico.providers.litellm_provider  # noqa: F401
    import pico.providers.openai_codex_provider  # noqa: F401
    import pico.providers.per_model_provider  # noqa: F401

    seen: set[type] = set()
    stack = list(LLMProvider.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if getattr(cls, "__abstractmethods__", frozenset()):
            continue
        if cls.__module__.startswith("pico.providers"):
            seen.add(cls)
    return seen


def test_exactly_six_concrete_backend_classes() -> None:
    # The lazy and per-model wrappers join four concrete request providers.
    # This asserts class existence only.
    from pico.providers.azure_openai_provider import AzureOpenAIProvider
    from pico.providers.custom_provider import CustomProvider
    from pico.providers.lazy import LazyProvider
    from pico.providers.litellm_provider import LiteLLMProvider
    from pico.providers.openai_codex_provider import OpenAICodexProvider
    from pico.providers.per_model_provider import PerModelProvider

    expected = {
        LiteLLMProvider,
        AzureOpenAIProvider,
        OpenAICodexProvider,
        CustomProvider,
        LazyProvider,
        PerModelProvider,
    }
    assert _concrete_provider_subclasses() == expected
    for cls in expected:
        assert issubclass(cls, LLMProvider)
