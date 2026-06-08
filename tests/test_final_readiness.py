from pico.core.final_readiness import evaluate_final_readiness
from pico.core.task_state import TaskState


def task_state():
    return TaskState.create(task_id="task_1", run_id="run_1", user_request="demo")


def test_final_readiness_detects_unresolved_current_run_high_priority_todo():
    state = task_state()
    state.todo_changes = [
        {
            "action": "add",
            "todo": {
                "id": "todo_1",
                "priority": "high",
                "status": "pending",
            },
        }
    ]

    decision = evaluate_final_readiness(state, "strict")

    assert decision["decision"] == "warn"
    assert decision["action"] == "none"
    assert decision["reasons"] == ["unresolved_high_priority_todo"]


def test_final_readiness_uses_latest_current_run_todo_state():
    state = task_state()
    state.todo_changes = [
        {
            "action": "add",
            "todo": {"id": "todo_1", "priority": "high", "status": "pending"},
        },
        {
            "action": "update",
            "todo": {"id": "todo_1", "priority": "high", "status": "done"},
        },
    ]

    decision = evaluate_final_readiness(state, "strict")

    assert decision["decision"] == "allow"
    assert decision["reasons"] == []


def test_final_readiness_detects_unreduced_context_pressure():
    state = task_state()
    state.evidence_summaries = {
        "context_budget_summary": {
            "pressure_ratio": 0.98,
            "reductions": [],
        }
    }

    decision = evaluate_final_readiness(state, "strict")

    assert decision["decision"] == "warn"
    assert decision["action"] == "none"
    assert decision["reasons"] == ["context_pressure_without_reduction"]


def test_final_readiness_allows_context_pressure_after_successful_reduction():
    state = task_state()
    state.evidence_summaries = {
        "context_budget_summary": {
            "pressure_ratio": 0.98,
            "reductions": [{"source": "microcompact", "saved_chars": 100}],
        }
    }

    decision = evaluate_final_readiness(state, "strict")

    assert decision["decision"] == "allow"
    assert decision["reasons"] == []


def test_final_readiness_blocks_partial_success_workspace_change():
    state = task_state()
    state.runtime_reminders = [
        {
            "event": "tool_executed",
            "tool": "run_shell",
            "status": "partial_success",
            "workspace_changed": True,
            "affected_paths": ["notes/result.txt"],
        }
    ]

    decision = evaluate_final_readiness(state, "strict")

    assert decision["decision"] == "block"
    assert decision["action"] == "block"
    assert decision["reasons"] == ["partial_success_workspace_changed"]
