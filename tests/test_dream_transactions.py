import re

from pico import Pico, SessionStore, WorkspaceContext
from pico.cli import handle_repl_command
from pico.features.memory import (
    DREAM_SESSION_CAP,
    apply_dream_task,
    load_dream_state,
    load_dream_task,
    release_dream_lock,
    try_acquire_dream_lock,
)
from pico.testing import ScriptedModelClient


class DreamPathModelClient:
    def __init__(self, mode="valid"):
        self.mode = mode
        self.prompts = []
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}
        self._dream_outputs = None

    def complete(self, prompt, max_new_tokens, **kwargs):
        self.prompts.append(prompt)
        if self._dream_outputs is None:
            match = re.search(r"Memory directory: `([^`]+)`", prompt)
            if not match:
                return "<final>Done.</final>"
            memory_dir = match.group(1)
            if self.mode == "secret":
                self._dream_outputs = [
                    '<tool>{"name":"read_file","args":{"path":"'
                    + memory_dir
                    + '/MEMORY.md","start":1,"end":50}}</tool>',
                    '<tool>{"name":"write_file","args":{"path":"'
                    + memory_dir
                    + '/MEMORY.md","content":"# Durable Memory Index\\n\\n- [Secret](topics/secret.md): sk-test-token\\n"}}</tool>',
                    "<final>Dream candidate contains a secret.</final>",
                ]
            else:
                self._dream_outputs = [
                    '<tool>{"name":"read_file","args":{"path":"'
                    + memory_dir
                    + '/MEMORY.md","start":1,"end":50}}</tool>',
                    '<tool>{"name":"write_file","args":{"path":"'
                    + memory_dir
                    + '/MEMORY.md","content":"# Durable Memory Index\\n\\n- [User Preferences](topics/user-preferences.md): User preferences\\n"}}</tool>',
                    '<tool>{"name":"write_file","args":{"path":"'
                    + memory_dir
                    + '/topics/user-preferences.md","content":"---\\nname: User Preferences\\ndescription: User preferences\\ntype: user\\n---\\n\\n# User Preferences\\n\\n## Notes\\n- Prefers concise reports.\\n"}}</tool>',
                    "<final>Dream candidate ready.</final>",
                ]
        if not self._dream_outputs:
            raise RuntimeError("dream scripted model ran out of outputs")
        return self._dream_outputs.pop(0)


def build_agent(tmp_path, model_client=None):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    return Pico(
        model_client=model_client or ScriptedModelClient([]),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
    )


def test_manual_dream_creates_candidate_and_apply_updates_official_memory(tmp_path):
    agent = build_agent(tmp_path, DreamPathModelClient())
    handle_repl_command(agent, "/remember Prefers concise reports.")

    handled, should_exit, output = handle_repl_command(agent, "/dream")

    assert handled is True
    assert should_exit is False
    assert "Dream task" in output
    assert "status: completed_candidate" in output
    assert "lint: passed" in output
    assert "User Preferences" not in (tmp_path / ".pico" / "memory" / "MEMORY.md").read_text(encoding="utf-8")

    task_id = agent.last_dream_task_id
    task = load_dream_task(agent.memory_dir, task_id)
    run_dir = tmp_path / ".pico" / "memory" / ".dream" / "runs" / task_id
    candidate_index = run_dir / "candidate" / "MEMORY.md"
    assert task["status"] == "completed_candidate"
    assert task["lint_status"] == "passed"
    assert (run_dir / "task.json").exists()
    assert (run_dir / "diff.patch").exists()
    assert (run_dir / "lint.json").exists()
    assert (run_dir / "report.md").exists()
    assert "User Preferences" in candidate_index.read_text(encoding="utf-8")

    handled, should_exit, review = handle_repl_command(agent, f"/dream review {task_id}")
    assert handled is True
    assert should_exit is False
    assert "changed files" in review.lower()
    assert "MEMORY.md" in review

    handled, should_exit, applied = handle_repl_command(agent, f"/dream apply {task_id}")
    assert handled is True
    assert should_exit is False
    assert "Applied dream task" in applied
    assert "User Preferences" in (tmp_path / ".pico" / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    notes = agent.memory.retrieval_candidates("concise reports", limit=3)
    assert any(note["text"] == "Prefers concise reports." for note in notes)
    assert list((tmp_path / ".pico" / "memory" / ".dream" / "snapshots").iterdir())


def test_lint_failed_dream_cannot_be_applied(tmp_path):
    agent = build_agent(tmp_path, DreamPathModelClient(mode="secret"))

    handled, should_exit, output = handle_repl_command(agent, "/dream")

    assert handled is True
    assert should_exit is False
    assert "lint: failed" in output
    task_id = agent.last_dream_task_id

    handled, should_exit, applied = handle_repl_command(agent, f"/dream apply {task_id}")
    assert handled is True
    assert should_exit is False
    assert "error:" in applied
    assert "sk-test-token" not in (tmp_path / ".pico" / "memory" / "MEMORY.md").read_text(encoding="utf-8")


def test_manual_dream_uses_shared_lock(tmp_path):
    agent = build_agent(tmp_path, DreamPathModelClient())
    assert try_acquire_dream_lock(agent.memory_dir) is True

    try:
        handled, should_exit, output = handle_repl_command(agent, "/dream")
    finally:
        release_dream_lock(agent.memory_dir)

    assert handled is True
    assert should_exit is False
    assert output == "Dream already running."
    assert getattr(agent, "last_dream_task_id", None) is None


def test_discard_marks_candidate_without_updating_official_memory(tmp_path):
    agent = build_agent(tmp_path, DreamPathModelClient())

    handled, should_exit, output = handle_repl_command(agent, "/dream")

    assert handled is True
    assert should_exit is False
    assert "Dream task" in output
    task_id = agent.last_dream_task_id

    handled, should_exit, discarded = handle_repl_command(agent, f"/dream discard {task_id}")
    assert handled is True
    assert should_exit is False
    assert "Discarded dream task" in discarded

    handled, should_exit, status = handle_repl_command(agent, "/dream status")
    assert handled is True
    assert should_exit is False
    assert "status: discarded" in status
    assert load_dream_task(agent.memory_dir, task_id)["status"] == "discarded"
    assert "User Preferences" not in (tmp_path / ".pico" / "memory" / "MEMORY.md").read_text(encoding="utf-8")


def test_session_cap_keeps_unapplied_sessions_pending_until_apply(tmp_path):
    agent = build_agent(tmp_path, ScriptedModelClient(["<final>No changes.</final>"]))
    session_ids = [f"session-{index:02d}" for index in range(DREAM_SESSION_CAP + 5)]

    agent.run_dream(session_ids=session_ids)

    task_id = agent.last_dream_task_id
    task = load_dream_task(agent.memory_dir, task_id)
    state = load_dream_state(agent.memory_dir)
    assert len(task["input_sessions"]) == DREAM_SESSION_CAP
    assert len(state["pending_session_ids"]) == DREAM_SESSION_CAP + 5
    assert state["processed_session_ids"] == []

    apply_dream_task(agent, task_id)

    state = load_dream_state(agent.memory_dir)
    assert len(state["processed_session_ids"]) == DREAM_SESSION_CAP
    assert len(state["pending_session_ids"]) == 5
