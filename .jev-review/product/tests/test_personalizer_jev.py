"""Credential-free policy, transport, accounting and cancellation checks."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from pico.agent.personalizer.jev import JevPreferenceGate
from pico.agent.personalizer.jev_policy import QUESTIONS, DecisionContractError, evaluate_answers
from pico.agent.personalizer.personalizer import Personalizer
from pico.call_efficiency import CallEfficiency, CallEfficiencyProvider
from pico.config.personalization import PersonalizationGateConfig
from pico.config.schema import AgentDefaults
from pico.providers.base import LLMProvider, LLMResponse
from pico.tracing.context import turn_scope


def _payload(choices=("none", "not_applicable", "not_needed"), probability=0.995, confidence=0.99):
    answers = {}
    for (key, question), choice in zip(QUESTIONS.items(), choices, strict=True):
        options = question["criteria"]
        answers[key] = {
            "type": "choice",
            "choice": choice,
            "probabilities": {name: probability if name == choice else (1 - probability) / (len(options) - 1) for name in options},
            "confidence": confidence,
        }
    return {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 500, "output_tokens": 80}}


def _config(**kwargs):
    values = {"mode": "enforce", "data_consent": True, "policy_digest": "a" * 64, "api_key_env": "TYPESAFE_TEST_KEY"}
    values.update(kwargs)
    return PersonalizationGateConfig(**values)


@pytest.fixture
def accounting(tmp_path):
    controller = CallEfficiency(telemetry_dir=tmp_path / "telemetry", persist=True)
    yield controller
    controller.close()


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_TEST_KEY", "test-credential-never-sent-to-network")


@pytest.mark.parametrize("choices", [
    ("none", "not_applicable", "not_needed"),
    ("relevant", "complete", "not_needed"),
    ("relevant", "incomplete", "available"),
])
def test_exact_consistent_fast_pass_combinations(choices):
    passed, reason, _ = evaluate_answers(_payload(choices)["answers"], min_confidence=0.98, min_choice_probability=0.98)
    assert passed and reason == "clear_no_clarification"


@pytest.mark.parametrize("choices", [
    ("relevant", "incomplete", "unavailable"),
    ("none", "incomplete", "available"),
    ("relevant", "not_applicable", "not_needed"),
    ("unknown", "unknown", "unknown"),
])
def test_uncertainty_or_conflict_does_not_fast_pass(choices):
    passed, _, _ = evaluate_answers(_payload(choices)["answers"], min_confidence=0.98, min_choice_probability=0.98)
    assert not passed


@pytest.mark.parametrize("field,value", [
    ("confidence", True), ("confidence", float("nan")), ("confidence", 1.1),
    ("confidence", "0.99"), ("type", "score"), ("choice", "invented"),
    ("probabilities", {"none": 1.0}),
    ("probabilities", {"none": 0.1, "relevant": 0.1, "unknown": 0.1}),
    ("probabilities", {"none": 0.0, "relevant": 1.0, "unknown": 0.0}),
    ("probabilities", {"none": True, "relevant": 0.0, "unknown": 0.0}),
])
def test_malformed_choice_is_rejected(field, value):
    answers = _payload()["answers"]
    answers["relevance"][field] = value
    with pytest.raises(DecisionContractError):
        evaluate_answers(answers, min_confidence=0.98, min_choice_probability=0.98)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_question_set_must_match(mutation):
    answers = _payload()["answers"]
    if mutation == "missing":
        del answers["coverage"]
    else:
        answers["injected"] = copy.deepcopy(answers["coverage"])
    with pytest.raises(DecisionContractError, match="question_mismatch"):
        evaluate_answers(answers, min_confidence=0.98, min_choice_probability=0.98)


def test_config_defaults_and_consent():
    assert AgentDefaults().personalization_gate.mode == "off"
    assert AgentDefaults().enable_personalization is False
    assert PersonalizationGateConfig().mode == "off"
    for values in [
        {"mode": "shadow"}, {"mode": "enforce", "data_consent": True},
        {"model": "jev-latest"}, {"min_confidence": float("nan")},
        {"timeout_seconds": 0}, {"max_concurrent": 0}, {"requests_per_minute": 0},
        {"unknown_option": True},
    ]:
        with pytest.raises(ValidationError):
            PersonalizationGateConfig(**values)
    assert PersonalizationGateConfig.model_validate({"mode": "shadow", "dataConsent": True}).data_consent


async def test_success_records_one_billable_attempt_without_sensitive_text(accounting, key):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        assert request.url == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["authorization"].startswith("Bearer ")
        return httpx.Response(200, json=_payload())
    gate = JevPreferenceGate(_config(), accounting, transport=httpx.MockTransport(handler))
    try:
        with turn_scope(session_key="cli:one", channel="cli", chat_id="one", root_span_id="root") as ctx:
            result = await gate.assess("用 Python 写 CSV 清洗脚本", [], "private preference sentinel")
        assert result.fast_pass
        assert len(seen) == len(accounting.records) == 1
        record = accounting.records[0]
        assert record.call_id == result.call_id
        assert record.call_kind == "decision"
        assert record.session_key == "cli:one" and record.trace_id == ctx.trace_id
        assert record.usage.input_tokens == 500 and record.usage.output_tokens == 80
        assert record.estimated_cost_usd == pytest.approx(500 * 0.042 / 1_000_000)
        serialized = json.dumps(asdict(record), ensure_ascii=False)
        for secret in ("private preference sentinel", "test-credential-never-sent-to-network", "CSV 清洗"):
            assert secret not in serialized
        assert seen[0]["questions"] == QUESTIONS
        assert seen[0]["model"] == "jev-1.13.0"
        assert record.duration_ms is not None
    finally:
        await gate.aclose()


@pytest.mark.parametrize("mode,fast_pass", [("shadow", False), ("enforce", True)])
async def test_shadow_never_changes_the_classifier_result(accounting, key, mode, fast_pass):
    gate = JevPreferenceGate(_config(mode=mode), accounting, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_payload())))
    try:
        decision = await gate.assess("Explain CSV", [], "")
        assert decision.would_fast_pass
        assert decision.fast_pass is fast_pass
        assert accounting.records[0].details["mode"] == mode
    finally:
        await gate.aclose()


@pytest.mark.parametrize("probability,confidence", [(0.7, 0.99), (0.995, 0.5)])
async def test_low_evidence_falls_back(accounting, key, probability, confidence):
    gate = JevPreferenceGate(_config(), accounting, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_payload(probability=probability, confidence=confidence))))
    try:
        result = await gate.assess("Explain CSV", [], "")
        assert not result.fast_pass and result.reason == "low_confidence"
        assert len(accounting.records) == 1
    finally:
        await gate.aclose()


@pytest.mark.parametrize("mutation,reason", [
    ("version", "model_mismatch"), ("usage", "usage_incomplete"),
    ("bool_usage", "usage_incomplete"), ("answer", "question_mismatch"),
])
async def test_bad_contract_keeps_usage_evidence(accounting, key, mutation, reason):
    payload = _payload()
    if mutation == "version":
        payload["model"] = "jev-9.99.0"
    elif mutation == "usage":
        del payload["usage"]
    elif mutation == "bool_usage":
        payload["usage"]["input_tokens"] = True
    else:
        del payload["answers"]["coverage"]
    gate = JevPreferenceGate(_config(), accounting, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    try:
        result = await gate.assess("Explain CSV", [], "")
        assert not result.fast_pass and result.reason == reason
        record = accounting.records[0]
        if mutation in {"usage", "bool_usage", "version"}:
            assert record.estimated_cost_usd is None
        else:
            assert record.estimated_cost_usd is not None
    finally:
        await gate.aclose()


@pytest.mark.parametrize("status", [401, 403, 422, 429, 500, 529, 302])
async def test_http_failures_do_not_retry_and_open_circuit(accounting, key, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://not-authorized.invalid", "retry-after": "120"})
    gate = JevPreferenceGate(_config(failure_threshold=1), accounting, transport=httpx.MockTransport(handler))
    try:
        first = await gate.assess("Explain CSV", [], "")
        second = await gate.assess("Explain JSON", [], "")
        assert first.reason == f"http_{status}" and not first.fast_pass
        assert second.reason == "circuit_open"
        assert len(calls) == len(accounting.records) == 1
        assert accounting.records[0].estimated_cost_usd is None
        assert not accounting.records[0].usage.complete
    finally:
        await gate.aclose()


async def test_timeout_is_bounded_and_usage_unknown(accounting, key):
    cancelled = asyncio.Event()
    async def handler(request):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    gate = JevPreferenceGate(_config(timeout_seconds=0.02), accounting, transport=httpx.MockTransport(handler))
    try:
        result = await gate.assess("Explain CSV", [], "")
        assert result.reason == "timeout" and cancelled.is_set()
        assert len(accounting.records) == 1 and accounting.records[0].estimated_cost_usd is None
    finally:
        await gate.aclose()


@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancellation_is_recorded_and_propagates(accounting, key, shutdown):
    started = asyncio.Event()
    async def handler(request):
        started.set()
        await asyncio.Event().wait()
    gate = JevPreferenceGate(_config(), accounting, transport=httpx.MockTransport(handler))
    provider = SimpleNamespace(chat=AsyncMock())
    personalizer = Personalizer(SimpleNamespace(read_long_term=lambda: ""), provider, "main", gate=gate)
    task = asyncio.create_task(personalizer.classify("Explain CSV", allow_gate=True))
    await started.wait()
    if shutdown:
        await gate.aclose()
    else:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not provider.chat.called
    assert len(accounting.records) == 1 and accounting.records[0].outcome == "cancelled"
    assert accounting.records[0].estimated_cost_usd is None
    await gate.aclose()
    assert not gate._pending


async def test_local_limits_and_closed_gate_make_no_extra_attempts(accounting, key):
    gate = JevPreferenceGate(_config(requests_per_minute=1), accounting, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_payload())))
    try:
        assert (await gate.assess("Explain CSV", [], "")).fast_pass
        assert (await gate.assess("Explain JSON", [], "")).reason == "local_rate_limit"
        assert len(accounting.records) == 1
    finally:
        await gate.aclose()
    assert (await gate.assess("Explain JSON", [], "")).reason == "closed"
    assert len(accounting.records) == 1


async def test_capacity_is_nonblocking(accounting, key):
    started = asyncio.Event()
    release = asyncio.Event()
    async def handler(request):
        started.set()
        await release.wait()
        return httpx.Response(200, json=_payload())
    gate = JevPreferenceGate(_config(max_concurrent=1), accounting, transport=httpx.MockTransport(handler))
    first = asyncio.create_task(gate.assess("First", [], ""))
    try:
        await started.wait()
        assert (await gate.assess("Second", [], "")).reason == "capacity"
        release.set()
        assert (await first).fast_pass
        assert len(accounting.records) == 1
    finally:
        await gate.aclose()


@pytest.mark.parametrize("case,reason", [
    ("off", "off"), ("credentials", "missing_credentials"), ("empty", "empty_message"),
    ("large", "state_too_large"), ("history", "unsupported_history"), ("media", "unsupported_history"),
    ("accounting", "accounting_unavailable"),
])
async def test_ineligible_inputs_never_create_a_client(accounting, monkeypatch, case, reason):
    config = _config(mode="off" if case == "off" else "enforce")
    if case != "credentials":
        monkeypatch.setenv(config.api_key_env, "test-key")
    if case == "accounting":
        accounting.mode = "off"
    message = "" if case == "empty" else "x" * 13_000 if case == "large" else "Explain CSV"
    history = [{"role": "user", "content": "x" * 201}] if case == "history" else []
    if case == "media":
        history = [{"role": "user", "content": [{"type": "image_url"}]}]
    gate = JevPreferenceGate(config, accounting)
    result = await gate.assess(message, history, "")
    assert result.reason == reason and not result.fast_pass
    assert gate._client is None and not accounting.records
    await gate.aclose()


async def test_malformed_and_oversized_response(accounting, key):
    for content, reason in [(b"not-json", "transport_or_json_error"), (b"x" * 70_000, "response_too_large")]:
        gate = JevPreferenceGate(_config(), accounting, transport=httpx.MockTransport(lambda _, body=content: httpx.Response(200, content=body)))
        try:
            assert (await gate.assess("Explain CSV", [], "")).reason == reason
        finally:
            await gate.aclose()
    assert len(accounting.records) == 2


class _ClassifierProvider(LLMProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def get_default_model(self):
        return "main-test-model"

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.calls += 1
        return LLMResponse(content='{"needs_clarification":false,"domain":""}', model="main-test-model", usage={"prompt_tokens": 100, "completion_tokens": 10})


@pytest.mark.parametrize("mode,expected_calls", [("shadow", 1), ("enforce", 0)])
async def test_only_enforce_removes_the_existing_provider_call(accounting, key, mode, expected_calls):
    delegate = _ClassifierProvider()
    provider = CallEfficiencyProvider(delegate, accounting)
    gate = JevPreferenceGate(_config(mode=mode), accounting, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_payload())))
    personalizer = Personalizer(SimpleNamespace(read_long_term=lambda: ""), provider, "main-test-model", gate=gate)
    try:
        assert await personalizer.classify("Explain CSV", allow_gate=True) == {"needs_clarification": False, "domain": ""}
        assert delegate.calls == expected_calls
        assert len(accounting.records) == 1 + expected_calls
        assert sum(record.call_kind == "decision" for record in accounting.records) == 1
    finally:
        await gate.aclose()


async def test_ledger_failure_never_authorizes_fast_pass(accounting, key, monkeypatch):
    def fail(record):
        raise RuntimeError("synthetic ledger failure")
    monkeypatch.setattr(accounting.ledger, "append", fail)
    gate = JevPreferenceGate(_config(), accounting, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_payload())))
    try:
        result = await gate.assess("Explain CSV", [], "")
        assert not result.fast_pass and result.reason == "ledger_write_failed"
    finally:
        await gate.aclose()


async def test_transport_failure_and_session_isolation(accounting, key):
    async def handler(request):
        state = json.loads(request.content)["state"]
        if state["message"] == "broken":
            raise httpx.ConnectError("fixture only", request=request)
        await asyncio.sleep(0)
        return httpx.Response(200, json=_payload())
    gate = JevPreferenceGate(_config(), accounting, transport=httpx.MockTransport(handler))
    async def run(session, message):
        with turn_scope(session_key=session, channel="cli", chat_id=session, root_span_id="root"):
            return await gate.assess(message, [], "")
    try:
        good, broken = await asyncio.gather(run("one", "Explain CSV"), run("two", "broken"))
        assert good.fast_pass and not broken.fast_pass
        assert len(accounting.records) == 2
        assert {record.session_key for record in accounting.records} == {"one", "two"}
        assert len({record.call_id for record in accounting.records}) == 2
        assert next(record for record in accounting.records if record.session_key == "two").estimated_cost_usd is None
    finally:
        await gate.aclose()


async def test_persistent_ledger_reconciles_decision_and_fallback(accounting, key):
    provider = CallEfficiencyProvider(_ClassifierProvider(), accounting)
    gate = JevPreferenceGate(_config(mode="shadow"), accounting, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_payload())))
    try:
        personalizer = Personalizer(SimpleNamespace(read_long_term=lambda: ""), provider, "main-test-model", gate=gate)
        await personalizer.classify("Explain CSV", allow_gate=True)
    finally:
        await gate.aclose()
    accounting.close()
    records = [json.loads(line) for path in accounting.ledger.telemetry_dir.glob("call-efficiency-2*.jsonl") for line in path.read_text().splitlines()]
    assert len(records) == 2
    assert {record["call_kind"] for record in records} == {"chat", "decision"}
    health = json.loads((accounting.ledger.telemetry_dir / "call-efficiency-ledger-health.json").read_text())
    assert health["accepted_records"] == health["persisted_records"] == 2
    assert health["status"] == "healthy"
