from pico.core.run_context import RunContext
from pico.core.task_state import RunState, TaskState


def test_run_context_has_no_counter_fallback_fields():
    fields = set(RunContext.__dataclass_fields__)

    assert "_attempts" not in fields
    assert "_tool_steps" not in fields


def test_reduce_run_state_updates_core_counters():
    from pico.core.run_events import RunEvent
    from pico.core.run_reducer import reduce_run_state

    state = RunState.create(run_id="run_1", task_id="task_1", user_request="test")
    reduce_run_state(state, RunEvent("model_attempted"))
    reduce_run_state(state, RunEvent("tool_executed", {"name": "read_file"}))
    reduce_run_state(state, RunEvent("run_finished", {"final_answer": "done"}))

    assert state.attempts == 1
    assert state.tool_steps == 1
    assert state.last_tool == "read_file"
    assert state.final_answer == "done"
    assert state.stop_reason == "final_answer_returned"
    assert TaskState is RunState


def test_runtime_paths_use_run_events_for_counter_mutation():
    import inspect

    from pico.core.run_lifecycle import RunLifecycle
    from pico.core.runtime_engine import RuntimeEngine

    engine_source = inspect.getsource(RuntimeEngine.run)
    lifecycle_source = inspect.getsource(RunLifecycle.execute_tool_step)

    assert 'RunEvent("model_attempted"' in engine_source
    assert 'RunEvent("tool_executed"' in lifecycle_source
