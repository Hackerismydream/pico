from pico.core.run_context import RunContext
from pico.core.task_state import TaskState


def test_run_context_tracks_budget_and_attempt_state():
    task_state = TaskState.create("task_1", "build project", run_id="run_1")
    context = RunContext.create(
        task_state=task_state,
        user_message="build project",
        max_steps=5,
        max_new_tokens=1024,
    )

    context.record_attempt()
    context.record_tool("write_file")

    assert context.attempts == 1
    assert context.tool_steps == 1
    assert context.task_state.attempts == 1
    assert context.task_state.tool_steps == 1
    assert context.remaining_tool_steps == 4
    assert context.can_continue()


def test_run_context_uses_task_state_as_counter_truth():
    task_state = TaskState.create("task_1", "build project", run_id="run_1")
    context = RunContext.create(
        task_state=task_state,
        user_message="build project",
        max_steps=3,
        max_new_tokens=1024,
    )

    task_state.record_attempt()
    task_state.record_tool("read_file")

    assert context.attempts == 1
    assert context.tool_steps == 1
    assert context.remaining_tool_steps == 2
