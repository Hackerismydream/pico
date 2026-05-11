import sys
import threading

import pytest

from pico import FakeModelClient, Pico, SessionStore, WorkspaceContext


def build_agent(tmp_path, outputs, approval_policy="auto", **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    return Pico(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy=approval_policy,
        **kwargs,
    )


def assistant_contents(app):
    from pico.tui.widgets import AssistantMessage

    return [message.content for message in app.query(AssistantMessage)]


def rendered_text(widget) -> str:
    rendered = widget.render()
    return getattr(rendered, "plain", str(rendered))


def test_cli_defaults_interactive_mode_to_tui():
    from pico.cli import build_arg_parser, interaction_mode

    args = build_arg_parser().parse_args(["--cwd", "/tmp/workspace"])

    assert interaction_mode(args) == "tui"


def test_cli_keeps_prompt_as_one_shot_mode():
    from pico.cli import build_arg_parser, interaction_mode

    args = build_arg_parser().parse_args(["inspect", "tests"])

    assert interaction_mode(args) == "one_shot"


def test_cli_repl_flag_restores_plain_repl():
    from pico.cli import build_arg_parser, interaction_mode

    args = build_arg_parser().parse_args(["--repl", "--cwd", "/tmp/workspace"])

    assert interaction_mode(args) == "repl"


def test_cli_accepts_explicit_tui_flag():
    from pico.cli import build_arg_parser, interaction_mode

    args = build_arg_parser().parse_args(["--tui", "--cwd", "/tmp/workspace"])

    assert args.tui is True
    assert interaction_mode(args) == "tui"
    assert args.cwd == "/tmp/workspace"


def test_tui_agents_text_and_status_bar_show_subagents(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import StatusBar

    agent = build_agent(tmp_path, ["<final>Plan noted.</final>"])
    agent.session["subagents"] = [
        {
            "task_id": "agent-1234abcd",
            "description": "Inspect runtime",
            "subagent_type": "Explore",
            "status": "completed",
            "usage": {"tool_uses": 2, "duration_ms": 50},
            "result": "Found runtime.py",
        }
    ]
    app = PicoTuiApp(agent)

    text = app._agents_text()
    assert "Subagents" in text
    assert "agent-1234abcd" in text
    assert "Inspect runtime" in text

    status = StatusBar()
    status.update_agent(agent)
    assert "agents 1" in rendered_text(status)


def test_status_bar_updates_from_runtime_snapshot():
    from pico.core.runtime_snapshot import RuntimeSnapshot
    from pico.tui.widgets import StatusBar

    snapshot = RuntimeSnapshot(
        model_name="fake-model",
        approval_policy="auto",
        session_id="session-123456",
        cwd="/tmp/pico",
        runtime_mode="plan",
        stage="planning",
        tasks=[{"status": "completed"}, {"status": "pending"}],
        verification_status="failed",
        completion_gate={"blocked": True},
        subagent_count=2,
    )
    status = StatusBar()

    status.update_agent(snapshot)

    assert status.model_name == "fake-model"
    assert status.runtime_mode == "plan"
    assert status.stage == "planning"
    assert status.tasks_completed == 1
    assert status.tasks_total == 2
    assert status.verify_status == "failed"
    assert status.gate_status == "blocked"
    assert status.subagent_count == 2


def test_slash_command_registry_suggests_and_parses_subagent():
    from pico.commands.slash import parse_skill_args, parse_subagent_args, resolve_command, suggest_commands

    suggestions = suggest_commands("/sub")

    assert suggestions[0].name == "subagent"
    command = resolve_command("sub")
    assert command.name == "subagent"
    assert "bounded local child run" in command.description

    payload, error = parse_subagent_args("worker --scope README.md,src update docs")

    assert error == ""
    assert payload["subagent_type"] == "Worker"
    assert payload["write_scope"] == ["README.md", "src"]
    assert payload["prompt"] == "update docs"

    skill_suggestions = [command.name for command in suggest_commands("/sk")]
    assert "skills" in skill_suggestions
    assert "skill" in skill_suggestions
    assert resolve_command("skill").name == "skill"
    payload, error = parse_skill_args("pytest tests/test_pico.py")
    assert error == ""
    assert payload == {"name": "pytest", "args": "tests/test_pico.py"}
    payload, error = parse_skill_args("skill:pytest tests/test_pico.py")
    assert error == ""
    assert payload == {"name": "pytest", "args": "tests/test_pico.py"}
    payload, error = parse_skill_args('skill:review "pico/features with space" --deep')
    assert error == ""
    assert payload == {"name": "review", "args": "pico/features with space --deep"}


def test_tui_skills_text_lists_only_user_invocable_skills(tmp_path):
    from pico.tui.app import PicoTuiApp

    skill_root = tmp_path / ".pico" / "skills"
    (skill_root / "user").mkdir(parents=True)
    (skill_root / "model").mkdir(parents=True)
    (skill_root / "user" / "SKILL.md").write_text(
        "---\nname: user\ndescription: User skill.\n---\nBody.\n",
        encoding="utf-8",
    )
    (skill_root / "model" / "SKILL.md").write_text(
        "---\nname: model\ndescription: Model-only skill.\nuser-invocable: false\n---\nBody.\n",
        encoding="utf-8",
    )
    agent = build_agent(tmp_path, [])
    app = PicoTuiApp(agent)

    text = app._skills_text()

    assert "/skill:user" in text
    assert "/skill:model" not in text


@pytest.mark.asyncio
async def test_tui_slash_suggestions_complete_partial_command(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar, SlashSuggestions

    agent = build_agent(tmp_path, [])
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.text = "/sub"
        bar.update_slash_suggestions()

        suggestions = app.query_one(SlashSuggestions)
        assert suggestions.visible is True
        assert "/subagent" in rendered_text(suggestions)

        await pilot.press("tab")

        assert bar.input.text == "/subagent "
        assert suggestions.visible is False


@pytest.mark.asyncio
async def test_tui_subagent_command_launches_explore_subagent(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar

    agent = build_agent(tmp_path, ["<final>Subagent checked README.</final>"])
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.text = "/subagent explore inspect README"
        await pilot.press("enter")
        await pilot.pause(delay=0.2)

        text = "\n".join(assistant_contents(app))
        subagents = list(agent.session.get("subagents", []) or [])
        assert "Started subagent" in text
        assert subagents
        assert subagents[-1]["subagent_type"] == "Explore"


@pytest.mark.asyncio
async def test_tui_subagent_command_drains_completion_notification(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar

    agent = build_agent(tmp_path, ["<final>Subagent checked README.</final>"])
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.text = "/subagent explore inspect README"
        await pilot.press("enter")
        await pilot.pause(delay=1.0)

        text = "\n".join(assistant_contents(app))
        assert "Subagent checked README." in text
        assert any(item.get("status") == "completed" for item in agent.session.get("subagents", []))


@pytest.mark.asyncio
async def test_tui_subagent_usage_keeps_task_placeholder_visible(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar

    agent = build_agent(tmp_path, [])
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.text = "/subagent"
        await pilot.press("enter")
        await pilot.pause(delay=0.1)

        assert "`/subagent explore <task>`" in "\n".join(assistant_contents(app))


@pytest.mark.asyncio
async def test_tui_help_context_and_trace_commands(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar

    agent = build_agent(tmp_path, [])
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)

        bar.input.text = "/help"
        await pilot.press("enter")
        await pilot.pause(delay=0.1)

        bar.input.text = "/context"
        await pilot.press("enter")
        await pilot.pause(delay=0.1)

        bar.input.text = "/trace"
        await pilot.press("enter")
        await pilot.pause(delay=0.1)

        text = "\n".join(assistant_contents(app))
        assert "Pico TUI commands" in text
        assert "Context usage" in text
        assert "No run trace yet" in text


@pytest.mark.asyncio
async def test_tui_exposes_plan_compact_history_and_resume_commands(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar

    other = build_agent(tmp_path, ["<final>Other session.</final>"])
    other.ask("older session")

    agent = build_agent(tmp_path, [])
    original_session_id = agent.session["id"]
    for index in range(6):
        agent.record({"role": "user", "content": f"request {index}", "created_at": f"2026-01-01T00:00:0{index}+00:00"})
        agent.record({"role": "assistant", "content": f"answer {index}", "created_at": f"2026-01-01T00:00:1{index}+00:00"})
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)

        for command in (
            "/history",
            "/compact",
            "/plan improve context",
            "/execute",
            f"/resume {other.session['id']}",
        ):
            bar.input.text = command
            await pilot.press("enter")
            await pilot.pause(delay=0.1)

        text = "\n".join(assistant_contents(app))
        assert "Session history" in text
        assert "Compacted" in text
        assert "Entered plan mode" in text
        assert "Exited plan mode" in text
        assert "Resumed session" in text
        assert agent.session["id"] == other.session["id"]
        assert agent.session["id"] != original_session_id


@pytest.mark.asyncio
async def test_tui_plan_command_is_idempotent_and_status_shows_plan_mode(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar, StatusBar

    agent = build_agent(tmp_path, [])
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.text = "/plan inspect runtime"
        await pilot.press("enter")
        await pilot.pause(delay=0.5)
        first_plan = agent.active_plan_path()

        bar.input.text = "/plan inspect runtime again"
        await pilot.press("enter")
        await pilot.pause(delay=0.5)

        assert agent.active_plan_path() == first_plan
        text = "\n".join(assistant_contents(app))
        assert "Already in plan mode" in text
        assert any("User planning request: inspect runtime" in item.get("content", "") for item in agent.session["history"])
        assert any("User planning request: inspect runtime again" in item.get("content", "") for item in agent.session["history"])
        assert "mode plan" in rendered_text(app.query_one(StatusBar))


@pytest.mark.asyncio
async def test_tui_starts_with_pico_cat_banner_and_status_logo(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import StatusBar, WelcomeBanner

    agent = build_agent(tmp_path, [])
    app = PicoTuiApp(agent)

    async with app.run_test():
        banner = app.query_one(WelcomeBanner)
        status = app.query_one(StatusBar)

        assert "Pico-Cat" in rendered_text(banner)
        assert "/\\___/\\" in rendered_text(banner)
        assert "=^._.^= PICO" in rendered_text(status)


@pytest.mark.asyncio
async def test_clear_keeps_pico_cat_banner(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar, WelcomeBanner

    agent = build_agent(tmp_path, [])
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.text = "/clear"
        await pilot.press("enter")
        await pilot.pause(delay=0.1)

        assert app.query_one(WelcomeBanner)


@pytest.mark.asyncio
async def test_tui_runs_agent_in_background_and_updates_status(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar, StatusBar, UserMessage

    agent = build_agent(tmp_path, ["<final>Done from TUI.</final>"])
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.text = "hello tui"
        await pilot.press("enter")
        await pilot.pause(delay=0.5)

        assert bar.busy is False
        assert app.query_one(StatusBar).step_count == 1
        assert app.query(UserMessage).last().content == "hello tui"
        assert "Done from TUI." in assistant_contents(app)[-1]


@pytest.mark.asyncio
async def test_tui_shows_thinking_indicator_while_agent_runs(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar, ThinkingIndicator

    release = threading.Event()

    class BlockingModelClient(FakeModelClient):
        def complete(self, prompt, max_new_tokens, **kwargs):
            release.wait(timeout=2)
            return super().complete(prompt, max_new_tokens, **kwargs)

    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    agent = Pico(
        model_client=BlockingModelClient(["<final>Done after wait.</final>"]),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
    )
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        indicator = app.query_one(ThinkingIndicator)
        bar.input.text = "slow request"
        await pilot.press("enter")
        await pilot.pause(delay=0.2)

        assert indicator.visible is True
        assert "Thinking" in rendered_text(indicator)

        release.set()
        await pilot.pause(delay=0.6)

        assert indicator.visible is False
        assert "Done after wait." in assistant_contents(app)[-1]


@pytest.mark.asyncio
async def test_tui_renders_tool_card_from_runtime_events(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar, ToolCard

    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            "<final>Read complete.</final>",
        ],
    )
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.text = "read the README"
        await pilot.press("enter")
        await pilot.pause(delay=0.8)

        card = app.query(ToolCard).last()
        assert card.tool_name == "read_file"
        assert card.status == "success"
        assert "README.md" in card.args_summary
        assert "demo" in card.output


@pytest.mark.asyncio
async def test_tui_inline_approval_allows_risky_tool(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import ConfirmPrompt, InputBar, ToolCard

    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"write_file","args":{"path":"notes.txt","content":"hello\\n"}}</tool>',
            "<final>Created notes.</final>",
        ],
        approval_policy="ask",
    )
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.text = "create notes"
        await pilot.press("enter")
        await pilot.pause(delay=0.5)

        assert app.query(ConfirmPrompt)
        await pilot.press("y")
        await pilot.pause(delay=0.8)

        assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello\n"
        card = app.query(ToolCard).last()
        assert card.tool_name == "write_file"
        assert card.status == "success"
        assert "Created notes." in assistant_contents(app)[-1]


def test_runtime_event_callback_and_approval_callback_are_used(tmp_path):
    events = []
    approvals = []
    approved = threading.Event()

    def approval_callback(name, args, metadata):
        approvals.append((name, args, metadata))
        approved.set()
        return True

    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"write_file","args":{"path":"notes.txt","content":"hello\\n"}}</tool>',
            "<final>Done.</final>",
        ],
        approval_policy="ask",
    )
    agent.event_callback = events.append
    agent.approval_callback = approval_callback

    answer = agent.ask("write notes")

    assert answer == "Done."
    assert approved.is_set()
    assert approvals[0][0] == "write_file"
    event_names = [event["event"] for event in events]
    assert "prompt_built" in event_names
    assert "tool_started" in event_names
    assert "tool_finished" in event_names
    assert "run_finished" in event_names


@pytest.mark.asyncio
async def test_tui_shows_stage_tasks_and_verification_commands(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar, StatusBar

    verify_command = f"{sys.executable} -c 'print(42)'"
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"todo_write","args":{"todos":[{"id":"task_1","content":"Run app","active_form":"Running app","status":"in_progress"},{"id":"task_2","content":"Verify app","active_form":"Verifying app","status":"pending","verification":true}]}}</tool>',
            f'<tool>{{"name":"run_shell","args":{{"command":"{verify_command}","timeout":20}}}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_1","status":"completed"}}</tool>',
            '<tool>{"name":"todo_update","args":{"id":"task_2","status":"completed"}}</tool>',
            "<final>Verified.</final>",
        ],
        max_steps=8,
    )
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.text = "run and verify app"
        await pilot.press("enter")
        await pilot.pause(delay=1.0)

        status_text = rendered_text(app.query_one(StatusBar))
        assert "stage completed" in status_text
        assert "tasks 2/2" in status_text
        assert "verify passed" in status_text

        bar.input.text = "/tasks"
        await pilot.press("enter")
        await pilot.pause(delay=0.1)

        bar.input.text = "/verify"
        await pilot.press("enter")
        await pilot.pause(delay=0.1)

        text = "\n".join(assistant_contents(app))
        assert "Task ledger" in text
        assert "task_1 [completed]" in text
        assert "Verification artifacts" in text
        assert "python -c" in text
