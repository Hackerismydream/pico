import json
import sys
import time

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.core.task_state import TaskState
from pico.features import completion

PY = sys.executable


def build_agent(tmp_path, outputs, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    return Pico(
        model_client=kwargs.pop("model_client", FakeModelClient(outputs)),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy=kwargs.pop("approval_policy", "auto"),
        **kwargs,
    )


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_todo_tools_manage_task_ledger_and_require_single_in_progress(tmp_path):
    agent = build_agent(tmp_path, [])

    result = agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Build backend", "active_form": "Building backend", "status": "in_progress"},
                {"id": "task_2", "content": "Build frontend", "active_form": "Building frontend", "status": "pending"},
                {"id": "task_3", "content": "Run verification", "active_form": "Running verification", "status": "pending", "verification": True},
            ]
        },
    )

    assert "updated 3 tasks" in result
    assert agent.current_tasks()[0]["status"] == "in_progress"

    rejected = agent.run_tool("todo_update", {"id": "task_2", "status": "in_progress"})
    assert "only one task can be in_progress" in rejected

    listed = agent.run_tool("todo_list", {})
    assert "task_1 [in_progress]" in listed
    assert "task_3 [pending] verification" in listed


def test_implementation_task_completion_without_workspace_change_records_warning(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Implement backend API", "active_form": "Implementing backend API", "status": "in_progress"},
                {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "pending", "verification": True},
            ]
        },
    )

    result = agent.run_tool("todo_update", {"id": "task_1", "status": "completed"})

    assert "updated task_1 completed" in result
    assert "WARNING: implementation task has no new file-change evidence" in result
    assert agent.current_tasks()[0]["status"] == "completed"


def test_verification_task_completion_without_passed_verification_records_warning(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Inspect workspace", "active_form": "Inspecting workspace", "status": "completed"},
                {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "in_progress", "verification": True},
            ]
        },
    )

    result = agent.run_tool("todo_update", {"id": "task_2", "status": "completed"})

    assert "updated task_2 completed" in result
    assert "WARNING: verification task completed without passed structured verification evidence" in result
    assert agent.current_tasks()[1]["status"] == "completed"


def test_todo_write_can_replace_open_tasks_but_warns(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Implement backend", "active_form": "Implementing backend", "status": "in_progress"},
                {"id": "task_2", "content": "Build frontend", "active_form": "Building frontend", "status": "pending"},
                {"id": "task_3", "content": "Verify app", "active_form": "Verifying app", "status": "pending", "verification": True},
            ]
        },
    )

    result = agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "new_1", "content": "Continue app", "active_form": "Continuing app", "status": "in_progress"},
                {"id": "new_2", "content": "Verify app", "active_form": "Verifying app", "status": "pending", "verification": True},
            ]
        },
    )

    assert "updated 2 tasks" in result
    assert "WARNING: replaced open tasks: task_1, task_2, task_3" in result
    assert [task["id"] for task in agent.current_tasks()] == ["new_1", "new_2"]


def test_todo_write_cannot_regress_completed_tasks(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Build backend", "active_form": "Building backend", "status": "in_progress"},
                {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "pending", "verification": True},
            ]
        },
    )
    agent.run_tool("todo_update", {"id": "task_1", "status": "completed"})

    result = agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Read existing files", "active_form": "Reading existing files", "status": "in_progress"},
                {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "pending", "verification": True},
            ]
        },
    )

    assert "cannot regress completed task task_1" in result
    assert agent.current_tasks()[0]["status"] == "completed"


def test_todo_write_completion_without_evidence_records_warning(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Write README", "active_form": "Writing README", "status": "in_progress"},
                {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "pending", "verification": True},
            ]
        },
    )

    result = agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Write README", "active_form": "Writing README", "status": "completed"},
                {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "pending", "verification": True},
            ]
        },
    )

    assert "updated 2 tasks" in result
    assert "WARNING: task_1 completed without new file-change evidence" in result
    assert agent.current_tasks()[0]["status"] == "completed"


def test_todo_write_preserves_in_progress_task_starting_evidence_count(tmp_path):
    agent = build_agent(tmp_path, [])
    task_state = TaskState.create(task_id="task_test", run_id="run_test", user_request="Build frontend")
    agent.current_task_state = task_state
    agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Build frontend", "active_form": "Building frontend", "status": "in_progress"},
                {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "pending", "verification": True},
            ]
        },
    )
    task_state.changed_paths = ["static/index.html"]

    agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Build frontend", "active_form": "Building frontend", "status": "in_progress"},
                {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "pending", "verification": True},
            ]
        },
    )

    assert agent.current_tasks()[0]["metadata"]["started_changed_path_count"] == 0
    assert "updated task_1 completed" in agent.run_tool("todo_update", {"id": "task_1", "status": "completed"})


def test_complex_task_direct_file_write_emits_todo_reminder_but_executes(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"write_file","args":{"path":"app.py","content":"print(1)\\n"}}</tool>',
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Create app","active_form":"Creating app","status":"in_progress"},{"id":"task_2","content":"Run verification","active_form":"Running verification","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"app.py","content":"print(1)\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            f'<tool>{{"name":"run_shell","args":{{"command":"{PY} app.py","timeout":20}}}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_2","status":"completed"}}</tool>',
            "<final>Created and verified.</final>",
        ],
        max_steps=8,
    )

    answer = agent.ask("Create a small frontend backend student management system with tests")

    assert answer == "Created and verified."
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "print(1)\n"
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    assert "runtime_reminder_emitted" in [event["event"] for event in trace]
    executed_writes = [event for event in trace if event["event"] == "tool_executed" and event.get("name") == "write_file"]
    assert len(executed_writes) == 2
    assert agent.current_task_state.stage == "completed"


def test_complex_task_reminds_todo_after_bounded_read_only_exploration(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":5}}</tool>',
            '<tool>{"name":"list_files","args":{"path":".pico"}}</tool>',
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Create app","active_form":"Creating app","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            "<final>Stopped for test.</final>",
        ],
        max_steps=8,
    )

    agent.ask("Build a full-stack app with API, UI, README, and verification")

    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    executed_list_calls = [event for event in trace if event["event"] == "tool_executed" and event.get("name") == "list_files"]
    executed_reads = [event for event in trace if event["event"] == "tool_executed" and event.get("name") == "read_file"]
    assert len(executed_list_calls) == 2
    assert len(executed_reads) == 1
    assert any(event["event"] == "runtime_reminder_emitted" and event.get("reason") == "todo_missing_after_exploration" for event in trace)


def test_runtime_reminders_are_rate_limited_by_reason(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":5}}</tool>',
            '<tool>{"name":"list_files","args":{"path":".pico"}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":5}}</tool>',
            "<final>Stopped for test.</final>",
        ],
        max_steps=8,
    )

    agent.ask("Build a full-stack app with API, UI, README, and verification")

    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    reminders = [
        event
        for event in trace
        if event["event"] == "runtime_reminder_emitted" and event.get("reason") == "todo_missing_after_exploration"
    ]
    assert len(reminders) == 1


def test_in_progress_implementation_task_reminds_status_update_after_two_write_batches(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Build frontend","active_form":"Building frontend","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"a.html","content":"a\\n"}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"b.css","content":"b\\n"}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"c.js","content":"c\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            "<final>Stopped for test.</final>",
        ],
        max_steps=10,
    )

    agent.ask("Build a frontend and verify it")

    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    executed_writes = [event for event in trace if event["event"] == "tool_executed" and event.get("name") == "write_file"]
    assert len(executed_writes) == 3
    assert any(event["event"] == "runtime_reminder_emitted" and event.get("reason") == "task_status_stale" for event in trace)


def test_repeated_stale_read_after_runtime_reminder_is_rejected(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Build frontend","active_form":"Building frontend","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"index.html","content":"<html></html>\\n"}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"style.css","content":"body{}\\n"}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"index.html","start":1,"end":20}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"index.html","start":1,"end":20}}</tool>',
            "<final>Stopped.</final>",
        ],
        max_steps=8,
    )

    agent.ask("Build frontend and verify")

    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    rejected_reads = [
        event
        for event in trace
        if event.get("event") == "tool_executed"
        and event.get("name") == "read_file"
        and event.get("tool_error_code") == "progress_guard_stale_task"
    ]
    assert rejected_reads


def test_in_progress_implementation_task_reminds_write_after_bounded_inspection(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Build frontend","active_form":"Building frontend","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"todo_list","args":{}}</tool>',
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"index.html","content":"ok\\n"}}</tool>',
            "<final>Stopped for test.</final>",
        ],
        max_steps=10,
    )

    agent.ask("Build a frontend and verify it")

    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    executed_list_calls = [event for event in trace if event["event"] == "tool_executed" and event.get("name") == "list_files"]
    assert len(executed_list_calls) == 2
    assert any(event["event"] == "runtime_reminder_emitted" and event.get("reason") == "implementation_needs_file_evidence" for event in trace)


def test_in_progress_implementation_task_allows_noop_todo_rewrite_with_reminder(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Write guide","active_form":"Writing guide","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Write guide","active_form":"Writing guide","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"GUIDE.md","content":"# App\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            f'<tool>{{"name":"run_shell","args":{{"command":"{PY} -c \\"print(1)\\"","timeout":20}}}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_2","status":"completed"}}</tool>',
            "<final>Done.</final>",
        ],
        max_steps=8,
    )

    answer = agent.ask("Build an app with README and verification")

    assert answer == "Done."
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    executed_todo_writes = [
        event for event in trace
        if event.get("event") == "tool_executed" and event.get("name") == "todo_write"
    ]
    assert len(executed_todo_writes) == 2
    assert any(event["event"] == "runtime_reminder_emitted" and event.get("reason") == "todo_rewrite_without_progress" for event in trace)
    assert (tmp_path / "GUIDE.md").read_text() == "# App\n"


def test_final_answer_after_file_change_is_blocked_until_verified(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Create app","active_form":"Creating app","status":"in_progress"},{"id":"task_2","content":"Run verification","active_form":"Running verification","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"app.py","content":"print(1)\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            "<final>Done.</final>",
            f'<tool>{{"name":"run_shell","args":{{"command":"{PY} app.py","timeout":20}}}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_2","status":"completed"}}</tool>',
            "<final>Done after verification.</final>",
        ],
        max_steps=8,
    )

    answer = agent.ask("Create an app and verify it")

    assert answer == "Done after verification."
    assert agent.current_task_state.completion_gate["blocked"] is False
    assert agent.current_task_state.completion_gate["status"] == "completed"
    assert agent.current_task_state.verifications
    report = json.loads(agent.run_store.report_path(agent.current_task_state).read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert report["final_status"] == "completed"
    assert report["completion_assessment"]["status"] == "completed"
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    assert "completion_assessed" in [event["event"] for event in trace]
    assert "completion_gate_blocked" in [event["event"] for event in trace]


def test_complex_tasks_get_adaptive_step_budget_before_stopping(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Create backend","active_form":"Creating backend","status":"in_progress"},{"id":"task_2","content":"Create frontend","active_form":"Creating frontend","status":"pending"},{"id":"task_3","content":"Write README","active_form":"Writing README","status":"pending"},{"id":"task_4","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"backend.py","content":"print(42)\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_2","status":"in_progress"}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"frontend.html","content":"ok\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_2","status":"completed"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_3","status":"in_progress"}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":20}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"README.md","content":"done\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_3","status":"completed"}}</tool>',
            f'<tool>{{"name":"run_shell","args":{{"command":"{PY} backend.py","timeout":20}}}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_4","status":"completed"}}</tool>',
            "<final>Done with verification.</final>",
        ],
        max_steps=6,
    )

    answer = agent.ask("Build a full-stack app with backend, frontend, README, and verification")

    assert answer == "Done with verification."
    assert agent.current_task_state.tool_steps > 6
    assert agent.effective_max_steps("Build a full-stack app with backend, frontend, README, and verification") >= 30
    assert agent.current_task_state.status == "completed"


def test_failed_verification_sets_repairing_until_later_passes(tmp_path):
    agent = build_agent(tmp_path, [])

    failed = agent.run_tool("run_shell", {"command": f"{PY} -c 'import sys; sys.exit(2)'", "timeout": 20})
    assert "exit_code: 2" in failed
    assert agent.current_task_state is None or agent._last_tool_result_metadata["verification"]["status"] == "failed"

    passed = agent.run_tool("run_shell", {"command": f"{PY} -c 'print(42)'", "timeout": 20})
    assert "exit_code: 0" in passed
    assert agent._last_tool_result_metadata["verification"]["status"] == "passed"


def test_provider_length_finish_reason_triggers_truncation_recovery(tmp_path):
    class LengthThenFinal(FakeModelClient):
        def complete(self, prompt, max_new_tokens, **kwargs):
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                self.last_completion_metadata = {"finish_reason": "length", "output_tokens": max_new_tokens}
                return '<tool name="write_file" path="broken.py"><content>print("unterminated'
            self.last_completion_metadata = {"finish_reason": "stop", "output_tokens": 4}
            return "<final>Recovered.</final>"

    agent = build_agent(tmp_path, [], model_client=LengthThenFinal([]), max_steps=2, max_new_tokens=16)

    answer = agent.ask("Handle truncated provider output")

    assert answer == "Recovered."
    assert len(agent.model_client.prompts) == 2
    assert not (tmp_path / "broken.py").exists()
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    recovery_events = [event for event in trace if event["event"] == "truncation_recovered"]
    assert recovery_events
    assert recovery_events[0]["next_max_new_tokens"] > 16


def test_recoverable_empty_provider_text_retries_before_stopping(tmp_path):
    class EmptyThenFinal(FakeModelClient):
        def complete(self, prompt, max_new_tokens, **kwargs):
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                self.last_completion_metadata = {"finish_reason": "stop", "output_tokens": 0}
                raise RuntimeError("OpenAI-compatible chat fallback error: could not extract text from response")
            self.last_completion_metadata = {"finish_reason": "stop", "output_tokens": 4}
            return "<final>Recovered.</final>"

    agent = build_agent(tmp_path, [], model_client=EmptyThenFinal([]), max_steps=2)

    answer = agent.ask("Explain status")

    assert answer == "Recovered."
    assert len(agent.model_client.prompts) == 2
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    assert "model_error_recovered" in [event["event"] for event in trace]


def test_model_error_stops_cleanly_and_writes_report(tmp_path):
    class RaisingModelClient:
        supports_prompt_cache = False

        def __init__(self):
            self.last_completion_metadata = {"provider_transport": "test"}

        def complete(self, prompt, max_new_tokens, **kwargs):
            self.last_completion_metadata = {"provider_transport": "test"}
            raise RuntimeError("provider timed out after 1s")

    agent = build_agent(tmp_path, [], model_client=RaisingModelClient(), max_steps=1)

    answer = agent.ask("Create a small app")

    assert "Stopped after model error: provider timed out after 1s" == answer
    assert agent.current_task_state.status == "failed"
    assert agent.current_task_state.stop_reason == "model_error"
    report = json.loads(agent.run_store.report_path(agent.current_task_state).read_text(encoding="utf-8"))
    assert report["task_state"]["stop_reason"] == "model_error"
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    assert "model_error" in [event["event"] for event in trace]
    assert trace[-1]["event"] == "run_finished"


def test_model_call_hard_deadline_stops_hanging_provider(tmp_path):
    class HangingModelClient:
        supports_prompt_cache = False
        timeout = 0.1

        def __init__(self):
            self.last_completion_metadata = {}

        def complete(self, prompt, max_new_tokens, **kwargs):
            time.sleep(5)
            return "<final>late</final>"

    agent = build_agent(tmp_path, [], model_client=HangingModelClient(), max_steps=1)

    started = time.monotonic()
    answer = agent.ask("Say hi")
    duration = time.monotonic() - started

    assert duration < 1
    assert "model request timed out after 0.1s" in answer
    assert agent.current_task_state.stop_reason == "model_error"


def test_repeated_reads_of_changed_files_emit_warning_but_execute(tmp_path):
    agent = build_agent(tmp_path, [])
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    agent.current_task_state = TaskState.create(task_id="task_test", run_id="run_test", user_request="Create app")
    agent.current_task_state.changed_paths = ["app.py"]
    agent.record({"role": "tool", "name": "list_files", "args": {"path": "."}, "content": "read", "created_at": "now"})
    agent.record({"role": "tool", "name": "read_file", "args": {"path": "README.md"}, "content": "read", "created_at": "now"})

    result = agent.run_tool("read_file", {"path": "app.py"})

    assert "# app.py" in result
    assert agent._last_tool_result_metadata["tool_status"] == "ok"
    assert "rereading a file changed in this run" in "\n".join(agent._last_tool_result_metadata.get("runtime_warnings", []))


def test_existing_file_write_requires_fresh_prior_read(tmp_path):
    agent = build_agent(tmp_path, [])
    (tmp_path / "app.py").write_text("print('old')\n", encoding="utf-8")

    rejected = agent.run_tool("write_file", {"path": "app.py", "content": "print('new')\n"})

    assert "requires prior read_file" in rejected
    assert 'Next tool: read_file with path "app.py"' in rejected
    assert agent._last_tool_result_metadata["tool_error_code"] == "prior_read_required"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "print('old')\n"

    assert "# app.py" in agent.run_tool("read_file", {"path": "app.py", "start": 1, "end": 1})
    (tmp_path / "app.py").write_text("print('external')\n", encoding="utf-8")

    stale = agent.run_tool("write_file", {"path": "app.py", "content": "print('new')\n"})

    assert "requires a fresh read_file" in stale
    assert 'Next tool: read_file with path "app.py"' in stale
    assert agent._last_tool_result_metadata["tool_error_code"] == "stale_prior_read"


def test_prior_read_rejection_emits_recovery_reminder(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"write_file","args":{"path":"README.md","content":"new\\n"}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":20}}</tool>',
            "<final>stopped</final>",
        ],
        max_steps=4,
    )

    agent.ask("Update README and verify")

    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    reminders = [event for event in trace if event["event"] == "runtime_reminder_emitted"]
    assert any(event.get("reason") == "tool_rejection_recovery" for event in reminders)
    assert any("read_file" in event.get("message", "") for event in reminders)


def test_prompt_includes_current_runtime_state(tmp_path):
    agent = build_agent(tmp_path, [])
    state = TaskState.create(task_id="task_test", run_id="run_test", user_request="Build app")
    state.changed_paths = ["backend.py"]
    state.artifact_graph = {"summary": {"backend": 1, "frontend": 0}, "api": {"backend_routes": ["/students"], "frontend_references": []}}
    state.verification_plan = {"suggested_commands": [{"command": "uv run python -m compileall .", "reason": "python files changed"}]}
    agent.current_task_state = state
    agent.set_tasks(
        [
            {"id": "task_1", "content": "Build backend", "active_form": "Building backend", "status": "completed"},
            {"id": "task_2", "content": "Build frontend", "active_form": "Building frontend", "status": "in_progress"},
        ]
    )

    prompt = agent.prompt("Continue")

    assert "Runtime state:" in prompt
    assert "task_1 [completed]" in prompt
    assert "Changed paths: backend.py" in prompt
    assert "Suggested verification: uv run python -m compileall ." in prompt


def test_step_limit_report_assesses_completion_quality(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"write_file","args":{"path":"app.py","content":"print(1)\\n"}}</tool>',
        ],
        max_steps=1,
    )
    agent.effective_max_steps = lambda _message: 1

    answer = agent.ask("Build backend and frontend with verification")

    assert "step limit" in answer
    report = json.loads(agent.run_store.report_path(agent.current_task_state).read_text(encoding="utf-8"))
    assert report["final_status"] != "running"
    assert report["completion_assessment"]["status"] in {"incomplete", "unverified", "completed_with_warnings"}


def test_verification_artifact_contains_structured_evidence_checks(tmp_path):
    agent = build_agent(tmp_path, [])

    result = agent.run_tool("run_shell", {"command": f"{PY} -c 'print(42)'", "timeout": 20})

    verification = agent._last_tool_result_metadata["verification"]
    assert "exit_code: 0" in result
    assert verification["status"] == "passed"
    assert verification["checks"][0]["command"] == f"{PY} -c 'print(42)'"
    assert verification["checks"][0]["result"] == "PASS"
    assert "42" in verification["checks"][0]["output_observed"]
    assert verification["checks"][0]["adversarial_probe"] is False


def test_passed_verification_artifact_completes_open_verification_task(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Build app","active_form":"Building app","status":"completed"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"in_progress","verification":true}]}}</tool>',
            f'<tool>{{"name":"run_shell","args":{{"command":"{PY} -c \\"print(42)\\"","timeout":20}}}}</tool>',
            "<final>Verified.</final>",
        ],
        max_steps=5,
    )

    agent.ask("Build and verify app")

    tasks = agent.current_task_state.tasks
    assert tasks[1]["status"] == "completed"
    assert tasks[1]["metadata"]["auto_completed_by_verification"] is True


def test_completion_assessment_warns_about_verification_without_evidence_checks(tmp_path):
    agent = build_agent(tmp_path, [])
    task_state = TaskState.create(task_id="task_test", run_id="run_test", user_request="Create and verify app")
    task_state.changed_paths = ["app.py"]
    task_state.verifications = [
        {"command": "python app.py", "exit_code": 0, "status": "passed", "summary": "ok", "created_at": "now"}
    ]
    agent.current_task_state = task_state

    gate = agent.completion_gate(task_state, "Create and verify app")

    assert gate["blocked"] is False
    assert gate["status"] == "unverified"
    assert "record structured verification evidence" in gate["warnings"]


def test_completion_gate_uses_generic_structured_verification_not_stack_specific_smoke(tmp_path):
    (tmp_path / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "app.js").write_text("fetch('/api/students')\n", encoding="utf-8")
    agent = build_agent(tmp_path, [])
    task_state = TaskState.create(task_id="task_test", run_id="run_test", user_request="Build FastAPI backend and frontend API")
    task_state.tasks = [
        {"id": "task_1", "content": "Build app", "active_form": "Building app", "status": "completed"},
        {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "completed", "verification": True},
    ]
    agent.set_tasks(task_state.tasks)
    task_state.changed_paths = ["app.py", "static/app.js"]
    task_state.verifications = [
        {
            "command": "grep -n fetch static/app.js && python -m py_compile app.py",
            "exit_code": 0,
            "status": "passed",
            "summary": "syntax ok",
            "checks": [
                {
                    "command": "grep -n fetch static/app.js && python -m py_compile app.py",
                    "expected": "command exits with code 0",
                    "output_observed": "fetch('/api/students')",
                    "result": "PASS",
                    "adversarial_probe": False,
                }
            ],
        }
    ]
    agent.current_task_state = task_state

    gate = agent.completion_gate(task_state, "Build FastAPI backend and frontend API")

    assert gate["blocked"] is False
    assert "run API smoke verification" not in gate["reasons"]


def test_route_text_check_is_not_special_cased_as_api_smoke(tmp_path):
    (tmp_path / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "app.js").write_text("const apiPath = '/api/students';\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Run uvicorn app:app --reload\n", encoding="utf-8")
    agent = build_agent(tmp_path, [])
    task_state = TaskState.create(task_id="task_test", run_id="run_test", user_request="Build FastAPI backend and frontend API")
    task_state.changed_paths = ["app.py", "static/app.js", "README.md"]
    task_state.verifications = [
        {
            "command": "python -m py_compile app.py && python - <<'PY'\nprint('uvicorn app:app --reload')\nprint('/api/students')\nPY",
            "exit_code": 0,
            "status": "passed",
            "summary": "ok",
            "checks": [
                {
                    "command": "python -m py_compile app.py && python - <<'PY'\nprint('uvicorn app:app --reload')\nprint('/api/students')\nPY",
                    "expected": "command exits with code 0",
                    "output_observed": "uvicorn app:app --reload\n/api/students",
                    "result": "PASS",
                    "adversarial_probe": False,
                }
            ],
        }
    ]
    agent.current_task_state = task_state
    agent.set_tasks(
        [
            {"id": "task_1", "content": "Build app", "active_form": "Building app", "status": "completed"},
            {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "completed", "verification": True},
        ]
    )

    gate = agent.completion_gate(task_state, "Build FastAPI backend and frontend API")

    assert gate["blocked"] is False
    assert "run API smoke verification" not in gate["reasons"]


def test_verification_task_accepts_structured_evidence_without_stack_specific_gate(tmp_path):
    (tmp_path / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "app.js").write_text("fetch('/api/students')\n", encoding="utf-8")
    agent = build_agent(tmp_path, [])
    task_state = TaskState.create(task_id="task_test", run_id="run_test", user_request="Build FastAPI backend and frontend API")
    task_state.changed_paths = ["app.py", "static/app.js"]
    task_state.verifications = [
        {
            "command": "grep -n fetch static/app.js && python -m py_compile app.py",
            "exit_code": 0,
            "status": "passed",
            "summary": "syntax ok",
            "checks": [
                {
                    "command": "grep -n fetch static/app.js && python -m py_compile app.py",
                    "expected": "command exits with code 0",
                    "output_observed": "fetch('/api/students')",
                    "result": "PASS",
                    "adversarial_probe": False,
                }
            ],
        }
    ]
    agent.current_task_state = task_state
    agent.run_tool(
        "todo_write",
        {
            "todos": [
                {"id": "task_1", "content": "Build app", "active_form": "Building app", "status": "completed"},
                {"id": "task_2", "content": "Verify app", "active_form": "Verifying app", "status": "in_progress", "verification": True},
            ]
        },
    )

    result = agent.run_tool("todo_update", {"id": "task_2", "status": "completed"})

    assert "updated task_2 completed" in result
    assert agent.current_tasks()[1]["status"] == "completed"


def test_completion_gate_does_not_hard_block_missing_referenced_frontend_asset(tmp_path):
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text(
        '<!doctype html><script src="/static/app.js"></script>\n',
        encoding="utf-8",
    )
    agent = build_agent(tmp_path, [])
    task_state = TaskState.create(task_id="task_test", run_id="run_test", user_request="Build frontend")
    task_state.changed_paths = ["static/index.html"]
    task_state.verifications = [
        {
            "command": "python -m py_compile main.py",
            "exit_code": 0,
            "status": "passed",
            "summary": "ok",
            "checks": [
                {
                    "command": "python -m py_compile main.py",
                    "expected": "command exits with code 0",
                    "output_observed": "ok",
                    "result": "PASS",
                    "adversarial_probe": False,
                }
            ],
        }
    ]
    agent.current_task_state = task_state
    agent.set_tasks(
        [
            {"id": "task_1", "content": "Build frontend", "active_form": "Building frontend", "status": "completed"},
            {"id": "task_2", "content": "Verify frontend", "active_form": "Verifying frontend", "status": "completed", "verification": True},
        ]
    )

    gate = agent.completion_gate(task_state, "Build frontend")

    assert gate["blocked"] is False
    assert "create referenced frontend assets" not in gate["reasons"]


def test_complex_request_detection_is_generic_not_student_template():
    assert completion.is_complex_request("Build a small CRM with API, UI, README, and verification")
    assert completion.is_complex_request("做一个订单管理系统，包含接口、页面、数据存储和验收")
    assert not completion.is_complex_request("Explain why a student management system is hard")


def test_malformed_tool_retry_records_parse_error_type(tmp_path):
    agent = build_agent(tmp_path, ['<tool>{"name":"read_file","args":"bad"}</tool>', "<final>Recovered.</final>"])

    answer = agent.ask("trigger malformed tool")

    assert answer == "Recovered."
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    parsed = [event for event in trace if event["event"] == "model_parsed"]
    assert any(event.get("parse_error_type") == "invalid_tool_args" for event in parsed)
