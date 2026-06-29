import json

from pico.cli import main
from pico.kernel_gate import evaluate_kernel_release_candidate
from pico.providers.clients import FakeModelClient


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _valid_live_acceptance():
    return {
        "status": "passed",
        "run_id": "acceptance_fixture",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "scenarios": [
            {
                "name": "no-tool",
                "status": "passed",
                "run_id": "invocation_no_tool",
                "runtime_status": "completed",
                "finish_reason": "stop",
                "provider_status": "completed",
                "tool_result_count": 0,
                "final_answer": "pico kernel no-tool acceptance ok",
            },
            {
                "name": "read-only-tool",
                "status": "passed",
                "run_id": "invocation_readonly",
                "runtime_status": "completed",
                "finish_reason": "stop",
                "provider_status": "completed",
                "tool_result_count": 1,
                "final_answer": "Observed pico-kernel-readonly-acceptance-marker.",
            },
        ],
    }


def _valid_projection_inspection():
    runtime_events_path = "/fixture/runtime_events.jsonl"
    trace_path = "/fixture/trace.jsonl"
    report_path = "/fixture/report.json"
    ledger = [
        {"type": "invocation_start", "payload": {"invocation_id": "run_fixture"}},
        {"type": "user_input", "payload": {"invocation_id": "run_fixture", "text": "hello"}},
        {"type": "model_output", "payload": {"invocation_id": "run_fixture", "text": "answer"}},
        {"type": "final_answer", "payload": {"invocation_id": "run_fixture", "text": "answer"}},
        {"type": "terminal_status", "payload": {"invocation_id": "run_fixture", "status": "completed"}},
    ]
    return {
        "ledger": ledger,
        "session": {"run_id": "run_fixture", "status": "completed"},
        "trace": [{"event": "invocation_start", "payload": {"invocation_id": "run_fixture"}}],
        "report": {"run_id": "run_fixture", "status": "completed"},
        "export": {"run_id": "run_fixture", "status": "completed"},
        "artifacts": {
            "runtime_events": {"path": runtime_events_path, "exists": True},
            "trace": {"path": trace_path, "exists": True},
            "report": {"path": report_path, "exists": True},
        },
    }


def _valid_headless_task_export():
    return {
        "artifact_type": "headless-task-run-export",
        "schema_version": 1,
        "task_run_id": "taskrun_fixture",
        "status": "pass",
        "failure_kind": "",
        "failure_category": "",
        "runtime": {
            "run_id": "run_fixture",
            "status": "completed",
            "event_count": 5,
            "event_type_counts": {
                "invocation_start": 1,
                "user_input": 1,
                "model_output": 1,
                "final_answer": 1,
                "terminal_status": 1,
            },
            "runtime_events_relpath": "workspace/.pico/runs/run_fixture/runtime_events.jsonl",
        },
        "verifier": {
            "exit_code": 0,
            "protected_boundary": True,
            "timed_out": False,
        },
        "boundaries": {
            "verifier_visible_to_runtime": False,
        },
        "policy": {
            "runtime": "kernel",
            "model_provider": "fake",
            "tool_policy": "headless_explicit_readonly_allowlist",
            "fail_closed": True,
        },
        "artifacts": {
            "task_run_export_relpath": "task_run_export.json",
        },
    }


def _write_release_candidate(root, *, live_acceptance=None):
    gate_dir = root / ".pico" / "kernel-gates"
    live_path = _write_json(
        gate_dir / "live-acceptance.json",
        _valid_live_acceptance() if live_acceptance is None else live_acceptance,
    )
    runtime_events_path = root / ".pico" / "runs" / "run_fixture" / "runtime_events.jsonl"
    trace_path = root / ".pico" / "runs" / "run_fixture" / "trace.jsonl"
    report_path = root / ".pico" / "runs" / "run_fixture" / "report.json"
    runtime_events_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_events_path.write_text('{"type":"terminal_status","payload":{"status":"completed"}}\n', encoding="utf-8")
    trace_path.write_text('{"event":"terminal_status","payload":{"status":"completed"}}\n', encoding="utf-8")
    report_path.write_text('{"status":"completed"}\n', encoding="utf-8")
    projection = _valid_projection_inspection()
    projection["artifacts"]["runtime_events"]["path"] = str(runtime_events_path)
    projection["artifacts"]["trace"]["path"] = str(trace_path)
    projection["artifacts"]["report"]["path"] = str(report_path)
    projection_path = _write_json(gate_dir / "projection-inspection.json", projection)
    headless_path = _write_json(gate_dir / "task_run_export.json", _valid_headless_task_export())
    headless_runtime_events_path = gate_dir / "workspace" / ".pico" / "runs" / "run_fixture" / "runtime_events.jsonl"
    headless_runtime_events_path.parent.mkdir(parents=True, exist_ok=True)
    headless_runtime_events_path.write_text('{"type":"terminal_status","payload":{"status":"completed"}}\n', encoding="utf-8")

    return _write_json(
        root / ".pico" / "kernel-release-candidate.json",
        {
            "schema_version": 1,
            "runtime": "kernel",
            "status": "release_candidate",
            "gates": {
                "fake_provider_tests": {
                    "status": "passed",
                    "command": (
                        "uv run pytest tests/test_runtime_kernel.py "
                        "tests/test_kernel_acceptance.py tests/test_headless_task.py -q"
                    ),
                    "test_files": [
                        "tests/test_runtime_kernel.py",
                        "tests/test_kernel_acceptance.py",
                        "tests/test_headless_task.py",
                    ],
                },
                "live_provider_acceptance": {"artifacts": [str(live_path.relative_to(root))]},
                "projection_inspection": {"artifact": str(projection_path.relative_to(root))},
                "headless_single_task": {"artifact": str(headless_path.relative_to(root))},
            },
        },
    )


def test_kernel_release_candidate_gate_accepts_documented_artifacts(tmp_path):
    manifest = _write_release_candidate(tmp_path)

    result = evaluate_kernel_release_candidate(manifest, workspace_root=tmp_path)

    assert result.passed is True
    assert result.failures == ()


def test_kernel_release_candidate_gate_requires_both_live_scenarios(tmp_path):
    live_acceptance = _valid_live_acceptance()
    live_acceptance["scenarios"] = live_acceptance["scenarios"][:1]
    manifest = _write_release_candidate(tmp_path, live_acceptance=live_acceptance)

    result = evaluate_kernel_release_candidate(manifest, workspace_root=tmp_path)

    assert result.passed is False
    assert any("read-only-tool" in failure for failure in result.failures)


def test_kernel_release_candidate_gate_rejects_missing_projection_artifacts(tmp_path):
    manifest = _write_release_candidate(tmp_path)
    projection_path = tmp_path / ".pico" / "kernel-gates" / "projection-inspection.json"
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    missing = tmp_path / ".pico" / "runs" / "run_fixture" / "runtime_events.jsonl"
    missing.unlink()
    projection["artifacts"]["runtime_events"]["exists"] = True
    projection_path.write_text(json.dumps(projection), encoding="utf-8")

    result = evaluate_kernel_release_candidate(manifest, workspace_root=tmp_path)

    assert result.passed is False
    assert any("runtime_events path must exist" in failure for failure in result.failures)


def test_kernel_release_candidate_gate_rejects_manifest_artifact_escape(tmp_path):
    manifest = _write_release_candidate(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["gates"]["live_provider_acceptance"] = {"artifact": "../live-acceptance.json"}
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_kernel_release_candidate(manifest, workspace_root=tmp_path)

    assert result.passed is False
    assert any("escapes workspace" in failure for failure in result.failures)


def test_default_runtime_uses_kernel_after_release_candidate_gate_passes(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    _write_release_candidate(tmp_path)
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(["Default kernel answer."]),
    )

    status = main(["--cwd", str(tmp_path), "hello"])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out.strip() == "Default kernel answer."
    assert "local coding agent" not in captured.out


def test_default_runtime_falls_back_to_legacy_when_gate_fails(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    live_acceptance = _valid_live_acceptance()
    live_acceptance["status"] = "failed"
    _write_release_candidate(tmp_path, live_acceptance=live_acceptance)
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(["<final>Legacy fallback answer.</final>"]),
    )

    status = main(["--cwd", str(tmp_path), "--approval", "auto", "hello"])

    captured = capsys.readouterr()
    assert status == 0
    assert "local coding agent" in captured.out
    assert "Legacy fallback answer." in captured.out
    assert "kernel default gate failed" in captured.err


def test_explicit_legacy_runtime_remains_available_after_gate_passes(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    _write_release_candidate(tmp_path)
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(["<final>Explicit legacy answer.</final>"]),
    )

    status = main(["--runtime", "legacy", "--cwd", str(tmp_path), "--approval", "auto", "hello"])

    captured = capsys.readouterr()
    assert status == 0
    assert "local coding agent" in captured.out
    assert "Explicit legacy answer." in captured.out
