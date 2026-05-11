import inspect
from types import SimpleNamespace

from pico import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from pico.core.run_context import RunContext
from pico.core.task_state import RunState


def test_runtime_engine_boundary_types_exist():
    from pico.core.runtime_engine import CompletionTurnResult, RunRequest, RunResult, RuntimeEngine, RuntimeHost

    assert RuntimeEngine is not None
    assert RuntimeHost is not None
    result = CompletionTurnResult(text="<final>ok</final>", metadata={"finish_reason": "stop"})
    assert result.text == "<final>ok</final>"
    assert result.metadata["finish_reason"] == "stop"
    assert RunRequest(user_message="hi", raw_user_message="hi") is not None
    assert RunResult(final_answer="ok").final_answer == "ok"


def test_pico_ask_is_facade_without_runtime_loop():
    import pico.core.agent as agent_module

    source = inspect.getsource(agent_module.Pico.ask)

    assert "while run_context.can_continue()" not in source
    assert "RuntimeEngine" in source
    assert len(source.splitlines()) <= 90


def test_pico_ask_runs_through_runtime_engine(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    agent = MiniAgent(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
    )

    assert agent.ask("say ok") == "ok"
    assert agent.current_task_state.stop_reason == "final_answer_returned"


def test_runtime_engine_runs_against_minimal_host_protocol():
    from pico.core.runtime_engine import CompletionTurnResult, RunRequest, RuntimeEngine

    class Host:
        def __init__(self):
            self.records = []
            self.traces = []
            self.writes = 0

        def build_prompt_for_turn(self, user_message):
            return f"prompt: {user_message}", {}

        def auto_compact_history(self, prompt_metadata):
            return {"compacted": False}

        def complete_model_turn(self, prompt, max_new_tokens, **kwargs):
            return CompletionTurnResult("<final>ok</final>", {"finish_reason": "stop"})

        def parse_with_metadata(self, raw):
            return ("final", "ok", "")

        def execute_tool_request(self, *args, **kwargs):
            raise AssertionError("tool should not execute")

        def finish_run(self, task_state, user_message, final, run_started_at, **kwargs):
            self.records.append({"role": "assistant", "content": final})
            return final

        def emit_trace(self, task_state, event, payload=None):
            self.traces.append(event)

        def record(self, item):
            self.records.append(dict(item))

        def write_task_state(self, task_state):
            self.writes += 1

        def drain_subagent_notifications(self):
            return None

        def create_checkpoint(self, task_state, user_message, trigger):
            return {"checkpoint_id": f"ckpt_{trigger}"}

        def is_recoverable_model_error(self, exc):
            return False

        def is_truncated_completion(self, metadata):
            return False

        def record_control_decision(self, task_state, phase, decision):
            return None

        def supports_prompt_cache(self):
            return False

        def set_prompt_metadata(self, metadata):
            self.prompt_metadata = dict(metadata)

        def model_error_metadata(self, exc):
            return {"finish_reason": "error", "error_type": exc.__class__.__name__, "error_message": str(exc)}

        def before_tool(self, task_state, name, args, user_message):
            raise AssertionError("tool control should not run")

        def before_final(self, task_state, final, user_message):
            return SimpleNamespace(action="allow", metadata={}, to_dict=lambda: {})

        def runtime_reminder_once(self, reason):
            return True

    state = RunState.create(run_id="run_1", task_id="task_1", user_request="say ok")
    context = RunContext.create(state, "say ok", max_steps=2, max_new_tokens=128)
    host = Host()

    result = RuntimeEngine().run(host, state, context, RunRequest(user_message="say ok"))

    assert result.final_answer == "ok"
    assert state.stop_reason == "final_answer_returned"
    assert "model_requested" in host.traces
