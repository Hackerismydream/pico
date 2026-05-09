import json

from pico.testing import ScriptedModelClient
from pico import Pico, SessionStore, WorkspaceContext
from pico.core.permissions import PermissionDecision


def build_agent(tmp_path, outputs=None, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    return Pico(
        model_client=ScriptedModelClient(outputs or []),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def read_session_events(agent):
    return [
        json.loads(line)
        for line in agent.session_event_bus.path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_permission_checker_is_the_single_default_tool_gate(tmp_path):
    agent = build_agent(tmp_path, approval_policy="never")

    read_decision = agent.permission_checker.check(agent.tools["read_file"], {"path": "README.md"})
    shell_decision = agent.permission_checker.check(agent.tools["run_shell"], {"command": "echo hi", "timeout": 20})

    assert read_decision == PermissionDecision.allow("read_only")
    assert shell_decision == PermissionDecision.deny("approval_denied", security_event_type="approval_denied")

    result = agent.run_tool("run_shell", {"command": "echo hi", "timeout": 20})

    assert result == "error: approval denied for run_shell"
    assert agent._last_tool_result_metadata["tool_error_code"] == "approval_denied"
    assert any(
        event["event"] == "permission_decision"
        and event["tool_name"] == "run_shell"
        and event["decision"] == "deny"
        and event["reason"] == "approval_denied"
        for event in read_session_events(agent)
    )


def test_plan_mode_switches_tool_profile_and_allows_only_active_plan_file(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool name="write_file" path=".pico/plans/v3-plan.md"><content># Plan\n- Gate 1\n</content></tool>',
            "<final>Plan ready.</final>",
        ],
        max_steps=3,
    )

    assert agent.active_tool_profile.name == "default"

    plan_path = agent.enter_plan_mode("v3")

    assert plan_path == ".pico/plans/v3-plan.md"
    assert agent.active_tool_profile.name == "plan"
    assert "run_shell" not in agent.active_tool_profile.allowed_tools

    rejected = agent.run_tool("write_file", {"path": "src.py", "content": "print('no')\n"})
    assert rejected == "error: plan mode can only write the active plan artifact (.pico/plans/v3-plan.md)"
    assert not (tmp_path / "src.py").exists()

    answer = agent.ask("draft the plan")

    assert answer == "Plan ready."
    assert agent.active_tool_profile.name == "default"
    assert (tmp_path / ".pico" / "plans" / "v3-plan.md").read_text(encoding="utf-8").startswith("# Plan")
    events = read_session_events(agent)
    assert any(
        event["event"] == "permission_decision"
        and event["tool_name"] == "write_file"
        and event["decision"] == "deny"
        and event["reason"] == "plan_mode_path_mismatch"
        for event in events
    )
    assert any(
        event["event"] == "permission_decision"
        and event["tool_name"] == "write_file"
        and event["decision"] == "allow"
        and event["reason"] == "plan_artifact_write"
        for event in events
    )
