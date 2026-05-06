from types import SimpleNamespace

from pico.core.tool_runner import ToolExecutionContext, ToolRunner


def test_tool_runner_returns_content_and_metadata_without_trace_side_effects(tmp_path):
    trace_calls = []
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
        emit_trace=lambda *args, **kwargs: trace_calls.append((args, kwargs)),
    )

    result = ToolRunner(context).run("echo", {})

    assert result.content == "ok"
    assert result.metadata["tool_status"] == "ok"
    assert result.metadata["read_only"] is True
    assert trace_calls == []


def test_tool_runner_reports_unknown_and_not_allowed_tools():
    context = ToolExecutionContext(tools={}, allowed_tools=("read_file",))

    result = ToolRunner(context).run("run_shell", {"command": "echo nope"})

    assert "not allowed" in result.content
    assert result.metadata["tool_status"] == "rejected"
    assert result.metadata["tool_error_code"] == "tool_not_allowed"
