import json

from pico.cli import main
from pico.kernel_gate import REQUIRED_FAKE_TEST_FILES, evaluate_kernel_release_candidate
from pico.providers.clients import FakeModelClient
from pico.run_store import RunStore
from pico.runtime_events import RuntimeEventLedgerV2, runtime_event_v2_to_dict
from pico.runtime_projections import ProjectionManager


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _valid_live_acceptance():
    return {
        "artifact_type": "kernel-live-provider-acceptance",
        "schema_version": 1,
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
                "runtime_event_schema_version": 2,
                "finish_reason": "stop",
                "provider_status": "completed",
                "tool_result_count": 0,
                "final_answer": "pico kernel no-tool acceptance ok",
                "provider_metadata": {"finish_reason": "stop"},
            },
            {
                "name": "read-only-tool",
                "status": "passed",
                "run_id": "invocation_readonly",
                "runtime_status": "completed",
                "runtime_event_schema_version": 2,
                "finish_reason": "stop",
                "provider_status": "completed",
                "tool_result_count": 1,
                "tool_evidence": [
                    {
                        "name": "read_file",
                        "status": "ok",
                        "failure_classification": "",
                        "content": "# README.md\n   1: pico-kernel-readonly-acceptance-marker",
                    }
                ],
                "final_answer": "Observed pico-kernel-readonly-acceptance-marker.",
                "provider_metadata": {"finish_reason": "stop"},
            },
        ],
    }


def _live_scenario_events(scenario):
    run_id = scenario["run_id"]
    ledger = RuntimeEventLedgerV2(run_id)
    if scenario["name"] == "no-tool":
        ledger.append("invocation_start", status="started", actor="runtime_runner", payload={})
        ledger.append("user_input", status="completed", actor="runtime_runner", payload={"text": "no tool"})
        ledger.append(
            "model_output",
            status="completed",
            actor="model_adapter",
            payload={
                "model_call_id": "model_call_1",
                "text": "<final>pico kernel no-tool acceptance ok</final>",
                "provider": "AnthropicCompatibleModelClient:deepseek-v4-pro",
                "metadata": {"finish_reason": "stop", "provider_status": "completed"},
                "step": 1,
            },
            correlation_id="model_call_1",
        )
        ledger.append(
            "final_answer",
            status="completed",
            actor="agent_flow",
            payload={"text": "pico kernel no-tool acceptance ok"},
        )
        ledger.append(
            "terminal_status",
            status="completed",
            actor="runtime_runner",
            payload={"status": "completed"},
        )
        return ledger.events
    ledger.append("invocation_start", status="started", actor="runtime_runner", payload={})
    ledger.append("user_input", status="completed", actor="runtime_runner", payload={"text": "read README"})
    ledger.append(
        "model_output",
        status="completed",
        actor="model_adapter",
        payload={
            "model_call_id": "model_call_1",
            "text": '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
            "provider": "AnthropicCompatibleModelClient:deepseek-v4-pro",
            "metadata": {"finish_reason": "tool_use", "provider_status": "in_progress"},
            "step": 1,
        },
        correlation_id="model_call_1",
    )
    ledger.append(
        "tool_call_requested",
        status="started",
        actor="tool_runtime",
        payload={
            "tool_call_id": "tool_1",
            "name": "read_file",
            "args": {"path": "README.md"},
            "read_only": True,
        },
        correlation_id="tool_1",
    )
    ledger.append(
        "tool_permission_decision",
        status="ok",
        actor="permission_policy",
        payload={
            "tool_call_id": "tool_1",
            "name": "read_file",
            "decision": "allow",
            "reason": "kernel acceptance allows read-only tools",
            "policy_name": "allow_readonly",
            "failure_classification": "",
            "available": True,
        },
        correlation_id="tool_1",
    )
    ledger.append(
        "tool_result",
        status="ok",
        actor="tool_runtime",
        payload={
            "tool_call_id": "tool_1",
            "name": "read_file",
            "status": "ok",
            "content": "# README.md\n   1: pico-kernel-readonly-acceptance-marker",
            "failure_classification": "",
            "read_only": True,
        },
        correlation_id="tool_1",
    )
    ledger.append(
        "model_output",
        status="completed",
        actor="model_adapter",
        payload={
            "model_call_id": "model_call_2",
            "text": "<final>Observed pico-kernel-readonly-acceptance-marker.</final>",
            "provider": "AnthropicCompatibleModelClient:deepseek-v4-pro",
            "metadata": {"finish_reason": "stop", "provider_status": "completed"},
            "step": 2,
        },
        correlation_id="model_call_2",
    )
    ledger.append(
        "final_answer",
        status="completed",
        actor="agent_flow",
        payload={"text": "Observed pico-kernel-readonly-acceptance-marker."},
    )
    ledger.append(
        "terminal_status",
        status="completed",
        actor="runtime_runner",
        payload={"status": "completed"},
    )
    return ledger.events


def _attach_live_projection_artifacts(gate_dir, live_acceptance):
    artifacts_root = gate_dir / "live-artifacts"
    for scenario in live_acceptance["scenarios"]:
        artifacts = ProjectionManager(RunStore(artifacts_root / scenario["name"])).capture(
            _live_scenario_events(scenario),
            run_id=scenario["run_id"],
        )
        scenario["artifacts"] = {
            name: {
                "path": str(path.relative_to(gate_dir)),
                "exists": path.exists(),
            }
            for name, path in artifacts.artifact_paths.items()
        }
    return live_acceptance


def _valid_projection_inspection():
    runtime_events_path = "/fixture/runtime_events.jsonl"
    trace_path = "/fixture/trace.jsonl"
    report_path = "/fixture/report.json"
    ledger = [runtime_event_v2_to_dict(event) for event in _live_scenario_events({"name": "no-tool", "run_id": "run_fixture"})]
    return {
        "ledger": ledger,
        "session": {"run_id": "run_fixture", "status": "completed"},
        "trace": ledger,
        "report": {"run_id": "run_fixture", "status": "completed"},
        "export": {"run_id": "run_fixture", "status": "completed"},
        "artifacts": {
            "runtime_events": {"path": runtime_events_path, "exists": True},
            "trace": {"path": trace_path, "exists": True},
            "report": {"path": report_path, "exists": True},
        },
    }


def _write_release_candidate(root, *, live_acceptance=None):
    gate_dir = root / ".pico" / "kernel-gates"
    live_acceptance = _valid_live_acceptance() if live_acceptance is None else live_acceptance
    live_acceptance = _attach_live_projection_artifacts(gate_dir, live_acceptance)
    live_path = _write_json(
        gate_dir / "live-acceptance.json",
        live_acceptance,
    )
    runtime_events_path = root / ".pico" / "runs" / "run_fixture" / "runtime_events.jsonl"
    trace_path = root / ".pico" / "runs" / "run_fixture" / "trace.jsonl"
    report_path = root / ".pico" / "runs" / "run_fixture" / "report.json"
    runtime_events_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_events = [runtime_event_v2_to_dict(event) for event in _live_scenario_events({"name": "no-tool", "run_id": "run_fixture"})]
    runtime_events_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in fixture_events) + "\n",
        encoding="utf-8",
    )
    trace_path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in fixture_events) + "\n",
        encoding="utf-8",
    )
    report_path.write_text('{"status":"completed"}\n', encoding="utf-8")
    projection = _valid_projection_inspection()
    projection["artifacts"]["runtime_events"]["path"] = str(runtime_events_path)
    projection["artifacts"]["trace"]["path"] = str(trace_path)
    projection["artifacts"]["report"]["path"] = str(report_path)
    projection_path = _write_json(gate_dir / "projection-inspection.json", projection)
    for test_file in REQUIRED_FAKE_TEST_FILES:
        path = root / test_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture test file\n", encoding="utf-8")
    fake_provider_path = _write_json(
        gate_dir / "fake-provider-tests.json",
        {
            "artifact_type": "kernel-fake-provider-test-run",
            "schema_version": 1,
            "status": "passed",
            "exit_code": 0,
            "commit": "fixture",
            "command": (
                "uv run pytest tests/test_runtime_events.py tests/test_runtime_kernel.py "
                "tests/test_projection_manager.py tests/test_projection_acceptance.py "
                "tests/test_run_store.py tests/test_kernel_default_gate.py -q"
            ),
            "test_files": list(REQUIRED_FAKE_TEST_FILES),
            "output": {"summary": "fixture fake-provider test run passed"},
        },
    )

    return _write_json(
        root / ".pico" / "kernel-release-candidate.json",
        {
            "schema_version": 1,
            "runtime": "kernel",
            "status": "release_candidate",
            "gates": {
                "fake_provider_tests": {"artifact": str(fake_provider_path.relative_to(root))},
                "live_provider_acceptance": {"artifacts": [str(live_path.relative_to(root))]},
                "projection_inspection": {"artifact": str(projection_path.relative_to(root))},
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


def test_kernel_release_candidate_gate_rejects_missing_fake_test_file(tmp_path):
    manifest = _write_release_candidate(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    fake_path = tmp_path / payload["gates"]["fake_provider_tests"]["artifact"]
    fake_tests = json.loads(fake_path.read_text(encoding="utf-8"))
    fake_tests["test_files"].append("tests/missing_kernel_test.py")
    fake_path.write_text(json.dumps(fake_tests), encoding="utf-8")

    result = evaluate_kernel_release_candidate(manifest, workspace_root=tmp_path)

    assert result.passed is False
    assert any("tests/missing_kernel_test.py" in failure for failure in result.failures)


def test_default_runtime_without_prompt_keeps_legacy_repl_after_gate_passes(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    _write_release_candidate(tmp_path)
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(["<final>unused</final>"]),
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError()))

    status = main(["--cwd", str(tmp_path)])

    captured = capsys.readouterr()
    assert status == 0
    assert "local coding agent" in captured.out
    assert "kernel runtime currently supports one-shot prompts only" not in captured.err


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
