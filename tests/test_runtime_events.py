from types import SimpleNamespace

from pico.core.runtime_events import RuntimeEvents


def test_runtime_events_build_session_event_envelope():
    task_state = SimpleNamespace(run_id="run_1", task_id="task_1")

    event = RuntimeEvents.session_event(
        "user_message",
        {"content": "hi"},
        session_id="session_1",
        turn_id="turn_1",
        task_state=task_state,
        event_id="evt_fixed",
        created_at="2026-01-01T00:00:00",
    )

    assert event == {
        "schema_version": "session-event-v1",
        "event_id": "evt_fixed",
        "session_id": "session_1",
        "event": "user_message",
        "created_at": "2026-01-01T00:00:00",
        "turn_id": "turn_1",
        "run_id": "run_1",
        "task_id": "task_1",
        "content": "hi",
    }


def test_runtime_events_build_trace_event_envelope():
    task_state = SimpleNamespace(run_id="run_1", task_id="task_1")

    event = RuntimeEvents.trace_event(
        task_state,
        "model_requested",
        {"attempts": 1},
        sequence=3,
        turn_id="turn_1",
        span_id="span_fixed",
        created_at="2026-01-01T00:00:00",
    )

    assert event == {
        "schema_version": "trace-v2",
        "trace_id": "run_1",
        "span_id": "span_fixed",
        "parent_span_id": "",
        "turn_id": "turn_1",
        "phase": "model",
        "status": "started",
        "event": "model_requested",
        "sequence": 3,
        "created_at": "2026-01-01T00:00:00",
        "attempts": 1,
    }


def test_runtime_events_build_runtime_event_envelope():
    task_state = SimpleNamespace(run_id="run_1", task_id="task_1")

    event = RuntimeEvents.runtime_event(
        "tool_started",
        {"name": "read_file"},
        session_id="session_1",
        turn_id="turn_1",
        task_state=task_state,
        created_at="2026-01-01T00:00:00",
    )

    assert event == {
        "event": "tool_started",
        "created_at": "2026-01-01T00:00:00",
        "session_id": "session_1",
        "turn_id": "turn_1",
        "run_id": "run_1",
        "task_id": "task_1",
        "name": "read_file",
    }
