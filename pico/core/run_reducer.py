"""Reducers for applying internal run-domain events to RunState."""

from __future__ import annotations

from .run_events import RunEvent


def reduce_run_state(state, event: RunEvent):
    event_type = str(event.type)
    payload = dict(event.payload or {})

    if event_type == "model_attempted":
        state.record_attempt()
    elif event_type == "tool_executed":
        state.record_tool(str(payload.get("name", "")))
    elif event_type == "stage_changed":
        state.stage = str(payload.get("stage", state.stage))
    elif event_type == "control_decision_recorded":
        state.control_decisions = list(state.control_decisions or [])
        state.control_decisions.append(dict(payload.get("decision", payload)))
    elif event_type == "runtime_reminder_emitted":
        state.runtime_reminders = list(state.runtime_reminders or [])
        state.runtime_reminders.append(dict(payload))
    elif event_type == "checkpoint_created":
        state.checkpoint_id = str(payload.get("checkpoint_id", state.checkpoint_id))
    elif event_type == "completion_assessed":
        state.completion_gate = dict(payload.get("assessment", state.completion_gate or {}) or {})
    elif event_type == "verification_recorded":
        state.verifications = list(state.verifications or [])
        state.verifications.append(dict(payload.get("verification", payload)))
    elif event_type == "run_finished":
        state.finish_success(str(payload.get("final_answer", state.final_answer)))
    elif event_type == "run_stopped":
        state.stop(str(payload.get("stop_reason", state.stop_reason or "run_stopped")), final_answer=str(payload.get("final_answer", "")))
    elif event_type == "model_error":
        state.stop_model_error(str(payload.get("final_answer", "")))
    elif event_type == "output_truncated":
        state.stop_output_truncated(str(payload.get("final_answer", "")))
    return state
