"""Read-model projections derived from kernel runtime events."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .security import redact_artifact


RUNTIME_ARTIFACT_MANIFEST_SCHEMA_VERSION = 1


class ProjectionCaptureError(RuntimeError):
    """Raised when runtime artifacts cannot be captured safely."""


@dataclass(frozen=True)
class RuntimeArtifactSet:
    run_id: str
    status: str
    terminal_status: dict
    runtime_events_path: Path
    trace_path: Path
    report_path: Path
    manifest_path: Path
    session_projection: dict
    export_projection: dict
    diagnostics: tuple

    @property
    def artifact_paths(self):
        return {
            "runtime_events": self.runtime_events_path,
            "trace": self.trace_path,
            "report": self.report_path,
            "manifest": self.manifest_path,
        }


@dataclass(frozen=True)
class _ProjectionRuntimeEvent:
    type: str
    payload: dict
    created_at: str = ""


class ProjectionManager:
    def __init__(self, store, *, secret_env_names=None):
        self.store = store
        self.secret_env_names = set(secret_env_names or ())

    def capture(self, events, *, run_id=None):
        normalized_events, diagnostics = _normalize_events(events)
        run_id = str(run_id or project_run_id(normalized_events))
        if not run_id:
            raise ProjectionCaptureError("cannot capture runtime artifacts without a run id")

        terminal = _last_event(normalized_events, "terminal_status")
        terminal_status = {} if terminal is None else dict(terminal.payload)
        status = "unknown" if terminal is None else str(terminal_status.get("status") or "unknown")
        if terminal is None:
            diagnostics.append(
                _diagnostic(
                    "missing_terminal_status",
                    "runtime event history has no terminal_status event; status projected as unknown",
                )
            )
        elif "status" not in terminal_status:
            diagnostics.append(
                _diagnostic(
                    "missing_terminal_status_value",
                    "terminal_status event has no status field; status projected as unknown",
                )
            )

        try:
            runtime_event_dicts = [
                redact_artifact(_event_to_dict(event), secret_env_names=self.secret_env_names)
                for event in normalized_events
            ]
            trace = redact_artifact(project_trace(normalized_events), secret_env_names=self.secret_env_names)
            report = redact_artifact(project_report(normalized_events), secret_env_names=self.secret_env_names)
            session = redact_artifact(project_session(normalized_events), secret_env_names=self.secret_env_names)
            export = redact_artifact(project_export(normalized_events), secret_env_names=self.secret_env_names)
        except Exception as exc:
            raise ProjectionCaptureError(f"redaction failed while capturing runtime artifacts: {exc}") from exc

        try:
            runtime_events_path = self.store.write_runtime_event_dicts(run_id, runtime_event_dicts)
            trace_path = self.store.write_trace(run_id, trace)
            report_path = self.store.write_report(run_id, report)
            manifest_path = self.store.manifest_path(run_id)
            manifest = {
                "schema_version": RUNTIME_ARTIFACT_MANIFEST_SCHEMA_VERSION,
                "run_id": run_id,
                "status": status,
                "terminal_status": terminal_status,
                "artifacts": {
                    "runtime_events": {"path": _store_relative_path(self.store, run_id, runtime_events_path)},
                    "trace": {"path": _store_relative_path(self.store, run_id, trace_path)},
                    "report": {"path": _store_relative_path(self.store, run_id, report_path)},
                    "manifest": {"path": _store_relative_path(self.store, run_id, manifest_path)},
                },
                "projections": {
                    "session": session,
                    "export": export,
                },
                "diagnostics": diagnostics,
            }
            manifest_path = self.store.write_manifest(run_id, manifest)
        except Exception as exc:
            raise ProjectionCaptureError(f"storage failed while capturing runtime artifacts: {exc}") from exc

        return RuntimeArtifactSet(
            run_id=run_id,
            status=status,
            terminal_status=terminal_status,
            runtime_events_path=Path(runtime_events_path),
            trace_path=Path(trace_path),
            report_path=Path(report_path),
            manifest_path=Path(manifest_path),
            session_projection=session,
            export_projection=export,
            diagnostics=tuple(diagnostics),
        )


def _normalize_events(events):
    normalized = []
    diagnostics = []
    for index, event in enumerate(events or ()):
        event_type = _event_field(event, "type")
        payload = _event_field(event, "payload")
        created_at = _event_field(event, "created_at", "")
        if not event_type:
            diagnostics.append(
                _diagnostic(
                    "unsupported_event_shape",
                    "runtime event is missing a type and was skipped",
                    event_index=index,
                )
            )
            continue
        if not isinstance(payload, Mapping):
            diagnostics.append(
                _diagnostic(
                    "unsupported_event_shape",
                    "runtime event payload is not an object and was skipped",
                    event_index=index,
                    event_type=str(event_type),
                )
            )
            continue
        if not created_at:
            diagnostics.append(
                _diagnostic(
                    "incomplete_event_shape",
                    "runtime event has no created_at timestamp",
                    event_index=index,
                    event_type=str(event_type),
                )
            )
        normalized.append(
            _ProjectionRuntimeEvent(
                type=str(event_type),
                payload=dict(payload),
                created_at=str(created_at or ""),
            )
        )
    return normalized, diagnostics


def _event_field(event, name, default=None):
    if isinstance(event, Mapping):
        return event.get(name, default)
    return getattr(event, name, default)


def _event_to_dict(event):
    return {
        "type": event.type,
        "created_at": event.created_at,
        "payload": dict(event.payload),
    }


def _diagnostic(code, message, **details):
    diagnostic = {
        "code": code,
        "severity": "warning",
        "message": message,
    }
    diagnostic.update(details)
    return diagnostic


def _store_relative_path(store, run_id, path):
    path = Path(path)
    try:
        return str(path.relative_to(store.run_dir(run_id)))
    except ValueError:
        return str(path)


def _last_event(events, event_type):
    for event in reversed(events):
        if event.type == event_type:
            return event
    return None


def project_run_id(events):
    for event in events:
        invocation_id = event.payload.get("invocation_id")
        if invocation_id:
            return str(invocation_id)
    return ""


def project_final_answer(events):
    terminal = _last_event(events, "terminal_status")
    if terminal is None or terminal.payload.get("status") != "completed":
        return ""
    final = _last_event(events, "final_answer")
    if final is not None:
        return str(final.payload.get("text", ""))
    output = _last_event(events, "model_output")
    if output is None:
        return ""
    return str(output.payload.get("text", ""))


def project_cli_runtime_events(events):
    lines = []
    for event in events:
        if event.type == "tool_call_requested":
            lines.append(f"tool {event.payload.get('name')} requested")
        elif event.type == "tool_permission_decision":
            name = event.payload.get("name", "")
            decision = event.payload.get("decision", "")
            reason = event.payload.get("reason", "")
            lines.append(f"tool {name} permission {decision}: {reason}")
        elif event.type == "tool_result":
            status = event.payload.get("status", "")
            name = event.payload.get("name", "")
            failure = event.payload.get("failure_classification", "")
            suffix = f" ({failure})" if failure else ""
            lines.append(f"tool {name} {status}{suffix}")
    final_answer = project_final_answer(events)
    if final_answer:
        lines.append(f"final {final_answer}")
    return "\n".join(lines)


def project_trace(events):
    return [
        {
            "event": event.type,
            "created_at": event.created_at,
            "payload": dict(event.payload),
        }
        for event in events
    ]


def project_report(events):
    terminal = _last_event(events, "terminal_status")
    tool_results = [
        {
            "name": event.payload.get("name", ""),
            "status": event.payload.get("status", ""),
            "failure_classification": event.payload.get("failure_classification", ""),
            "content": event.payload.get("content", ""),
        }
        for event in events
        if event.type == "tool_result"
    ]
    provider_calls = [
        {
            "provider": event.payload.get("provider", ""),
            "metadata": dict(event.payload.get("metadata", {}) or {}),
            "step": event.payload.get("step", ""),
        }
        for event in events
        if event.type == "model_output"
    ]
    permission_decisions = [
        {
            "tool_call_id": event.payload.get("tool_call_id", ""),
            "name": event.payload.get("name", ""),
            "decision": event.payload.get("decision", ""),
            "reason": event.payload.get("reason", ""),
            "policy_name": event.payload.get("policy_name", ""),
            "failure_classification": event.payload.get("failure_classification", ""),
        }
        for event in events
        if event.type == "tool_permission_decision"
    ]
    return {
        "run_id": project_run_id(events),
        "status": "unknown" if terminal is None else str(terminal.payload.get("status", "unknown")),
        "final_answer": project_final_answer(events),
        "tool_calls": tool_results,
        "permission_decisions": permission_decisions,
        "provider_calls": provider_calls,
        "terminal_status": {} if terminal is None else dict(terminal.payload),
    }


def project_session(events):
    history = []
    tool_calls = _project_tool_calls(events)
    for event in events:
        if event.type == "user_input":
            history.append({"role": "user", "content": str(event.payload.get("text", ""))})
        elif event.type == "model_output":
            history.append(
                {
                    "role": "assistant",
                    "content": str(event.payload.get("text", "")),
                    "provider": str(event.payload.get("provider", "")),
                    "metadata": dict(event.payload.get("metadata", {}) or {}),
                }
            )
        elif event.type == "tool_result":
            history.append(
                {
                    "role": "tool",
                    "name": str(event.payload.get("name", "")),
                    "tool_call_id": str(event.payload.get("tool_call_id", "")),
                    "status": str(event.payload.get("status", "")),
                    "content": str(event.payload.get("content", "")),
                    "failure_classification": str(event.payload.get("failure_classification", "")),
                }
            )
        elif event.type == "final_answer":
            history.append({"role": "assistant", "content": str(event.payload.get("text", "")), "final": True})
    terminal = _last_event(events, "terminal_status")
    return {
        "projection": "session",
        "run_id": project_run_id(events),
        "status": "unknown" if terminal is None else str(terminal.payload.get("status", "unknown")),
        "history": history,
        "tool_calls": tool_calls,
        "terminal_status": {} if terminal is None else dict(terminal.payload),
    }


def project_export(events):
    terminal = _last_event(events, "terminal_status")
    provider_calls = [
        {
            "provider": event.payload.get("provider", ""),
            "metadata": dict(event.payload.get("metadata", {}) or {}),
            "step": event.payload.get("step", ""),
        }
        for event in events
        if event.type == "model_output"
    ]
    return {
        "artifact_type": "kernel-runtime-export",
        "run_id": project_run_id(events),
        "status": "unknown" if terminal is None else str(terminal.payload.get("status", "unknown")),
        "final_answer": project_final_answer(events),
        "tool_calls": _project_tool_calls(events),
        "provider_calls": provider_calls,
        "terminal_status": {} if terminal is None else dict(terminal.payload),
    }


def _project_tool_calls(events):
    calls = []
    by_id = {}
    for event in events:
        if event.type != "tool_call_requested":
            continue
        tool_call_id = str(event.payload.get("tool_call_id", ""))
        item = {
            "tool_call_id": tool_call_id,
            "name": str(event.payload.get("name", "")),
            "args": dict(event.payload.get("args", {}) or {}),
            "read_only": bool(event.payload.get("read_only", False)),
            "permission": {},
            "result": {},
        }
        calls.append(item)
        by_id[tool_call_id] = item
    for event in events:
        tool_call_id = str(event.payload.get("tool_call_id", ""))
        if tool_call_id not in by_id:
            continue
        if event.type == "tool_permission_decision":
            by_id[tool_call_id]["permission"] = {
                "decision": str(event.payload.get("decision", "")),
                "reason": str(event.payload.get("reason", "")),
                "policy_name": str(event.payload.get("policy_name", "")),
                "failure_classification": str(event.payload.get("failure_classification", "")),
                "available": event.payload.get("available", ""),
            }
        elif event.type == "tool_result":
            by_id[tool_call_id]["result"] = {
                "status": str(event.payload.get("status", "")),
                "content": str(event.payload.get("content", "")),
                "error_message": str(event.payload.get("error_message", "")),
                "failure_classification": str(event.payload.get("failure_classification", "")),
            }
    return calls


def project_terminal_error(events):
    terminal = _last_event(events, "terminal_status")
    if terminal is None:
        return "runtime_error: missing terminal status"
    error_type = str(terminal.payload.get("error_type") or "runtime_error")
    message = str(terminal.payload.get("error_message") or "runtime failed")
    return f"{error_type}: {message}"
