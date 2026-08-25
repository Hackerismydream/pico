from __future__ import annotations

import subprocess
from pathlib import Path

from pico.agent.tools.base import ToolResult
from pico.agent.tools.execution import ToolEffect, ToolExecution, ToolExecutionContext, ToolInvocation
from pico.agent.turn_evidence import TurnEvidenceLog, repository_revision, verification_name


def _execution(
    *,
    name: str,
    call_id: str,
    arguments: dict,
    failed: bool = False,
    receipt: dict | None = None,
) -> ToolExecution:
    return ToolExecution(
        invocation=ToolInvocation(
            name=name,
            arguments=arguments,
            context=ToolExecutionContext(call_id=call_id, session_key="session"),
        ),
        result=ToolResult("observed", failed=failed, receipt=receipt),
        duration_ms=12.6,
    )


def test_system_receipts_build_closed_turn_feedback(tmp_path: Path) -> None:
    log = TurnEvidenceLog(
        workspace=tmp_path,
        session_id="session-1",
        turn_id="turn-1",
        trace_id="trace-1",
        injected_skill_ids=["myna/skill-b", "myna/skill-a"],
        referenced_skill_ids=["local/reference"],
    )
    log.observe(
        _execution(
            name="exec",
            call_id="call-check",
            arguments={"command": "uv run pytest -q"},
            receipt={"command": "uv run pytest -q", "exit_code": 0},
        ),
        effect=ToolEffect.EXECUTE,
    )
    log.observe(
        _execution(name="write_file", call_id="call-write", arguments={"path": "src/widget.py", "content": "x"}),
        effect=ToolEffect.WRITE,
    )

    feedback = log.feedback(terminal_state="completed", delivery_state="delivered", edited_files=["src/widget.py"])

    assert set(feedback) == {
        "schema",
        "base_revision",
        "session_id",
        "turn_id",
        "trace_id",
        "terminal_state",
        "delivery_state",
        "tool_receipts",
        "command_receipts",
        "file_changes",
        "verifications",
        "injected_skill_ids",
        "referenced_skill_ids",
    }
    assert feedback["command_receipts"] == [{"call_id": "call-check", "command": "uv run pytest -q", "exit_code": 0}]
    assert feedback["verifications"] == [{"check_name": "pytest", "outcome": "success", "call_id": "call-check"}]
    assert feedback["file_changes"] == [{"path": "src/widget.py", "change_kind": "unknown", "destination_path": None}]
    assert feedback["injected_skill_ids"] == ["myna/skill-a", "myna/skill-b"]


def test_failed_check_and_non_check_do_not_invent_success(tmp_path: Path) -> None:
    log = TurnEvidenceLog(
        workspace=tmp_path,
        session_id="session-1",
        turn_id="turn-1",
        trace_id="trace-1",
        injected_skill_ids=[],
        referenced_skill_ids=[],
    )
    log.observe(
        _execution(
            name="exec",
            call_id="failed",
            arguments={"command": "make check"},
            failed=True,
            receipt={"command": "make check", "exit_code": 2},
        ),
        effect=ToolEffect.EXECUTE,
    )
    log.observe(
        _execution(
            name="exec",
            call_id="echo",
            arguments={"command": "echo ok"},
            receipt={"command": "echo ok", "exit_code": 0},
        ),
        effect=ToolEffect.EXECUTE,
    )

    feedback = log.feedback(terminal_state="completed", delivery_state="unknown", edited_files=[])

    assert feedback["verifications"] == [{"check_name": "make", "outcome": "failure", "call_id": "failed"}]
    assert verification_name("echo tests passed") is None


def test_repository_revision_is_full_git_head_or_unknown(tmp_path: Path) -> None:
    assert repository_revision(tmp_path) is None
    subprocess.run(("git", "init", "-q", str(tmp_path)), check=True)
    (tmp_path / "file.txt").write_text("content")
    subprocess.run(("git", "-C", str(tmp_path), "add", "file.txt"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Pico Test",
            "-c",
            "user.email=pico@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ),
        check=True,
    )

    revision = repository_revision(tmp_path)

    assert revision is not None
    assert len(revision) == 40
