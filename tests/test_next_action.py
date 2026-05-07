from pico.core.task_state import TaskState
from pico.features.control import RuntimeControlPlane


class StubAgent:
    def __init__(self, tasks=None, verification_plan=None):
        self._tasks = list(tasks or [])
        self._runtime_reminder_keys = set()
        self._last_tool_result_metadata = {}
        self.tools = {"read_file": {"read_only": True}}
        self.verification_plan = verification_plan or {}

    def current_tasks(self):
        return list(self._tasks)

    def runtime_tool_reminder(self, name, user_message, args):
        del name, user_message, args
        return None

    def assess_completion(self, task_state, user_message):
        del task_state, user_message
        return {"warnings": []}


def make_state(**fields):
    state = TaskState.create("task_1", "build frontend backend and verify", run_id="run_1")
    for key, value in fields.items():
        setattr(state, key, value)
    return state


def test_planner_requires_pending_task_activation_before_read_only_work():
    tasks = [
        {"id": "task_1", "content": "Backend", "active_form": "Backend", "status": "completed", "verification": False},
        {"id": "task_2", "content": "Frontend", "active_form": "Frontend", "status": "pending", "verification": False},
    ]
    state = make_state(tasks=tasks)

    action = RuntimeControlPlane().before_tool(
        StubAgent(tasks=tasks),
        state,
        "read_file",
        {"path": "main.py"},
        "build app",
    )

    assert action.action == "remind"
    assert action.reason == "pending_task_needs_activation"
    assert action.next_tool == "todo_update"
    assert action.tool_args == {"id": "task_2", "status": "in_progress"}


def test_planner_recommends_verifier_action_when_final_lacks_evidence():
    state = make_state(
        changed_paths=["app.py"],
        tasks=[],
        verification_plan={
            "missing_evidence": [{"requirement": "runtime_verification", "reason": "no passed verification artifact has been recorded"}],
            "suggested_commands": [{"command": "uv run python -m compileall .", "reason": "python files changed"}],
            "static_checks": [],
        },
    )

    action = RuntimeControlPlane().before_final(StubAgent(), state, "done", "build and verify this app")

    assert action.action == "block_final"
    assert action.reason == "completion_gate_blocked"
    assert action.next_tool == "run_shell"
    assert action.tool_args == {"command": "uv run python -m compileall .", "timeout": 60}
