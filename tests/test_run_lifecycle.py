import inspect

from pico.core.run_context import RunContext
from pico.core.run_reducer import reduce_run_state
from pico.core.task_state import RunState
from pico.core.tool_runner import ToolExecutionResult
from pico.tools.spec import Effect


def test_run_lifecycle_boundary_exists():
    from pico.core.run_lifecycle import RunLifecycle

    lifecycle = RunLifecycle()
    assert lifecycle is not None
    assert callable(lifecycle.execute_tool_step)
    assert callable(lifecycle.finish_run)


def test_pico_lifecycle_methods_are_wrappers():
    import pico.core.agent as agent_module

    execute_source = inspect.getsource(agent_module.Pico._execute_tool_step)
    finish_source = inspect.getsource(agent_module.Pico._finish_run)

    assert "RunLifecycle" in execute_source or "run_lifecycle" in execute_source
    assert "RunLifecycle" in finish_source or "run_lifecycle" in finish_source
    assert len(execute_source.splitlines()) <= 30
    assert len(finish_source.splitlines()) <= 30


class _LifecycleFakeHost:
    def __init__(self):
        self.applied_events = []
        self.persisted_states = []
        self.records = []
        self.traces = []
        self.runtime_events = []

    def __getattr__(self, name):
        if name == "_last_tool_result_metadata":
            raise AssertionError("RunLifecycle must not read tool metadata from a Pico side channel")
        if name == "current_tasks":
            raise AssertionError("RunLifecycle must not call current_tasks() to mutate RunState")
        if name == "run_tool":
            raise AssertionError("RunLifecycle must execute tools through ToolExecutionResult")
        raise AttributeError(name)

    def execute_tool(self, name, args):
        assert name == "write_file"
        return ToolExecutionResult(
            content="wrote src/app.py",
            effects={Effect.WORKSPACE_WRITE},
            metadata={
                "tool_status": "ok",
                "tool_error_code": "",
                "affected_paths": ["src/app.py"],
                "workspace_changed": True,
                "diff_summary": [{"path": "src/app.py", "status": "modified"}],
                "verification": {"command": "pytest", "status": "passed", "summary": "1 passed"},
                "artifact_relpath": "tool_artifacts/write_file.txt",
                "effective_effects": ["workspace_write"],
            },
        )

    def apply_run_events(self, task_state, events):
        for event in events:
            self.applied_events.append(event)
            reduce_run_state(task_state, event)

    def task_ledger_snapshot(self):
        return [{"id": "task-1", "content": "write app", "status": "completed"}]

    def artifact_state_for_run(self, task_state):
        return {
            "artifact_graph": {"summary": {"files": len(task_state.changed_paths or [])}},
            "verification_plan": {"suggested_commands": [{"command": "pytest"}]},
        }

    def persist_run_state(self, task_state):
        self.persisted_states.append(task_state.to_dict())

    def emit_runtime_event(self, event, payload):
        self.runtime_events.append((event, payload))

    def record(self, item):
        self.records.append(dict(item))

    def emit_trace(self, task_state, event, payload=None):
        self.traces.append((event, dict(payload or {})))

    def drain_subagent_notifications(self):
        return None

    def create_checkpoint(self, task_state, user_message, trigger):
        return {"checkpoint_id": f"chk-{trigger}"}


def test_run_lifecycle_applies_tool_execution_through_run_events():
    from pico.core.run_lifecycle import RunLifecycle

    host = _LifecycleFakeHost()
    state = RunState.create(run_id="run_1", task_id="task_1", user_request="write app")
    context = RunContext.create(task_state=state, user_message="write app", max_steps=5, max_new_tokens=1000)

    result = RunLifecycle().execute_tool_step(host, state, context, "write app", "write_file", {"path": "src/app.py"})

    assert result == "wrote src/app.py"
    assert state.tool_steps == 1
    assert state.changed_paths == ["src/app.py"]
    assert state.verifications == [
        {"command": "pytest", "status": "passed", "summary": "1 passed", "checked_paths": ["src/app.py"]}
    ]
    assert state.tasks == [{"id": "task-1", "content": "write app", "status": "completed"}]
    assert state.artifact_graph == {"summary": {"files": 1}}
    assert state.verification_plan == {"suggested_commands": [{"command": "pytest"}]}
    assert state.checkpoint_id == "chk-tool_executed"
    assert [event.type for event in host.applied_events] == [
        "tool_executed",
        "changed_paths_recorded",
        "task_list_updated",
        "verification_recorded",
        "artifact_graph_updated",
        "verification_plan_updated",
        "checkpoint_created",
    ]
    assert host.persisted_states
