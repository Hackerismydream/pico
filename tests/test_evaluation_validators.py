import json

from pico.evaluation.validators import (
    CommandVerifier,
    EvidenceVerifier,
    ForbiddenPathVerifier,
    SecretRedactionVerifier,
    StopReasonVerifier,
    evaluate_task,
)


def test_command_forbidden_path_secret_and_evidence_verifiers(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("hello\n", encoding="utf-8")
    run_dir = workspace / ".pico" / "runs" / "run_1"
    session_dir = workspace / ".pico" / "sessions"
    run_dir.mkdir(parents=True)
    session_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "stop_reason": "final_answer_returned",
                "tool_steps": 1,
                "tool_name_counts": {"run_shell": 1},
                "tool_status_counts": {"success": 1},
                "security_event_counts": {},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "task_state.json").write_text(
        json.dumps({"status": "completed", "stop_reason": "final_answer_returned"}),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        json.dumps({"event": "tool_executed", "name": "run_shell", "tool_status": "success"}) + "\n"
        + json.dumps({"event": "run_finished", "status": "completed", "stop_reason": "final_answer_returned"}) + "\n",
        encoding="utf-8",
    )
    (session_dir / "session.json").write_text("{}", encoding="utf-8")
    (session_dir / "session.events.jsonl").write_text("", encoding="utf-8")

    checks = [
        CommandVerifier("python -c \"import pathlib; assert pathlib.Path('README.md').exists()\"").run(workspace),
        ForbiddenPathVerifier([".env"]).run(workspace),
        SecretRedactionVerifier(["sk-live-secret"]).run(workspace),
        EvidenceVerifier().run(workspace),
    ]

    assert all(check.passed for check in checks)


def test_evaluate_task_uses_strict_pass_and_failure_category(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("TOKEN=1\n", encoding="utf-8")

    result = evaluate_task(
        "core_001",
        [
            ForbiddenPathVerifier([".env"]).run(workspace),
            CommandVerifier("python -c \"raise SystemExit(0)\"").run(workspace),
        ],
    )

    assert result.task_id == "core_001"
    assert result.strict_pass is False
    assert result.failure_category == "forbidden_path_modified"
    assert result.score == 0.5


def test_stop_reason_verifier_classifies_model_error_before_public_test_failure(tmp_path):
    workspace = tmp_path / "workspace"
    run_dir = workspace / ".pico" / "runs" / "run_1"
    session_dir = workspace / ".pico" / "sessions"
    run_dir.mkdir(parents=True)
    session_dir.mkdir(parents=True)
    (run_dir / "report.json").write_text(
        json.dumps({"status": "failed", "stop_reason": "model_error", "tool_steps": 0}),
        encoding="utf-8",
    )
    (run_dir / "task_state.json").write_text(
        json.dumps({"status": "failed", "stop_reason": "model_error"}),
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        json.dumps({"event": "run_finished", "status": "failed", "stop_reason": "model_error"}) + "\n",
        encoding="utf-8",
    )
    (session_dir / "session.json").write_text("{}", encoding="utf-8")
    (session_dir / "session.events.jsonl").write_text("", encoding="utf-8")

    result = evaluate_task(
        "core_001",
        [
            StopReasonVerifier().run(workspace),
            CommandVerifier("python -c \"raise SystemExit(1)\"", name="public_test").run(workspace),
        ],
    )

    assert result.failure_category == "model_error"
