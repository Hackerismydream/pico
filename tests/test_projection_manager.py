import json

import pytest

import pico.runtime_projections as projections
from pico.run_store import RunStore
from pico.runtime_kernel import RuntimeEvent
from pico.runtime_projections import ProjectionCaptureError, ProjectionManager


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_projection_manager_captures_no_tool_final_answer_and_redacts(tmp_path, monkeypatch):
    secret = "sk-projection-secret-123"
    monkeypatch.setenv("CUSTOM_SECRET", secret)
    store = RunStore(tmp_path / ".pico" / "runs")
    events = [
        RuntimeEvent(type="invocation_start", payload={"invocation_id": "run_final"}),
        RuntimeEvent(type="user_input", payload={"invocation_id": "run_final", "text": f"Hide {secret}."}),
        RuntimeEvent(
            type="model_output",
            payload={
                "invocation_id": "run_final",
                "text": f"<final>The answer avoids {secret}.</final>",
                "provider": "FakeModelClient:fake",
                "metadata": {"finish_reason": "stop"},
                "step": 1,
            },
        ),
        RuntimeEvent(type="final_answer", payload={"invocation_id": "run_final", "text": f"Done {secret}."}),
        RuntimeEvent(type="terminal_status", payload={"invocation_id": "run_final", "status": "completed"}),
    ]

    artifacts = ProjectionManager(store, secret_env_names={"CUSTOM_SECRET"}).capture(events)

    assert artifacts.run_id == "run_final"
    assert artifacts.status == "completed"
    assert artifacts.session_projection["history"][-1]["content"] == "Done <redacted>."
    assert artifacts.export_projection["final_answer"] == "Done <redacted>."
    assert artifacts.diagnostics == ()
    for path in artifacts.artifact_paths.values():
        text = path.read_text(encoding="utf-8")
        assert secret not in text
    assert "<redacted>" in artifacts.manifest_path.read_text(encoding="utf-8")


def test_projection_manager_captures_read_only_tool_events(tmp_path):
    store = RunStore(tmp_path / ".pico" / "runs")
    events = [
        RuntimeEvent(type="invocation_start", payload={"invocation_id": "run_tool"}),
        RuntimeEvent(type="user_input", payload={"invocation_id": "run_tool", "text": "Read README."}),
        RuntimeEvent(
            type="tool_call_requested",
            payload={
                "invocation_id": "run_tool",
                "tool_call_id": "tool_1",
                "name": "read_file",
                "args": {"path": "README.md"},
                "read_only": True,
            },
        ),
        RuntimeEvent(
            type="tool_permission_decision",
            payload={
                "invocation_id": "run_tool",
                "tool_call_id": "tool_1",
                "name": "read_file",
                "decision": "allow",
                "reason": "read-only tools are allowed",
                "policy_name": "allow_readonly",
                "available": True,
            },
        ),
        RuntimeEvent(
            type="tool_result",
            payload={
                "invocation_id": "run_tool",
                "tool_call_id": "tool_1",
                "name": "read_file",
                "status": "ok",
                "content": "# README",
            },
        ),
        RuntimeEvent(type="final_answer", payload={"invocation_id": "run_tool", "text": "README."}),
        RuntimeEvent(type="terminal_status", payload={"invocation_id": "run_tool", "status": "completed"}),
    ]

    artifacts = ProjectionManager(store).capture(events)

    tool_call = artifacts.session_projection["tool_calls"][0]
    assert tool_call["read_only"] is True
    assert tool_call["permission"]["decision"] == "allow"
    assert tool_call["result"]["content"] == "# README"
    assert artifacts.export_projection["tool_calls"][0]["permission"]["reason"] == "read-only tools are allowed"


def test_projection_manager_manifest_contract(tmp_path):
    store = RunStore(tmp_path / ".pico" / "runs")
    events = [
        RuntimeEvent(type="invocation_start", payload={"invocation_id": "run_manifest"}),
        RuntimeEvent(type="final_answer", payload={"invocation_id": "run_manifest", "text": "Ok."}),
        RuntimeEvent(type="terminal_status", payload={"invocation_id": "run_manifest", "status": "completed"}),
    ]

    artifacts = ProjectionManager(store).capture(events)
    manifest = store.load_manifest("run_manifest")

    assert manifest["schema_version"] == 1
    assert manifest["run_id"] == "run_manifest"
    assert manifest["status"] == "completed"
    assert manifest["terminal_status"] == {"invocation_id": "run_manifest", "status": "completed"}
    assert manifest["artifacts"] == {
        "runtime_events": {"path": "runtime_events.jsonl"},
        "trace": {"path": "trace.jsonl"},
        "report": {"path": "report.json"},
        "manifest": {"path": "runtime_manifest.json"},
    }
    assert manifest["projections"]["session"]["status"] == "completed"
    assert manifest["projections"]["export"]["artifact_type"] == "kernel-runtime-export"
    assert manifest["diagnostics"] == []
    assert artifacts.manifest_path == store.manifest_path("run_manifest")
    assert _read_jsonl(artifacts.runtime_events_path)[0]["type"] == "invocation_start"


def test_projection_manager_redacts_manifest_terminal_status(tmp_path, monkeypatch):
    secret = "sk-terminal-secret-123"
    monkeypatch.setenv("TERMINAL_SECRET", secret)
    store = RunStore(tmp_path / ".pico" / "runs")
    events = [
        RuntimeEvent(type="invocation_start", payload={"invocation_id": "run_terminal_secret"}),
        RuntimeEvent(
            type="terminal_status",
            payload={
                "invocation_id": "run_terminal_secret",
                "status": "failed",
                "error_type": "provider_error",
                "error_message": f"provider returned {secret}",
            },
        ),
    ]

    artifacts = ProjectionManager(store, secret_env_names={"TERMINAL_SECRET"}).capture(events)
    manifest = store.load_manifest("run_terminal_secret")

    assert artifacts.status == "failed"
    assert artifacts.terminal_status["error_message"] == "provider returned <redacted>"
    assert manifest["terminal_status"]["error_message"] == "provider returned <redacted>"
    assert secret not in json.dumps(artifacts.terminal_status, sort_keys=True)
    assert secret not in artifacts.manifest_path.read_text(encoding="utf-8")


def test_projection_manager_records_diagnostics_for_missing_terminal_and_bad_events(tmp_path):
    store = RunStore(tmp_path / ".pico" / "runs")
    events = [
        RuntimeEvent(type="invocation_start", payload={"invocation_id": "run_diagnostics"}),
        {"type": "tool_result", "payload": "not-an-object", "created_at": "2026-06-30T00:00:00+00:00"},
        {"payload": {"invocation_id": "run_diagnostics"}},
    ]

    artifacts = ProjectionManager(store).capture(events)
    manifest = store.load_manifest("run_diagnostics")

    assert artifacts.status == "unknown"
    assert manifest["status"] == "unknown"
    assert manifest["terminal_status"] == {}
    assert [item["code"] for item in manifest["diagnostics"]] == [
        "unsupported_event_shape",
        "unsupported_event_shape",
        "missing_terminal_status",
    ]
    assert _read_jsonl(artifacts.runtime_events_path) == [
        {
            "created_at": events[0].created_at,
            "payload": {"invocation_id": "run_diagnostics"},
            "type": "invocation_start",
        }
    ]


def test_projection_manager_capture_failure_does_not_return_artifact_set(tmp_path, monkeypatch):
    store = RunStore(tmp_path / ".pico" / "runs")
    events = [
        RuntimeEvent(type="invocation_start", payload={"invocation_id": "run_failure"}),
        RuntimeEvent(type="terminal_status", payload={"invocation_id": "run_failure", "status": "completed"}),
    ]

    def fail_redaction(value, **kwargs):
        raise RuntimeError("redaction unavailable")

    monkeypatch.setattr(projections, "redact_artifact", fail_redaction)

    with pytest.raises(ProjectionCaptureError, match="redaction failed"):
        ProjectionManager(store).capture(events)

    assert not store.runtime_events_path("run_failure").exists()
    assert not store.manifest_path("run_failure").exists()


def test_projection_manager_capture_storage_failure_is_closed(tmp_path, monkeypatch):
    store = RunStore(tmp_path / ".pico" / "runs")
    events = [
        RuntimeEvent(type="invocation_start", payload={"invocation_id": "run_storage_failure"}),
        RuntimeEvent(
            type="terminal_status",
            payload={"invocation_id": "run_storage_failure", "status": "completed"},
        ),
    ]

    def fail_report(run_id, report):
        raise OSError("disk full")

    monkeypatch.setattr(store, "write_report", fail_report)

    with pytest.raises(ProjectionCaptureError, match="storage failed"):
        ProjectionManager(store).capture(events)

    assert not store.report_path("run_storage_failure").exists()
    assert not store.manifest_path("run_storage_failure").exists()
