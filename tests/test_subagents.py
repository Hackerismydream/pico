import json
import time

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.features.subagents import SubagentManager


class FakeRunner:
    def __init__(self, result="ok", error=None):
        self.result = result
        self.error = error
        self.cancelled = False
        self.prompts = []

    def __call__(self, task, prompt, cancel_event):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        if self.cancelled or cancel_event.is_set():
            return {"status": "killed", "result": ""}
        return {"status": "completed", "result": self.result, "tool_uses": 2, "run_id": "run_child"}


def wait_notification(manager, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        notifications = manager.drain_notifications()
        if notifications:
            return notifications[0]
        time.sleep(0.01)
    raise AssertionError("timed out waiting for subagent notification")


def build_agent(tmp_path, outputs, **kwargs):
    workspace = WorkspaceContext.build(tmp_path)
    return Pico(
        model_client=kwargs.pop("model_client", FakeModelClient(outputs)),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy=kwargs.pop("approval_policy", "auto"),
        **kwargs,
    )


def test_subagent_manager_spawns_and_reports_completion():
    runner = FakeRunner(result="found auth flow")
    manager = SubagentManager({"Explore": runner})

    launched = manager.spawn(description="Inspect auth", prompt="find auth", subagent_type="Explore")
    notification = wait_notification(manager)

    assert launched["task_id"].startswith("agent-")
    assert notification["status"] == "completed"
    assert notification["result"] == "found auth flow"
    assert notification["usage"]["tool_uses"] == 2
    assert manager.snapshot()[0]["status"] == "completed"


def test_subagent_manager_can_continue_completed_task():
    runner = FakeRunner(result="done")
    manager = SubagentManager({"Explore": runner})

    launched = manager.spawn(description="Inspect", prompt="first", subagent_type="Explore")
    wait_notification(manager)
    manager.continue_task(task_id=launched["task_id"], message="second")
    wait_notification(manager)

    assert runner.prompts == ["first", "second"]


def test_send_message_reuses_subagent_conversation_context(tmp_path):
    model = FakeModelClient(["<final>first result</final>", "<final>second result</final>"])
    agent = build_agent(tmp_path, [], model_client=model)

    launched = json.loads(
        agent.run_tool(
            "agent",
            {
                "description": "Inspect files",
                "prompt": "First child task",
                "subagent_type": "Explore",
                "background": False,
            },
        )
    )
    continued = json.loads(
        agent.run_tool(
            "send_message",
            {
                "to": launched["task_id"],
                "message": "Continue child task",
                "background": False,
            },
        )
    )

    assert continued["status"] == "completed"
    assert len(model.prompts) == 2
    assert "First child task" in model.prompts[1]
    assert "first result" in model.prompts[1]


def test_subagent_manager_can_stop_running_task():
    def runner(task, prompt, cancel_event):
        while not cancel_event.is_set():
            time.sleep(0.01)
        return {"status": "killed", "result": ""}

    manager = SubagentManager({"Explore": runner})
    launched = manager.spawn(description="Long search", prompt="wait", subagent_type="Explore")

    stopped = manager.stop_task(launched["task_id"])
    notification = wait_notification(manager)

    assert stopped["status"] == "stopping"
    assert notification["status"] == "killed"


def test_agent_tool_launches_explore_and_delivers_notification_to_runtime(tmp_path):
    agent = build_agent(tmp_path, ["<final>Explore result</final>"])

    result = agent.run_tool(
        "agent",
        {"description": "Inspect files", "prompt": "Read README only", "subagent_type": "Explore"},
    )
    payload = json.loads(result)
    assert payload["status"] == "started"

    notification = wait_notification(agent.subagent_manager)
    delivered = agent.deliver_subagent_notification(notification)

    assert delivered["event"] == "subagent_completed"
    assert agent.session["subagents"][0]["status"] == "completed"
    assert "Explore result" in agent.session["history"][-1]["content"]


def test_subagent_tools_are_not_marked_read_only(tmp_path):
    agent = build_agent(tmp_path, [])

    assert agent.tools["agent"]["risky"] is True
    assert agent.tools["agent"]["read_only"] is False
    assert agent.tools["send_message"]["risky"] is True
    assert agent.tools["send_message"]["read_only"] is False


def test_background_subagent_started_status_is_recorded_as_running(tmp_path):
    agent = build_agent(tmp_path, ["<final>Explore result</final>"])

    result = agent.run_tool(
        "agent",
        {"description": "Inspect files", "prompt": "Read README only", "subagent_type": "Explore"},
    )
    payload = json.loads(result)

    assert payload["status"] == "started"
    assert agent.session["subagents"][0]["status"] == "running"


def test_explore_subagent_can_run_safe_read_only_shell(tmp_path):
    agent = build_agent(
        tmp_path,
        ['<tool>{"name":"run_shell","args":{"command":"pwd","timeout":5}}</tool>', "<final>checked</final>"],
    )

    result = agent.run_tool(
        "agent",
        {"description": "Inspect pwd", "prompt": "Run pwd", "subagent_type": "Explore", "background": False},
    )
    payload = json.loads(result)

    assert payload["status"] == "completed"
    assert "approval denied" not in payload["result"]
    assert "checked" in payload["result"]


def test_explore_subagent_rejects_mutating_shell(tmp_path):
    agent = build_agent(
        tmp_path,
        ['<tool>{"name":"run_shell","args":{"command":"touch x.txt","timeout":5}}</tool>', "<final>done</final>"],
    )

    result = agent.run_tool(
        "agent",
        {"description": "Try touch", "prompt": "Touch x.txt", "subagent_type": "Explore", "background": False},
    )
    payload = json.loads(result)

    assert payload["status"] == "completed"
    assert not (tmp_path / "x.txt").exists()
    assert "approval denied" in payload["result"]


def test_explore_subagent_cannot_modify_files(tmp_path):
    agent = build_agent(
        tmp_path,
        ['<tool>{"name":"write_file","args":{"path":"x.txt","content":"bad"}}</tool>', "<final>done</final>"],
    )

    result = agent.run_tool(
        "agent",
        {"description": "Try write", "prompt": "Write x.txt", "subagent_type": "Explore", "background": False},
    )
    payload = json.loads(result)

    assert payload["status"] == "completed"
    assert not (tmp_path / "x.txt").exists()
    assert "not allowed" in payload["result"] or "approval denied" in payload["result"]


def test_worker_subagent_requires_write_scope_and_enforces_it(tmp_path):
    agent = build_agent(tmp_path, [])

    missing_scope = agent.run_tool(
        "agent",
        {"description": "Write", "prompt": "Write ok.txt", "subagent_type": "Worker"},
    )
    assert "write_scope is required" in missing_scope

    allowed = build_agent(
        tmp_path,
        ['<tool>{"name":"write_file","args":{"path":"allowed.txt","content":"ok"}}</tool>', "<final>written</final>"],
    )
    result = allowed.run_tool(
        "agent",
        {
            "description": "Write allowed",
            "prompt": "Write allowed.txt",
            "subagent_type": "Worker",
            "write_scope": ["allowed.txt"],
            "background": False,
        },
    )
    payload = json.loads(result)
    assert payload["status"] == "completed"
    assert (tmp_path / "allowed.txt").read_text(encoding="utf-8") == "ok"

    blocked = build_agent(
        tmp_path,
        ['<tool>{"name":"write_file","args":{"path":"blocked.txt","content":"bad"}}</tool>', "<final>blocked</final>"],
    )
    result = blocked.run_tool(
        "agent",
        {
            "description": "Write blocked",
            "prompt": "Write blocked.txt",
            "subagent_type": "Worker",
            "write_scope": ["allowed.txt"],
            "background": False,
        },
    )
    payload = json.loads(result)
    assert not (tmp_path / "blocked.txt").exists()
    assert "outside subagent write_scope" in payload["result"]


def test_worker_subagent_cannot_bypass_write_scope_with_shell(tmp_path):
    agent = build_agent(
        tmp_path,
        ['<tool>{"name":"run_shell","args":{"command":"touch blocked.txt","timeout":5}}</tool>', "<final>done</final>"],
    )

    result = agent.run_tool(
        "agent",
        {
            "description": "Try shell write",
            "prompt": "Touch blocked.txt",
            "subagent_type": "Worker",
            "write_scope": ["allowed.txt"],
            "background": False,
        },
    )
    payload = json.loads(result)

    assert payload["status"] == "completed"
    assert not (tmp_path / "blocked.txt").exists()
    assert "run_shell" in payload["result"]
    assert "not allowed" in payload["result"]
