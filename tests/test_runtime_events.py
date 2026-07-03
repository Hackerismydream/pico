import json

import pytest

from pico.runtime_events import (
    RUNTIME_EVENT_SCHEMA_VERSION,
    RuntimeEvent,
    RuntimeEventLedgerV2,
    RuntimeEventValidationError,
    RuntimeEventV2,
    normalize_runtime_event,
    normalize_runtime_events,
    runtime_event_from_dict,
    runtime_event_to_dict,
    runtime_event_v2_from_dict,
    runtime_event_v2_to_dict,
)


def test_runtime_event_v2_ledger_assigns_sequence_and_round_trips():
    ledger = RuntimeEventLedgerV2("invocation_test")

    first = ledger.append(
        "invocation_start",
        status="started",
        actor="runtime_runner",
        payload={"workspace_root": "/tmp/workspace"},
    )
    second = ledger.append(
        "model_output",
        status="completed",
        actor="model_adapter",
        payload={"model_call_id": "model_call_1", "text": "<final>ok</final>"},
        correlation_id="model_call_1",
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert first.invocation_id == "invocation_test"
    assert second.event_id.startswith("evt_")
    assert second.correlation_id == "model_call_1"

    payload = runtime_event_v2_to_dict(second)
    assert payload["schema_version"] == RUNTIME_EVENT_SCHEMA_VERSION
    assert payload["kind"] == "model_output"
    assert payload["sequence"] == 2
    assert payload["payload"]["text"] == "<final>ok</final>"
    assert runtime_event_v2_from_dict(payload) == second


def test_runtime_event_codec_handles_v2_and_legacy_shapes():
    ledger = RuntimeEventLedgerV2("invocation_codec")
    v2 = ledger.append(
        "terminal_status",
        status="completed",
        actor="runtime_runner",
        payload={"status": "completed"},
    )
    legacy = RuntimeEvent(
        type="terminal_status",
        payload={"invocation_id": "invocation_legacy", "status": "completed"},
        created_at="2026-06-30T00:00:00+00:00",
    )

    v2_payload = runtime_event_to_dict(v2)
    legacy_payload = runtime_event_to_dict(legacy)

    assert v2_payload["schema_version"] == RUNTIME_EVENT_SCHEMA_VERSION
    assert v2_payload["kind"] == "terminal_status"
    assert runtime_event_from_dict(v2_payload) == v2
    assert legacy_payload == {
        "type": "terminal_status",
        "created_at": "2026-06-30T00:00:00+00:00",
        "payload": {"invocation_id": "invocation_legacy", "status": "completed"},
    }
    assert runtime_event_from_dict(legacy_payload) == legacy


def test_runtime_event_v2_rejects_invalid_new_writes():
    with pytest.raises(RuntimeEventValidationError, match="unknown_kind"):
        RuntimeEventLedgerV2("invocation_test").append(
            "desktop_timeline_item",
            status="completed",
            actor="runtime_runner",
            payload={},
        )

    with pytest.raises(RuntimeEventValidationError, match="unknown_status"):
        RuntimeEventLedgerV2("invocation_test").append(
            "model_output",
            status="success",
            actor="model_adapter",
            payload={},
        )

    with pytest.raises(RuntimeEventValidationError, match="unknown_actor"):
        RuntimeEventLedgerV2("invocation_test").append(
            "model_output",
            status="completed",
            actor="kernel",
            payload={},
        )


def test_runtime_event_v2_terminal_status_is_close_event_contract():
    event = RuntimeEventLedgerV2("invocation_test").append(
        "terminal_status",
        status="completed",
        actor="runtime_runner",
        payload={"reason": "final_answer"},
    )

    assert event.kind == "terminal_status"
    assert event.status == "completed"

    with pytest.raises(RuntimeEventValidationError, match="invalid_terminal_status"):
        RuntimeEventLedgerV2("invocation_test").append(
            "terminal_status",
            status="ok",
            actor="runtime_runner",
            payload={},
        )


def test_normalize_runtime_event_preserves_v2_and_reports_diagnostics_for_bad_envelope():
    event = RuntimeEventV2(
        schema_version=2,
        event_id="evt_1",
        invocation_id="invocation_test",
        sequence=1,
        kind="model_output",
        status="success",
        actor="model_adapter",
        created_at="2026-06-30T00:00:00+00:00",
        payload={"text": "ok"},
    )

    normalized, diagnostics = normalize_runtime_event(event)

    assert normalized == event
    assert [item["code"] for item in diagnostics] == ["unknown_status"]


def test_normalize_legacy_event_to_v2_read_shape_with_diagnostics():
    legacy = {
        "type": "tool_result",
        "created_at": "2026-06-30T00:00:00+00:00",
        "payload": {
            "invocation_id": "invocation_legacy",
            "tool_call_id": "tool_1",
            "name": "read_file",
            "status": "ok",
            "content": "# README",
        },
    }

    normalized, diagnostics = normalize_runtime_event(legacy, event_index=4)

    assert normalized is not None
    assert normalized.schema_version == 2
    assert normalized.event_id == "legacy_evt_5"
    assert normalized.invocation_id == "invocation_legacy"
    assert normalized.sequence == 5
    assert normalized.kind == "tool_result"
    assert normalized.status == "ok"
    assert normalized.actor == "tool_runtime"
    assert normalized.correlation_id == "tool_1"
    assert normalized.payload["content"] == "# README"
    assert [item["code"] for item in diagnostics] == ["legacy_event_shape"]


def test_normalize_legacy_events_skips_unsupported_shapes_and_does_not_rewrite_input():
    legacy = {
        "type": "user_input",
        "payload": {"invocation_id": "invocation_legacy", "text": "hello"},
    }
    bad = {"type": "tool_result", "payload": "not-an-object"}
    original = json.loads(json.dumps([legacy, bad], sort_keys=True))

    normalized, diagnostics = normalize_runtime_events([legacy, bad])

    assert [event.kind for event in normalized] == ["user_input"]
    assert [item["code"] for item in diagnostics] == [
        "legacy_event_shape",
        "incomplete_event_shape",
        "missing_created_at",
        "unsupported_event_shape",
    ]
    assert [legacy, bad] == original
