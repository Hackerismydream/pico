"""Contracts for the Runtime-owned CallEfficiency subsystem."""

from __future__ import annotations

import asyncio
import json
import threading
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from pico.agent.loop import AgentLoop
from pico.call_efficiency import CallEfficiency
from pico.call_efficiency.provider import CallEfficiencyProvider
from pico.providers.base import LLMProvider, LLMResponse, StreamDelta
from pico.tracing.usage import normalize as normalize_trace_usage


def _cache_markers(value) -> int:
    if isinstance(value, dict):
        return int("cache_control" in value) + sum(_cache_markers(item) for item in value.values())
    if isinstance(value, list):
        return sum(_cache_markers(item) for item in value)
    return 0


@pytest.mark.parametrize(
    ("model", "usage", "expected_fresh"),
    [
        (
            "deepseek/deepseek-v4-flash",
            {
                "prompt_tokens": 1000,
                "completion_tokens": 50,
                "total_tokens": 1050,
                "cache_read_input_tokens": 800,
                "cache_miss_input_tokens": 200,
            },
            200,
        ),
        (
            "anthropic/claude-sonnet-4-5",
            {
                "prompt_tokens": 200,
                "completion_tokens": 50,
                "cache_read_input_tokens": 800,
            },
            200,
        ),
        (
            "openai/gpt-4.1-mini",
            {
                "prompt_tokens": 1000,
                "completion_tokens": 50,
                "cache_read_input_tokens": 800,
            },
            200,
        ),
    ],
)
def test_usage_normalization_uses_provider_semantics(
    tmp_path,
    model: str,
    usage: dict[str, int],
    expected_fresh: int,
) -> None:
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False)

    record = controller.record(
        LLMResponse(content="ok", usage=usage, model=model),
        requested_model=model,
        session_key="session-1",
    )

    assert record.usage.input_tokens == expected_fresh
    assert record.usage.cache_read_tokens == 800
    assert record.usage.output_tokens == 50
    assert record.usage.complete is True
    assert record.session_key == "session-1"


def test_ambiguous_cached_usage_fails_closed_for_cost(tmp_path) -> None:
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False)

    record = controller.record(
        LLMResponse(
            content="ok",
            usage={
                "prompt_tokens": 1000,
                "completion_tokens": 50,
                "cache_read_input_tokens": 800,
            },
        ),
        requested_model="custom/unknown-model",
        session_key="session-1",
    )

    assert record.usage.complete is False
    assert record.estimated_cost_usd is None
    assert "input_token_semantics_ambiguous" in record.findings


def test_runtime_pricing_never_imports_litellm_on_the_response_path(monkeypatch, tmp_path) -> None:
    import pico.call_efficiency.pricing as pricing

    seen: list[bool] = []

    def _rates(model, input_tokens, output_tokens, *, allow_import):
        seen.append(allow_import)
        return None

    monkeypatch.setattr(pricing, "_try_litellm_rates", _rates)
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False)

    record = controller.record(
        LLMResponse(
            content="ok",
            usage={"prompt_tokens": 10, "completion_tokens": 2},
            model="private/local-model",
        ),
        requested_model="private/local-model",
        session_key="session-1",
    )

    assert seen == [False]
    assert record.estimated_cost_usd is None


def test_tracing_pricing_never_imports_litellm_on_the_response_path(monkeypatch) -> None:
    import pico.call_efficiency.pricing as pricing

    seen: list[bool] = []

    def _rates(model, input_tokens, output_tokens, *, allow_import):
        seen.append(allow_import)
        return None

    monkeypatch.setattr(pricing, "_try_litellm_rates", _rates)

    projected = normalize_trace_usage(
        {"prompt_tokens": 10, "completion_tokens": 2},
        "private/local-model",
    )

    assert seen == [False]
    assert projected["cost_usd"] is None


@pytest.mark.parametrize(
    ("model", "usage", "finding"),
    [
        (
            "deepseek/deepseek-v4-flash",
            {
                "prompt_tokens": 100,
                "completion_tokens": 5,
                "cache_read_input_tokens": 80,
                "cache_miss_input_tokens": 30,
            },
            "provider_usage_total_mismatch",
        ),
        (
            "openai/gpt-4.1-mini",
            {"prompt_tokens": 10, "completion_tokens": 5, "cache_read_input_tokens": 20},
            "provider_usage_cache_exceeds_prompt",
        ),
        (
            "deepseek/deepseek-v4-flash",
            {"prompt_tokens": True, "completion_tokens": 5},
            "invalid_usage_field:prompt_tokens",
        ),
        (
            "deepseek/deepseek-v4-flash",
            {"prompt_tokens": "bad", "completion_tokens": 5},
            "invalid_usage_field:prompt_tokens",
        ),
        (
            "deepseek/deepseek-v4-flash",
            {"prompt_tokens": -1, "completion_tokens": 5},
            "negative_usage_field:prompt_tokens",
        ),
        (
            "deepseek/deepseek-v4-flash",
            {"completion_tokens": 5},
            None,
        ),
    ],
)
def test_usage_normalization_fails_closed_for_incomplete_or_invalid_usage(
    tmp_path,
    model: str,
    usage: dict,
    finding: str | None,
) -> None:
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False)

    record = controller.record(
        LLMResponse(content="ok", usage=usage, model=model),
        requested_model=model,
        session_key="session-1",
    )

    assert record.usage.complete is False
    assert record.estimated_cost_usd is None
    if finding is not None:
        assert finding in record.findings


def test_tracing_projects_the_same_anthropic_usage_semantics() -> None:
    usage = {
        "prompt_tokens": 200,
        "completion_tokens": 50,
        "cache_read_input_tokens": 800,
    }

    projected = normalize_trace_usage(usage, "anthropic/claude-sonnet-4-5")

    assert projected["input_tokens"] == 200
    assert projected["cache_read_tokens"] == 800
    assert projected["usage_complete"] is True
    assert projected["findings"] == ()


def test_tracing_projects_invalid_usage_without_raising() -> None:
    projected = normalize_trace_usage(
        {"prompt_tokens": "bad", "completion_tokens": 5},
        "deepseek/deepseek-v4-flash",
    )

    assert projected["input_tokens"] == 0
    assert projected["output_tokens"] == 5
    assert projected["total_tokens"] == 5
    assert projected["usage_complete"] is False
    assert projected["findings"] == ("invalid_usage_field:prompt_tokens",)


def test_openrouter_route_controls_usage_and_pricing_semantics(tmp_path) -> None:
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False)

    record = controller.record(
        LLMResponse(
            content="ok",
            model="anthropic/claude-sonnet-4-5",
            usage={
                "prompt_tokens": 1000,
                "completion_tokens": 50,
                "cache_read_input_tokens": 800,
            },
        ),
        requested_model="openrouter/anthropic/claude-sonnet-4-5",
        session_key="session-1",
    )

    assert record.actual_model == "anthropic/claude-sonnet-4-5"
    assert record.accounting_model == "openrouter/anthropic/claude-sonnet-4-5"
    assert record.usage.input_tokens == 200
    assert record.usage.complete is True


def test_observe_mode_never_rewrites_provider_request(tmp_path) -> None:
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False)
    messages = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "hello"},
    ]
    tools = [{"type": "function", "function": {"name": "read", "description": "read"}}]

    prepared = controller.prepare(messages, tools, "anthropic/claude-sonnet-4-5")

    assert prepared.messages is messages
    assert prepared.tools is tools
    assert prepared.cache_policy == "observe_only"
    assert _cache_markers(prepared.messages) + _cache_markers(prepared.tools) == 0


def test_optimize_mode_owns_one_anthropic_cache_plan(tmp_path) -> None:
    controller = CallEfficiency(
        mode="optimize",
        telemetry_dir=tmp_path,
        persist=False,
        max_cache_breakpoints=4,
    )
    messages = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
        {"role": "user", "content": "three"},
    ]
    tools = [{"type": "function", "function": {"name": "read", "description": "read"}}]
    original_messages = deepcopy(messages)
    original_tools = deepcopy(tools)

    prepared = controller.prepare(messages, tools, "anthropic/claude-sonnet-4-5")

    assert prepared.cache_policy == "anthropic_explicit_v1"
    assert _cache_markers(prepared.messages) + _cache_markers(prepared.tools) == 4
    assert messages == original_messages
    assert tools == original_tools

    repeated = controller.prepare(prepared.messages, prepared.tools, "anthropic/claude-sonnet-4-5")
    assert _cache_markers(repeated.messages) + _cache_markers(repeated.tools) == 4


def test_optimize_mode_uses_underlying_model_for_openrouter_cache_plan(tmp_path) -> None:
    controller = CallEfficiency(
        mode="optimize",
        telemetry_dir=tmp_path,
        persist=False,
        max_cache_breakpoints=4,
    )
    messages = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "hello"},
    ]
    tools = [{"type": "function", "function": {"name": "read"}}]

    prepared = controller.prepare(
        messages,
        tools,
        "openrouter/anthropic/claude-sonnet-4-5",
    )

    assert prepared.cache_policy == "anthropic_explicit_v1"
    assert _cache_markers(prepared.messages) + _cache_markers(prepared.tools) == 3


def test_tool_parameter_named_cache_control_does_not_look_like_an_external_marker(tmp_path) -> None:
    controller = CallEfficiency(
        mode="optimize",
        telemetry_dir=tmp_path,
        persist=False,
    )
    messages = [{"role": "system", "content": "stable"}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "configure",
                "parameters": {"properties": {"cache_control": {"type": "string"}}},
            },
        }
    ]

    prepared = controller.prepare(messages, tools, "anthropic/claude-sonnet-4-5")

    assert prepared.cache_policy == "anthropic_explicit_v1"
    assert _cache_markers(prepared.messages) + _cache_markers(prepared.tools) == 3


def test_optimize_mode_replans_malformed_external_cache_markers(tmp_path) -> None:
    controller = CallEfficiency(
        mode="optimize",
        telemetry_dir=tmp_path,
        persist=False,
    )
    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "stable",
                    "cache_control": {"type": "permanent"},
                }
            ],
        },
        {"role": "user", "content": "hello"},
    ]

    prepared = controller.prepare(messages, None, "anthropic/claude-sonnet-4-5")

    assert prepared.cache_policy == "anthropic_explicit_replanned_v1"
    assert _cache_markers(prepared.messages) == 2
    markers = [
        block["cache_control"]
        for message in prepared.messages
        for block in message.get("content", [])
        if isinstance(block, dict) and "cache_control" in block
    ]
    assert markers == [{"type": "ephemeral"}, {"type": "ephemeral"}]


def test_optimize_mode_replans_external_markers_above_provider_limit(tmp_path) -> None:
    controller = CallEfficiency(
        mode="optimize",
        telemetry_dir=tmp_path,
        persist=False,
        max_cache_breakpoints=4,
    )
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": str(index),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
        for index in range(5)
    ]

    prepared = controller.prepare(messages, None, "anthropic/claude-sonnet-4-5")

    assert prepared.cache_policy == "anthropic_explicit_replanned_v1"
    assert _cache_markers(prepared.messages) == 4


def test_optimize_mode_strips_external_markers_for_automatic_cache_provider(tmp_path) -> None:
    controller = CallEfficiency(mode="optimize", telemetry_dir=tmp_path, persist=False)
    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "stable",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    ]

    prepared = controller.prepare(messages, None, "deepseek/deepseek-v4-flash")

    assert prepared.cache_policy == "provider_automatic"
    assert _cache_markers(prepared.messages) == 0
    assert _cache_markers(messages) == 1


@pytest.mark.parametrize("model", ["deepseek/deepseek-v4-flash", "openai/gpt-4.1-mini"])
def test_optimize_mode_leaves_automatic_cache_providers_untouched(tmp_path, model: str) -> None:
    controller = CallEfficiency(mode="optimize", telemetry_dir=tmp_path, persist=False)
    messages = [{"role": "user", "content": "hello"}]
    tools = [{"type": "function", "function": {"name": "read"}}]

    prepared = controller.prepare(messages, tools, model)

    assert prepared.messages is messages
    assert prepared.tools is tools
    assert prepared.cache_policy == "provider_automatic"


def test_ledger_preserves_schema_and_evidence_lineage(tmp_path) -> None:
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=True)
    controller.record(
        LLMResponse(
            content="ok",
            usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            model="deepseek/deepseek-v4-flash",
        ),
        requested_model="deepseek/deepseek-v4-flash",
        session_key="session-1",
    )
    controller.close()

    rows = list(tmp_path.glob("call-efficiency-*.jsonl"))
    assert len(rows) == 1
    payload = json.loads(rows[0].read_text(encoding="utf-8").strip())
    assert payload["schema"] == "pico.call-efficiency.call.v1"
    assert payload["requested_model"] == "deepseek/deepseek-v4-flash"
    assert payload["attempted_model"] == "deepseek/deepseek-v4-flash"
    assert payload["actual_model"] == "deepseek/deepseek-v4-flash"
    assert payload["outcome"] == "success"
    assert payload["finish_reason"] == "stop"
    assert payload["error_category"] is None
    assert payload["session_key"] == "session-1"
    assert payload["usage"]["complete"] is True
    health = json.loads((tmp_path / "call-efficiency-ledger-health.json").read_text(encoding="utf-8"))
    assert health["status"] == "healthy"
    assert health["accepted_records"] == 1
    assert health["persisted_records"] == 1
    assert health["lost_records"] == 0


def test_ledger_persists_on_a_background_writer(monkeypatch, tmp_path) -> None:
    writer_threads: list[int] = []

    def _locked_append(path, lines, **_kwargs):
        writer_threads.append(threading.get_ident())
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("".join(f"{line}\n" for line in lines))

    monkeypatch.setattr("pico.call_efficiency.ledger.locked_append", _locked_append)
    caller_thread = threading.get_ident()
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=True)

    controller.record(
        LLMResponse(
            content="ok",
            usage={"prompt_tokens": 10, "completion_tokens": 2},
            model="deepseek/deepseek-v4-flash",
        ),
        requested_model="deepseek/deepseek-v4-flash",
        session_key="session-1",
    )
    controller.close()

    assert writer_threads
    assert all(thread_id != caller_thread for thread_id in writer_threads)


def test_ledger_retains_only_a_bounded_recent_window(tmp_path) -> None:
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False)

    for index in range(300):
        controller.record(
            LLMResponse(
                content="ok",
                usage={"prompt_tokens": index, "completion_tokens": 1},
                model="deepseek/deepseek-v4-flash",
            ),
            requested_model="deepseek/deepseek-v4-flash",
            session_key="session-1",
        )

    assert len(controller.records) == 256
    assert controller.records[0].usage.input_tokens == 44

    controller.close()
    assert not (tmp_path / "call-efficiency-ledger-health.json").exists()


def test_ledger_write_failure_persists_machine_readable_degradation(monkeypatch, tmp_path) -> None:
    def _fail(*_args, **_kwargs):
        raise OSError("disk offline")

    monkeypatch.setattr("pico.call_efficiency.ledger.locked_append", _fail)
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=True)
    controller.record(
        LLMResponse(
            content="ok",
            usage={"prompt_tokens": 10, "completion_tokens": 2},
            model="deepseek/deepseek-v4-flash",
        ),
        requested_model="deepseek/deepseek-v4-flash",
        session_key="session-1",
    )

    with pytest.raises(RuntimeError, match="ledger writer failed"):
        controller.close()

    health = json.loads((tmp_path / "call-efficiency-ledger-health.json").read_text(encoding="utf-8"))
    assert health["schema"] == "pico.call-efficiency.ledger-health.v1"
    assert health["status"] == "degraded"
    assert health["accepted_records"] == 1
    assert health["persisted_records"] == 0
    assert health["lost_records"] == 1


def test_ledger_failure_updates_loss_evidence_for_later_calls(monkeypatch, tmp_path) -> None:
    def _fail(*_args, **_kwargs):
        raise OSError("disk offline")

    monkeypatch.setattr("pico.call_efficiency.ledger.locked_append", _fail)
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=True)
    response = LLMResponse(
        content="ok",
        usage={"prompt_tokens": 10, "completion_tokens": 2},
        model="deepseek/deepseek-v4-flash",
    )
    controller.record(
        response,
        requested_model="deepseek/deepseek-v4-flash",
        session_key="session-1",
    )
    assert controller.ledger._writer is not None
    controller.ledger._writer.join(timeout=1.0)

    write_health = controller.ledger._write_health
    health_spy = MagicMock()
    monkeypatch.setattr(controller.ledger, "_write_health", health_spy)
    controller.record(
        response,
        requested_model="deepseek/deepseek-v4-flash",
        session_key="session-1",
    )
    health_spy.assert_not_called()
    monkeypatch.setattr(controller.ledger, "_write_health", write_health)

    with pytest.raises(RuntimeError, match="ledger writer failed"):
        controller.close()
    health = json.loads((tmp_path / "call-efficiency-ledger-health.json").read_text(encoding="utf-8"))
    assert health["accepted_records"] == 2
    assert health["persisted_records"] == 0
    assert health["lost_records"] == 2


def test_ledger_failure_health_write_does_not_block_later_calls(monkeypatch, tmp_path) -> None:
    health_started = threading.Event()
    release_health = threading.Event()

    def _fail(*_args, **_kwargs):
        raise OSError("disk offline")

    monkeypatch.setattr("pico.call_efficiency.ledger.locked_append", _fail)
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=True)
    original_write_health = controller.ledger._write_health

    def _slow_health(status: str) -> None:
        health_started.set()
        assert release_health.wait(timeout=2.0)
        original_write_health(status)

    monkeypatch.setattr(controller.ledger, "_write_health", _slow_health)
    response = LLMResponse(
        content="ok",
        usage={"prompt_tokens": 10, "completion_tokens": 2},
        model="deepseek/deepseek-v4-flash",
    )
    controller.record(
        response,
        requested_model="deepseek/deepseek-v4-flash",
        session_key="session-1",
    )
    assert health_started.wait(timeout=1.0)

    later_call = threading.Thread(
        target=lambda: controller.record(
            response,
            requested_model="deepseek/deepseek-v4-flash",
            session_key="session-1",
        )
    )
    later_call.start()
    later_call.join(timeout=0.25)
    try:
        assert not later_call.is_alive()
    finally:
        release_health.set()
        later_call.join(timeout=1.0)

    with pytest.raises(RuntimeError, match="ledger writer failed"):
        controller.close()


def test_ledger_health_degradation_is_monotonic_across_runtimes(monkeypatch, tmp_path) -> None:
    import pico.call_efficiency.ledger as ledger_module

    original_append = ledger_module.locked_append

    def _fail(*_args, **_kwargs):
        raise OSError("disk offline")

    monkeypatch.setattr(ledger_module, "locked_append", _fail)
    degraded = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=True)
    degraded.record(
        LLMResponse(content="lost", usage={"prompt_tokens": 1, "completion_tokens": 1}),
        requested_model="custom/local-model",
        session_key="session-1",
    )
    with pytest.raises(RuntimeError, match="ledger writer failed"):
        degraded.close()

    monkeypatch.setattr(ledger_module, "locked_append", original_append)
    healthy = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=True)
    healthy.record(
        LLMResponse(content="saved", usage={"prompt_tokens": 1, "completion_tokens": 1}),
        requested_model="custom/local-model",
        session_key="session-2",
    )
    healthy.close()

    health = json.loads((tmp_path / "call-efficiency-ledger-health.json").read_text(encoding="utf-8"))
    assert health["status"] == "degraded"
    assert health["accepted_records"] == 2
    assert health["persisted_records"] == 1
    assert health["lost_records"] == 1


def test_runtime_builder_defaults_observe_for_legacy_config_stubs(tmp_path) -> None:
    controller = CallEfficiency.from_config(MagicMock(), telemetry_dir=tmp_path)

    assert controller.mode == "observe"
    assert controller.max_cache_breakpoints == 4


class _ProviderDouble(LLMProvider):
    def __init__(self, model: str, *, explicit: bool = False) -> None:
        super().__init__(api_key="test")
        self.model = model
        self.explicit = explicit
        self.calls = []

    def supports_explicit_cache_control(self, model: str) -> bool:
        return self.explicit

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.calls.append((messages, tools, model))
        return LLMResponse(
            content="ok",
            model=model or self.model,
            usage={"prompt_tokens": 10, "completion_tokens": 2},
        )

    async def chat_stream(self, messages, tools=None, model=None, **kwargs):
        self.calls.append((messages, tools, model))
        yield StreamDelta(content="ok", model=model or self.model)
        yield StreamDelta(
            content=None,
            model=model or self.model,
            usage={"prompt_tokens": 10, "completion_tokens": 2},
        )

    def get_default_model(self) -> str:
        return self.model


class _FallbackProvider(_ProviderDouble):
    def supports_explicit_cache_control(self, model: str) -> bool:
        return model.startswith("anthropic/")

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.calls.append((messages, tools, model))
        if model and model.startswith("anthropic/"):
            return LLMResponse(content="503 overloaded", finish_reason="error", model=model)
        return LLMResponse(
            content="ok",
            model=model or self.model,
            usage={"prompt_tokens": 10, "completion_tokens": 2},
        )


class _BlockingCapabilityProvider(_ProviderDouble):
    def __init__(self, model: str, *, explicit: bool, ready: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__(model, explicit=explicit)
        self.ready = ready
        self.release = release

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.ready.set()
        await self.release.wait()
        return await super().chat(messages, tools, model, **kwargs)


class _RaisingProvider(_ProviderDouble):
    async def chat(self, messages, tools=None, model=None, **kwargs):
        raise OSError("transport offline")

    async def chat_stream(self, messages, tools=None, model=None, **kwargs):
        yield StreamDelta(content="partial", model=model or self.model)
        raise OSError("stream interrupted")


class _CancellableProvider(_ProviderDouble):
    def __init__(self, model: str, started: asyncio.Event) -> None:
        super().__init__(model)
        self.started = started

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_provider_decorator_owns_prepare_and_record_for_direct_calls(tmp_path) -> None:
    delegate = _ProviderDouble("anthropic/claude-sonnet-4-5", explicit=True)
    controller = CallEfficiency(
        mode="optimize",
        telemetry_dir=tmp_path,
        persist=False,
        provider=delegate,
    )
    provider = CallEfficiencyProvider(delegate, controller)

    response = await provider.chat(
        messages=[{"role": "system", "content": "stable"}],
        tools=[{"type": "function", "function": {"name": "read"}}],
    )

    assert _cache_markers(delegate.calls[0][0]) + _cache_markers(delegate.calls[0][1]) == 2
    assert response.call_record is controller.records[-1]
    assert response.call_record.cache_policy == "anthropic_explicit_v1"


@pytest.mark.asyncio
async def test_provider_decorator_updates_capabilities_when_runtime_switches_model(tmp_path) -> None:
    anthropic = _ProviderDouble("anthropic/claude-sonnet-4-5", explicit=True)
    controller = CallEfficiency(
        mode="optimize",
        telemetry_dir=tmp_path,
        persist=False,
        provider=anthropic,
    )
    provider = CallEfficiencyProvider(anthropic, controller)
    deepseek = _ProviderDouble("deepseek/deepseek-v4-flash")

    provider.replace(deepseek)
    await provider.chat(
        messages=[{"role": "system", "content": "stable"}],
        model="deepseek/deepseek-v4-flash",
    )

    assert controller.provider is deepseek
    assert _cache_markers(deepseek.calls[0][0]) == 0
    assert controller.records[-1].cache_policy == "provider_automatic"


def test_agent_loop_replaces_provider_and_all_default_model_consumers(tmp_path) -> None:
    old_delegate = _ProviderDouble("anthropic/claude-sonnet-4-5", explicit=True)
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False, provider=old_delegate)
    provider = CallEfficiencyProvider(old_delegate, controller)
    agent = AgentLoop(
        provider=provider,
        workspace=tmp_path,
        model="anthropic/claude-sonnet-4-5",
        restrict_to_workspace=True,
        call_efficiency=controller,
    )
    new_delegate = _ProviderDouble("deepseek/deepseek-v4-flash")

    agent.replace_provider(new_delegate, model="deepseek/deepseek-v4-flash")

    assert agent.provider is provider
    assert provider.delegate is new_delegate
    assert controller.provider is new_delegate
    assert agent.model == "deepseek/deepseek-v4-flash"
    assert agent.subagents.model == "deepseek/deepseek-v4-flash"
    assert agent.memory_consolidator.model == "deepseek/deepseek-v4-flash"
    curator = next(builder for builder in agent.context_engine._builders if builder.name == "curator")
    assert curator.model == "deepseek/deepseek-v4-flash"
    assert curator.curator_model == agent.context_config.curator_model
    assert curator.assembler.model == "deepseek/deepseek-v4-flash"
    assert curator.assembler.trimmer.model == "deepseek/deepseek-v4-flash"


@pytest.mark.asyncio
async def test_in_flight_call_keeps_the_delegate_capability_snapshot(tmp_path) -> None:
    ready = asyncio.Event()
    release = asyncio.Event()
    old_delegate = _BlockingCapabilityProvider(
        "anthropic/claude-sonnet-4-5",
        explicit=False,
        ready=ready,
        release=release,
    )
    controller = CallEfficiency(
        mode="optimize",
        telemetry_dir=tmp_path,
        persist=False,
        provider=old_delegate,
    )
    provider = CallEfficiencyProvider(old_delegate, controller)
    task = asyncio.create_task(provider.chat_with_retry(messages=[{"role": "system", "content": "stable"}]))
    await ready.wait()

    provider.replace(_ProviderDouble("anthropic/claude-sonnet-4-5", explicit=True))
    release.set()
    await task

    assert _cache_markers(old_delegate.calls[0][0]) == 0
    assert controller.records[-1].cache_policy == "unsupported"


@pytest.mark.asyncio
async def test_provider_decorator_strips_external_anthropic_markers_on_fallback(tmp_path) -> None:
    delegate = _FallbackProvider("anthropic/claude-sonnet-4-5")
    delegate._CHAT_RETRY_DELAYS = ()
    controller = CallEfficiency(
        mode="optimize",
        telemetry_dir=tmp_path,
        persist=False,
        provider=delegate,
    )
    provider = CallEfficiencyProvider(delegate, controller)
    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": "stable",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    ]

    response = await provider.chat_with_retry(
        messages=messages,
        model="anthropic/claude-sonnet-4-5",
        fallback_models=["deepseek/deepseek-v4-flash"],
    )

    assert response.content == "ok"
    assert len(delegate.calls) == 2
    assert _cache_markers(delegate.calls[0][0]) == 1
    assert _cache_markers(delegate.calls[1][0]) == 0
    assert [record.attempted_model for record in controller.records] == [
        "anthropic/claude-sonnet-4-5",
        "deepseek/deepseek-v4-flash",
    ]
    assert [record.outcome for record in controller.records] == ["error", "success"]
    assert controller.records[0].error_category == "server"


@pytest.mark.asyncio
async def test_provider_decorator_records_direct_transport_exception(tmp_path) -> None:
    delegate = _RaisingProvider("custom/local-model")
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False, provider=delegate)
    provider = CallEfficiencyProvider(delegate, controller)

    with pytest.raises(OSError, match="transport offline"):
        await provider.chat(messages=[])

    assert len(controller.records) == 1
    assert controller.records[0].outcome == "error"
    assert controller.records[0].error_category == "network"
    assert controller.records[0].usage.complete is False


@pytest.mark.asyncio
async def test_provider_decorator_records_interrupted_stream_attempt(tmp_path) -> None:
    delegate = _RaisingProvider("custom/local-model")
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False, provider=delegate)
    provider = CallEfficiencyProvider(delegate, controller)

    received: list[str] = []
    with pytest.raises(OSError, match="stream interrupted"):
        async for delta in provider.chat_stream(messages=[]):
            if delta.content:
                received.append(delta.content)

    assert received == ["partial"]
    assert len(controller.records) == 1
    assert controller.records[0].outcome == "error"
    assert controller.records[0].error_category == "network"
    assert controller.records[0].usage.complete is False


@pytest.mark.asyncio
async def test_provider_decorator_records_cancelled_retry_attempt(tmp_path) -> None:
    started = asyncio.Event()
    delegate = _CancellableProvider("custom/local-model", started)
    controller = CallEfficiency(mode="observe", telemetry_dir=tmp_path, persist=False, provider=delegate)
    provider = CallEfficiencyProvider(delegate, controller)
    task = asyncio.create_task(provider.chat_with_retry(messages=[]))
    await started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(controller.records) == 1
    assert controller.records[0].outcome == "cancelled"
    assert controller.records[0].error_category == "cancelled"
    assert controller.records[0].usage.complete is False
