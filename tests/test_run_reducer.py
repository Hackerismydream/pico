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


def test_reduce_run_state_golden_core_snapshot():
    from pico.core.run_events import RunEvent
    from pico.core.run_reducer import reduce_run_state

    state = RunState.create(run_id="run_1", task_id="task_1", user_request="build")
    events = [
        RunEvent("model_attempted"),
        RunEvent("model_attempted"),
        RunEvent("tool_executed", {"name": "write_file"}),
        RunEvent("changed_paths_recorded", {"paths": ["app.py", "app.py", "README.md"]}),
        RunEvent("task_list_updated", {"tasks": [{"id": "1", "status": "completed"}]}),
        RunEvent("verification_recorded", {"verification": {"command": "pytest", "status": "passed"}}),
        RunEvent("artifact_graph_updated", {"artifact_graph": {"summary": {"backend": 1}}}),
        RunEvent("verification_plan_updated", {"verification_plan": {"suggested_commands": [{"command": "pytest"}]}}),
        RunEvent("completion_gate_updated", {"completion_gate": {"blocked": False, "status": "completed"}}),
        RunEvent("checkpoint_created", {"checkpoint_id": "chk_1"}),
        RunEvent("run_finished", {"final_answer": "done"}),
    ]

    for event in events:
        reduce_run_state(state, event)

    assert state.attempts == 2
    assert state.tool_steps == 1
    assert state.last_tool == "write_file"
    assert state.changed_paths == ["app.py", "README.md"]
    assert state.tasks == [{"id": "1", "status": "completed"}]
    assert state.verifications == [{"command": "pytest", "status": "passed"}]
    assert state.artifact_graph == {"summary": {"backend": 1}}
    assert state.verification_plan == {"suggested_commands": [{"command": "pytest"}]}
    assert state.completion_gate == {"blocked": False, "status": "completed"}
    assert state.checkpoint_id == "chk_1"
    assert state.final_answer == "done"
    assert state.status == "completed"
