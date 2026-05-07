import json
import sys

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.features.artifacts import build_artifact_graph
from pico.features.verifier_driver import build_verification_plan, select_verification_action

PY = sys.executable


def build_agent(tmp_path, outputs, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    return Pico(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy=kwargs.pop("approval_policy", "auto"),
        **kwargs,
    )


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_completion_gate_blocks_final_until_verification_evidence_exists(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Create app","active_form":"Creating app","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"app.py","content":"print(1)\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            "<final>Done.</final>",
            f'<tool>{{"name":"run_shell","args":{{"command":"{PY} app.py","timeout":20}}}}</tool>',
            "<final>Done after verification.</final>",
        ],
        max_steps=8,
    )

    answer = agent.ask("Create an app and verify it")

    assert answer == "Done after verification."
    assert agent.current_task_state.status == "completed"
    assert agent.current_task_state.completion_gate["status"] == "completed"
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    blocked = [event for event in trace if event["event"] == "completion_gate_blocked"]
    assert blocked
    assert "run a real verification command before final answer" in blocked[0]["decision"]["message"]


def test_completion_gate_blocks_final_while_task_ledger_has_open_items(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Create backend","active_form":"Creating backend","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            "<final>Done.</final>",
            '<tool>{"name":"write_file","args":{"path":"backend.py","content":"print(42)\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            f'<tool>{{"name":"run_shell","args":{{"command":"{PY} backend.py","timeout":20}}}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_2","status":"completed"}}</tool>',
            "<final>Done after cleanup.</final>",
        ],
        max_steps=6,
    )

    answer = agent.ask("Build backend and verify it")

    assert answer == "Done after cleanup."
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    assert any(
        event["event"] == "completion_gate_blocked"
        and "complete or unblock all task ledger items" in event["decision"]["message"]
        for event in trace
    )


def test_completion_gate_blocks_complex_final_without_progress(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            "<final>I started the task ledger and will inspect next.</final>",
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Create tracker","active_form":"Creating tracker","status":"in_progress"},{"id":"task_2","content":"Verify tracker","active_form":"Verifying tracker","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"student_tracker.py","content":"def add_student(students, name):\\n    students.append(name)\\n    return students\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            f'<tool>{{"name":"run_shell","args":{{"command":"{PY} -m py_compile student_tracker.py","timeout":20}}}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_2","status":"completed"}}</tool>',
            "<final>Done after real progress.</final>",
        ],
        max_steps=8,
    )

    answer = agent.ask("Create a tiny Python student tracker with tests and verification")

    assert answer == "Done after real progress."
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    assert any(
        event["event"] == "completion_gate_blocked"
        and "create a todo list first with todo_write" in event["decision"]["message"]
        for event in trace
    )
    assert (tmp_path / "student_tracker.py").exists()


def test_completion_gate_forces_workspace_inspection_before_final(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    agent = build_agent(
        tmp_path,
        [
            "<final>我先看一下当前仓库的文件结构。</final>",
            "<final>当前仓库里有 README.md。</final>",
        ],
        max_steps=4,
    )

    answer = agent.ask("你看下当前仓库有啥")

    assert answer == "当前仓库里有 README.md。"
    tool_events = [item for item in agent.session["history"] if item["role"] == "tool"]
    assert tool_events[0]["name"] == "list_files"
    assert "README.md" in tool_events[0]["content"]
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    assert any(
        event["event"] == "completion_gate_blocked"
        and "inspect workspace with list_files before final answer" in event["decision"]["message"]
        for event in trace
    )


def test_completion_gate_does_not_turn_incidental_todo_into_read_only_deadlock(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Inspect repo","active_form":"Inspecting repo","status":"in_progress"}]}}</tool>',
            "<final>我先看一下当前仓库。</final>",
            "<final>当前仓库里有 README.md。</final>",
        ],
        max_steps=4,
    )

    answer = agent.ask("你看下当前仓库有啥")

    assert answer == "当前仓库里有 README.md。"
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    blocked = [event for event in trace if event["event"] == "completion_gate_blocked"]
    assert len(blocked) == 1
    assert "inspect workspace with list_files before final answer" in blocked[0]["decision"]["message"]
    assert "complete or unblock all task ledger items" not in blocked[0]["decision"]["message"]
    assert any(event["event"] == "tool_executed" and event["name"] == "list_files" for event in trace)


def test_verifier_driver_builds_generic_plan_from_artifacts(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\n", encoding="utf-8")
    (tmp_path / "backend.py").write_text('@app.get("/api/students")\ndef list(): pass\n@app.get("/api/students/{student_id}")\ndef read(): pass\n', encoding="utf-8")
    (tmp_path / "frontend.js").write_text('fetch("http://localhost:8000/api/students/123")\n', encoding="utf-8")

    graph = build_artifact_graph(tmp_path, ["requirements.txt", "backend.py", "frontend.js"])
    plan = build_verification_plan(tmp_path, graph, verifications=[])

    requirement_ids = [item["id"] for item in plan["requirements"]]
    assert "python_syntax_or_tests" in requirement_ids
    assert "api_consistency" in requirement_ids
    assert any(item["id"] == "api_consistency" and item["status"] == "passed" for item in plan["static_checks"])
    assert any("compileall" in item["command"] for item in plan["suggested_commands"])
    assert "student manager" not in json.dumps(plan).lower()
    assert "student management" not in json.dumps(plan).lower()
    assert "fastapi smoke" not in json.dumps(plan).lower()


def test_verifier_driver_marks_api_mismatch_as_missing_evidence(tmp_path):
    (tmp_path / "backend.py").write_text('@app.get("/api/users")\ndef users(): pass\n', encoding="utf-8")
    (tmp_path / "frontend.js").write_text('fetch("/api/students")\n', encoding="utf-8")

    graph = build_artifact_graph(tmp_path, ["backend.py", "frontend.js"])
    plan = build_verification_plan(tmp_path, graph, verifications=[])

    assert any(item["id"] == "api_consistency" and item["status"] == "failed" for item in plan["static_checks"])
    assert any(item["requirement"] == "api_consistency" for item in plan["missing_evidence"])


def test_artifact_graph_ignores_bare_template_suffix_as_api_reference(tmp_path):
    (tmp_path / "backend.py").write_text(
        '@app.get("/api/students")\ndef list_students(): pass\n@app.get("/api/students/{student_id}")\ndef read(): pass\n',
        encoding="utf-8",
    )
    (tmp_path / "frontend.js").write_text("const API_BASE = '/api/students';\nfetch(`${API_BASE}/${id}`);\n", encoding="utf-8")

    graph = build_artifact_graph(tmp_path, ["backend.py", "frontend.js"])
    plan = build_verification_plan(tmp_path, graph, verifications=[])

    assert "/${id}" not in graph["api"]["frontend_references"]
    assert any(item["id"] == "api_consistency" and item["status"] == "passed" for item in plan["static_checks"])


def test_artifact_graph_marks_verified_paths_and_stale_changes(tmp_path):
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "ui.js").write_text("fetch('/api/items')\n", encoding="utf-8")

    verified = build_artifact_graph(
        tmp_path,
        ["app.py"],
        verifications=[{"status": "passed", "checked_paths": ["app.py"]}],
    )
    stale = build_artifact_graph(
        tmp_path,
        ["app.py", "ui.js"],
        verifications=[{"status": "passed", "checked_paths": ["app.py"]}],
    )

    verified_nodes = {node["path"]: node for node in verified["artifacts"]}
    stale_nodes = {node["path"]: node for node in stale["artifacts"]}

    assert verified_nodes["app.py"]["status"] == "verified"
    assert stale_nodes["app.py"]["status"] == "verified"
    assert stale_nodes["ui.js"]["status"] == "stale"


def test_verifier_driver_requires_evidence_for_stale_artifacts(tmp_path):
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "ui.js").write_text("console.log(1)\n", encoding="utf-8")

    graph = build_artifact_graph(
        tmp_path,
        ["app.py", "ui.js"],
        verifications=[{"status": "passed", "checked_paths": ["app.py"]}],
    )
    plan = build_verification_plan(
        tmp_path,
        graph,
        verifications=[{"status": "passed", "checked_paths": ["app.py"]}],
    )

    assert any(item["requirement"] == "stale_artifacts" for item in plan["missing_evidence"])


def test_progress_guard_blocks_read_only_when_pending_tasks_need_activation(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Create backend","active_form":"Creating backend","status":"in_progress"},{"id":"task_2","content":"Create frontend","active_form":"Creating frontend","status":"pending"},{"id":"task_3","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"backend.py","content":"print(1)\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"backend.py","start":1,"end":20}}</tool>',
            '<tool>{"name":"read_file","args":{"path":"backend.py","start":1,"end":20}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_2","status":"in_progress"}}</tool>',
            "<final>Stopped.</final>",
        ],
        max_steps=10,
    )

    agent.ask("Build backend frontend and verify")

    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    assert any(event["event"] == "runtime_reminder_emitted" and event.get("reason") == "pending_task_needs_activation" for event in trace)
    assert any(
        event.get("event") == "tool_executed"
        and event.get("name") == "read_file"
        and event.get("tool_error_code") == "progress_guard_stale_task"
        for event in trace
    )


def test_verifier_driver_selects_runnable_action_from_plan():
    action = select_verification_action(
        {
            "missing_evidence": [{"requirement": "runtime_verification", "reason": "missing"}],
            "suggested_commands": [{"command": "uv run python -m compileall .", "reason": "python changed"}],
        }
    )

    assert action == {"name": "run_shell", "args": {"command": "uv run python -m compileall .", "timeout": 60}}


def test_verifier_driver_does_not_auto_execute_package_scripts():
    action = select_verification_action(
        {
            "missing_evidence": [{"requirement": "runtime_verification", "reason": "missing"}],
            "suggested_commands": [{"command": "npm test", "reason": "package.json defines a test script"}],
        }
    )

    assert action == {}


def test_runtime_executes_verifier_action_when_final_is_blocked(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Create Python app","active_form":"Creating Python app","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"app.py","content":"print(1)\\n"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            "<final>Done.</final>",
            "<final>Done after runtime verification.</final>",
        ],
        max_steps=8,
    )

    answer = agent.ask("Create a Python app and verify it")

    assert answer == "Done after runtime verification."
    assert agent.current_task_state.verifications
    assert agent.current_task_state.verifications[-1]["status"] == "passed"
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    assert any(event["event"] == "completion_gate_blocked" for event in trace)
    assert any(event["event"] == "tool_executed" and event["name"] == "run_shell" for event in trace)
