"""Personalizer integration contracts; no semantic-accuracy claims."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pico.agent.personalizer.jev_policy import GateDecision
from pico.agent.personalizer.personalizer import Personalizer
from pico.providers.base import LLMResponse
from pico.spine.message import Media
from pico.spine.turn import Origin


@pytest.mark.parametrize(
    "payload",
    [
        {"needs_clarification": "false", "domain": "language"},
        {"needs_clarification": 1, "domain": "language"},
        {"needs_clarification": True, "domain": []},
        {"needs_clarification": True},
        {"needs_clarification": True, "domain": " "},
        {"needs_clarification": True, "domain": "x" * 129},
        {},
        None,
    ],
)
async def test_invalid_legacy_classifier_output_is_neutral(payload):
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(payload))))
    personalizer = Personalizer(SimpleNamespace(read_long_term=lambda: ""), provider, "test")
    assert await personalizer.classify("request") == {"needs_clarification": False, "domain": ""}
    assert provider.chat.await_count == 1


@pytest.mark.parametrize("failed", [False, True])
async def test_valid_true_requires_a_successful_provider_response(failed):
    provider = SimpleNamespace(
        chat=AsyncMock(
            return_value=LLMResponse(
                content='{"needs_clarification":true,"domain":" framework "}',
                finish_reason="error" if failed else "stop",
            )
        )
    )
    personalizer = Personalizer(SimpleNamespace(read_long_term=lambda: ""), provider, "test")
    result = await personalizer.classify("request")
    assert result == {"needs_clarification": not failed, "domain": "" if failed else "framework"}


async def test_gate_bug_falls_back_to_existing_provider():
    provider = SimpleNamespace(
        chat=AsyncMock(return_value=LLMResponse(content='{"needs_clarification":false,"domain":""}'))
    )
    gate = SimpleNamespace(assess=AsyncMock(side_effect=RuntimeError("test")))
    personalizer = Personalizer(SimpleNamespace(read_long_term=lambda: ""), provider, "test", gate=gate)
    assert not (await personalizer.classify("request", allow_gate=True))["needs_clarification"]
    assert provider.chat.await_count == 1


@pytest.mark.parametrize("allow_gate", [False, True])
async def test_direct_call_is_opt_in(allow_gate):
    provider = SimpleNamespace(
        chat=AsyncMock(return_value=LLMResponse(content='{"needs_clarification":false,"domain":""}'))
    )
    gate = SimpleNamespace(assess=AsyncMock(return_value=GateDecision(fast_pass=True)))
    personalizer = Personalizer(SimpleNamespace(read_long_term=lambda: ""), provider, "test", gate=gate)
    await personalizer.classify("request", allow_gate=allow_gate)
    assert gate.assess.await_count == int(allow_gate)
    assert provider.chat.await_count == int(not allow_gate)


@pytest.mark.parametrize("origin", [Origin.USER, Origin.CRON, Origin.SUBAGENT])
async def test_only_user_origin_enters_personalization(tmp_path, origin):
    from tests.test_agent_loop_memory_pipeline import _FakeBackend, _make_agent, _msg

    agent = _make_agent(tmp_path, backend=_FakeBackend())
    gate = SimpleNamespace(assess=AsyncMock(return_value=GateDecision(fast_pass=True)))
    agent.configure_personalization(True, gate=gate)
    agent._start_personalization_task = MagicMock()
    try:
        await agent._process_message(replace(_msg(), origin=origin), origin=origin)
        assert gate.assess.await_count == int(origin is Origin.USER)
        assert agent._start_personalization_task.call_count == int(origin is Origin.USER)
    finally:
        await agent.close()


@pytest.mark.parametrize("pending,media", [(True, False), (False, True)])
async def test_pending_clarification_and_media_bypass_jev(tmp_path, pending, media):
    from tests.test_agent_loop_memory_pipeline import _FakeBackend, _make_agent, _msg

    agent = _make_agent(tmp_path, backend=_FakeBackend())
    gate = SimpleNamespace(assess=AsyncMock(return_value=GateDecision(fast_pass=True)))
    agent.configure_personalization(True, gate=gate)
    agent._start_personalization_task = MagicMock()
    request = _msg()
    if pending:
        agent.sessions.get_or_create("mock:c1").pending_clarification = {
            "original_message": "set up my project",
            "question": "Which framework?",
            "domain": "framework",
        }
    if media:
        request = replace(request, media=(Media(path="/nonexistent/test.png", mime="image/png", kind="image"),))
        agent._assemble_context_messages = AsyncMock(return_value=[{"role": "user", "content": "request"}])
    try:
        await agent._process_message(request, origin=Origin.USER)
        gate.assess.assert_not_awaited()
    finally:
        await agent.close()


async def test_memory_off_cannot_enable_gate(tmp_path):
    from tests.test_agent_loop_memory_pipeline import _make_agent, _msg

    agent = _make_agent(tmp_path)
    gate = SimpleNamespace(assess=AsyncMock())
    agent.configure_personalization(True, gate=gate)
    try:
        assert not agent.enable_personalization
        await agent._process_message(_msg())
        gate.assess.assert_not_awaited()
    finally:
        await agent.close()


async def test_shutdown_closes_gate_before_accounting_even_when_gate_errors():
    from pico.cli._runtime_assembly import RuntimeAssembly

    order = []

    async def close_gate():
        order.append("gate")
        raise RuntimeError("test gate close")

    gate = SimpleNamespace(begin_close=MagicMock(), aclose=close_gate)
    agent = SimpleNamespace(begin_close=MagicMock(), close=AsyncMock())
    accounting = SimpleNamespace(close=lambda: order.append("accounting"))
    backend = SimpleNamespace(stop=AsyncMock())
    runtime = RuntimeAssembly(agent, object(), backend, call_efficiency=accounting, personalization_gate=gate)
    await runtime.close()
    assert order == ["gate", "accounting"]
    backend.stop.assert_awaited_once()


@pytest.mark.parametrize(
    "enabled,backend_present,mode,expected",
    [
        (True, True, "shadow", True),
        (True, True, "off", False),
        (False, True, "shadow", False),
        (True, False, "shadow", False),
    ],
)
async def test_shared_assembly_owns_only_an_active_gate(
    monkeypatch, tmp_path, enabled, backend_present, mode, expected
):
    from pico.call_efficiency import CallEfficiency
    from pico.cli._runtime_assembly import assemble_runtime
    from pico.config.personalization import PersonalizationGateConfig
    from tests.test_cli_runtime_assembly import _runtime_configs

    config, pico_config = _runtime_configs(tmp_path)
    config.agents.defaults.enable_personalization = enabled
    config.agents.defaults.personalization_gate = PersonalizationGateConfig(mode=mode, data_consent=True)
    accounting = CallEfficiency(telemetry_dir=tmp_path / "telemetry", persist=True)
    backend = SimpleNamespace(stop=AsyncMock()) if backend_present else None
    monkeypatch.setattr("pico.call_efficiency.CallEfficiency.from_config", lambda *args, **kwargs: accounting)
    monkeypatch.setattr("pico.cli._plugin_stack.build_plugin_registry", lambda *args, **kwargs: object())
    monkeypatch.setattr("pico.cli._plugin_stack.maybe_build_memory_backend", lambda *args, **kwargs: backend)
    monkeypatch.setattr("pico.cli._plugin_stack.build_plugin_tools", lambda *args, **kwargs: [])
    loop = SimpleNamespace(configure_personalization=MagicMock(), begin_close=MagicMock(), close=AsyncMock())
    monkeypatch.setattr("pico.agent.loop.AgentLoop", lambda **kwargs: loop)
    runtime = assemble_runtime(
        config, pico_config, provider=object(), cron_service=None, interactive=False, session_manager=object()
    )
    try:
        assert (runtime.personalization_gate is not None) is expected
        if expected:
            assert runtime.personalization_gate._client is None
            loop.configure_personalization.assert_called_once_with(True, gate=runtime.personalization_gate)
        else:
            loop.configure_personalization.assert_called_once_with(enabled)
        assert not accounting.records
    finally:
        await runtime.close()


async def test_disabled_gate_keeps_legacy_classifier_call_shape(monkeypatch, tmp_path):
    from tests.test_agent_loop_memory_pipeline import _FakeBackend, _make_agent, _msg

    calls = []

    async def legacy_classify(self, message, history=None):
        calls.append(message)
        return {"needs_clarification": False, "domain": ""}

    monkeypatch.setattr(Personalizer, "classify", legacy_classify)
    agent = _make_agent(tmp_path, backend=_FakeBackend())
    agent.configure_personalization(True)
    agent._start_personalization_task = MagicMock()
    try:
        await agent._process_message(_msg(), origin=Origin.USER)
        assert len(calls) == 1
    finally:
        await agent.close()
