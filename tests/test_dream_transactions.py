import re
import os
from pathlib import Path

from pico import Pico, SessionStore, WorkspaceContext
from pico.cli import handle_repl_command
from pico.commands.dream import handle_dream_command
from pico.features.dream_lint import lint_memory_candidate as lint_candidate_direct
from pico.features.dream_report import redact_sensitive_text
from pico.features.dream_store import DreamLock, collect_non_runtime_files, is_official_memory_payload
from pico.features.memory import (
    DREAM_SESSION_CAP,
    apply_dream_task,
    evaluate_auto_dream_gate,
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


class WarningModelClient(DreamPathModelClient):
    def complete(self, prompt, max_new_tokens, **kwargs):
        self.prompts.append(prompt)
        if self._dream_outputs is None:
            match = re.search(r"Memory directory: `([^`]+)`", prompt)
            if not match:
                return "<final>Done.</final>"
            memory_dir = match.group(1)
            self._dream_outputs = [
                '<tool>{"name":"read_file","args":{"path":"'
                + memory_dir
                + '/MEMORY.md","start":1,"end":50}}</tool>',
                '<tool>{"name":"write_file","args":{"path":"'
                + memory_dir
                + '/MEMORY.md","content":"# Durable Memory Index\\n\\n- [Loose Memory](topics/loose.md): Loose memory\\n"}}</tool>',
                '<tool>{"name":"write_file","args":{"path":"'
                + memory_dir
                + '/topics/loose.md","content":"# Loose Memory\\n\\n## Notes\\n- Prefers manual review.\\n"}}</tool>',
                "<final>Dream candidate ready with warnings.</final>",
            ]
        if not self._dream_outputs:
            raise RuntimeError("dream scripted model ran out of outputs")
        return self._dream_outputs.pop(0)


class ExtraFileModelClient(DreamPathModelClient):
    def complete(self, prompt, max_new_tokens, **kwargs):
        self.prompts.append(prompt)
        if self._dream_outputs is None:
            match = re.search(r"Memory directory: `([^`]+)`", prompt)
            if not match:
                return "<final>Done.</final>"
            memory_dir = match.group(1)
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
                '<tool>{"name":"write_file","args":{"path":"'
                + memory_dir
                + '/random.txt","content":"scratch\\n"}}</tool>',
                "<final>Dream candidate ready with scratch file.</final>",
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


def test_dream_command_handler_requires_task_id_for_review(tmp_path):
    agent = build_agent(tmp_path)

    output = handle_dream_command(agent, "review")

    assert output == "Usage: /dream review <task_id>"


def test_dream_command_handler_rejects_unknown_action(tmp_path):
    agent = build_agent(tmp_path)

    output = handle_dream_command(agent, "unknown")

    assert output == "Usage: /dream [status|review <task_id>|apply <task_id>|discard <task_id>]"


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


def test_dream_lint_module_reports_secret_value(tmp_path):
    candidate = tmp_path / "candidate"
    (candidate / "topics").mkdir(parents=True)
    (candidate / "MEMORY.md").write_text(
        "# Durable Memory Index\n\n- [Secret](topics/secret.md): Secret\n",
        encoding="utf-8",
    )
    (candidate / "topics" / "secret.md").write_text(
        "---\nname: Secret\ndescription: Secret\ntype: user\n---\n\n"
        "# Secret\n\n## Notes\n- token: sk-test-token\n",
        encoding="utf-8",
    )

    result = lint_candidate_direct(candidate)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "secret_shaped"


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

    handled, should_exit, applied = handle_repl_command(agent, f"/dream apply {task_id}")
    assert handled is True
    assert should_exit is False
    assert "error:" in applied
    assert "discarded" in applied
    assert "User Preferences" not in (tmp_path / ".pico" / "memory" / "MEMORY.md").read_text(encoding="utf-8")


def test_apply_uses_lock_and_rejects_when_dream_running(tmp_path):
    agent = build_agent(tmp_path, DreamPathModelClient())
    handle_repl_command(agent, "/dream")
    task_id = agent.last_dream_task_id
    assert try_acquire_dream_lock(agent.memory_dir) is True

    try:
        handled, should_exit, applied = handle_repl_command(agent, f"/dream apply {task_id}")
    finally:
        release_dream_lock(agent.memory_dir)

    assert handled is True
    assert should_exit is False
    assert "error:" in applied
    assert "Dream already running" in applied
    assert "User Preferences" not in (tmp_path / ".pico" / "memory" / "MEMORY.md").read_text(encoding="utf-8")


def test_apply_re_runs_lint_after_candidate_tamper(tmp_path):
    agent = build_agent(tmp_path, DreamPathModelClient())
    handle_repl_command(agent, "/dream")
    task_id = agent.last_dream_task_id
    task = load_dream_task(agent.memory_dir, task_id)
    candidate_index = Path(task["candidate_store"]) / "MEMORY.md"
    candidate_index.write_text("# Durable Memory Index\n\n- [Secret](topics/secret.md): sk-test-token\n", encoding="utf-8")

    handled, should_exit, applied = handle_repl_command(agent, f"/dream apply {task_id}")

    assert handled is True
    assert should_exit is False
    assert "error:" in applied
    assert "lint status" in applied
    assert "sk-test-token" not in (tmp_path / ".pico" / "memory" / "MEMORY.md").read_text(encoding="utf-8")


def test_apply_rejects_stale_candidate_when_official_memory_changed(tmp_path):
    agent = build_agent(tmp_path, DreamPathModelClient())
    handle_repl_command(agent, "/dream")
    task_id = agent.last_dream_task_id
    official_index = tmp_path / ".pico" / "memory" / "MEMORY.md"
    official_index.write_text("# Durable Memory Index\n\n- manual edit\n", encoding="utf-8")

    handled, should_exit, applied = handle_repl_command(agent, f"/dream apply {task_id}")

    assert handled is True
    assert should_exit is False
    assert "error:" in applied
    assert "official memory changed" in applied
    assert official_index.read_text(encoding="utf-8") == "# Durable Memory Index\n\n- manual edit\n"


def test_warning_candidate_can_be_manually_applied(tmp_path):
    agent = build_agent(tmp_path, WarningModelClient())

    handled, should_exit, output = handle_repl_command(agent, "/dream")

    assert handled is True
    assert should_exit is False
    assert "lint: warning" in output
    task_id = agent.last_dream_task_id

    handled, should_exit, applied = handle_repl_command(agent, f"/dream apply {task_id}")

    assert handled is True
    assert should_exit is False
    assert "Applied dream task" in applied
    assert "Loose Memory" in (tmp_path / ".pico" / "memory" / "MEMORY.md").read_text(encoding="utf-8")


def test_arbitrary_candidate_file_is_not_applied(tmp_path):
    agent = build_agent(tmp_path, ExtraFileModelClient())
    handle_repl_command(agent, "/dream")
    task_id = agent.last_dream_task_id

    handled, should_exit, applied = handle_repl_command(agent, f"/dream apply {task_id}")

    assert handled is True
    assert should_exit is False
    assert "Applied dream task" in applied
    assert not (tmp_path / ".pico" / "memory" / "random.txt").exists()


def test_secret_diff_is_redacted_in_review(tmp_path):
    agent = build_agent(tmp_path, DreamPathModelClient(mode="secret"))
    handle_repl_command(agent, "/dream")
    task_id = agent.last_dream_task_id

    handled, should_exit, review = handle_repl_command(agent, f"/dream review {task_id}")

    assert handled is True
    assert should_exit is False
    assert "sk-test-token" not in review
    assert "<redacted>" in review


def test_dream_report_redacts_secret_values():
    text = "token: sk-test-token and normal text"

    redacted = redact_sensitive_text(text)

    assert "sk-test-token" not in redacted
    assert "<redacted>" in redacted
    assert "normal text" in redacted


def test_dream_store_payload_allowlist(tmp_path):
    candidate = tmp_path / "candidate"
    (candidate / "topics").mkdir(parents=True)
    (candidate / "logs").mkdir()
    (candidate / ".dream").mkdir()
    (candidate / "MEMORY.md").write_text("# Durable Memory Index\n", encoding="utf-8")
    (candidate / "topics" / "good.md").write_text("# Good\n", encoding="utf-8")
    (candidate / "logs" / "ignored.md").write_text("ignored\n", encoding="utf-8")
    (candidate / ".dream" / "ignored.md").write_text("ignored\n", encoding="utf-8")
    (candidate / "scratch.txt").write_text("scratch\n", encoding="utf-8")

    texts = collect_non_runtime_files(candidate)

    assert "MEMORY.md" in texts
    assert "topics/good.md" in texts
    assert "scratch.txt" in texts
    assert "logs/ignored.md" not in texts
    assert ".dream/ignored.md" not in texts
    assert is_official_memory_payload("MEMORY.md") is True
    assert is_official_memory_payload("topics/good.md") is True
    assert is_official_memory_payload("scratch.txt") is False


def test_dream_lock_context_manager_releases_lock(tmp_path):
    agent = build_agent(tmp_path)

    with DreamLock(agent.memory_dir).acquire(purpose="test", task_id="task"):
        assert try_acquire_dream_lock(agent.memory_dir) is False

    assert try_acquire_dream_lock(agent.memory_dir) is True
    release_dream_lock(agent.memory_dir)


def test_em_dash_index_and_non_notes_topic_are_retrievable(tmp_path):
    agent = build_agent(tmp_path)
    memory_dir = tmp_path / ".pico" / "memory"
    (memory_dir / "topics").mkdir(parents=True, exist_ok=True)
    (memory_dir / "MEMORY.md").write_text(
        "# Durable Memory Index\n\n- [User Preferences](topics/user-preferences.md) — User preferences\n",
        encoding="utf-8",
    )
    (memory_dir / "topics" / "user-preferences.md").write_text(
        "---\nname: User Preferences\ndescription: User preferences\ntype: user\n---\n\n# User Preferences\n\n## Decisions\n- Prefers concise reports.\n",
        encoding="utf-8",
    )

    notes = agent.memory.retrieval_candidates("concise reports", limit=3)

    assert any(note["text"] == "Prefers concise reports." for note in notes)


def test_session_cap_keeps_unapplied_sessions_pending_until_apply(tmp_path):
    agent = build_agent(tmp_path, ScriptedModelClient(["<final>No changes.</final>"]))
    session_ids = [f"session-{index:02d}" for index in range(DREAM_SESSION_CAP + 5)]

    agent.run_dream(session_ids=session_ids)

    task_id = agent.last_dream_task_id
    task = load_dream_task(agent.memory_dir, task_id)
    state = load_dream_state(agent.memory_dir)
    assert len(task["input_sessions"]) == DREAM_SESSION_CAP
    assert task["input_sessions"] == session_ids[:DREAM_SESSION_CAP]
    assert len(state["pending_session_ids"]) == DREAM_SESSION_CAP + 5
    assert state["processed_session_ids"] == []

    apply_dream_task(agent, task_id)

    state = load_dream_state(agent.memory_dir)
    assert len(state["processed_session_ids"]) == DREAM_SESSION_CAP
    assert state["processed_session_ids"] == session_ids[:DREAM_SESSION_CAP]
    assert len(state["pending_session_ids"]) == 5
    assert state["pending_session_ids"] == session_ids[DREAM_SESSION_CAP:]


def test_session_created_during_dream_scan_window_is_not_lost(tmp_path):
    agent = build_agent(tmp_path, ScriptedModelClient(["<final>No changes.</final>"]))
    sessions_dir = tmp_path / ".pico" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    for index in range(5):
        (sessions_dir / f"session-{index}.jsonl").write_text("{}\n", encoding="utf-8")

    gate = evaluate_auto_dream_gate(
        agent.memory_dir,
        min_hours=0,
        min_sessions=1,
        current_session_id=agent.session["id"],
        sessions_dir=sessions_dir,
    )
    assert gate["should_run"] is True
    assert "scan_cutoff" in gate

    during = sessions_dir / "during-dream.jsonl"
    during.write_text("{}\n", encoding="utf-8")
    os.utime(during, (gate["scan_cutoff"] + 0.001, gate["scan_cutoff"] + 0.001))

    agent.run_dream(session_ids=gate["session_ids"], scan_cutoff=gate["scan_cutoff"])
    next_gate = evaluate_auto_dream_gate(
        agent.memory_dir,
        min_hours=0,
        min_sessions=1,
        current_session_id=agent.session["id"],
        sessions_dir=sessions_dir,
    )

    assert "during-dream" in next_gate["session_ids"]
