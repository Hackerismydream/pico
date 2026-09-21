"""``ModelRouter.select_model_chain`` exposes the selector's fallback list."""

from __future__ import annotations

import pytest

from pico.routing.router import ModelRouter
from pico.routing.types import ModelScore, SelectionResult


def _result(primary: str, fallbacks: list[str]) -> SelectionResult:
    def _score(m: str) -> ModelScore:
        return ModelScore(model=m, provider="p", task_score=1.0, cost_score=1.0, composite_score=1.0)

    return SelectionResult(
        primary=_score(primary),
        fallbacks=[_score(m) for m in fallbacks],
        category="tool_use",
        profile="balanced",
    )


@pytest.mark.asyncio
async def test_select_model_chain_returns_primary_and_fallbacks(monkeypatch):
    router = ModelRouter(api_key="test")

    async def fake_route(_prompt):
        return _result("a/primary", ["b/second", "c/third"])

    monkeypatch.setattr(router, "route", fake_route)
    primary, fallbacks = await router.select_model_chain("hi")
    assert primary == "a/primary"
    assert fallbacks == ["b/second", "c/third"]


@pytest.mark.asyncio
async def test_configured_fallback_model_appended_as_last_resort(monkeypatch):
    router = ModelRouter(api_key="test", fallback_model="z/default")

    async def fake_route(_prompt):
        return _result("a/primary", ["b/second"])

    monkeypatch.setattr(router, "route", fake_route)
    primary, fallbacks = await router.select_model_chain("hi")
    assert primary == "a/primary"
    assert fallbacks == ["b/second", "z/default"]


@pytest.mark.asyncio
async def test_configured_fallback_not_duplicated(monkeypatch):
    router = ModelRouter(api_key="test", fallback_model="b/second")

    async def fake_route(_prompt):
        return _result("a/primary", ["b/second"])

    monkeypatch.setattr(router, "route", fake_route)
    _primary, fallbacks = await router.select_model_chain("hi")
    assert fallbacks == ["b/second"]


@pytest.mark.asyncio
async def test_configured_fallback_skipped_when_equals_primary(monkeypatch):
    router = ModelRouter(api_key="test", fallback_model="a/primary")

    async def fake_route(_prompt):
        return _result("a/primary", [])

    monkeypatch.setattr(router, "route", fake_route)
    _primary, fallbacks = await router.select_model_chain("hi")
    assert fallbacks == []


@pytest.mark.asyncio
async def test_route_none_yields_empty_chain(monkeypatch):
    router = ModelRouter(api_key="test", fallback_model="z/default")

    async def fake_route(_prompt):
        return None

    monkeypatch.setattr(router, "route", fake_route)
    primary, fallbacks = await router.select_model_chain("hi")
    assert primary is None
    assert fallbacks == []


@pytest.mark.parametrize("similarity", [0.0, -0.1, float("nan"), float("inf"), float("-inf")])
async def test_classifier_without_evidence_retains_default(monkeypatch, similarity):
    from unittest.mock import AsyncMock, MagicMock

    from pico.routing.types import ClassificationResult

    router = ModelRouter(api_key="test")
    router._data = {}
    monkeypatch.setattr(
        router._classifier,
        "classify",
        AsyncMock(return_value=ClassificationResult(category="sanity", similarity=similarity)),
    )
    selector = MagicMock()
    monkeypatch.setattr("pico.routing.router.select_model", selector)
    assert await router.select_model_chain("not a known task") == (None, [])
    selector.assert_not_called()


async def test_real_positive_sanity_classification_still_routes(monkeypatch):
    from unittest.mock import AsyncMock

    from pico.routing.types import ClassificationResult

    router = ModelRouter(api_key="test")
    router._data = {}
    monkeypatch.setattr(
        router._classifier, "classify", AsyncMock(return_value=ClassificationResult(category="sanity", similarity=0.9))
    )
    monkeypatch.setattr("pico.routing.router.select_model", lambda *args: _result("a/primary", []))
    assert await router.select_model_chain("hello") == ("a/primary", [])
