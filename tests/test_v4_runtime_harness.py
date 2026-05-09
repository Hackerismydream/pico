import json
import sys
from types import SimpleNamespace

from pico import FakeModelClient, MiniAgent, SessionStore, WorkspaceContext
from pico.core.task_state import TaskState
from pico.features.skills import parse_skill_command
from pico.providers.clients import AnthropicSDKModelClient


def build_agent(tmp_path, outputs, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return MiniAgent(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy=kwargs.pop("approval_policy", "auto"),
        **kwargs,
    )


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_first_prompt_has_context_usage_and_does_not_echo_current_user_in_history(tmp_path):
    agent = build_agent(tmp_path, ["<final>hello</final>"])

    agent.ask("hi")

    first_prompt = agent.model_client.prompts[0]
    assert "Transcript:\n- empty" in first_prompt
    assert "[user] hi" not in first_prompt
    assert first_prompt.rstrip().endswith("Current user request:\nhi")

    usage = agent.last_prompt_metadata["context_usage"]
    assert usage["estimated_prompt_tokens"] > 0
    assert usage["model_context_window_tokens"] >= usage["reserved_output_tokens"]
    assert usage["budget_status"] in {"ok", "over_budget"}
    assert "prefix" in usage["section_estimated_tokens"]


def test_session_event_log_and_trace_schema_are_written_per_turn(tmp_path):
    agent = build_agent(tmp_path, ["<final>done</final>"])

    agent.ask("record a trace")

    events = read_jsonl(agent.session_store.event_path(agent.session["id"]))
    event_names = [event["event"] for event in events]
    assert event_names[:2] == ["session_started", "user_message"]
    assert event_names[-1] == "assistant_message"
    assert events[1]["turn_id"] == events[-1]["turn_id"]
    assert events[1]["session_id"] == agent.session["id"]

    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    first = trace[0]
    assert first["schema_version"] == "trace-v2"
    assert first["trace_id"] == agent.current_task_state.run_id
    assert first["span_id"].startswith("span_")
    assert first["phase"] == "run"
    assert first["status"] == "started"
    assert all(event.get("turn_id") == events[1]["turn_id"] for event in trace)


def test_tool_policy_enforces_allowed_tools_and_prior_read_for_patch(tmp_path):
    (tmp_path / "sample.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    agent = build_agent(tmp_path, [], allowed_tools=("read_file", "patch_file"))

    assert "run_shell" not in agent.tools
    denied = agent.run_tool("run_shell", {"command": "echo nope"})
    assert "not allowed" in denied
    assert agent._last_tool_result_metadata["tool_error_code"] == "tool_not_allowed"

    rejected = agent.run_tool("patch_file", {"path": "sample.txt", "old_text": "beta", "new_text": "locked"})
    assert "requires prior read_file" in rejected
    assert agent._last_tool_result_metadata["tool_error_code"] == "prior_read_required"

    read_result = agent.run_tool("read_file", {"path": "sample.txt", "start": 1, "end": 2})
    assert "# sample.txt" in read_result
    patched = agent.run_tool("patch_file", {"path": "sample.txt", "old_text": "beta", "new_text": "locked"})
    assert patched == "patched sample.txt"
    assert (tmp_path / "sample.txt").read_text(encoding="utf-8") == "alpha\nlocked\n"


def test_long_tool_result_is_clipped_with_artifact_pointer(tmp_path):
    agent = build_agent(tmp_path, [])
    raw = "line\n" * 600
    agent.tools = {
        "long_read": {
            "schema": {},
            "risky": False,
            "description": "Return a long read-only result.",
            "run": lambda args: raw,
            "policy": {"max_result_chars": 120},
        }
    }

    result = agent.run_tool("long_read", {})

    assert len(result) < len(raw)
    artifact_relpath = agent._last_tool_result_metadata["artifact_relpath"]
    artifact_path = tmp_path / artifact_relpath
    assert artifact_path.read_text(encoding="utf-8") == raw
    assert artifact_relpath in result


def write_skill(root, name, frontmatter="", body=""):
    skill_dir = root / ".pico" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"{frontmatter}"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )
    return skill_dir


def test_skill_catalog_discloses_summary_without_keyword_body_and_signs_runtime(tmp_path):
    skill_dir = tmp_path / ".pico" / "skills" / "pytest"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: pytest\n"
        "description: Run focused pytest coverage.\n"
        "when_to_use: Python test work.\n"
        "triggers: pytest, tests\n"
        "---\n"
        "# Pytest skill\n\n"
        "Always run the narrow pytest command before the full suite.\n",
        encoding="utf-8",
    )
    agent = build_agent(tmp_path, ["<final>ok</final>"])

    agent.ask("please add pytest coverage")

    prompt = agent.model_client.prompts[0]
    assert "Available skills:" in prompt
    assert "/skill:pytest" in prompt
    assert "Run focused pytest coverage." in prompt
    assert "Always run the narrow pytest command" not in prompt
    skills = agent.last_prompt_metadata["skills"]
    assert skills["available_count"] == 1
    assert skills["visible"][0]["name"] == "pytest"
    assert skills["legacy_matches"][0]["name"] == "pytest"
    assert skills["invoked"] == []
    assert skills["selected"] == []
    assert agent.current_runtime_identity()["skill_signature"] == agent.skill_signature()

    previous_signature = agent.skill_signature()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: pytest\n"
        "description: Run focused pytest coverage.\n"
        "---\n"
        "Updated instructions.\n",
        encoding="utf-8",
    )
    assert agent.skill_signature() != previous_signature


def test_load_skill_tool_expands_body_arguments_and_records_invocation(tmp_path):
    skill_dir = write_skill(
        tmp_path,
        "pytest",
        "description: Run focused pytest coverage.\n"
        "argument-hint: target\n",
        "# Pytest skill\n\nRun `$ARGUMENTS` from ${PICO_SKILL_DIR}.\n",
    )
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"load_skill","args":{"name":"pytest","args":"tests/test_pico.py"}}</tool>',
            "<final>ok</final>",
        ],
    )

    answer = agent.ask("use the pytest skill")

    assert answer == "ok"
    tool_events = [item for item in agent.session["history"] if item.get("role") == "tool"]
    assert tool_events[-1]["name"] == "load_skill"
    assert '<skill name="pytest"' in tool_events[-1]["content"]
    assert "tests/test_pico.py" in tool_events[-1]["content"]
    assert str(skill_dir) in tool_events[-1]["content"]
    assert "${PICO_SKILL_DIR}" not in tool_events[-1]["content"]
    events = read_jsonl(agent.session_store.event_path(agent.session["id"]))
    skill_events = [event for event in events if event["event"] == "skill_invoked"]
    assert skill_events[-1]["name"] == "pytest"
    assert skill_events[-1]["invocation_source"] == "model"
    assert skill_events[-1]["context"] == "inline"


def test_loaded_long_skill_body_is_pinned_in_next_prompt(tmp_path):
    long_body = "# Long skill\n\n" + "\n".join(f"step {index}: preserve detail" for index in range(260))
    long_body += "\nTAIL_SENTINEL: run the final verification matrix.\n"
    write_skill(
        tmp_path,
        "think",
        "description: Turn architecture ideas into a validated plan.\n"
        "argument-hint: topic\n",
        long_body,
    )
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"load_skill","args":{"name":"think","args":"skill architecture"}}</tool>',
            "<final>planned</final>",
        ],
    )

    answer = agent.ask("use the think skill")

    assert answer == "planned"
    second_prompt = agent.model_client.prompts[1]
    assert "TAIL_SENTINEL: run the final verification matrix." in second_prompt
    skill_section = agent.last_prompt_metadata["sections"]["skills"]
    assert skill_section["rendered_chars"] == skill_section["raw_chars"]
    assert all(item["section"] != "skills" for item in agent.last_prompt_metadata["budget_reductions"])


def test_skill_slash_command_invokes_same_runtime_path(tmp_path):
    write_skill(
        tmp_path,
        "review",
        "description: Review code changes.\n"
        "argument-hint: scope\n",
        "Review `$ARGUMENTS` using this checklist.\n",
    )
    agent = build_agent(tmp_path, ["<final>reviewed</final>"])

    answer = agent.ask("/skill:review pico/features")

    assert answer == "reviewed"
    prompt = agent.model_client.prompts[0]
    assert '<skill name="review"' in prompt
    assert "Review `pico/features` using this checklist." in prompt
    assert "Current user request:\npico/features" in prompt
    assert agent.last_prompt_metadata["skills"]["invoked"][0]["name"] == "review"
    assert agent.last_prompt_metadata["skills"]["invoked"][0]["invocation_source"] == "user"


def test_skill_invocation_respects_allowed_tools_and_feature_flag(tmp_path):
    write_skill(
        tmp_path,
        "review",
        "description: Review code changes.\n",
        "Review `$ARGUMENTS`.\n",
    )
    restricted = build_agent(tmp_path, [], allowed_tools=("read_file",))

    result = restricted.ask('/skill:review "src path"')

    assert "load_skill" in result
    assert "not allowed" in result
    assert restricted.model_client.prompts == []
    assert '<skill name="review"' not in "\n".join(item.get("content", "") for item in restricted.session["history"])

    disabled = build_agent(tmp_path, [], feature_flags={"skills": False})
    result = disabled.ask("/skill:review src")

    assert "skills are disabled" in result
    assert disabled.model_client.prompts == []
    assert "load_skill" not in disabled.tools


def test_skill_command_parser_uses_same_quoted_args_as_tui_parser():
    command = parse_skill_command('/skill:review "pico/features with space" --deep')

    assert command is not None
    assert command.name == "review"
    assert command.args == "pico/features with space --deep"


def test_fork_skill_runs_bounded_subagent_and_records_result(tmp_path):
    write_skill(
        tmp_path,
        "audit",
        "description: Audit a target in isolation.\n"
        "context: fork\n",
        "Audit `$ARGUMENTS` and return concise findings.\n",
    )
    agent = build_agent(tmp_path, ["<final>fork audit result</final>"])

    result = agent.run_tool("load_skill", {"name": "audit", "args": "README.md"})

    assert "forked skill audit completed" in result
    assert "fork audit result" in result
    assert agent.session["subagents"][0]["status"] == "completed"
    assert "audit" in agent.session["subagents"][0]["description"]


def test_fork_skill_stays_isolated_from_parent_prompt_and_trace_starts(tmp_path):
    write_skill(
        tmp_path,
        "audit",
        "description: Audit a target in isolation.\n"
        "context: fork\n",
        "FORK_SECRET_SENTINEL `$ARGUMENTS`.\n",
    )
    agent = build_agent(
        tmp_path,
        [
            "<final>fork audit result</final>",
            "<final>parent done</final>",
        ],
    )

    answer = agent.ask("/skill:audit README.md")

    assert "fork audit result" in answer
    assert len(agent.model_client.prompts) == 1
    assert "FORK_SECRET_SENTINEL" in agent.model_client.prompts[0]
    trace = read_jsonl(agent.run_store.trace_path(agent.current_task_state))
    assert trace[0]["event"] == "run_started"
    assert trace[-1]["event"] == "run_finished"

    agent.ask("continue after fork")

    parent_prompt = agent.model_client.prompts[-1]
    assert "forked skill audit completed" in parent_prompt
    assert "FORK_SECRET_SENTINEL" not in parent_prompt


def test_list_skills_tool_discovers_entries_omitted_from_prompt_budget(tmp_path):
    for index in range(40):
        write_skill(
            tmp_path,
            f"skill{index}",
            f"description: Skill {index} summary {'x' * 90}.\n",
            f"Body {index}.\n",
        )
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"list_skills","args":{"query":"skill39","limit":5}}</tool>',
            "<final>listed</final>",
        ],
    )

    answer = agent.ask("find a rare skill")

    assert answer == "listed"
    tool_events = [item for item in agent.session["history"] if item.get("role") == "tool"]
    assert tool_events[-1]["name"] == "list_skills"
    assert "/skill:skill39" in tool_events[-1]["content"]
    assert "Body 39" not in tool_events[-1]["content"]


def test_anthropic_sdk_client_uses_official_messages_api(monkeypatch):
    calls = {}

    class FakeMessages:
        def create(self, **kwargs):
            calls["create"] = kwargs
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="sdk response")],
                usage=SimpleNamespace(input_tokens=12, output_tokens=3),
                id="msg_123",
            )

    class FakeAnthropic:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.messages = FakeMessages()

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=FakeAnthropic))
    client = AnthropicSDKModelClient(
        model="claude-sonnet",
        base_url="https://www.right.codes/claude/v1",
        api_key="key",
        temperature=0.1,
        timeout=60,
    )

    text = client.complete("hello", max_new_tokens=128)

    assert text == "sdk response"
    assert calls["client"] == {"api_key": "key", "base_url": "https://www.right.codes/claude", "timeout": 60}
    assert calls["create"]["model"] == "claude-sonnet"
    assert calls["create"]["max_tokens"] == 128
    assert calls["create"]["messages"] == [{"role": "user", "content": "hello"}]
    assert client.last_completion_metadata["provider_transport"] == "anthropic_sdk"
    assert client.last_completion_metadata["input_tokens"] == 12


def test_plan_mode_only_allows_reading_and_active_plan_file_writes(tmp_path):
    agent = build_agent(tmp_path, [])

    plan_path = agent.enter_plan_mode("add compact command")
    plan_relpath = plan_path.relative_to(tmp_path).as_posix()

    assert agent.runtime_mode == "plan"
    assert plan_relpath.startswith(".pico/plans/")
    assert "Runtime mode: plan" in agent.prefix
    assert plan_relpath in agent.prefix

    rejected = agent.run_tool("write_file", {"path": "notes.txt", "content": "nope\n"})
    assert "plan mode" in rejected
    assert "active plan file" in rejected
    assert not (tmp_path / "notes.txt").exists()
    assert agent._last_tool_result_metadata["tool_error_code"] == "plan_mode_denied"

    written = agent.run_tool("write_file", {"path": plan_relpath, "content": "# Plan\n- inspect context\n"})
    assert written.startswith("wrote .pico/plans/")
    assert plan_path.read_text(encoding="utf-8") == "# Plan\n- inspect context\n"

    plan_text = agent.exit_plan_mode()
    assert "# Plan" in plan_text
    assert agent.runtime_mode == "execute"
    assert "Runtime mode: plan" not in agent.prefix


def test_plan_mode_final_can_complete_after_active_plan_file_is_written(tmp_path):
    agent = build_agent(tmp_path, [], max_steps=3)
    plan_path = agent.enter_plan_mode("student management system")
    plan_relpath = plan_path.relative_to(tmp_path).as_posix()
    agent.model_client.outputs = [
        f'<tool>{{"name":"write_file","args":{{"path":"{plan_relpath}","content":"# Plan\\n- Build backend\\n- Build frontend\\n"}}}}</tool>',
        "<final>Plan written.</final>",
    ]

    answer = agent.ask("We are in plan mode. Write the plan into the active plan file.")

    assert answer == "Plan written."
    assert agent.current_task_state.status == "completed"
    assert agent.current_task_state.completion_gate["status"] == "completed"
    assert agent.current_task_state.completion_gate["runtime_mode"] == "plan"
    assert plan_path.read_text(encoding="utf-8").startswith("# Plan")


def test_plan_mode_final_is_blocked_until_active_plan_file_is_written(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.enter_plan_mode("student management system")
    state = TaskState.create(task_id="task_plan", user_request="plan", run_id="run_plan")

    decision = agent.runtime_control.before_final(
        agent,
        state,
        "Plan written.",
        "We are in plan mode. Write the plan into the active plan file.",
    )

    assert decision.action == "block_final"
    assert "write the active plan file before final answer" in decision.message


def test_manual_compact_replaces_old_history_with_persisted_summary(tmp_path):
    agent = build_agent(tmp_path, [])
    for index in range(8):
        agent.record({"role": "user", "content": f"old request {index}", "created_at": f"2026-01-01T00:00:0{index}+00:00"})
        agent.record({"role": "assistant", "content": f"old answer {index}", "created_at": f"2026-01-01T00:00:1{index}+00:00"})

    result = agent.compact_history(keep_recent=4)

    assert result["compacted"] is True
    assert result["before_messages"] == 16
    assert result["after_messages"] == 5
    assert agent.session["history"][0]["role"] == "assistant"
    assert "[compacted context]" in agent.session["history"][0]["content"]
    assert "old request 0" in agent.session["history"][0]["content"]
    assert agent.session["history"][-1]["content"] == "old answer 7"

    resumed = MiniAgent.from_session(
        model_client=FakeModelClient(["<final>ok</final>"]),
        workspace=agent.workspace,
        session_store=agent.session_store,
        session_id=agent.session["id"],
        approval_policy="auto",
    )
    assert resumed.session["history"][0]["content"] == agent.session["history"][0]["content"]
    assert resumed.session["compaction"]["compact_count"] == 1


def test_manual_compact_uses_model_summary_when_available(tmp_path):
    agent = build_agent(tmp_path, ["semantic summary with files and next step"])
    for index in range(5):
        agent.record({"role": "user", "content": f"request {index}", "created_at": f"2026-01-01T00:00:0{index}+00:00"})
        agent.record({"role": "assistant", "content": f"answer {index}", "created_at": f"2026-01-01T00:00:1{index}+00:00"})

    result = agent.compact_history(keep_recent=4)

    assert result["compacted"] is True
    assert result["summary_source"] == "model"
    assert "semantic summary with files and next step" in agent.session["history"][0]["content"]
    assert "request 0" in agent.model_client.prompts[0]
    assert agent.session["compaction"]["last_summary_source"] == "model"


def test_manual_compact_falls_back_to_deterministic_summary_when_model_summary_fails(tmp_path):
    agent = build_agent(tmp_path, [])
    for index in range(5):
        agent.record({"role": "user", "content": f"fallback request {index}", "created_at": f"2026-01-01T00:00:0{index}+00:00"})
        agent.record({"role": "assistant", "content": f"fallback answer {index}", "created_at": f"2026-01-01T00:00:1{index}+00:00"})

    result = agent.compact_history(keep_recent=4)

    assert result["compacted"] is True
    assert result["summary_source"] == "deterministic_fallback"
    assert "fallback request 0" in agent.session["history"][0]["content"]
    assert agent.session["compaction"]["last_summary_source"] == "deterministic_fallback"
    assert "RuntimeError" in agent.session["compaction"]["last_error"]


def test_auto_compact_runs_before_model_request_and_persists_event(tmp_path):
    agent = build_agent(tmp_path, ["auto semantic summary", "<final>continued</final>"])
    agent.compact_service.auto_threshold_override_tokens = 20
    agent.compact_service.min_recent_tokens = 20
    for index in range(12):
        agent.record({"role": "user", "content": f"auto request {index} " + ("A" * 80), "created_at": f"2026-01-01T00:{index:02d}:00+00:00"})
        agent.record({"role": "assistant", "content": f"auto answer {index} " + ("B" * 80), "created_at": f"2026-01-01T00:{index:02d}:30+00:00"})

    answer = agent.ask("continue after auto compact")

    assert answer == "continued"
    assert len(agent.model_client.prompts) == 2
    assert "Summarize the compacted Pico conversation history" in agent.model_client.prompts[0]
    assert "Current user request:\ncontinue after auto compact" in agent.model_client.prompts[1]
    assert "[compacted context]" in agent.session["history"][0]["content"]
    assert "auto semantic summary" in agent.session["history"][0]["content"]
    assert agent.last_prompt_metadata["auto_compaction"]["trigger"] == "auto"
    assert agent.last_prompt_metadata["auto_compaction"]["summary_source"] == "model"
    events = read_jsonl(agent.session_store.event_path(agent.session["id"]))
    compact_events = [event for event in events if event["event"] == "history_compacted"]
    assert compact_events[-1]["trigger"] == "auto"
    assert compact_events[-1]["summary_source"] == "model"


def test_tool_registry_exposes_protocol_fields_for_policy_trace_and_tui(tmp_path):
    agent = build_agent(tmp_path, [])
    read_tool = agent.tools["read_file"]
    write_tool = agent.tools["write_file"]

    assert read_tool["read_only"] is True
    assert write_tool["read_only"] is False
    assert agent.tool_activity_description("read_file", {"path": "README.md"}) == "Reading README.md"
    assert agent.tool_activity_description("write_file", {"path": "notes.txt", "content": "hello"}) == "Writing notes.txt"

    result = agent.run_tool("read_file", {"path": "README.md", "start": 1, "end": 1})

    assert "demo" in result
    assert agent._last_tool_result_metadata["read_only"] is True
    assert agent._last_tool_result_metadata["activity"] == "Reading README.md"
