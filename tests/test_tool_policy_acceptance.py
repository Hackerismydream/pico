import json
import shlex
import sys

from pico.testing import ScriptedModelClient
from pico import Pico, SessionStore, WorkspaceContext
from pico.core.context_manager import ContextManager
from pico.features.sandbox.config import SandboxConfig


def build_agent(tmp_path, outputs=None, **kwargs):
    (tmp_path / "README.md").write_text("hello world\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return Pico(
        model_client=ScriptedModelClient(outputs or []),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        **kwargs,
    )


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_patch_requires_prior_fresh_read_and_allows_after_read(tmp_path):
    agent = build_agent(tmp_path)

    rejected = agent.run_tool("patch_file", {"path": "README.md", "old_text": "world", "new_text": "pico"})

    assert "read_file" in rejected
    assert agent._last_tool_result_metadata["tool_error_code"] == "prior_read_required"
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "hello world\n"

    agent.run_tool("read_file", {"path": "README.md", "start": 1, "end": 1})
    patched = agent.run_tool("patch_file", {"path": "README.md", "old_text": "world", "new_text": "pico"})

    assert patched == "patched README.md"
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "hello pico\n"


def test_rejected_patch_can_be_retried_after_informing_read(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool name="patch_file" path="README.md"><old_text>world</old_text><new_text>pico</new_text></tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            '<tool name="patch_file" path="README.md"><old_text>world</old_text><new_text>pico</new_text></tool>',
            "<final>done</final>",
        ],
        max_steps=4,
    )

    assert agent.ask("retry a patch only after reading the target file") == "done"
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "hello pico\n"

    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    patch_events = [
        event
        for event in trace
        if event["event"] == "tool_executed" and event.get("name") == "patch_file"
    ]
    assert [event.get("tool_error_code") for event in patch_events] == [
        "prior_read_required",
        "",
    ]


def test_write_file_allows_new_file_but_requires_read_before_overwrite(tmp_path):
    agent = build_agent(tmp_path)

    assert agent.run_tool("write_file", {"path": "notes.txt", "content": "new\n"}) == "wrote notes.txt (4 chars)"
    rejected = agent.run_tool("write_file", {"path": "README.md", "content": "overwrite\n"})

    assert "read_file" in rejected
    assert agent._last_tool_result_metadata["tool_error_code"] == "prior_read_required"

    agent.run_tool("read_file", {"path": "README.md", "start": 1, "end": 1})
    assert agent.run_tool("write_file", {"path": "README.md", "content": "overwrite\n"}) == "wrote README.md (10 chars)"


def test_patch_allows_self_authored_file_without_extra_read(tmp_path):
    agent = build_agent(tmp_path)

    assert agent.run_tool("write_file", {"path": "scripts/check.py", "content": "assert False\n"}) == "wrote scripts/check.py (13 chars)"
    patched = agent.run_tool(
        "patch_file",
        {"path": "scripts/check.py", "old_text": "assert False", "new_text": "assert True"},
    )

    assert patched == "patched scripts/check.py"
    assert (tmp_path / "scripts" / "check.py").read_text(encoding="utf-8") == "assert True\n"


def test_repeated_mutating_file_tool_cannot_overwrite_later_patch(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool name="write_file" path="scripts/check.py"><content>VALUE = False\n</content></tool>',
            '<tool name="patch_file" path="scripts/check.py"><old_text>False</old_text><new_text>True</new_text></tool>',
            '<tool name="write_file" path="scripts/check.py"><content>VALUE = False\n</content></tool>',
            "<final>done</final>",
        ],
        max_steps=4,
    )

    assert agent.ask("write then patch then accidentally repeat the same write") == "done"
    assert (tmp_path / "scripts" / "check.py").read_text(encoding="utf-8") == "VALUE = True\n"

    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    write_events = [
        event
        for event in trace
        if event["event"] == "tool_executed" and event.get("name") == "write_file"
    ]
    assert [event.get("tool_error_code") for event in write_events] == [
        "",
        "repeated_identical_call",
    ]


def test_shell_search_like_commands_are_rejected_by_policy(tmp_path):
    agent = build_agent(tmp_path)

    rejected = agent.run_tool("run_shell", {"command": "grep -R hello .", "timeout": 20})

    assert "search" in rejected
    assert agent._last_tool_result_metadata["tool_error_code"] == "shell_search_should_use_tool"
    assert any(
        event["event"] == "tool_policy_decision"
        and event["tool_name"] == "run_shell"
        and event["decision"] == "deny"
        for event in read_jsonl(agent.session_event_bus.path)
    )


def test_tool_governance_decisions_are_run_trace_evidence(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"missing_tool","args":{}}</tool>',
            '<tool>{"name":"run_shell","args":{"command":"grep -R hello .","timeout":20}}</tool>',
            "<final>done</final>",
        ],
        max_steps=3,
    )

    assert agent.ask("exercise tool governance") == "done"

    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    decisions = [event for event in trace if event["event"] == "governance_decision"]
    assert [(event["decision"], event["reason_code"]) for event in decisions] == [
        ("deny", "unknown_tool"),
        ("allow", "approval_auto"),
        ("deny", "shell_search_should_use_tool"),
    ]

    report = json.loads(
        (agent.current_run_dir / "report.json").read_text(encoding="utf-8")
    )
    assert report["evidence_summaries"]["governance_summary"] == {
        "allow_count": 1,
        "deny_count": 2,
        "warn_count": 0,
        "reasons": {
            "unknown_tool": 1,
            "approval_auto": 1,
            "shell_search_should_use_tool": 1,
        },
        "last_denied_reason": "shell_search_should_use_tool",
    }


def test_tool_governance_covers_validation_repetition_and_permission_denials(tmp_path):
    repeated_agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            "<final>done</final>",
        ],
        max_steps=5,
    )

    assert repeated_agent.ask("exercise early governance denials") == "done"

    trace = read_jsonl(repeated_agent.current_run_dir / "trace.jsonl")
    denied_reasons = [
        event["reason_code"]
        for event in trace
        if event["event"] == "governance_decision" and event["decision"] == "deny"
    ]
    assert "invalid_arguments" in denied_reasons
    assert "repeated_identical_call" in denied_reasons

    readonly_agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"run_shell","args":{"command":"echo hi","timeout":20}}</tool>',
            "<final>done</final>",
        ],
        read_only=True,
        max_steps=2,
    )

    assert readonly_agent.ask("exercise read only denial") == "done"

    trace = read_jsonl(readonly_agent.current_run_dir / "trace.jsonl")
    permission_denial = next(
        event
        for event in trace
        if event["event"] == "governance_decision" and event["decision"] == "deny"
    )
    assert permission_denial["decision_type"] == "permission"
    assert permission_denial["reason_code"] == "read_only_violation"


def test_tool_governance_records_required_sandbox_unavailable(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"run_shell","args":{"command":"echo hi","timeout":20}}</tool>',
            "<final>done</final>",
        ],
        sandbox_config=SandboxConfig(mode="required", backend="bubblewrap"),
        max_steps=2,
    )
    agent.sandbox_runner.which = lambda name: None

    assert agent.ask("exercise sandbox denial") == "done"

    trace = read_jsonl(agent.current_run_dir / "trace.jsonl")
    assert any(
        event["event"] == "governance_decision"
        and event["decision"] == "deny"
        and event["reason_code"] == "sandbox_rejected_command"
        for event in trace
    )


def test_shell_policy_allows_head_tail_grep_after_pipe(tmp_path):
    """`pip install ... 2>&1 | tail -5` 和 `git log | head -10` 是合法的输出管理，
    policy 不应该把它们当作 workspace search 拒绝。"""
    agent = build_agent(tmp_path)

    for command in (
        "echo hello && echo world | tail -1",
        "python3 --version 2>&1 | head -3",
        "echo a; echo b | grep b",
    ):
        result = agent.run_tool("run_shell", {"command": command, "timeout": 20})
        assert "exit_code: 0" in result, f"command should run, got: {result[:200]}"

    rejected_after_seq = agent.run_tool(
        "run_shell", {"command": "echo a; cat README.md", "timeout": 20}
    )
    assert "search" in rejected_after_seq, "命令分号后跟 cat 仍应被禁"
    assert agent._last_tool_result_metadata["tool_error_code"] == "shell_search_should_use_tool"


def test_long_shell_output_is_clipped_and_full_output_is_saved_as_run_artifact(tmp_path):
    script = "print('x'*6000)"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
    agent = build_agent(
        tmp_path,
        [
            f'<tool>{{"name":"run_shell","args":{{"command":{json.dumps(command)},"timeout":20}}}}</tool>',
            "<final>captured</final>",
        ],
    )

    assert agent.ask("produce long shell output") == "captured"

    tool_item = next(item for item in agent.session["history"] if item["role"] == "tool" and item["name"] == "run_shell")
    assert len(tool_item["content"]) < 1200
    assert "full output saved:" in tool_item["content"]
    assert "full output saved:" in agent.model_client.prompts[1]

    report = json.loads((agent.current_run_dir / "report.json").read_text(encoding="utf-8"))
    artifact_path = report["runtime_reminders"][0]["artifact_path"] if report["runtime_reminders"] else agent._last_tool_result_metadata["full_output_artifact"]
    full_output = (tmp_path / artifact_path).read_text(encoding="utf-8")
    assert "x" * 6000 in full_output

    trace_events = read_jsonl(agent.current_run_dir / "trace.jsonl")
    tool_event = next(event for event in trace_events if event["event"] == "tool_executed")
    assert tool_event["full_output_artifact"] == artifact_path


def test_long_read_file_result_is_artifact_backed_when_history_is_microcompacted(tmp_path):
    large_text = "\n".join(f"line-{index} " + ("x" * 40) for index in range(120))
    (tmp_path / "large.txt").write_text(large_text, encoding="utf-8")
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"large.txt","start":1,"end":120}}</tool>',
            "<final>read</final>",
        ],
    )

    assert agent.ask("read the large file") == "read"
    tool_item = next(item for item in agent.session["history"] if item["role"] == "tool")
    original_history_content = tool_item["content"]
    artifact_ref = tool_item["artifact_ref"]

    assert artifact_ref.endswith(".txt")
    assert tool_item["original_chars"] > len(original_history_content)
    assert "line-119" in (tmp_path / artifact_ref).read_text(encoding="utf-8")

    for index in range(4):
        agent.record({"role": "user", "content": f"later user {index}"})
        agent.record({"role": "assistant", "content": f"later answer {index}"})

    before_history = json.dumps(agent.session["history"], sort_keys=True)
    prompt, metadata = ContextManager(agent).build("continue")

    persisted_tool_item = next(
        item for item in agent.session["history"] if item.get("artifact_ref") == artifact_ref
    )
    assert json.dumps(agent.session["history"], sort_keys=True) == before_history
    assert persisted_tool_item["content"] == original_history_content
    assert artifact_ref in prompt
    assert "line-119" not in prompt
    assert metadata["history"]["microcompact_artifact_refs"] == [artifact_ref]
    assert metadata["history"]["microcompact_saved_chars"] > 0


def test_microcompact_keeps_latest_failed_tool_result_visible(tmp_path):
    script = "for i in range(140): print(f'FAIL-{i}')\nraise SystemExit(1)"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
    agent = build_agent(
        tmp_path,
        [
            f'<tool>{{"name":"run_shell","args":{{"command":{json.dumps(command)},"timeout":20}}}}</tool>',
            "<final>captured failure</final>",
        ],
    )

    assert agent.ask("capture a long failure") == "captured failure"
    for index in range(4):
        agent.record({"role": "user", "content": f"later-{index}"})
        agent.record({"role": "assistant", "content": f"done-{index}"})

    prompt, metadata = ContextManager(agent).build("continue")

    assert "FAIL-0" in prompt
    assert "run_shell output saved:" not in prompt
    assert metadata["history"]["microcompact_artifact_refs"] == []


def test_microcompact_keeps_latest_workspace_changing_tool_result_visible(tmp_path):
    script = "\n".join(
        [
            "from pathlib import Path",
            "Path('notes').mkdir(exist_ok=True)",
            "Path('notes/out.txt').write_text('ok\\n')",
            "for i in range(140): print(f'CHANGED-{i}')",
        ]
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
    agent = build_agent(
        tmp_path,
        [
            f'<tool>{{"name":"run_shell","args":{{"command":{json.dumps(command)},"timeout":20}}}}</tool>',
            "<final>captured change</final>",
        ],
    )

    assert agent.ask("capture a long workspace change") == "captured change"
    for index in range(4):
        agent.record({"role": "user", "content": f"later-{index}"})
        agent.record({"role": "assistant", "content": f"done-{index}"})

    prompt, metadata = ContextManager(agent).build("continue")

    assert "CHANGED-0" in prompt
    assert "run_shell output saved:" not in prompt
    assert metadata["history"]["microcompact_artifact_refs"] == []
