from types import SimpleNamespace

from pico.core.tool_runner import ToolExecutionContext, ToolPreflightResult, ToolRunner
from pico.tools.spec import Effect, ToolPolicy


def test_tool_runner_returns_content_and_metadata_without_trace_side_effects(tmp_path):
    context = ToolExecutionContext(
        tools={
            "echo": {
                "schema": {},
                "risky": False,
                "read_only": True,
                "description": "Echo.",
                "run": lambda args: "ok",
                "policy": {"max_result_chars": 100},
            }
        },
        allowed_tools=None,
        workspace=SimpleNamespace(fingerprint=lambda: "fp"),
        capture_workspace_snapshot=lambda: {},
    )

    result = ToolRunner(context).run("echo", {})

    assert result.content == "ok"
    assert result.metadata["tool_status"] == "ok"
    assert result.metadata["read_only"] is True
    assert result.effects == {Effect.WORKSPACE_READ}
    assert result.metadata["effective_effects"] == ["workspace_read"]


def test_tool_runner_context_no_longer_owns_runtime_side_effect_callbacks():
    fields = set(ToolExecutionContext.__dataclass_fields__)

    assert "emit_trace" not in fields
    assert "update_memory_after_tool" not in fields
    assert "update_tool_policy_after_tool" not in fields
    assert "record_process_note_for_tool" not in fields
    assert "approve" not in fields
    assert "changed_path_read_stall" not in fields
    assert "repeated_tool_call" not in fields
    assert "consecutive_read_only_tool_count" not in fields


def test_tool_runner_reports_unknown_and_not_allowed_tools():
    context = ToolExecutionContext(tools={}, allowed_tools=("read_file",))

    result = ToolRunner(context).run("run_shell", {"command": "echo nope"})

    assert "not allowed" in result.content
    assert result.metadata["tool_status"] == "rejected"
    assert result.metadata["tool_error_code"] == "tool_not_allowed"


def test_tool_runner_accepts_structured_preflight_rejection():
    context = ToolExecutionContext(
        tools={
            "write_file": {
                "schema": {},
                "risky": True,
                "read_only": False,
                "description": "Write file.",
                "run": lambda args: "should not run",
                "policy": {},
            }
        },
        preflight_tool=lambda name, args, tool: ToolPreflightResult.reject(
            message="error: plan mode denied for write_file",
            code="plan_mode_denied",
            security_event_type="",
            recovery_message="Write only the active plan file.",
            read_only=False,
            risk_level="high",
        ),
    )

    result = ToolRunner(context).run("write_file", {"path": "README.md", "content": "x"})

    assert result.content == "error: plan mode denied for write_file\nWrite only the active plan file."
    assert result.metadata["tool_status"] == "rejected"
    assert result.metadata["tool_error_code"] == "plan_mode_denied"
    assert result.metadata["recovery_message"] == "Write only the active plan file."


def test_tool_policy_exposes_effects_without_removing_read_only_compatibility():
    read_policy = ToolPolicy(read_only=True)
    write_policy = ToolPolicy(read_only=False)
    runtime_policy = ToolPolicy(read_only=True, effects=(Effect.RUNTIME_STATE_WRITE,))

    assert read_policy.to_dict()["effects"] == ["workspace_read"]
    assert write_policy.to_dict()["effects"] == ["workspace_write"]
    assert runtime_policy.to_dict()["effects"] == ["runtime_state_write"]
    assert runtime_policy.to_dict()["read_only"] is True


def test_run_shell_effects_reflect_read_only_commands():
    context = ToolExecutionContext(
        tools={
            "run_shell": {
                "schema": {},
                "risky": True,
                "read_only": False,
                "description": "Run shell.",
                "run": lambda args: "exit_code: 0\nok",
                "policy": {"max_result_chars": 100, "effects": ["process_exec"]},
            }
        },
    )

    result = ToolRunner(context).run("run_shell", {"command": "ls"})

    assert result.effects == {Effect.PROCESS_READ}
    assert result.metadata["effective_effects"] == ["process_read"]
