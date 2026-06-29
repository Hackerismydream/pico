import json

from pico.cli import main
from pico.providers.clients import FakeModelClient
from pico.runtime_kernel import (
    InvocationContext,
    RuntimeEvent,
    ToolPermissionPolicy,
    RuntimeRunner,
    ToolRuntime,
    project_export,
    project_final_answer,
    project_report,
    project_session,
    project_trace,
)
from pico.tools import BASE_TOOL_SPECS


def test_kernel_runner_records_no_tool_final_answer_from_events(tmp_path):
    runner = RuntimeRunner(model_client=FakeModelClient(["Kernel answer."]))

    result = runner.run(
        InvocationContext(
            user_message="Answer directly",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    event_types = [event.type for event in result.events]
    assert event_types == [
        "invocation_start",
        "user_input",
        "model_output",
        "final_answer",
        "terminal_status",
    ]
    assert result.status == "completed"
    assert result.final_answer == "Kernel answer."
    assert project_final_answer(result.events) == "Kernel answer."


def test_kernel_runner_executes_readonly_tool_and_projects_result_to_next_model_input(tmp_path):
    (tmp_path / "README.md").write_text("project fact: alpha\n", encoding="utf-8")
    client = FakeModelClient(
        [
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            "<final>The project fact is alpha.</final>",
        ]
    )
    runner = RuntimeRunner(model_client=client)

    result = runner.run(
        InvocationContext(
            user_message="Read the project fact.",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    assert result.status == "completed"
    assert result.final_answer == "The project fact is alpha."
    event_types = [event.type for event in result.events]
    assert event_types == [
        "invocation_start",
        "user_input",
        "model_output",
        "tool_call_requested",
        "tool_permission_decision",
        "tool_argument_validation",
        "tool_result",
        "model_output",
        "final_answer",
        "terminal_status",
    ]
    permission = next(event for event in result.events if event.type == "tool_permission_decision")
    assert permission.payload["decision"] == "allow"
    assert permission.payload["reason"] == "read-only tools are allowed"
    validation = next(event for event in result.events if event.type == "tool_argument_validation")
    assert validation.payload["status"] == "ok"
    tool_result = next(event for event in result.events if event.type == "tool_result")
    assert tool_result.payload["status"] == "ok"
    assert tool_result.payload["failure_classification"] == ""
    assert "project fact: alpha" in tool_result.payload["content"]
    assert len(client.prompts) == 2
    assert "Available read-only tools: read_file, list_files, search." in client.prompts[0]
    assert "Runtime tool results" in client.prompts[1]
    assert '"name": "read_file"' in client.prompts[1]
    assert "project fact: alpha" in client.prompts[1]


def test_kernel_tool_runtime_records_denied_permission_result(tmp_path):
    (tmp_path / "README.md").write_text("project fact: alpha\n", encoding="utf-8")
    client = FakeModelClient(
        [
            '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
            "<final>The read was denied.</final>",
        ]
    )
    tool_runtime = ToolRuntime(
        tmp_path,
        permission_policy=ToolPermissionPolicy.deny_all("headless sandbox denies tools"),
    )

    result = RuntimeRunner(model_client=client, tool_runtime=tool_runtime).run(
        InvocationContext(
            user_message="Read README.",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    event_types = [event.type for event in result.events]
    assert "tool_argument_validation" not in event_types
    assert event_types[:5] == [
        "invocation_start",
        "user_input",
        "model_output",
        "tool_call_requested",
        "tool_permission_decision",
    ]
    permission = next(event for event in result.events if event.type == "tool_permission_decision")
    assert permission.payload["decision"] == "deny"
    assert permission.payload["reason"] == "headless sandbox denies tools"
    tool_result = next(event for event in result.events if event.type == "tool_result")
    assert tool_result.payload["status"] == "denied"
    assert tool_result.payload["failure_classification"] == "permission_denied"
    assert "headless sandbox denies tools" in tool_result.payload["content"]
    assert '"status": "denied"' in client.prompts[1]
    assert "headless sandbox denies tools" in client.prompts[1]


def test_kernel_tool_runtime_records_parked_permission_result(tmp_path):
    (tmp_path / "README.md").write_text("project fact: alpha\n", encoding="utf-8")
    client = FakeModelClient(
        [
            '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
            "<final>The read needs a permission decision.</final>",
        ]
    )

    def must_not_run(args):
        raise AssertionError(f"parked tool call executed with {args}")

    tool_runtime = ToolRuntime(
        tmp_path,
        tool_registry={
            "read_file": {
                **BASE_TOOL_SPECS["read_file"],
                "run": must_not_run,
            }
        },
        permission_policy=ToolPermissionPolicy.require_decision("approval required"),
    )

    result = RuntimeRunner(model_client=client, tool_runtime=tool_runtime).run(
        InvocationContext(
            user_message="Read README.",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    event_types = [event.type for event in result.events]
    assert "tool_argument_validation" not in event_types
    permission = next(event for event in result.events if event.type == "tool_permission_decision")
    assert permission.payload["decision"] == "requires_decision"
    assert permission.payload["reason"] == "approval required"
    tool_result = next(event for event in result.events if event.type == "tool_result")
    assert tool_result.payload["status"] == "requires_decision"
    assert tool_result.payload["failure_classification"] == "permission_required"
    assert "approval required" in tool_result.payload["content"]
    assert '"status": "requires_decision"' in client.prompts[1]
    assert "approval required" in client.prompts[1]


def test_kernel_tool_runtime_exposes_list_files_and_search_surfaces(tmp_path):
    (tmp_path / "README.md").write_text("project fact: alpha\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("VALUE = 'needle'\n", encoding="utf-8")
    client = FakeModelClient(
        [
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            '<tool>{"name":"search","args":{"pattern":"needle","path":"src"}}</tool>',
            "<final>Found needle in src/main.py.</final>",
        ]
    )

    result = RuntimeRunner(model_client=client).run(
        InvocationContext(
            user_message="List and search.",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    assert result.status == "completed"
    tool_results = [event.payload for event in result.events if event.type == "tool_result"]
    assert [result["name"] for result in tool_results] == ["list_files", "search"]
    assert "[F] README.md" in tool_results[0]["content"]
    assert "src/main.py" in tool_results[1]["content"]
    assert "needle" in client.prompts[2]


def test_kernel_tool_runtime_records_invalid_arguments(tmp_path):
    client = FakeModelClient(
        [
            '<tool>{"name":"read_file","args":{}}</tool>',
            "<final>The read failed because the path was missing.</final>",
        ]
    )

    result = RuntimeRunner(model_client=client).run(
        InvocationContext(
            user_message="Read a file.",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    assert result.status == "completed"
    tool_result = next(event for event in result.events if event.type == "tool_result")
    assert tool_result.payload["status"] == "error"
    assert tool_result.payload["failure_classification"] == "invalid_arguments"
    validation = next(event for event in result.events if event.type == "tool_argument_validation")
    assert validation.payload["status"] == "failed"
    assert "invalid_arguments" in client.prompts[1]


def test_kernel_tool_runtime_records_missing_file_case(tmp_path):
    client = FakeModelClient(
        [
            '<tool>{"name":"read_file","args":{"path":"missing.txt"}}</tool>',
            "<final>The file is missing.</final>",
        ]
    )

    result = RuntimeRunner(model_client=client).run(
        InvocationContext(
            user_message="Read the file.",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    assert result.status == "completed"
    tool_result = next(event for event in result.events if event.type == "tool_result")
    assert tool_result.payload["status"] == "error"
    assert tool_result.payload["failure_classification"] == "invalid_arguments"
    assert "path is not a file" in tool_result.payload["error_message"]
    assert "path is not a file" in client.prompts[1]


def test_kernel_tool_runtime_records_missing_search_path_case(tmp_path):
    client = FakeModelClient(
        [
            '<tool>{"name":"search","args":{"pattern":"needle","path":"missing-dir"}}</tool>',
            "<final>The search path is missing.</final>",
        ]
    )

    result = RuntimeRunner(model_client=client).run(
        InvocationContext(
            user_message="Search missing path.",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    assert result.status == "completed"
    tool_result = next(event for event in result.events if event.type == "tool_result")
    assert tool_result.payload["status"] == "error"
    assert tool_result.payload["failure_classification"] == "invalid_arguments"
    assert "path does not exist" in tool_result.payload["error_message"]
    assert "path does not exist" in client.prompts[1]


def test_kernel_tool_runtime_propagates_tool_execution_failure(tmp_path):
    (tmp_path / "README.md").write_text("project fact: alpha\n", encoding="utf-8")

    def fail_tool(args):
        raise RuntimeError("disk unavailable")

    tool_runtime = ToolRuntime(
        tmp_path,
        tool_registry={
            "read_file": {
                **BASE_TOOL_SPECS["read_file"],
                "run": fail_tool,
            }
        },
    )
    client = FakeModelClient(
        [
            '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
            "<final>The tool failed: disk unavailable.</final>",
        ]
    )

    result = RuntimeRunner(model_client=client, tool_runtime=tool_runtime).run(
        InvocationContext(
            user_message="Read README.",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    assert result.status == "completed"
    tool_result = next(event for event in result.events if event.type == "tool_result")
    assert tool_result.payload["status"] == "error"
    assert tool_result.payload["failure_classification"] == "tool_failed"
    assert "disk unavailable" in tool_result.payload["content"]
    assert "disk unavailable" in client.prompts[1]


def test_kernel_tool_runtime_keeps_write_and_shell_tools_unavailable(tmp_path):
    client = FakeModelClient(
        [
            '<tool>{"name":"write_file","args":{"path":"x.txt","content":"nope"}}</tool>',
            "<final>Write tools are unavailable.</final>",
        ]
    )

    result = RuntimeRunner(model_client=client).run(
        InvocationContext(
            user_message="Try to write.",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    permission = next(event for event in result.events if event.type == "tool_permission_decision")
    assert permission.payload["decision"] == "deny"
    assert permission.payload["failure_classification"] == "tool_not_allowed"
    tool_result = next(event for event in result.events if event.type == "tool_result")
    assert tool_result.payload["status"] == "denied"
    assert tool_result.payload["failure_classification"] == "tool_not_allowed"
    assert not (tmp_path / "x.txt").exists()


def test_kernel_trace_and_report_projection_include_tool_call_and_final_answer(tmp_path):
    (tmp_path / "README.md").write_text("project fact: alpha\n", encoding="utf-8")
    result = RuntimeRunner(
        model_client=FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>The project fact is alpha.</final>",
            ]
        )
    ).run(
        InvocationContext(
            user_message="Read the project fact.",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    trace = project_trace(result.events)
    report = project_report(result.events)
    assert any(event["event"] == "tool_result" for event in trace)
    assert report["status"] == "completed"
    assert report["final_answer"] == "The project fact is alpha."
    assert report["tool_calls"] == [
        {
            "name": "read_file",
            "status": "ok",
            "failure_classification": "",
            "content": "# README.md\n   1: project fact: alpha",
        }
    ]


def test_kernel_projection_consistency_from_fixture_runtime_events():
    events = [
        RuntimeEvent(type="invocation_start", payload={"invocation_id": "run_fixture", "workspace_root": "/repo"}),
        RuntimeEvent(type="user_input", payload={"invocation_id": "run_fixture", "text": "Read README."}),
        RuntimeEvent(
            type="model_output",
            payload={
                "invocation_id": "run_fixture",
                "text": '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
                "provider": "FakeModelClient:fake",
                "metadata": {"model": "fake", "finish_reason": "tool_calls"},
                "step": 1,
            },
        ),
        RuntimeEvent(
            type="tool_call_requested",
            payload={
                "invocation_id": "run_fixture",
                "tool_call_id": "tool_1",
                "name": "read_file",
                "args": {"path": "README.md"},
                "read_only": True,
            },
        ),
        RuntimeEvent(
            type="tool_permission_decision",
            payload={
                "invocation_id": "run_fixture",
                "tool_call_id": "tool_1",
                "name": "read_file",
                "args": {"path": "README.md"},
                "decision": "allow",
                "reason": "read-only tools are allowed",
                "policy_name": "allow_readonly",
                "failure_classification": "",
                "read_only": True,
                "available": True,
            },
        ),
        RuntimeEvent(
            type="tool_result",
            payload={
                "invocation_id": "run_fixture",
                "tool_call_id": "tool_1",
                "name": "read_file",
                "args": {"path": "README.md"},
                "status": "ok",
                "content": "# README.md\n   1: alpha",
                "failure_classification": "",
                "read_only": True,
            },
        ),
        RuntimeEvent(
            type="model_output",
            payload={
                "invocation_id": "run_fixture",
                "text": "<final>Alpha.</final>",
                "provider": "FakeModelClient:fake",
                "metadata": {"model": "fake", "finish_reason": "stop"},
                "step": 2,
            },
        ),
        RuntimeEvent(type="final_answer", payload={"invocation_id": "run_fixture", "text": "Alpha."}),
        RuntimeEvent(type="terminal_status", payload={"invocation_id": "run_fixture", "status": "completed"}),
    ]

    session = project_session(events)
    trace = project_trace(events)
    report = project_report(events)
    export = project_export(events)

    assert session["run_id"] == trace[0]["payload"]["invocation_id"] == report["run_id"] == export["run_id"]
    assert session["status"] == report["status"] == export["status"] == "completed"
    assert session["history"][-1]["content"] == report["final_answer"] == export["final_answer"] == "Alpha."
    assert session["tool_calls"][0]["tool_call_id"] == "tool_1"
    assert session["tool_calls"][0]["permission"]["decision"] == "allow"
    assert report["permission_decisions"][0]["decision"] == "allow"
    assert export["tool_calls"][0]["permission"]["reason"] == "read-only tools are allowed"
    assert report["provider_calls"][0]["metadata"]["finish_reason"] == "tool_calls"
    assert export["provider_calls"][1]["metadata"]["finish_reason"] == "stop"
    assert report["terminal_status"]["status"] == export["terminal_status"]["status"] == "completed"


def test_kernel_projections_handle_incomplete_runtime_event_history():
    events = [
        RuntimeEvent(type="invocation_start", payload={"invocation_id": "run_incomplete", "workspace_root": "/repo"}),
        RuntimeEvent(type="user_input", payload={"invocation_id": "run_incomplete", "text": "Start."}),
        RuntimeEvent(
            type="tool_call_requested",
            payload={
                "invocation_id": "run_incomplete",
                "tool_call_id": "tool_1",
                "name": "read_file",
                "args": {"path": "README.md"},
                "read_only": True,
            },
        ),
    ]

    assert project_session(events)["status"] == "unknown"
    assert project_report(events)["status"] == "unknown"
    assert project_export(events)["terminal_status"] == {}
    assert project_trace(events)[-1]["event"] == "tool_call_requested"


def test_kernel_runner_normalizes_provider_failure(tmp_path):
    class BrokenModelClient:
        def complete(self, prompt, max_new_tokens, **kwargs):
            raise RuntimeError("backend unavailable")

    runner = RuntimeRunner(model_client=BrokenModelClient())

    result = runner.run(
        InvocationContext(
            user_message="Answer directly",
            workspace_root=str(tmp_path),
            max_new_tokens=128,
        )
    )

    assert result.status == "failed"
    assert result.error_type == "provider_error"
    assert "backend unavailable" in result.error_message
    terminal = result.events[-1]
    assert terminal.type == "terminal_status"
    assert terminal.payload["status"] == "failed"
    assert terminal.payload["error_type"] == "provider_error"


def test_cli_kernel_runtime_prints_projected_final_answer(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(["Projected answer."]),
    )

    status = main(["--runtime", "kernel", "--cwd", str(tmp_path), "hello"])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out.strip() == "Projected answer."


def test_cli_kernel_runtime_can_use_fake_provider(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    monkeypatch.setenv("PICO_FAKE_MODEL_OUTPUT", "Fake provider answer.")

    status = main(["--runtime", "kernel", "--provider", "fake", "--cwd", str(tmp_path), "hello"])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out.strip() == "Fake provider answer."


def test_cli_kernel_runtime_can_show_tool_event_summary(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("project fact: alpha\n", encoding="utf-8")
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>The project fact is alpha.</final>",
            ]
        ),
    )

    status = main(
        [
            "--runtime",
            "kernel",
            "--approval",
            "auto",
            "--show-runtime-events",
            "--cwd",
            str(tmp_path),
            "hello",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out.strip() == "The project fact is alpha."
    assert "tool read_file requested" in captured.err
    assert "tool read_file permission allow" in captured.err
    assert "tool read_file ok" in captured.err
    assert "final The project fact is alpha." in captured.err


def test_cli_kernel_runtime_persists_and_inspects_runtime_event_views(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("project fact: alpha\n", encoding="utf-8")
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
                "<final>The project fact is alpha.</final>",
            ]
        ),
    )

    status = main(["--runtime", "kernel", "--approval", "auto", "--cwd", str(tmp_path), "hello"])
    assert status == 0
    capsys.readouterr()
    run_dirs = sorted((tmp_path / ".pico" / "runs").iterdir())
    run_id = run_dirs[0].name
    assert (run_dirs[0] / "runtime_events.jsonl").exists()
    assert (run_dirs[0] / "trace.jsonl").exists()
    assert (run_dirs[0] / "report.json").exists()

    assert main(["--cwd", str(tmp_path), "--inspect-run", run_id, "--inspect-view", "ledger"]) == 0
    ledger_output = capsys.readouterr().out
    ledger_events = [json.loads(line) for line in ledger_output.splitlines()]
    assert [event["type"] for event in ledger_events][:2] == ["invocation_start", "user_input"]
    assert any(event["type"] == "tool_permission_decision" for event in ledger_events)

    assert main(["--cwd", str(tmp_path), "--inspect-run", run_id, "--inspect-view", "session"]) == 0
    session = json.loads(capsys.readouterr().out)
    assert session["run_id"] == run_id
    assert session["tool_calls"][0]["permission"]["decision"] == "allow"
    assert session["history"][-1]["content"] == "The project fact is alpha."

    assert main(["--cwd", str(tmp_path), "--inspect-run", run_id, "--inspect-view", "report"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["run_id"] == run_id
    assert report["tool_calls"][0]["name"] == "read_file"
    assert report["permission_decisions"][0]["decision"] == "allow"


def test_cli_kernel_runtime_maps_approval_never_to_permission_denied(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("project fact: alpha\n", encoding="utf-8")
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
                "<final>The tool result was denied.</final>",
            ]
        ),
    )

    status = main(
        [
            "--runtime",
            "kernel",
            "--approval",
            "never",
            "--show-runtime-events",
            "--cwd",
            str(tmp_path),
            "hello",
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out.strip() == "The tool result was denied."
    assert "tool read_file permission deny: CLI approval policy 'never' denies tool execution" in captured.err
    assert "tool read_file denied (permission_denied)" in captured.err


def test_cli_kernel_runtime_default_approval_ask_parks_tool_call(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("project fact: alpha\n", encoding="utf-8")
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"README.md"}}</tool>',
                "<final>The tool result requires a decision.</final>",
            ]
        ),
    )

    status = main(["--runtime", "kernel", "--show-runtime-events", "--cwd", str(tmp_path), "hello"])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out.strip() == "The tool result requires a decision."
    assert "tool read_file permission requires_decision" in captured.err
    assert "tool read_file requires_decision (permission_required)" in captured.err


def test_cli_legacy_runtime_path_remains_explicit(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    monkeypatch.setattr(
        "pico.cli._build_model_client",
        lambda args: FakeModelClient(["<final>Legacy answer.</final>"]),
    )

    status = main(["--runtime", "legacy", "--cwd", str(tmp_path), "--approval", "auto", "hello"])

    assert status == 0


def test_cli_kernel_runtime_reports_provider_failure(tmp_path, capsys, monkeypatch):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")

    class BrokenModelClient:
        def complete(self, prompt, max_new_tokens, **kwargs):
            raise RuntimeError("backend unavailable")

    monkeypatch.setattr("pico.cli._build_model_client", lambda args: BrokenModelClient())

    status = main(["--runtime", "kernel", "--cwd", str(tmp_path), "hello"])

    captured = capsys.readouterr()
    assert status == 1
    assert captured.out == ""
    assert "provider_error" in captured.err
    assert "backend unavailable" in captured.err
