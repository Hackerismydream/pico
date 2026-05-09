import json

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext
from pico.features.artifacts import suggest_verification_commands


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


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_tool_events_update_artifact_graph_and_report(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"write_file","args":{"path":"backend/app.py","content":"from fastapi import FastAPI\\napp = FastAPI()\\n@app.get(\\"/api/students\\")\\ndef students():\\n    return []\\n"}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"frontend/app.js","content":"export async function loadStudents() { return fetch(\\"/api/students\\"); }\\n"}}</tool>',
            '<tool>{"name":"write_file","args":{"path":"README-app.md","content":"# Student app\\n\\nRun backend and frontend separately.\\n"}}</tool>',
            "<final>Implemented files.</final>",
        ],
        max_steps=6,
    )

    agent.ask("Build a small full-stack app with API, UI, docs, and verification")

    task_state = agent.current_task_state
    graph = task_state.artifact_graph
    assert graph["summary"]["backend"] == 1
    assert graph["summary"]["frontend"] == 1
    assert graph["summary"]["docs"] == 1
    assert "/api/students" in graph["api"]["backend_routes"]
    assert "/api/students" in graph["api"]["frontend_references"]

    state_json = read_json(agent.run_store.task_state_path(task_state))
    assert state_json["artifact_graph"]["summary"]["frontend"] == 1

    report = read_json(agent.run_store.report_path(task_state))
    assert report["artifact_graph"]["summary"]["backend"] == 1
    assert report["verification_plan"]["suggested_commands"]


def test_runtime_reminders_are_persisted_as_state(tmp_path):
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"write_file","args":{"path":"app.py","content":"print(1)\\n"}}</tool>',
            "<final>Created.</final>",
        ],
        max_steps=4,
    )

    agent.ask("Create a backend and frontend project with tests")

    reminders = agent.current_task_state.runtime_reminders
    assert reminders
    assert reminders[0]["reason"] == "missing_task_ledger"
    assert reminders[0]["tool"] == "write_file"

    report = read_json(agent.run_store.report_path(agent.current_task_state))
    assert report["runtime_reminders"][0]["reason"] == "missing_task_ledger"


def test_verification_commands_use_project_metadata_without_hardcoded_business_rules(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run", "build": "vite build"}}),
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    suggestions = suggest_verification_commands(tmp_path, {"paths": {"backend": [], "frontend": [], "tests": ["tests/test_app.py"]}})

    commands = [item["command"] for item in suggestions]
    assert "npm test" in commands
    assert "npm run build" in commands
    assert "uv run python -m pytest -q" in commands


def test_verification_commands_use_requirements_with_python_commands(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.111.0\n", encoding="utf-8")

    suggestions = suggest_verification_commands(tmp_path, {"paths": {"backend": ["main.py"], "frontend": [], "tests": []}})

    commands = [item["command"] for item in suggestions]
    assert "uv run --with-requirements requirements.txt python -m compileall ." in commands


def test_artifact_graph_extracts_absolute_and_template_api_paths(tmp_path):
    (tmp_path / "main.py").write_text('@app.get("/students/{student_id}")\ndef read(): pass\n', encoding="utf-8")
    (tmp_path / "index.html").write_text(
        "const API_BASE = 'http://localhost:8000';\nfetch(`${API_BASE}/students`);\nfetch('http://localhost:8000/students/1');\n",
        encoding="utf-8",
    )

    from pico.features.artifacts import build_artifact_graph

    graph = build_artifact_graph(tmp_path, ["main.py", "index.html"])

    assert "/students/{student_id}" in graph["api"]["backend_routes"]
    assert "/students" in graph["api"]["frontend_references"]
    assert "/students/1" in graph["api"]["frontend_references"]
