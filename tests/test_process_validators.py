import json

from pico.evaluation.validators import build_verifier


def _write_evidence(workspace, trace_events, session_events=None):
    run_dir = workspace / ".pico" / "runs" / "run_1"
    session_dir = workspace / ".pico" / "sessions"
    run_dir.mkdir(parents=True)
    session_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps({"status": "completed", "stop_reason": "final_answer_returned", "tool_steps": len(trace_events)}),
        encoding="utf-8",
    )
    (run_dir / "task_state.json").write_text(
        json.dumps({"status": "completed", "stop_reason": "final_answer_returned"}),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in trace_events),
        encoding="utf-8",
    )
    (session_dir / "session.json").write_text("{}", encoding="utf-8")
    (session_dir / "session.events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in (session_events or [])),
        encoding="utf-8",
    )
    return run_dir


def test_required_tool_sequence_and_must_run_tests_pass(tmp_path):
    run_dir = _write_evidence(
        tmp_path,
        [
            {"event": "tool_executed", "name": "read_file", "args": {"path": "app.py"}},
            {"event": "tool_executed", "name": "patch_file", "args": {"path": "app.py"}},
            {"event": "tool_executed", "name": "run_shell", "args": {"command": "python -m pytest tests -q"}},
            {"event": "run_finished", "status": "completed", "stop_reason": "final_answer_returned"},
        ],
    )
    (run_dir / "artifacts").mkdir()
    (run_dir / "artifacts" / "stdout.txt").write_text("ok\n", encoding="utf-8")

    checks = [
        build_verifier({"type": "required_tool_sequence", "sequence": ["read_file", "patch_file", "run_shell"]}).run(tmp_path),
        build_verifier({"type": "must_run_tests"}).run(tmp_path),
        build_verifier({"type": "must_read_before_write"}).run(tmp_path),
        build_verifier({"type": "required_trace_event", "event": "run_finished", "fields": {"status": "completed"}}).run(tmp_path),
        build_verifier({"type": "artifact_exists", "paths": ["artifacts/stdout.txt"]}).run(tmp_path),
    ]

    assert all(check.passed for check in checks)


def test_process_validators_report_specific_failures(tmp_path):
    _write_evidence(
        tmp_path,
        [
            {"event": "tool_executed", "name": "patch_file", "args": {"path": "app.py"}},
            {"event": "tool_executed", "name": "run_shell", "args": {"command": "python -m compileall ."}},
            {"event": "run_finished", "status": "completed", "stop_reason": "final_answer_returned"},
        ],
        session_events=[{"event": "skill_invoked", "name": "deploy"}],
    )

    assert build_verifier({"type": "required_tool_sequence", "sequence": ["read_file", "patch_file"]}).run(tmp_path).passed is False
    assert build_verifier({"type": "must_run_tests"}).run(tmp_path).failure_category == "test_not_run"
    assert build_verifier({"type": "must_read_before_write"}).run(tmp_path).failure_category == "tool_policy_violation"
    assert build_verifier({"type": "required_session_event", "event": "skill_invoked", "fields": {"name": "deploy"}}).run(tmp_path).passed is True
    assert build_verifier({"type": "required_session_event", "event": "memory_note_appended"}).run(tmp_path).passed is False


def test_artifact_exists_accepts_trace_artifact_references(tmp_path):
    run_dir = _write_evidence(
        tmp_path,
        [
            {
                "event": "tool_executed",
                "name": "run_shell",
                "full_output_artifact": "artifacts/full-output.txt",
            },
            {"event": "run_finished", "status": "completed", "stop_reason": "final_answer_returned"},
        ],
    )
    (run_dir / "artifacts").mkdir()
    (run_dir / "artifacts" / "full-output.txt").write_text("large output\n", encoding="utf-8")

    result = build_verifier({"type": "artifact_exists", "from_evidence": True}).run(tmp_path)

    assert result.passed is True
    assert result.details["evidence_artifacts"] == ["artifacts/full-output.txt"]


def test_artifact_exists_accepts_evidence_bundle_manifest(tmp_path):
    run_dir = _write_evidence(
        tmp_path,
        [{"event": "run_finished", "status": "completed", "stop_reason": "final_answer_returned"}],
    )
    (run_dir / "evidence_bundle_manifest.json").write_text(
        json.dumps({"files": ["report.json", "trace.jsonl"]}),
        encoding="utf-8",
    )

    result = build_verifier({"type": "artifact_exists", "paths": ["trace.jsonl"], "from_manifest": True}).run(tmp_path)

    assert result.passed is True
