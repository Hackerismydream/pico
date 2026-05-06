"""Runtime event envelope builders."""

import uuid
from datetime import datetime, timezone

TRACE_SCHEMA_VERSION = "trace-v2"
SESSION_EVENT_SCHEMA_VERSION = "session-event-v1"
TRACE_PHASE_STATUS = {
    "run_started": ("run", "started"),
    "prompt_built": ("context", "ok"),
    "checkpoint_created": ("checkpoint", "ok"),
    "runtime_identity_mismatch": ("session", "warning"),
    "model_requested": ("model", "started"),
    "model_error": ("model", "error"),
    "model_parsed": ("model", "ok"),
    "tool_executed": ("tool", "ok"),
    "task_list_updated": ("task", "ok"),
    "stage_changed": ("task", "ok"),
    "verification_recorded": ("verification", "ok"),
    "completion_assessed": ("completion", "ok"),
    "completion_gate_blocked": ("completion", "warning"),
    "runtime_reminder_emitted": ("runtime", "warning"),
    "truncation_recovered": ("model", "warning"),
    "model_error_recovered": ("model", "warning"),
    "history_compacted": ("context", "ok"),
    "run_finished": ("run", "finished"),
}


class RuntimeEvents:
    @staticmethod
    def session_event(
        event,
        payload=None,
        *,
        session_id,
        turn_id="",
        task_state=None,
        event_id=None,
        created_at=None,
    ):
        envelope = {
            "schema_version": SESSION_EVENT_SCHEMA_VERSION,
            "event_id": event_id or "evt_" + uuid.uuid4().hex[:12],
            "session_id": session_id,
            "event": event,
            "created_at": created_at or _now(),
        }
        if turn_id:
            envelope["turn_id"] = turn_id
        if task_state is not None:
            envelope["run_id"] = task_state.run_id
            envelope["task_id"] = task_state.task_id
        envelope.update(payload or {})
        return envelope

    @staticmethod
    def trace_event(
        task_state,
        event,
        payload=None,
        *,
        sequence,
        turn_id="",
        span_id=None,
        created_at=None,
    ):
        phase, status = TRACE_PHASE_STATUS.get(event, ("runtime", "ok"))
        envelope = dict(payload or {})
        envelope.setdefault("schema_version", TRACE_SCHEMA_VERSION)
        envelope.setdefault("trace_id", task_state.run_id)
        envelope.setdefault("span_id", span_id or "span_" + uuid.uuid4().hex[:12])
        envelope.setdefault("parent_span_id", "")
        envelope.setdefault("turn_id", turn_id or task_state.task_id)
        envelope.setdefault("phase", phase)
        envelope.setdefault("status", status)
        envelope["event"] = event
        envelope["sequence"] = sequence
        envelope["created_at"] = created_at or _now()
        return envelope

    @staticmethod
    def runtime_event(
        event,
        payload=None,
        *,
        session_id,
        turn_id="",
        task_state=None,
        created_at=None,
    ):
        envelope = {
            "event": event,
            "created_at": created_at or _now(),
            "session_id": session_id,
        }
        if turn_id:
            envelope["turn_id"] = turn_id
        if task_state is not None:
            envelope["run_id"] = task_state.run_id
            envelope["task_id"] = task_state.task_id
        envelope.update(payload or {})
        return envelope


def _now():
    return datetime.now(timezone.utc).isoformat()
